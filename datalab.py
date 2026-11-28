# -*- coding: utf-8 -*-
"""v0.36 数据工作台逻辑：CSV 识别、字段画像、清洗、图表与报告包。

只做本机可复核的清洗与报告：不调用 AI，不替用户下结论；清洗规则、字段处理
和已知限制都写进报告，原始文件只读。
"""

import csv
import datetime
import hashlib
import html
import io
import json
import os
import re
import statistics
import zipfile
from pathlib import Path

from database import DATA_NOTE_SECTIONS, RepositoryError

MISSING_TOKENS = {"", "-", "—", "na", "n/a", "null", "none", "nan", "无"}
ENC_ORDER = ("utf-8-sig", "utf-8", "gb18030", "utf-16")
DATE_RE = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$")


def _clean(value):
    return str(value or "").strip()


def _safe(name):
    text = re.sub(r'[\\/:*?"<>|]+', "_", _clean(name))
    return text.strip(" ._") or "未命名"


def _num(value):
    text = _clean(value).replace(",", "").replace("，", "")
    text = text.replace("¥", "").replace("￥", "").replace("$", "").strip()
    if text.endswith("%"):
        try:
            return float(text[:-1]) / 100.0
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _is_missing(value):
    return _clean(value).lower() in MISSING_TOKENS


def _uniq_headers(headers):
    out, seen = [], {}
    for idx, raw in enumerate(headers, 1):
        name = _clean(raw) or ("列%d" % idx)
        if name in seen:
            seen[name] += 1
            name = "%s_%d" % (name, seen[name])
        else:
            seen[name] = 1
        out.append(name)
    return out


def read_table(path):
    """读取 CSV，返回 headers/rows/encoding/delimiter；兼容 UTF-8 与 GB18030。"""
    raw = Path(path).read_bytes()
    text, encoding = "", ""
    labels = {"utf-8-sig": "UTF-8", "utf-8": "UTF-8",
              "gb18030": "GB18030", "utf-16": "UTF-16"}
    for enc in ENC_ORDER:
        try:
            text = raw.decode(enc)
            encoding = labels[enc]
            break
        except UnicodeDecodeError:
            continue
    if not encoding:
        raise RepositoryError("CSV 编码无法识别，请另存为 UTF-8 或 GBK 后再试")
    sample = text[:4096]
    delimiter = ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        pass
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    all_rows = [row for row in reader if any(_clean(cell) for cell in row)]
    if not all_rows:
        raise RepositoryError("CSV 是空表")
    headers = _uniq_headers(all_rows[0])
    rows = []
    for row in all_rows[1:]:
        row = list(row) + [""] * (len(headers) - len(row))
        rows.append([row[i] for i in range(len(headers))])
    if not rows:
        raise RepositoryError("CSV 只有表头，没有数据行")
    return {"headers": headers, "rows": rows, "encoding": encoding,
            "delimiter": delimiter}


def profile(headers, rows):
    """给每个字段做画像：类型、缺失、唯一值、异常数字与离群点。"""
    fields = []
    for idx, name in enumerate(headers):
        values = [row[idx] for row in rows]
        nonempty = [v for v in values if not _is_missing(v)]
        missing = len(values) - len(nonempty)
        unique_n = len({_clean(v) for v in nonempty})
        nums = [_num(v) for v in nonempty]
        parsed = [n for n in nums if n is not None]
        numeric_ok = bool(nonempty) and len(parsed) / len(nonempty) >= 0.8
        dates = sum(1 for v in nonempty if DATE_RE.match(_clean(v)))
        if numeric_ok:
            dtype = "整数" if all(float(n).is_integer() for n in parsed) else "数值"
            code_like = any(k in name for k in ("班", "组", "级", "编号", "序号",
                                                "学号", "代码", "编码"))
            if unique_n <= 12 and code_like:
                dtype = "文本"
        elif nonempty and dates / len(nonempty) >= 0.8:
            dtype = "日期"
        else:
            dtype = "文本"
        invalid_numeric = len(nonempty) - len(parsed) if dtype in ("整数", "数值") else 0
        outliers = []
        if dtype in ("整数", "数值"):
            if len(parsed) >= 8:
                q1, q3 = _quantile(parsed, 0.25), _quantile(parsed, 0.75)
                iqr = q3 - q1
                low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                outliers = [n for n in parsed if n < low or n > high]
        binary = bool(nonempty) and all(
            _clean(v).lower() in ("是", "否", "有", "无", "true", "false",
                                  "yes", "no", "到场", "缺席")
            for v in nonempty)
        fields.append({"name": name, "dtype": dtype, "missing": missing,
                       "unique_n": unique_n, "invalid_numeric": invalid_numeric,
                       "outliers": len(outliers),
                       "sample": _clean(nonempty[0]) if nonempty else "",
                       "binary": binary, "nonempty": len(nonempty)})
    keys = {}
    dupes = 0
    for row in rows:
        key = tuple(_clean(v) for v in row)
        keys[key] = keys.get(key, 0) + 1
    for count in keys.values():
        if count > 1:
            dupes += count - 1
    return {"fields": fields, "duplicate_rows": dupes,
            "rows": len(rows), "cols": len(headers),
            "missing_total": sum(f["missing"] for f in fields)}


def _quantile(values, q):
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * q
    low = int(pos)
    high = min(low + 1, len(data) - 1)
    return data[low] + (data[high] - data[low]) * (pos - low)


def clean_table(headers, rows, fields, source):
    """按字段动作与三项开关清洗；返回实际参与输出的表。"""
    trim = bool(source.get("trim", 1))
    dedupe = bool(source.get("dedupe", 1))
    numeric_guard = bool(source.get("numeric_guard", 1))
    kept = []
    for idx, field in enumerate(fields):
        if field.get("action") == "剔除":
            continue
        kept.append(idx)
    if not kept:
        raise RepositoryError("所有字段都被剔除，至少保留一个字段")
    out_headers = []
    for idx in kept:
        target = _clean(fields[idx].get("target")) or headers[idx]
        out_headers.append(target)
    out_headers = _uniq_headers(out_headers)
    out_rows = []
    blanked = 0
    for row in rows:
        values = [row[i] for i in kept]
        if trim:
            values = [v.strip() for v in values]
        if numeric_guard:
            for pos, idx in enumerate(kept):
                if fields[idx].get("dtype") in ("整数", "数值") and not _is_missing(values[pos]):
                    if _num(values[pos]) is None:
                        values[pos] = ""
                        blanked += 1
        out_rows.append(values)
    removed = 0
    if dedupe:
        seen, remain = set(), []
        for row in out_rows:
            key = tuple(_clean(v) for v in row)
            if key in seen:
                removed += 1
                continue
            seen.add(key)
            remain.append(row)
        out_rows = remain
    return {"headers": out_headers, "rows": out_rows,
            "kept_fields": [fields[i]["name"] for i in kept],
            "dropped_fields": [f["name"] for f in fields if f.get("action") == "剔除"],
            "removed_dupes": removed, "blanked_numeric": blanked,
            "trim": trim, "dedupe": dedupe, "numeric_guard": numeric_guard}


def auto_choices(headers, rows, fields):
    text_fields, num_fields = [], []
    for idx, field in enumerate(fields):
        if field.get("action") == "剔除":
            continue
        if field.get("dtype") in ("整数", "数值"):
            num_fields.append(field)
        elif (field.get("dtype") == "文本" and 1 < field.get("unique_n", 0) <= 30
              and not field.get("binary")):
            text_fields.append(field)
    dim = ("班", "组", "类", "别", "状态", "类型", "部门", "年级",
           "渠道", "地区", "性别", "类别")
    text_fields.sort(key=lambda f: (not any(k in f["name"] for k in dim),
                                    f.get("missing", 0) > 0,
                                    f.get("unique_n", 0) > 12,
                                    f.get("unique_n", 0)))
    hint = ("数", "量", "率", "分", "绩", "额", "价", "费", "时", "龄",
            "重", "长", "宽", "高", "温", "次", "占比")
    num_fields.sort(key=lambda f: (not any(k in f["name"] for k in hint),
                                   f.get("unique_n", 0)))
    return {"category": text_fields[0]["name"] if text_fields else "",
            "numeric": num_fields[0]["name"] if num_fields else ""}


def category_stats(headers, rows, name):
    if not name or name not in headers:
        return [], 0
    idx = headers.index(name)
    counts = {}
    for row in rows:
        key = _clean(row[idx]) or "（空）"
        counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top = ranked[:10]
    rest = sum(v for _, v in ranked[10:])
    if rest:
        top.append(("其他", rest))
    return top, total


def numeric_stats(headers, rows, name):
    if not name or name not in headers:
        return {}
    idx = headers.index(name)
    nums = [_num(row[idx]) for row in rows if not _is_missing(row[idx])]
    nums = [n for n in nums if n is not None]
    if not nums:
        return {}
    bins = min(8, max(4, int(len(nums) ** 0.5)))
    low, high = min(nums), max(nums)
    if high == low:
        hist = [{"label": _fmt_num(low), "count": len(nums)}]
    else:
        width = (high - low) / bins
        hist = []
        for i in range(bins):
            left = low + i * width
            right = left + width
            count = sum(1 for n in nums
                        if (n >= left and (n < right or i == bins - 1)))
            hist.append({"label": _fmt_num(left), "count": count})
    vals = sorted(nums)
    return {"count": len(nums), "min": min(nums), "max": max(nums),
            "mean": sum(nums) / len(nums), "median": statistics.median(vals),
            "hist": hist}


def _fmt_num(value):
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return ("%.2f" % value).rstrip("0").rstrip(".")


def bar_svg(items, title):
    width, row_h, left, right = 760, 30, 170, 40
    height = max(150, 46 + row_h * max(1, len(items))) + 20
    max_v = max([v for _, v in items] or [1]) or 1
    parts = ['<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
             'role="img" aria-label="%s">' % (width, height, html.escape(title))]
    parts.append('<text x="0" y="20" font-size="15" font-weight="700" '
                 'fill="#173b39">%s</text>' % html.escape(title))
    for i, (label, value) in enumerate(items):
        y = 42 + i * row_h
        bar_w = (value / max_v) * (width - left - right)
        parts.append('<text x="0" y="%d" font-size="12" fill="#40524f">%s</text>' %
                     (y + 15, html.escape(str(label)[:18])))
        parts.append('<rect x="%d" y="%d" width="%.1f" height="16" rx="3" fill="#2f6f6a"/>' %
                     (left, y + 2, max(2, bar_w)))
        parts.append('<text x="%d" y="%d" font-size="12" fill="#173b39">%s</text>' %
                     (left + max(2, bar_w) + 8, y + 15, str(value)))
    parts.append("</svg>")
    return "".join(parts)


def hist_svg(hist, title):
    width, height, left, bottom = 760, 260, 46, 36
    max_v = max([h["count"] for h in hist] or [1]) or 1
    plot_w, plot_h = width - left - 20, height - bottom - 40
    bw = plot_w / max(1, len(hist))
    parts = ['<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" '
             'role="img" aria-label="%s">' % (width, height, html.escape(title))]
    parts.append('<text x="0" y="20" font-size="15" font-weight="700" '
                 'fill="#173b39">%s</text>' % html.escape(title))
    parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#c9d6d2"/>' %
                 (left, 40 + plot_h, width - 20, 40 + plot_h))
    for i, item in enumerate(hist):
        h = (item["count"] / max_v) * plot_h
        x = left + i * bw + 4
        y = 40 + plot_h - h
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                     'rx="2" fill="#8fb8ae"/>' % (x, y, max(2, bw - 8), h))
        parts.append('<text x="%.1f" y="%d" font-size="11" fill="#40524f" '
                     'text-anchor="middle">%s</text>' %
                     (x + (bw - 8) / 2, 40 + plot_h + 16, html.escape(item["label"])))
        if item["count"]:
            parts.append('<text x="%.1f" y="%.1f" font-size="11" fill="#173b39" '
                         'text-anchor="middle">%d</text>' %
                         (x + (bw - 8) / 2, max(52, y - 4), item["count"]))
    parts.append("</svg>")
    return "".join(parts)


def _notes_map(repo, pid):
    return {n["section"]: n for n in repo.list_data_notes(pid)}


def seed_data(repo, pid):
    """补默认说明小节；重复执行不重复插入。"""
    if repo.find_project(pid) is None:
        raise RepositoryError("项目不存在")
    repo.apply_project_template(pid, "data")
    existing = {n["section"] for n in repo.list_data_notes(pid)}
    added = 0
    default = {
        "数据来源与口径": "写清数据从哪来、统计口径与时间范围，避免把不同口径混在一张表里。",
        "样本与字段": "说明每行代表什么、主键或唯一标识是什么，字段含义以原表为准。",
        "清洗规则": "默认去首尾空格、整行去重；数值字段的非法值置空并计数。",
        "已知限制": "本报告只做描述统计，不推断因果；缺失与异常不应被静默忽略。",
        "结论摘要": "先写能直接支撑行动的两三条结论，再写仍待核实的问题。",
    }
    for section in DATA_NOTE_SECTIONS:
        if section in existing or section not in default:
            continue
        repo.add_data_note(pid, {"section": section, "content": default[section]})
        added += 1
    return added


def stats(repo, pid):
    source = repo.list_data_source(pid)
    fields = repo.list_data_fields(pid)
    notes = repo.list_data_notes(pid)
    filled_notes = sum(1 for n in notes if _clean(n.get("content")))
    numeric = sum(1 for f in fields if f.get("dtype") in ("整数", "数值"))
    dropped = sum(1 for f in fields if f.get("action") == "剔除")
    return {"source": source, "fields": fields, "notes": notes,
            "rows": int(source.get("rows") or 0), "cols": int(source.get("cols") or 0),
            "tables": 1 if source else 0, "fields_n": len(fields),
            "numeric": numeric, "dropped": dropped, "notes_n": filled_notes}


def readiness(repo, pid):
    st = stats(repo, pid)
    checks = []
    src = st["source"]
    checks.append(("数据源已导入", bool(src), "#" if src else "先导入 CSV 数据源"))
    checks.append(("字段已识别", st["fields_n"] >= 2,
                   "%d 个字段" % st["fields_n"]))
    checks.append(("有数值字段", st["numeric"] >= 1,
                   "%d 个数值字段" % st["numeric"]))
    checks.append(("口径说明已写", st["notes_n"] >= 3,
                   "已填 %d / %d 小节" % (st["notes_n"], len(DATA_NOTE_SECTIONS))))
    checks.append(("清洗规则可复算", bool(src) and st["fields_n"] >= 1,
                   "去重 / 去空格 / 数值保护"))
    ok = all(item[1] for item in checks)
    return {"ok": ok, "checks": checks,
            "failed": [item[2] for item in checks if not item[1]]}


def _html_page(project, source, prof, cleaned, cat, num, notes, generated):
    esc = html.escape
    rows_in = prof["rows"]
    rows_out = len(cleaned["rows"])
    cards = [
        ("数据行", "%d → %d" % (rows_in, rows_out), "去重后 %d 行" % cleaned["removed_dupes"]),
        ("字段", "%d → %d" % (prof["cols"], len(cleaned["headers"])),
         "剔除 %d 个" % len(cleaned["dropped_fields"])),
        ("缺失值", str(prof["missing_total"]), "按字段列出，不静默补齐"),
        ("数值保护", str(cleaned["blanked_numeric"]), "非法数字置空计数"),
    ]
    card_html = "".join(
        '<div class="card"><i>%s</i><b>%s</b><span>%s</span></div>' %
        (esc(a), esc(b), esc(c)) for a, b, c in cards)
    field_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" %
        (esc(f["name"]), esc(f["dtype"]), f["missing"], f["unique_n"],
         esc(next((x.get("action", "保留") for x in cleaned.get("fields_meta", [])
                   if x["name"] == f["name"]), "保留")),
         esc(next((x.get("target", "") for x in cleaned.get("fields_meta", [])
                   if x["name"] == f["name"]), ""))) for f in prof["fields"])
    clean_log = []
    clean_log.append("去首尾空格：%s" % ("开" if cleaned["trim"] else "关"))
    clean_log.append("整行去重：%s，删除 %d 行" % ("开" if cleaned["dedupe"] else "关",
                                              cleaned["removed_dupes"]))
    clean_log.append("数值保护：%s，置空 %d 个非法值" %
                     ("开" if cleaned["numeric_guard"] else "关",
                      cleaned["blanked_numeric"]))
    if cleaned["dropped_fields"]:
        clean_log.append("剔除字段：%s" % "、".join(cleaned["dropped_fields"]))
    else:
        clean_log.append("剔除字段：无")
    log_html = "".join("<li>%s</li>" % esc(x) for x in clean_log)
    note_html = ""
    for section in DATA_NOTE_SECTIONS:
        row = notes.get(section, {})
        text = _clean(row.get("content")) or "（未填写）"
        note_html += ('<section class="note"><h3>%s</h3><p>%s</p></section>' %
                      (esc(section), esc(text).replace("\n", "<br>")))
    cat_html = (bar_svg(cat["items"], "按「%s」分布" % cat["name"])
                if cat.get("items") else '<div class="empty">未选择可用的分类字段。</div>')
    num_html = ""
    if num:
        s = num
        num_html = hist_svg(s["hist"], "「%s」分布" % s["name"])
        num_html += ('<p class="meta">样本 %d · 最小 %s · 中位 %s · 均值 %s · 最大 %s</p>' %
                     (s["count"], _fmt_num(s["min"]), _fmt_num(s["median"]),
                      _fmt_num(round(s["mean"], 2)), _fmt_num(s["max"])))
    else:
        num_html = '<div class="empty">未选择可用的数值字段。</div>'
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s · 数据报告</title>
<style>
:root{--ink:#173b39;--text:#31413e;--muted:#6b7b77;--line:#d8e2de;--paper:#f6f4ee;--accent:#2f6f6a}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--text);
font:14px/1.7 "Microsoft YaHei","PingFang SC",sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:34px 26px 56px}
header{border-bottom:2px solid var(--ink);padding-bottom:18px;margin-bottom:18px}
.kicker{color:var(--muted);font-size:12px;letter-spacing:.08em}
h1{font-size:28px;line-height:1.35;margin:6px 0 4px;color:var(--ink)}
.sub{color:var(--muted);font-size:13px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:20px 0}
.card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.card i{display:block;font-style:normal;color:var(--muted);font-size:12px}
.card b{display:block;font-size:20px;color:var(--ink);margin:2px 0}
.card span{font-size:12px;color:var(--muted)}
h2{font-size:18px;color:var(--ink);margin:28px 0 10px;border-left:4px solid var(--accent);padding-left:9px}
table{width:100%%;border-collapse:collapse;background:#fff}
th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;font-size:13px}
th{background:#eaf1ed;color:var(--ink);font-weight:600}
.chart{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px;margin:12px 0}
.chart svg{width:100%%;height:auto}
.meta{color:var(--muted);font-size:12px;margin:4px 0 0}
ul.rules{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px 26px;margin:0}
.note{background:#fff;border:1px solid var(--line);border-radius:8px;padding:8px 16px;margin:8px 0}
.note h3{margin:6px 0 2px;color:var(--ink);font-size:14px}.note p{margin:0 0 4px;white-space:normal}
.empty{padding:18px;color:var(--muted);background:#fff;border:1px dashed var(--line);border-radius:8px}
footer{margin-top:30px;border-top:1px solid var(--line);padding-top:10px;color:var(--muted);font-size:12px}
@media(max-width:760px){.cards{grid-template-columns:repeat(2,1fr)}.wrap{padding:22px 14px}}
@media print{body{background:#fff}.wrap{max-width:none}.chart{break-inside:avoid}}
</style></head><body><div class="wrap">
<header><div class="kicker">班级操作台 · 数据工作台 · v0.36</div>
<h1>%(title)s</h1><div class="sub">数据源：%(source)s ｜ 生成：%(generated)s</div></header>
<div class="cards">%(cards)s</div>
<h2>一、字段与清洗结果</h2>
<table><thead><tr><th>字段</th><th>类型</th><th>缺失</th><th>唯一值</th><th>处理</th><th>输出名</th></tr></thead><tbody>%(fields)s</tbody></table>
<h2>二、清洗规则</h2><ul class="rules">%(log)s</ul>
<h2>三、图表</h2><div class="chart">%(cat)s</div><div class="chart">%(num)s</div>
<h2>四、口径与结论</h2>%(notes)s
<footer>本报告由本地数据生成，未调用 AI。原文件只读；清洗结果另存为 CSV，可逐行复核。</footer>
</div></body></html>""" % {
        "title": esc(project.get("name", "数据报告")),
        "source": esc(os.path.basename(source.get("path", "")) or source.get("name", "")),
        "generated": esc(generated), "cards": card_html, "fields": field_rows,
        "log": log_html, "cat": cat_html, "num": num_html, "notes": note_html}


def _write_csv(path, headers, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def _unique_dir(parent, name):
    base = Path(parent) / name
    target = base
    n = 1
    while target.exists():
        n += 1
        target = Path(parent) / ("%s_%d" % (name, n))
    target.mkdir(parents=True, exist_ok=False)
    return target


def make_package(repo, pid, outdir, category="", numeric="", note="", make_zip=True):
    project = repo.find_project(pid)
    if project is None:
        raise RepositoryError("项目不存在")
    st = stats(repo, pid)
    source = st["source"]
    if not source:
        raise RepositoryError("还没有导入数据源")
    path = source.get("path")
    if not path or not os.path.exists(path):
        raise RepositoryError("数据源文件已不在原路径：%s" % (path or "（空）"))
    if not outdir:
        raise RepositoryError("请选择输出目录")
    Path(outdir).mkdir(parents=True, exist_ok=True)
    loaded = read_table(path)
    headers, rows = loaded["headers"], loaded["rows"]
    prof = profile(headers, rows)
    fields = repo.list_data_fields(pid)
    cleaned = clean_table(headers, rows, fields, source)
    cleaned["fields_meta"] = fields
    choices = auto_choices(headers, rows, fields)
    cat_name = category if category in headers else choices["category"]
    num_name = numeric if numeric in headers else choices["numeric"]
    cat_items, cat_total = category_stats(headers, rows, cat_name)
    num = numeric_stats(headers, rows, num_name)
    num = dict(num, name=num_name) if num else {}
    notes = _notes_map(repo, pid)
    now = datetime.datetime.now()
    package = _unique_dir(outdir, "%s_数据报告包" % _safe(project.get("name")))
    stem = _safe(project.get("name"))
    cleaned_path = package / ("%s_清洗结果.csv" % stem)
    fields_path = package / ("%s_字段清单.csv" % stem)
    report_path = package / ("%s_数据报告.html" % stem)
    readme_path = package / ("%s_报告说明.md" % stem)
    _write_csv(cleaned_path, cleaned["headers"], cleaned["rows"])
    field_headers = ["字段", "类型", "缺失", "唯一值", "处理", "输出名"]
    field_rows = [[f["name"], f["dtype"], f["missing"], f["unique_n"],
                   f.get("action", "保留"), f.get("target", "") or f["name"]]
                  for f in prof["fields"]]
    _write_csv(fields_path, field_headers, field_rows)
    page = _html_page(project, source, prof, cleaned, 
                      {"name": cat_name, "items": cat_items, "total": cat_total},
                      num, notes, now.strftime("%Y-%m-%d %H:%M"))
    report_path.write_text(page, encoding="utf-8")
    lines = ["# %s · 数据报告说明" % project.get("name", ""), "",
             "- 数据源：%s" % (source.get("path") or source.get("name")),
             "- 原始规模：%d 行 × %d 列（%s）" % (prof["rows"], prof["cols"], loaded["encoding"]),
             "- 清洗后：%d 行 × %d 列" % (len(cleaned["rows"]), len(cleaned["headers"])),
             "- 删除重复行：%d；置空非法数值：%d" % (cleaned["removed_dupes"], cleaned["blanked_numeric"]),
             "- 剔除字段：%s" % ("、".join(cleaned["dropped_fields"]) or "无"),
             "- 分类字段：%s" % (cat_name or "无"),
             "- 数值字段：%s" % (num_name or "无"), ""]
    if note:
        lines += ["## 本次补充说明", "", note, ""]
    lines += ["## 复算方式", "",
              "1. 打开 `%s`，按字段清单的处理动作复核。" % cleaned_path.name,
              "2. 打开 `%s` 查看图表与口径；图表只做描述统计。" % report_path.name,
              "3. 原文件未改动，路径为 `%s`。" % (source.get("path") or ""), ""]
    readme_path.write_text("\n".join(lines), encoding="utf-8")
    files = [cleaned_path, fields_path, report_path, readme_path]
    zip_path = ""
    if make_zip:
        zip_path = package / ("%s_数据报告包.zip" % stem)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, arcname=f.name)
    digest = hashlib.sha256(report_path.read_bytes()).hexdigest().upper()
    for f in files:
        repo.add_project_asset(pid, {"name": f.name, "path": str(f), "kind": "数据报告",
                                     "size": f.stat().st_size,
                                     "sha256": hashlib.sha256(f.read_bytes()).hexdigest().upper(),
                                     "note": "v0.36 数据报告"})
    if zip_path:
        repo.add_project_asset(pid, {"name": zip_path.name, "path": str(zip_path),
                                     "kind": "数据报告包", "size": zip_path.stat().st_size,
                                     "sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest().upper(),
                                     "note": "报告包 ZIP"})
    repo.add_project_run(pid, {"tool": "数据清洗与报告", "status": "已结束",
                               "params": "分类=%s 数值=%s" % (cat_name or "无", num_name or "无"),
                               "output": str(report_path), "log": "清洗与图表生成完成"})
    gate_note = "%d 行 → %d 行，%d 列" % (prof["rows"], len(cleaned["rows"]), len(cleaned["headers"]))
    repo.set_project_gate(pid, "清洗口径", "通过", note="字段动作与三项清洗规则已记录", checked_by="系统")
    repo.set_project_gate(pid, "数据核对", "通过", note=gate_note, checked_by="系统")
    repo.set_project_gate(pid, "图表报告", "通过" if cat_items and num else "不通过",
                          note="分类分布与数值分布", checked_by="系统")
    repo.set_project_gate(pid, "报告包", "通过", note="报告、清洗结果、字段清单、说明齐全", checked_by="系统")
    for name in ("数据源清单", "清洗口径", "分析图表", "结论报告"):
        for d in repo.list_deliverables(pid):
            if d["name"] == name:
                repo.update_deliverable(d["id"], {"status": "已通过",
                                                  "note": "由数据报告包生成"})
    return {"package": str(package), "files": [str(f) for f in files],
            "zip": str(zip_path) if zip_path else "",
            "zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest().upper() if zip_path else "",
            "zip_size": zip_path.stat().st_size if zip_path else 0,
            "report_sha256": digest,
            "summary": "%d 行 → %d 行；%d 字段；图表 %d 类" %
                       (prof["rows"], len(cleaned["rows"]),
                        len(cleaned["headers"]), bool(cat_items) + bool(num)),
            "stats": {"rows_in": prof["rows"], "rows_out": len(cleaned["rows"]),
                      "cols_out": len(cleaned["headers"]),
                      "removed_dupes": cleaned["removed_dupes"],
                      "blanked": cleaned["blanked_numeric"]}}


def open_report(path):
    if not path or not os.path.exists(path):
        raise RepositoryError("报告文件不存在")
    import webbrowser
    webbrowser.open(Path(path).resolve().as_uri())

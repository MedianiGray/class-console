# -*- coding: utf-8 -*-
"""v0.36 活动工作台逻辑：策划、名单与签到、预算结算、总结与结项包。

不接在线报名后端，也不替用户写活动内容；它只把一次活动从策划到结项
所需的口径、名单、签到与结算对齐，并把结果写回项目。
"""

import csv
import datetime
import hashlib
import html
import os
import re
import zipfile
from pathlib import Path

from database import (EVENT_PLAN_SECTIONS, EVENT_ROLES, EVENT_STATUS,
                      EVENT_SUMMARY_SECTIONS, RepositoryError)


def _clean(value):
    return str(value or "").strip()


def _safe(name):
    text = re.sub(r'[\\/:*?"<>|]+', "_", _clean(name))
    return text.strip(" ._") or "未命名"


def _money(value):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _fmt_money(value):
    return "{:,.2f}".format(_money(value))


def seed_event(repo, pid):
    """补策划与总结小节；内容留空，由用户填写，不编活动内容。"""
    if repo.find_project(pid) is None:
        raise RepositoryError("项目不存在")
    repo.apply_project_template(pid, "event")
    plan = {p["section"] for p in repo.list_event_plan(pid)}
    notes = {n["section"] for n in repo.list_event_notes(pid)}
    added = 0
    for section in EVENT_PLAN_SECTIONS:
        if section not in plan:
            repo.add_event_plan(pid, {"section": section, "content": ""})
            added += 1
    for section in EVENT_SUMMARY_SECTIONS:
        if section not in notes:
            repo.add_event_note(pid, {"section": section, "content": ""})
            added += 1
    return added


def plan_stats(repo, pid):
    rows = repo.list_event_plan(pid)
    filled = sum(1 for r in rows if _clean(r.get("content")))
    return {"rows": rows, "total": len(EVENT_PLAN_SECTIONS), "filled": filled,
            "rate": filled / len(EVENT_PLAN_SECTIONS) * 100 if EVENT_PLAN_SECTIONS else 0}


def people_stats(repo, pid):
    rows = repo.list_event_people(pid)
    counts = {s: 0 for s in EVENT_STATUS}
    for r in rows:
        status = r.get("status") if r.get("status") in EVENT_STATUS else "已报名"
        counts[status] += 1
    total = len(rows)
    attended = counts["已签到"] + counts["临时到场"]
    rate = attended / total * 100 if total else 0
    return {"rows": rows, "total": total, "counts": counts,
            "attended": attended, "absent": counts["缺席"],
            "registered": counts["已报名"], "walkin": counts["临时到场"],
            "rate": rate}


def expense_stats(repo, pid):
    rows = repo.list_event_expenses(pid)
    budget = sum(_money(r.get("budget")) for r in rows)
    actual = sum(_money(r.get("actual")) for r in rows)
    return {"rows": rows, "budget": budget, "actual": actual,
            "diff": budget - actual,
            "rate": actual / budget * 100 if budget else 0}


def note_stats(repo, pid):
    rows = repo.list_event_notes(pid)
    filled = sum(1 for r in rows if _clean(r.get("content")))
    return {"rows": rows, "filled": filled, "total": len(EVENT_SUMMARY_SECTIONS)}


def stats(repo, pid):
    return {"plan": plan_stats(repo, pid), "people": people_stats(repo, pid),
            "expense": expense_stats(repo, pid), "notes": note_stats(repo, pid)}


def readiness(repo, pid):
    st = stats(repo, pid)
    checks = [
        ("策划 8 小节", st["plan"]["filled"] >= 8,
         "%d / 8 已填" % st["plan"]["filled"]),
        ("名单已录入", st["people"]["total"] >= 1,
         "%d 人" % st["people"]["total"]),
        ("签到已核对", st["people"]["total"] >= 1 and
         (st["people"]["attended"] + st["people"]["absent"]) >= 1,
         "已到 %d、缺席 %d" % (st["people"]["attended"], st["people"]["absent"])),
        ("结算有明细", len(st["expense"]["rows"]) >= 1,
         "%d 项，预算 %s / 实付 %s" % (len(st["expense"]["rows"]),
                                    _fmt_money(st["expense"]["budget"]),
                                    _fmt_money(st["expense"]["actual"]))),
        ("总结已写", st["notes"]["filled"] >= 3,
         "%d / 4 小节" % st["notes"]["filled"]),
        ("活动名称与日期", bool(_clean(repo.find_project(pid).get("start_date"))),
         "项目开始日期即活动日期" if repo.find_project(pid).get("start_date") else "先补项目日期"),
    ]
    ok = all(c[1] for c in checks)
    return {"ok": ok, "checks": checks, "failed": [c[2] for c in checks if not c[1]],
            "stats": st}


def _status_rows(st):
    total = st["total"] or 1
    return [[s, st["counts"][s], "%.1f%%" % (st["counts"][s] / total * 100)]
            for s in EVENT_STATUS]


def _html_page(project, st, generated):
    esc = html.escape
    plan_rows = st["plan"]["rows"]
    people = st["people"]
    ex = st["expense"]
    cards = [
        ("名单", "%d 人" % people["total"], "已到 %d / 缺席 %d" % (people["attended"], people["absent"])),
        ("到场率", "%.1f%%" % people["rate"], "含临时到场 %d" % people["walkin"]),
        ("预算", "¥%s" % _fmt_money(ex["budget"]), "实付 ¥%s" % _fmt_money(ex["actual"])),
        ("结余", "¥%s" % _fmt_money(ex["diff"]), "为负表示超支"),
    ]
    card_html = "".join('<div class="card"><i>%s</i><b>%s</b><span>%s</span></div>' %
                        (esc(a), esc(b), esc(c)) for a, b, c in cards)
    plan_html = ""
    for row in plan_rows:
        text = _clean(row.get("content")) or "（未填写）"
        plan_html += '<section class="note"><h3>%s</h3><p>%s</p></section>' % (
            esc(row["section"]), esc(text).replace("\n", "<br>"))
    status_html = "".join("<tr><td>%s</td><td>%d</td><td>%s</td></tr>" %
                          (esc(a), b, c) for a, b, c in _status_rows(people))
    people_html = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" %
        (esc(p.get("name", "")), esc(p.get("sid", "")), esc(p.get("role", "")),
         esc(p.get("status", "")), esc(p.get("note", "")))
        for p in people["rows"])
    expense_html = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" %
        (esc(e.get("item", "")), _fmt_money(e.get("budget")), _fmt_money(e.get("actual")),
         _fmt_money(_money(e.get("budget")) - _money(e.get("actual"))), esc(e.get("note", "")))
        for e in ex["rows"])
    expense_html += ('<tr class="total"><td>合计</td><td>%s</td><td>%s</td><td>%s</td><td></td></tr>' %
                     (_fmt_money(ex["budget"]), _fmt_money(ex["actual"]), _fmt_money(ex["diff"])))
    notes_html = ""
    for n in st["notes"]["rows"]:
        text = _clean(n.get("content")) or "（未填写）"
        notes_html += '<section class="note"><h3>%s</h3><p>%s</p></section>' % (
            esc(n["section"]), esc(text).replace("\n", "<br>"))
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s · 活动总结</title>
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
.card b{display:block;font-size:19px;color:var(--ink);margin:2px 0}
.card span{font-size:12px;color:var(--muted)}
h2{font-size:18px;color:var(--ink);margin:28px 0 10px;border-left:4px solid var(--accent);padding-left:9px}
table{width:100%%;border-collapse:collapse;background:#fff}
th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;font-size:13px}
th{background:#eaf1ed;color:var(--ink);font-weight:600}
tr.total td{font-weight:700;background:#f0f5f2}
.note{background:#fff;border:1px solid var(--line);border-radius:8px;padding:8px 16px;margin:8px 0}
.note h3{margin:6px 0 2px;color:var(--ink);font-size:14px}.note p{margin:0 0 4px}
footer{margin-top:30px;border-top:1px solid var(--line);padding-top:10px;color:var(--muted);font-size:12px}
@media(max-width:760px){.cards{grid-template-columns:repeat(2,1fr)}.wrap{padding:22px 14px}}
@media print{body{background:#fff}.wrap{max-width:none}.note{break-inside:avoid}}
</style></head><body><div class="wrap">
<header><div class="kicker">班级操作台 · 活动工作台 · v0.36</div>
<h1>%(title)s · 活动总结</h1><div class="sub">活动日期：%(date)s ｜ 生成：%(generated)s</div></header>
<div class="cards">%(cards)s</div>
<h2>一、签到与到场</h2>
<table><thead><tr><th>状态</th><th>人数</th><th>占比</th></tr></thead><tbody>%(status)s</tbody></table>
<h2>二、名单明细</h2>
<table><thead><tr><th>姓名</th><th>学号</th><th>角色</th><th>状态</th><th>备注</th></tr></thead><tbody>%(people)s</tbody></table>
<h2>三、预算与结算</h2>
<table><thead><tr><th>项目</th><th>预算</th><th>实付</th><th>差额</th><th>说明</th></tr></thead><tbody>%(expense)s</tbody></table>
<h2>四、活动策划回顾</h2>%(plan)s
<h2>五、总结与改进</h2>%(notes)s
<footer>本总结由本地名单与结算表生成，未调用 AI；签到与金额可回到原始表逐条复核。</footer>
</div></body></html>""" % {
        "title": esc(project.get("name", "活动")),
        "date": esc(project.get("start_date", "")), "generated": esc(generated),
        "cards": card_html, "status": status_html, "people": people_html,
        "expense": expense_html, "plan": plan_html, "notes": notes_html}


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


def make_package(repo, pid, outdir, note="", make_zip=True):
    project = repo.find_project(pid)
    if project is None:
        raise RepositoryError("项目不存在")
    ready = readiness(repo, pid)
    if not ready["ok"]:
        raise RepositoryError("还不能结项：%s" % "；".join(ready["failed"]))
    if not outdir:
        raise RepositoryError("请选择输出目录")
    Path(outdir).mkdir(parents=True, exist_ok=True)
    st = ready["stats"]
    now = datetime.datetime.now()
    package = _unique_dir(outdir, "%s_活动结项包" % _safe(project.get("name")))
    stem = _safe(project.get("name"))
    plan_path = package / ("%s_策划.md" % stem)
    people_path = package / ("%s_签到明细.csv" % stem)
    status_path = package / ("%s_签到汇总.csv" % stem)
    expense_path = package / ("%s_预算结算.csv" % stem)
    report_path = package / ("%s_活动总结.html" % stem)
    readme_path = package / ("%s_结项说明.md" % stem)
    plan_lines = ["# %s · 活动策划" % project.get("name", ""), "",
                  "- 活动日期：%s" % (project.get("start_date") or "未填"),
                  "- 负责人：%s" % (project.get("owner") or "未填"), ""]
    for row in st["plan"]["rows"]:
        plan_lines += ["## %s" % row["section"], "",
                       _clean(row.get("content")) or "（未填写）", ""]
    plan_path.write_text("\n".join(plan_lines), encoding="utf-8")
    _write_csv(people_path, ["姓名", "学号", "角色", "状态", "联系方式", "备注"],
               [[p.get("name", ""), p.get("sid", ""), p.get("role", ""),
                 p.get("status", ""), p.get("contact", ""), p.get("note", "")]
                for p in st["people"]["rows"]])
    _write_csv(status_path, ["状态", "人数", "占比"], _status_rows(st["people"]))
    expense_rows = [[e.get("item", ""), _fmt_money(e.get("budget")),
                     _fmt_money(e.get("actual")),
                     _fmt_money(_money(e.get("budget")) - _money(e.get("actual"))),
                     e.get("note", "")] for e in st["expense"]["rows"]]
    expense_rows.append(["合计", _fmt_money(st["expense"]["budget"]),
                         _fmt_money(st["expense"]["actual"]),
                         _fmt_money(st["expense"]["diff"]), ""])
    _write_csv(expense_path, ["项目", "预算", "实付", "差额", "说明"], expense_rows)
    report_path.write_text(_html_page(project, st, now.strftime("%Y-%m-%d %H:%M")),
                           encoding="utf-8")
    lines = ["# %s · 结项说明" % project.get("name", ""), "",
             "- 名单 %d 人，已到 %d 人（含临时到场 %d），缺席 %d，到场率 %.1f%%。" %
             (st["people"]["total"], st["people"]["attended"], st["people"]["walkin"],
              st["people"]["absent"], st["people"]["rate"]),
             "- 预算 %s 元，实付 %s 元，差额 %s 元。" %
             (_fmt_money(st["expense"]["budget"]), _fmt_money(st["expense"]["actual"]),
              _fmt_money(st["expense"]["diff"])),
             "- 策划 8 小节全部有内容；总结 4 小节已填 %d 小节。" % st["notes"]["filled"], ""]
    if note:
        lines += ["## 补充说明", "", note, ""]
    lines += ["## 包内文件", "",
              "- `%s`：策划全文" % plan_path.name,
              "- `%s`：逐人签到明细" % people_path.name,
              "- `%s`：各状态人数与占比" % status_path.name,
              "- `%s`：预算、实付与差额" % expense_path.name,
              "- `%s`：可直接打印或归档的活动总结" % report_path.name, ""]
    readme_path.write_text("\n".join(lines), encoding="utf-8")
    files = [plan_path, people_path, status_path, expense_path, report_path, readme_path]
    zip_path = ""
    if make_zip:
        zip_path = package / ("%s_活动结项包.zip" % stem)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, arcname=f.name)
    for f in files:
        repo.add_project_asset(pid, {"name": f.name, "path": str(f), "kind": "活动结项",
                                     "size": f.stat().st_size,
                                     "sha256": hashlib.sha256(f.read_bytes()).hexdigest().upper(),
                                     "note": "v0.36 活动结项"})
    if zip_path:
        repo.add_project_asset(pid, {"name": zip_path.name, "path": str(zip_path),
                                     "kind": "活动结项包", "size": zip_path.stat().st_size,
                                     "sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest().upper(),
                                     "note": "结项包 ZIP"})
    repo.add_project_run(pid, {"tool": "活动结项包", "status": "已结束",
                               "params": "名单=%d 结算=%d" % (st["people"]["total"],
                                                             len(st["expense"]["rows"])),
                               "output": str(report_path), "log": "策划、签到、结算与总结已归档"})
    repo.set_project_gate(pid, "策划审批", "通过", note="8 个小节均有内容", checked_by="系统")
    repo.set_project_gate(pid, "签到核对", "通过",
                          note="名单 %d 人，已到 %d 人" % (st["people"]["total"], st["people"]["attended"]),
                          checked_by="系统")
    repo.set_project_gate(pid, "结算核对", "通过",
                          note="预算 %s / 实付 %s" % (_fmt_money(st["expense"]["budget"]),
                                                  _fmt_money(st["expense"]["actual"])),
                          checked_by="系统")
    repo.set_project_gate(pid, "结项包", "通过", note="策划、签到、结算、总结齐全", checked_by="系统")
    for name in ("策划与审批", "通知与报名", "现场执行", "总结与结算"):
        for d in repo.list_deliverables(pid):
            if d["name"] == name:
                repo.update_deliverable(d["id"], {"status": "已通过",
                                                  "note": "由活动结项包生成"})
    return {"package": str(package), "files": [str(f) for f in files],
            "zip": str(zip_path) if zip_path else "",
            "zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest().upper() if zip_path else "",
            "zip_size": zip_path.stat().st_size if zip_path else 0,
            "summary": "%d 人，到场率 %.1f%%；预算 %s / 实付 %s" %
                       (st["people"]["total"], st["people"]["rate"],
                        _fmt_money(st["expense"]["budget"]),
                        _fmt_money(st["expense"]["actual"]))}


def open_report(path):
    if not path or not os.path.exists(path):
        raise RepositoryError("总结文件不存在")
    import webbrowser
    webbrowser.open(Path(path).resolve().as_uri())

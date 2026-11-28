# -*- coding: utf-8 -*-
"""v0.34 赛事模板的逻辑层：赛程、报名、评审矩阵、提交校验与答辩包。

一条闭环：建赛事项目 → 排赛程 → 拉报名 → 对评审标准 → 校验提交包 →
生成答辩包。所有判断都在这里做成可测试的纯函数；界面只负责收集参数与展示。
不联网、不爬赛事官网，也不替用户编造赛事信息。
"""

import csv
import datetime
import hashlib
import json
import os
import re
import shutil
import zipfile

MILESTONE_DEFAULTS = (
    ("报名截止", "报名与资格"),
    ("作品提交截止", "提交校验"),
    ("答辩", "答辩包"),
)
RUBRIC_DEFAULTS = (
    ("创新性", 20),
    ("技术难度", 25),
    ("完成度", 25),
    ("实用价值", 20),
    ("表达与答辩", 10),
)
DEFAULT_SUBMIT_EXTS = (".pdf", ".zip")
DEFAULT_MAX_FILE_MB = 50
DEFAULT_MAX_TOTAL_MB = 100
DEFAULT_MAX_FILES = 30
NAME_MAX = 80
ILLEGAL_NAME_CHARS = '<>:"/\\|?*'
REPORT_PREFIX = "_提交校验_"
MANIFEST_PREFIX = "_答辩包清单_"


# ---------- 通用 ----------
def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _today(today=None) -> datetime.date:
    if isinstance(today, datetime.date):
        return today
    if today:
        parsed = _parse_date(today)
        if parsed:
            return parsed
    return datetime.date.today()


def _parse_date(value):
    raw = _clean(value)[:10]
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _human_size(size) -> str:
    try:
        size = float(size or 0)
    except (TypeError, ValueError):
        return "?"
    if size >= 1024 * 1024:
        return "%.1f MB" % (size / 1024.0 / 1024.0)
    if size >= 1024:
        return "%.0f KB" % (size / 1024.0)
    return "%d B" % size


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _unique_dir(base) -> str:
    if not os.path.exists(base):
        return base
    for i in range(2, 1000):
        candidate = "%s_%d" % (base, i)
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("同名目录太多，先清理旧输出")


def _unique_file(base) -> str:
    if not os.path.exists(base):
        return base
    root, ext = os.path.splitext(base)
    for i in range(2, 1000):
        candidate = "%s_%d%s" % (root, i, ext)
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("同名文件太多，先清理旧输出")


def _safe_name(value, fallback="答辩包") -> str:
    name = re.sub(r'[<>:"/\\|?*\r\n\t]', "_", _clean(value)).strip(" .")
    return (name or fallback)[:80]


# ---------- 赛程 ----------
def milestone_status(date_text, today=None, done=False) -> tuple:
    """返回（状态, 剩余文案, 天数）。天数为 None 表示未填或无法解析。"""
    if done:
        return ("已完成", "已完成", None)
    raw = _clean(date_text)
    if not raw:
        return ("未定", "未填日期", None)
    target = _parse_date(raw)
    if target is None:
        return ("日期无效", "检查日期格式", None)
    delta = (target - _today(today)).days
    if delta < 0:
        return ("已过期", "已过 %d 天" % abs(delta), delta)
    if delta == 0:
        return ("今天", "今天截止", 0)
    if delta <= 7:
        return ("临近", "%d 天后" % delta, delta)
    return ("未到", "%d 天后" % delta, delta)


def sorted_events(rows, today=None) -> list:
    out = []
    for row in rows or []:
        item = dict(row)
        state, left, days = milestone_status(item.get("date"), today, item.get("done"))
        item.update({"state": state, "left": left, "days": days})
        out.append(item)

    def key(item):
        done = 1 if item.get("done") else 0
        target = _parse_date(item.get("date"))
        return (done, target is None, target or datetime.date.max, item.get("sort_order") or 0, item.get("id") or 0)

    return sorted(out, key=key)


def event_stats(rows, today=None) -> dict:
    rows = sorted_events(rows, today)
    return {
        "total": len(rows),
        "done": sum(1 for r in rows if r.get("done")),
        "overdue": sum(1 for r in rows if r.get("state") == "已过期"),
        "soon": sum(1 for r in rows if r.get("state") in ("今天", "临近")),
        "undated": sum(1 for r in rows if r.get("state") in ("未定", "日期无效")),
    }


def seed_project(repo, project_id) -> dict:
    """给新建赛事项目补默认赛程与评审矩阵；已有数据不覆盖。"""
    project = repo.find_project(project_id)
    if project is None:
        raise ValueError("项目不存在")
    now = _now()
    added_events = 0
    existing = {e.get("title") for e in repo.list_competition_events(project_id)}
    for idx, (title, _stage) in enumerate(MILESTONE_DEFAULTS):
        if title in existing:
            continue
        date_text = ""
        if title == "报名截止":
            date_text = _clean(project.get("start_date"))
        elif title == "作品提交截止":
            date_text = _clean(project.get("due_date"))
        repo.add_competition_event(project_id, {
            "title": title, "date": date_text,
            "note": "新建项目自动排入，日期可再改", "done": 0,
        })
        added_events += 1
    added_rubric = 0
    existing_rubric = {r.get("criterion") for r in repo.list_competition_rubric(project_id)}
    for criterion, weight in RUBRIC_DEFAULTS:
        if criterion in existing_rubric:
            continue
        repo.add_competition_criterion(project_id, {
            "criterion": criterion, "weight": weight, "score": None,
            "evidence": "", "note": "默认占比，按赛事通知改",
        })
        added_rubric += 1
    repo.add_project_run(project_id, {
        "tool": "赛事模板", "params": "默认赛程 + 默认评审矩阵",
        "status": "成功", "started_at": now, "ended_at": _now(),
        "output": "", "log": "赛程 %d 项、评审项 %d 项" % (added_events, added_rubric),
    })
    return {"events": added_events, "rubric": added_rubric}


# ---------- 报名 ----------
def entry_stats(rows) -> dict:
    rows = rows or []
    return {
        "total": len(rows),
        "confirmed": sum(1 for r in rows if r.get("confirmed")),
        "pending": sum(1 for r in rows if not r.get("confirmed")),
        "leaders": sum(1 for r in rows if r.get("role") == "队长"),
        "members": sum(1 for r in rows if r.get("role") == "队员"),
        "teachers": sum(1 for r in rows if r.get("role") == "指导教师"),
    }


def import_from_roster(repo, project_id, students) -> dict:
    """把选中的班级名单加入报名；按学号去重，空学号按姓名去重。"""
    existing_sid = {_clean(e.get("sid")) for e in repo.list_competition_entries(project_id)
                    if _clean(e.get("sid"))}
    existing_name = {_clean(e.get("name")) for e in repo.list_competition_entries(project_id)
                     if not _clean(e.get("sid"))}
    added, skipped = 0, 0
    for student in students or []:
        sid = _clean(student.get("sid"))
        name = _clean(student.get("who") or student.get("name"))
        if not name:
            skipped += 1
            continue
        if (sid and sid in existing_sid) or (not sid and name in existing_name):
            skipped += 1
            continue
        try:
            repo.add_competition_entry(project_id, {
                "name": name, "sid": sid, "role": "队员",
                "contact": "", "confirmed": 1, "note": "从班级名单导入",
            })
        except Exception:
            skipped += 1
            continue
        added += 1
        if sid:
            existing_sid.add(sid)
        else:
            existing_name.add(name)
    return {"added": added, "skipped": skipped}


def export_entries(repo, project_id, path) -> dict:
    rows = repo.list_competition_entries(project_id)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["序号", "姓名", "学号", "角色", "联系方式", "已确认", "备注"])
        for i, row in enumerate(rows, 1):
            writer.writerow([i, row.get("name"), row.get("sid"), row.get("role"),
                             row.get("contact"), "是" if row.get("confirmed") else "否",
                             row.get("note")])
    return {"path": path, "count": len(rows)}


# ---------- 评审矩阵 ----------
def rubric_stats(rows) -> dict:
    rows = rows or []
    weights = []
    weighted = 0.0
    scored = 0
    for row in rows:
        try:
            weight = max(0, min(100, int(row.get("weight") or 0)))
        except (TypeError, ValueError):
            weight = 0
        weights.append(weight)
        score = row.get("score")
        if score not in ("", None):
            try:
                score = max(0, min(100, int(score)))
                scored += 1
            except (TypeError, ValueError):
                score = None
            if score is not None:
                weighted += score * weight / 100.0
    total_weight = sum(weights)
    return {
        "total": len(rows),
        "weight": total_weight,
        "weighted": round(weighted, 1),
        "scored": scored,
        "complete": bool(rows) and total_weight == 100 and scored == len(rows),
        "aligned": total_weight == 100,
    }


def rubric_text(rows) -> str:
    st = rubric_stats(rows)
    if not st["total"]:
        return "还没有评审项；先按赛事通知拆评分项与权重。"
    text = "评审项 %d · 权重合计 %d%% · 自评加权 %.1f" % (
        st["total"], st["weight"], st["weighted"])
    if not st["aligned"]:
        text += " · 权重未对齐 100%"
    if st["scored"] < st["total"]:
        text += " · 还有 %d 项没自评" % (st["total"] - st["scored"])
    return text


def export_rubric(repo, project_id, path) -> dict:
    rows = repo.list_competition_rubric(project_id)
    st = rubric_stats(rows)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["序号", "评分项", "权重%", "自评", "加权得分", "证据 / 对照", "备注"])
        for i, row in enumerate(rows, 1):
            try:
                weight = int(row.get("weight") or 0)
            except (TypeError, ValueError):
                weight = 0
            score = row.get("score")
            weighted = ""
            if score not in ("", None):
                try:
                    weighted = "%.1f" % (float(score) * weight / 100.0)
                except (TypeError, ValueError):
                    weighted = ""
            writer.writerow([i, row.get("criterion"), weight,
                             "" if score is None else score, weighted,
                             row.get("evidence"), row.get("note")])
        writer.writerow([])
        writer.writerow(["合计", "", st["weight"], "", "%.1f" % st["weighted"], "", ""])
    return {"path": path, "count": len(rows), "stats": st}


# ---------- 提交校验 ----------
def default_rules() -> dict:
    return {
        "exts": list(DEFAULT_SUBMIT_EXTS),
        "max_file_mb": DEFAULT_MAX_FILE_MB,
        "max_total_mb": DEFAULT_MAX_TOTAL_MB,
        "max_files": DEFAULT_MAX_FILES,
        "name_regex": "",
        "keyword": "",
    }


def _parse_exts(value) -> tuple:
    if isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        parts = re.split(r"[,，;；\s]+", _clean(value))
    out = []
    for part in parts:
        token = _clean(part).lower()
        if not token:
            continue
        if not token.startswith("."):
            token = "." + token
        if token not in out:
            out.append(token)
    return tuple(out)


def normalize_rules(rules=None) -> dict:
    base = default_rules()
    base.update(rules or {})
    exts = _parse_exts(base.get("exts"))
    if not exts:
        raise ValueError("必需格式不能为空，例如 .pdf,.zip")
    try:
        max_file = float(base.get("max_file_mb") or 0)
    except (TypeError, ValueError):
        raise ValueError("单文件上限应为数字")
    try:
        max_total = float(base.get("max_total_mb") or 0)
    except (TypeError, ValueError):
        raise ValueError("总大小上限应为数字")
    try:
        max_files = int(base.get("max_files") or 0)
    except (TypeError, ValueError):
        raise ValueError("文件数上限应为整数")
    if max_file <= 0 or max_total <= 0 or max_files <= 0:
        raise ValueError("大小与文件数上限都要大于 0")
    regex = _clean(base.get("name_regex"))
    if regex:
        try:
            re.compile(regex)
        except re.error as e:
            raise ValueError("命名正则不合法：%s" % e)
    return {
        "exts": exts,
        "max_file_mb": max_file,
        "max_total_mb": max_total,
        "max_files": max_files,
        "name_regex": regex,
        "keyword": _clean(base.get("keyword")),
    }


def rules_text(rules) -> str:
    rules = normalize_rules(rules)
    text = "%s；单文件≤%gMB；总≤%gMB；≤%d 个" % (
        "、".join(rules["exts"]), rules["max_file_mb"],
        rules["max_total_mb"], rules["max_files"])
    if rules["name_regex"]:
        text += "；命名匹配 %s" % rules["name_regex"]
    if rules["keyword"]:
        text += "；文件名含“%s”" % rules["keyword"]
    return text


def _scan(folder) -> list:
    files = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")
                   and d not in ("__MACOSX",) and not d.startswith("_提交校验")]
        for name in names:
            if name.startswith(REPORT_PREFIX) or name.startswith(MANIFEST_PREFIX):
                continue
            if name in (".DS_Store", "Thumbs.db"):
                continue
            full = os.path.join(root, name)
            if not os.path.isfile(full):
                continue
            files.append((full, os.path.relpath(full, folder)))
    return sorted(files, key=lambda x: x[1].lower())


def _name_check(name, rules) -> tuple:
    notes = []
    if len(name) > NAME_MAX:
        notes.append("文件名超过 %d 字" % NAME_MAX)
    if any(ch in name for ch in ILLEGAL_NAME_CHARS):
        notes.append("含非法字符")
    if rules.get("name_regex") and not re.fullmatch(rules["name_regex"], name):
        notes.append("不符合命名正则")
    if rules.get("keyword") and rules["keyword"] not in name:
        notes.append("缺关键词“%s”" % rules["keyword"])
    return (not notes, "；".join(notes) or "符合命名")


def _report_dir(folder) -> str:
    parent = os.path.dirname(os.path.abspath(folder.rstrip(os.sep))) or os.path.abspath(folder)
    target = os.path.join(parent, "_提交校验")
    os.makedirs(target, exist_ok=True)
    run_dir = _unique_dir(os.path.join(target, "提交校验_" + _stamp()))
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def validate_submission(folder, rules=None) -> dict:
    folder = os.path.abspath(_clean(folder))
    if not folder or not os.path.isdir(folder):
        raise ValueError("提交目录不存在")
    rules = normalize_rules(rules)
    started = _now()
    files = _scan(folder)
    rows = []
    total_bytes = 0
    for full, rel in files:
        name = os.path.basename(full)
        ext = os.path.splitext(name)[1].lower()
        try:
            size = os.path.getsize(full)
        except OSError:
            size = 0
        total_bytes += size
        format_ok = ext in rules["exts"]
        fmt_note = "格式通过" if format_ok else "格式不允许（%s）" % (ext or "无扩展名")
        name_ok, name_note = _name_check(name, rules)
        limit_bytes = rules["max_file_mb"] * 1024 * 1024
        if size <= 0:
            size_note = "空文件"
            size_ok = False
        elif size > limit_bytes:
            size_note = "超过单文件上限 %g MB" % rules["max_file_mb"]
            size_ok = False
        else:
            size_note = ""
            size_ok = True
        ok = format_ok and name_ok and size_ok
        notes = [x for x in (fmt_note if not format_ok else "",
                             name_note if not name_ok else "",
                             size_note) if x]
        rows.append({
            "file": rel, "name": name, "ext": ext or "(无扩展名)",
            "size": size, "format": "通过" if format_ok else "不允许",
            "naming": "通过" if name_ok else "不符合",
            "result": "通过" if ok else "不通过",
            "note": "；".join(notes) or "格式、命名、大小均通过",
        })
    passed = sum(1 for r in rows if r["result"] == "通过")
    failed = len(rows) - passed
    checks = []
    checks.append({
        "name": "非空包", "ok": bool(rows),
        "note": "%d 个文件" % len(rows) if rows else "目录里没有可校验文件",
    })
    checks.append({
        "name": "必需格式", "ok": bool(rows) and all(
            any(r["ext"] == ext and r["result"] == "通过" for r in rows)
            for ext in rules["exts"]),
        "note": "需要 " + "、".join(rules["exts"]),
    })
    checks.append({
        "name": "文件数", "ok": 0 < len(rows) <= rules["max_files"],
        "note": "%d / %d" % (len(rows), rules["max_files"]),
    })
    checks.append({
        "name": "单文件大小", "ok": bool(rows) and all(
            r["size"] <= rules["max_file_mb"] * 1024 * 1024 for r in rows),
        "note": "上限 %g MB" % rules["max_file_mb"],
    })
    checks.append({
        "name": "总大小", "ok": total_bytes <= rules["max_total_mb"] * 1024 * 1024,
        "note": "%s / %g MB" % (_human_size(total_bytes), rules["max_total_mb"]),
    })
    if rules["keyword"]:
        checks.append({
            "name": "关键词", "ok": any(rules["keyword"] in r["name"] for r in rows),
            "note": "文件名含“%s”" % rules["keyword"],
        })
    ok_all = bool(rows) and failed == 0 and all(c["ok"] for c in checks)
    report_dir = _report_dir(folder)
    report_csv = os.path.join(report_dir, "提交校验.csv")
    report_json = os.path.join(report_dir, "提交校验.json")
    with open(report_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["序号", "文件", "格式", "大小", "单文件格式", "命名", "结论", "说明"])
        for i, row in enumerate(rows, 1):
            writer.writerow([i, row["file"], row["ext"], _human_size(row["size"]),
                             row["format"], row["naming"], row["result"], row["note"]])
        writer.writerow([])
        writer.writerow(["包检查", "结论", "说明"])
        for c in checks:
            writer.writerow([c["name"], "通过" if c["ok"] else "不通过", c["note"]])
    payload = {
        "kind": "competition-submission", "folder": folder,
        "started_at": started, "ended_at": _now(),
        "rules": {**rules, "exts": list(rules["exts"])},
        "rules_text": rules_text(rules),
        "rows": rows, "checks": checks,
        "total": len(rows), "passed": passed, "failed": failed,
        "total_bytes": total_bytes, "ok": ok_all,
    }
    with open(report_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    result = dict(payload)
    result.update({"report_csv": report_csv, "report_json": report_json,
                   "report_dir": report_dir, "summary": submission_summary(payload)})
    return result


def submission_summary(result) -> str:
    if not result:
        return "还没有做提交校验。"
    text = "提交校验：%d 个文件，通过 %d，不通过 %d；%s" % (
        result.get("total", 0), result.get("passed", 0), result.get("failed", 0),
        "整包通过" if result.get("ok") else "整包未通过")
    bad = [c for c in result.get("checks") or [] if not c.get("ok")]
    if bad:
        text += "；卡在 " + "、".join(c["name"] for c in bad)
    return text


# ---------- 项目留痕 ----------
def _mark_deliverable(repo, project_id, keyword, status="已通过"):
    rows = repo.list_deliverables(project_id)
    for row in rows:
        if keyword in (row.get("name") or ""):
            repo.update_deliverable(row["id"], {"status": status})
            return row["name"]
    repo.add_deliverable(project_id, {
        "name": keyword, "stage": "交付", "status": status,
        "required": True, "note": "赛事工作台补建",
    })
    return keyword


def record_submission(repo, project_id, result, operator="系统") -> dict:
    if not result:
        raise ValueError("没有校验结果")
    repo.add_project_run(project_id, {
        "tool": "提交校验",
        "params": result.get("rules_text") or "",
        "status": "成功" if result.get("ok") else "不通过",
        "started_at": result.get("started_at") or "",
        "ended_at": result.get("ended_at") or "",
        "output": result.get("report_csv") or "",
        "log": submission_summary(result),
    })
    repo.set_project_gate(project_id, "提交校验",
                          "通过" if result.get("ok") else "不通过",
                          note=submission_summary(result), checked_by=operator)
    _mark_deliverable(repo, project_id, "提交校验",
                      "已通过" if result.get("ok") else "已驳回")
    return {"gate": "提交校验", "ok": bool(result.get("ok")),
            "deliverable": "提交校验"}


# ---------- 答辩包 ----------
def _outline(project, events, entries, rubric, files, submission=None) -> str:
    lines = ["# %s · 答辩包" % (project.get("name") or "赛事项目"), "",
             "生成时间：%s" % _now(), "",
             "## 一、项目目标", ""]
    lines.append(project.get("goal") or "还没有写目标；在项目工作台补一句。")
    lines += ["", "## 二、赛程", ""]
    if events:
        lines += ["| 事项 | 日期 | 状态 |", "| --- | --- | --- |"]
        for ev in sorted_events(events):
            lines.append("| %s | %s | %s |" % (
                ev.get("title"), ev.get("date") or "未定", ev.get("state")))
    else:
        lines.append("还没有排赛程。")
    lines += ["", "## 三、报名与分工", ""]
    st = entry_stats(entries)
    lines.append("报名 %d 人，已确认 %d 人，待确认 %d 人；队长 %d，队员 %d，指导教师 %d。" % (
        st["total"], st["confirmed"], st["pending"], st["leaders"],
        st["members"], st["teachers"]))
    if entries:
        lines += ["", "| 姓名 | 学号 | 角色 | 确认 |", "| --- | --- | --- | --- |"]
        for en in entries:
            lines.append("| %s | %s | %s | %s |" % (
                en.get("name"), en.get("sid"), en.get("role"),
                "是" if en.get("confirmed") else "否"))
    lines += ["", "## 四、评审矩阵", ""]
    rs = rubric_stats(rubric)
    lines.append("权重合计 %d%%，自评加权 %.1f；%s。" % (
        rs["weight"], rs["weighted"],
        "权重已对齐" if rs["aligned"] else "权重还没对齐 100%"))
    if rubric:
        lines += ["", "| 评分项 | 权重 | 自评 | 证据 / 对照 |",
                  "| --- | --- | --- | --- |"]
        for rb in rubric:
            lines.append("| %s | %d%% | %s | %s |" % (
                rb.get("criterion"), int(rb.get("weight") or 0),
                "未评" if rb.get("score") is None else rb.get("score"),
                (rb.get("evidence") or "").replace("\n", " ")))
    lines += ["", "## 五、提交校验", ""]
    if submission:
        lines.append(submission_summary(submission))
        for c in submission.get("checks") or []:
            lines.append("- %s：%s（%s）" % (
                c["name"], "通过" if c["ok"] else "不通过", c["note"]))
    else:
        lines.append("本次没有附带提交校验结果；提交前先在提交校验页跑一遍。")
    lines += ["", "## 六、答辩结构（建议）", "",
              "1. 30 秒：问题是什么，为什么现在做。",
              "2. 2 分钟：方案与关键取舍，用一页图讲清。",
              "3. 2 分钟：现场演示或证据，先跑通再讲细节。",
              "4. 1 分钟：对照评审标准，逐项给证据。",
              "5. 30 秒：风险、边界与下一步。",
              "", "## 七、包内文件", "",
              "| 文件 | 大小 | SHA256 |", "| --- | --- | --- |"]
    for item in files:
        lines.append("| %s | %s | `%s` |" % (
            item["name"], _human_size(item["size"]), item["sha256"]))
    lines.append("")
    return "\n".join(lines)


def make_defense_package(repo, project_id, files, outdir, name="", include_zip=True,
                         submission=None, operator="系统") -> dict:
    project = repo.find_project(project_id)
    if project is None:
        raise ValueError("项目不存在")
    files = [os.path.abspath(_clean(f)) for f in (files or []) if _clean(f)]
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        raise ValueError("答辩包至少要有一个文件")
    outdir = os.path.abspath(_clean(outdir))
    if not outdir:
        raise ValueError("先选答辩包输出目录")
    os.makedirs(outdir, exist_ok=True)
    base = _safe_name(name or (project.get("name") + "_答辩包"))
    root = _unique_dir(os.path.join(outdir, base))
    os.makedirs(root)
    manifest_rows = []
    copied = 0
    used = set()
    for src in files:
        raw = os.path.basename(src) or "文件"
        stem, ext = os.path.splitext(raw)
        dst_name = raw
        i = 2
        while dst_name.lower() in used or os.path.exists(os.path.join(root, dst_name)):
            dst_name = "%s_%d%s" % (stem, i, ext)
            i += 1
        used.add(dst_name.lower())
        dst = os.path.join(root, dst_name)
        shutil.copy2(src, dst)
        src_hash = _sha256(src)
        out_hash = _sha256(dst)
        if src_hash != out_hash:
            raise RuntimeError("复制后哈希不一致：%s" % raw)
        copied += 1
        manifest_rows.append({
            "name": dst_name, "size": os.path.getsize(dst),
            "sha256": out_hash, "source": src,
        })
    manifest_csv = os.path.join(root, "_答辩包清单.csv")
    with open(manifest_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["序号", "文件", "字节", "SHA256", "来源"])
        for i, item in enumerate(manifest_rows, 1):
            writer.writerow([i, item["name"], item["size"], item["sha256"], item["source"]])
    outline = os.path.join(root, "_答辩提纲.md")
    with open(outline, "w", encoding="utf-8") as f:
        f.write(_outline(project, repo.list_competition_events(project_id),
                         repo.list_competition_entries(project_id),
                         repo.list_competition_rubric(project_id),
                         manifest_rows, submission))
    zip_path = ""
    zip_size = 0
    zip_hash = ""
    if include_zip:
        zip_path = _unique_file(os.path.join(outdir, base + ".zip"))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in manifest_rows:
                zf.write(os.path.join(root, item["name"]), item["name"])
            zf.write(manifest_csv, os.path.basename(manifest_csv))
            zf.write(outline, os.path.basename(outline))
        zip_size = os.path.getsize(zip_path)
        zip_hash = _sha256(zip_path)
    total_bytes = sum(item["size"] for item in manifest_rows)
    result = {
        "root": root, "zip": zip_path, "manifest": manifest_csv, "outline": outline,
        "files": manifest_rows, "total": copied, "total_bytes": total_bytes,
        "zip_size": zip_size, "zip_sha256": zip_hash,
        "summary": "答辩包 %d 个文件 / %s；清单与提纲已写%s" % (
            copied, _human_size(total_bytes),
            "；ZIP 已生成" if zip_path else "；未打 ZIP"),
    }
    if zip_path:
        repo.add_project_asset(project_id, {
            "name": os.path.basename(zip_path), "path": zip_path, "kind": "zip",
            "size": zip_size, "sha256": zip_hash,
            "note": "赛事答辩包 · %d 个文件" % copied,
        })
    repo.add_project_run(project_id, {
        "tool": "答辩包", "params": "文件 %d 个；ZIP=%s" % (copied, "是" if zip_path else "否"),
        "status": "成功", "started_at": _now(), "ended_at": _now(),
        "output": zip_path or root, "log": result["summary"],
    })
    repo.set_project_gate(project_id, "答辩包", "通过",
                          note=result["summary"], checked_by=operator)
    _mark_deliverable(repo, project_id, "答辩包", "已通过")
    return result


def project_summary(repo, project_id, today=None) -> dict:
    events = repo.list_competition_events(project_id)
    entries = repo.list_competition_entries(project_id)
    rubric = repo.list_competition_rubric(project_id)
    return {
        "events": event_stats(events, today),
        "entries": entry_stats(entries),
        "rubric": rubric_stats(rubric),
        "text": "赛程 %d 项（临近/今天 %d，过期 %d） · 报名 %d 人（确认 %d） · 评审 %d 项（权重 %d%%）" % (
            event_stats(events, today)["total"],
            event_stats(events, today)["soon"],
            event_stats(events, today)["overdue"],
            entry_stats(entries)["total"], entry_stats(entries)["confirmed"],
            rubric_stats(rubric)["total"], rubric_stats(rubric)["weight"]),
    }

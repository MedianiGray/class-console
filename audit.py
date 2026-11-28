# -*- coding: utf-8 -*-
"""审计能力：流转链之外的完整性检查、恢复预览与证据包导出。

不依赖界面，所有函数都可用临时目录直接测试。原则：
  - 只报告问题，不静默改台账；修复动作必须由用户明确触发。
  - 磁盘上多出的文件只列出，绝不自动删除。
  - 证据包用标准 CSV / TXT / ZIP，评审方不装软件也能读懂。
"""

import csv
import datetime
import io
import json
import os
import zipfile
from pathlib import Path

import archive
from version import VERSION

MISSING = "缺失"
MAX_LIST = 200


def _norm(path) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    return os.path.normcase(os.path.abspath(text))


def _is_abs_path(text) -> bool:
    text = str(text or "").strip()
    return bool(text) and (os.path.isabs(text) or
                           (len(text) > 2 and text[1] == ":"))


def _relative(path, base):
    try:
        return os.path.relpath(str(path), str(base))
    except ValueError:
        return str(path)


def read_index(base=None) -> list:
    """读取 _归档索引.csv；不存在或格式异常返回空列表。"""
    path = Path(base) if base else archive.root()
    index = path / archive.INDEX_NAME
    if not index.exists():
        return []
    try:
        with open(index, "r", encoding="utf-8-sig", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def check_integrity(docs, base=None) -> dict:
    """索引 ↔ 磁盘 ↔ 台账三方比对。返回可展示的问题清单。"""
    base = Path(base) if base else archive.root()
    index_path = base / archive.INDEX_NAME
    index_rows = read_index(base)
    index_by_code = {}
    for row in index_rows:
        code = str(row.get("编号") or "").strip()
        if code:
            index_by_code[code] = row

    result = {
        "root": str(base), "checked_at": datetime.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"), "index_exists": index_path.exists(),
        "total": len(docs), "archived": 0,
        "missing_file": [], "no_archive_path": [], "source_missing": [],
        "index_missing": [], "index_mismatch": [], "index_orphan": [],
        "orphan_file": [],
    }
    doc_codes = set()
    archived_paths = set()
    for d in docs:
        if not isinstance(d, dict):
            continue
        code = str(d.get("code") or "").strip()
        name = str(d.get("name") or "未命名")
        status = str(d.get("status") or "")
        arch = str(d.get("arch") or "").strip()
        if code:
            doc_codes.add(code)
        if status == "已归档" or arch:
            result["archived"] += 1
        if status == "已归档":
            if not arch:
                result["no_archive_path"].append(
                    {"code": code, "name": name, "detail": "已归档但未记录归档路径"})
            elif not os.path.exists(arch):
                result["missing_file"].append(
                    {"code": code, "name": name, "detail": arch})
            else:
                archived_paths.add(_norm(arch))
        src = str(d.get("path") or d.get("file") or "").strip()
        if src and _is_abs_path(src) and not os.path.exists(src):
            result["source_missing"].append(
                {"code": code, "name": name, "detail": src})
        if code and (status == "已归档" or arch):
            row = index_by_code.get(code)
            if not row:
                result["index_missing"].append(
                    {"code": code, "name": name, "detail": "索引中没有该编号"})
            else:
                indexed = str(row.get("归档文件") or "").strip()
                if arch and indexed and _norm(indexed) != _norm(arch):
                    result["index_mismatch"].append(
                        {"code": code, "name": name,
                         "detail": "台账：%s｜索引：%s" % (arch, indexed)})
    for code, row in index_by_code.items():
        if code not in doc_codes:
            result["index_orphan"].append(
                {"code": code, "name": str(row.get("材料名称") or ""),
                 "detail": "索引有记录，台账无此编号"})

    if base.exists():
        for p in base.rglob("*"):
            if not p.is_file() or p.name == archive.INDEX_NAME:
                continue
            if _norm(p) in archived_paths:
                continue
            result["orphan_file"].append(
                {"code": "", "name": _relative(p, base),
                 "detail": "%d 字节" % p.stat().st_size})

    counts = {k: len(v) for k, v in result.items() if isinstance(v, list)}
    result["counts"] = counts
    result["issues"] = sum(counts.values())
    result["ok"] = result["issues"] == 0
    return result


def rebuild_index(docs, base=None) -> str:
    """按当前台账重写索引；只改索引文件，不碰材料文件。"""
    return archive.write_index(docs, base)


def repair_placements(repo, base=None) -> dict:
    """对归档文件缺失、但源文件仍在的记录重新归位，并重建索引。"""
    base = Path(base) if base else archive.root()
    docs = repo.list_docs()
    placed, failed = [], []
    for d in docs:
        if d.get("status") != "已归档":
            continue
        arch = str(d.get("arch") or "").strip()
        if arch and os.path.exists(arch):
            continue
        src = archive.source_file(d)
        if not src:
            failed.append({"code": d.get("code") or "", "name": d.get("name") or "",
                           "detail": "归档文件与源文件都不在本机"})
            continue
        res = archive.place(d, base)
        if res.get("path"):
            repo.set_arch(d.get("id"), res["path"], "完整性检查", "系统")
            placed.append({"code": d.get("code") or "", "name": d.get("name") or "",
                           "detail": res["path"]})
        else:
            failed.append({"code": d.get("code") or "", "name": d.get("name") or "",
                           "detail": res.get("note") or "归位失败"})
    index_path = rebuild_index(repo.list_docs(), base)
    return {"placed": placed, "failed": failed, "index": index_path}


def _parse_day(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("日期格式应为 YYYY-MM-DD：%s" % value)


def _doc_day(doc, events):
    for ev in events:
        if ev.get("act") == "提交":
            text = str(ev.get("time") or "")[:10]
            try:
                return datetime.datetime.strptime(text, "%Y-%m-%d").date()
            except ValueError:
                break
    text = str(doc.get("time") or "").strip()
    for fmt, sample in (("%Y-%m-%d %H:%M", text[:16]),
                        ("%Y-%m-%d", text[:10]),
                        ("%m-%d %H:%M", text[:11])):
        try:
            day = datetime.datetime.strptime(sample, fmt)
            return day.date().replace(year=datetime.date.today().year
                                      if fmt.startswith("%m") else day.year)
        except ValueError:
            continue
    return None


def _write_csv(path, heads, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(heads)
        for row in rows:
            w.writerow(row)


def export_evidence(repo, dest, cat="全部", start="", end="",
                    include_files=False) -> dict:
    """导出 ZIP 证据包；文件名与 README 保证脱离软件可读。"""
    start_day = _parse_day(start)
    end_day = _parse_day(end)
    if start_day and end_day and start_day > end_day:
        raise ValueError("起始日期不能晚于结束日期")
    dest = Path(dest)
    if dest.suffix.lower() != ".zip":
        dest = dest.with_suffix(".zip")
    docs = repo.list_docs(cat=cat or "全部")
    all_events = repo.list_all_events()
    by_doc = {}
    for ev in all_events:
        by_doc.setdefault(ev.get("doc_id"), []).append(ev)
    selected, undated = [], 0
    for d in docs:
        day = _doc_day(d, by_doc.get(d.get("id"), []))
        if day is None:
            undated += 1
        elif start_day and day < start_day:
            continue
        elif end_day and day > end_day:
            continue
        selected.append(d)
    logs = repo.list_logs()

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp = Path(str(dest) + ".tmp")
    base = archive.root()
    file_count = 0
    warnings = []
    if undated:
        warnings.append("有 %d 条材料无法从时间字段解析日期，已保留在包内。" % undated)
    if not base.exists():
        warnings.append("归档根目录尚不存在，文件树为空。")
    if not selected:
        warnings.append("当前筛选没有材料，证据包仅含日志与说明。")

    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            mat_rows = []
            for d in selected:
                tpl = d.get("form_type") or "general"
                mat_rows.append([
                    d.get("code", ""), d.get("name", ""), d.get("cat", ""),
                    tpl, d.get("who", ""), d.get("sid", ""), d.get("time", ""),
                    d.get("status", ""), d.get("reason", ""),
                    d.get("path") or d.get("file") or "", d.get("arch", ""),
                    d.get("note", ""),
                    json.dumps(d.get("extra") or {}, ensure_ascii=False)
                    if isinstance(d.get("extra"), dict) else ""])
            _write_csv(tmp.with_name(tmp.name + ".materials.csv"),
                       ["编号", "材料名称", "类别", "表单类型", "提交人", "学号",
                        "提交时间", "状态", "审核意见", "本地文件", "归档文件",
                        "说明", "附加字段"], mat_rows)
            z.write(tmp.with_name(tmp.name + ".materials.csv"), "材料清单.csv")
            os.remove(tmp.with_name(tmp.name + ".materials.csv"))

            idx_rows = [[d.get("code", ""), d.get("name", ""), d.get("cat", ""),
                         d.get("sid", ""), d.get("who", ""), d.get("status", ""),
                         d.get("path") or d.get("file") or "", d.get("arch", "")]
                        for d in selected]
            _write_csv(tmp.with_name(tmp.name + ".index.csv"),
                       ["编号", "材料名称", "类别", "学号", "姓名", "状态",
                        "本地文件", "归档文件"], idx_rows)
            z.write(tmp.with_name(tmp.name + ".index.csv"), "归档索引.csv")
            os.remove(tmp.with_name(tmp.name + ".index.csv"))

            log_rows = [[l.get("time", ""), l.get("who", ""), l.get("role", ""),
                         l.get("act", ""), l.get("obj", ""), l.get("src", "本机")]
                        for l in logs]
            _write_csv(tmp.with_name(tmp.name + ".logs.csv"),
                       ["时间", "操作人", "角色", "动作", "对象", "来源"], log_rows)
            z.write(tmp.with_name(tmp.name + ".logs.csv"), "操作日志.csv")
            os.remove(tmp.with_name(tmp.name + ".logs.csv"))

            tree_lines = []
            if base.exists():
                for p in sorted(base.rglob("*")):
                    if p.is_file():
                        rel = _relative(p, base)
                        tree_lines.append("%s\t%d 字节\t%s" % (
                            rel, p.stat().st_size,
                            datetime.datetime.fromtimestamp(
                                p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")))
            z.writestr("文件树.txt",
                       "归档根：%s\n生成时间：%s\n\n相对路径\t大小\t修改时间\n%s\n" % (
                           base, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                           "\n".join(tree_lines) if tree_lines else "（空）"))

            readme = """班级材料证据包
================

生成时间：%s
软件版本：v%s
筛选类别：%s
提交日期：%s 至 %s
材料数：%d 条；操作日志：%d 条

文件说明
--------
材料清单.csv   每条材料的编号、名称、类别、提交人、学号、状态、文件位置与附加字段。
归档索引.csv   台账与归档文件的对照表，可按编号定位磁盘文件。
操作日志.csv   本机的提交、归档、驳回、查看等操作留痕。
文件树.txt     归档根目录的相对路径、大小与修改时间。
归档文件/      可选附带的原始文件，目录结构与归档根一致。

阅读口径
--------
1. 状态「待审核」表示已登记但尚未审核；「已归档」表示材料已通过并落盘。
2. 「归档文件」为空并不等于材料丢失，可能是尚未归档或只建了目录。
3. 文件树与归档索引为空时，请确认归档根是否已设置并有文件。
4. CSV 使用 UTF-8 BOM，Excel 可直接打开；若乱码请选「数据→从文本导入」。
%s
""" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), VERSION,
       cat or "全部", start or "不限", end or "不限", len(selected), len(logs),
       ("\n注意：\n- " + "\n- ".join(warnings) + "\n") if warnings else "")
            z.writestr("README.txt", readme)

            manifest = {
                "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "version": VERSION, "archive_root": str(base),
                "filters": {"cat": cat, "start": start, "end": end},
                "counts": {"docs": len(selected), "logs": len(logs),
                           "undated": undated},
                "warnings": warnings,
            }
            z.writestr("manifest.json",
                       json.dumps(manifest, ensure_ascii=False, indent=2))

            if include_files:
                seen = set()
                for d in selected:
                    arch = str(d.get("arch") or "").strip()
                    if not arch or not os.path.isfile(arch):
                        continue
                    key = _norm(arch)
                    if key in seen:
                        continue
                    try:
                        rel = Path(arch).resolve().relative_to(base.resolve())
                    except (ValueError, OSError):
                        continue
                    seen.add(key)
                    z.write(arch, str(Path("归档文件") / rel))
                    file_count += 1
        os.replace(tmp, dest)
    finally:
        for leftover in (tmp, tmp.with_name(tmp.name + ".materials.csv"),
                         tmp.with_name(tmp.name + ".index.csv"),
                         tmp.with_name(tmp.name + ".logs.csv")):
            try:
                if leftover.exists():
                    leftover.unlink()
            except OSError:
                pass
    try:
        repo.add_log("证据包", "%s（%d 条材料）" % (dest.name, len(selected)),
                     "系统", "审计", src="本机")
    except Exception:
        pass
    return {"path": str(dest), "docs": len(selected), "logs": len(logs),
            "files": file_count, "size": dest.stat().st_size,
            "warnings": warnings}


def backup_preview(data, repo) -> dict:
    """导入前的覆盖预览：只算数量与风险，不改库。"""
    if not isinstance(data, dict):
        return {"ok": False, "text": "备份文件结构不正确，缺少 docs / logs 数据段。"}
    if data.get("app") and data.get("app") != "class-console":
        return {"ok": False, "text": "这不是本工作台导出的备份，已拒绝导入。"}
    docs, logs = data.get("docs"), data.get("logs")
    if not isinstance(docs, list) or not isinstance(logs, list):
        return {"ok": False, "text": "备份文件结构不正确，docs / logs 应为列表。"}
    valid_docs = [d for d in docs if isinstance(d, dict)]
    valid_logs = [l for l in logs if isinstance(l, dict)]
    if len(valid_docs) != len(docs) or len(valid_logs) != len(logs):
        return {"ok": False,
                "text": "有 %d 条记录格式异常，为避免丢数据未导入。"
                        % (len(docs) - len(valid_docs) + len(logs) - len(valid_logs))}
    attachments = data.get("attachments") if isinstance(
        data.get("attachments"), list) else []
    roster = data.get("roster") if isinstance(data.get("roster"), list) else []
    tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
    templates = data.get("templates") if isinstance(
        data.get("templates"), list) else []
    exemptions = data.get("exemptions") if isinstance(
        data.get("exemptions"), list) else []
    followups = data.get("followups") if isinstance(
        data.get("followups"), list) else []
    projects = data.get("projects") if isinstance(
        data.get("projects"), list) else []
    project_deliverables = data.get("project_deliverables") if isinstance(
        data.get("project_deliverables"), list) else []
    project_events = data.get("project_events") if isinstance(
        data.get("project_events"), list) else []
    counts = data.get("counts")
    if counts is not None:
        if not isinstance(counts, dict):
            return {"ok": False, "text": "备份声明的 counts 元数据格式不正确，已拒绝导入。"}
        actual = {"docs": len(valid_docs), "logs": len(valid_logs),
                  "roster": len(roster), "tasks": len(tasks),
                  "attachments": len(attachments),
                  "templates": len(templates),
                  "exemptions": len(exemptions),
                  "followups": len(followups),
                  "projects": len(projects),
                  "project_deliverables": len(project_deliverables),
                  "project_events": len(project_events)}
        for key, now in actual.items():
            if key not in counts:
                continue
            try:
                declared = int(counts.get(key))
            except (TypeError, ValueError):
                return {"ok": False,
                        "text": "备份声明的 %s 条数不是整数，已拒绝导入。" % key}
            if declared != now:
                return {"ok": False,
                        "text": "备份条数对不上：%s 声明 %d 条，实际 %d 条；"
                                "为避免丢数据未导入。" % (key, declared, now)}
    current = repo.stats()
    current_logs = len(repo.list_logs())
    codes = [str(d.get("code") or "").strip() for d in valid_docs]
    dup = len(codes) - len(set(c for c in codes if c))
    warnings = []
    if not data.get("events"):
        warnings.append("备份不含流转事件，恢复后将按当前状态自动补录最小节点。")
    if not templates:
        warnings.append("备份不含模板附加字段，恢复时保留本机现有配置。")
    if not exemptions and not followups:
        warnings.append("备份不含免交 / 延期与催交 / 回执登记，恢复后服务留痕为空。")
    if dup:
        warnings.append("备份中有 %d 个重复编号，恢复后仍会保留，需要人工核对。" % dup)
    text = (
        "导入将覆盖本机当前数据，且不可撤销。\n\n"
        "材料：当前 %d 条 → 备份 %d 条\n"
        "日志：当前 %d 条 → 备份 %d 条\n"
        "名单：当前 %d 人 → 备份 %d 人\n"
        "任务：当前 %d 条 → 备份 %d 条\n"
        "附件：备份 %d 个\n"
        "模板附加字段：备份 %d 项\n"
        "免交 / 延期：备份 %d 条\n"
        "催交 / 回执：备份 %d 条\n"
        "项目：备份 %d 个 · 交付物 %d 项 · 项目记录 %d 条\n" % (
            current["total"], len(valid_docs), current_logs, len(valid_logs),
            len(repo.list_roster()), len(roster), len(repo.list_tasks()),
            len(tasks), len(attachments), len(templates),
            len(exemptions), len(followups),
            len(projects), len(project_deliverables), len(project_events)))
    if warnings:
        text += "\n注意：\n- " + "\n- ".join(warnings) + "\n"
    text += "\n确定用备份覆盖本机数据吗？"
    return {"ok": True, "text": text,
            "counts": {"docs": len(valid_docs), "logs": len(valid_logs),
                       "roster": len(roster), "tasks": len(tasks),
                       "attachments": len(attachments), "templates": len(templates),
                       "exemptions": len(exemptions), "followups": len(followups),
                       "projects": len(projects),
                       "project_deliverables": len(project_deliverables),
                       "project_events": len(project_events)},
            "warnings": warnings}

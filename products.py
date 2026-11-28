# -*- coding: utf-8 -*-
"""v0.35 产品模板的逻辑层：PRD、架构、BOM、原型、测试、评审门与发布包。

一条闭环：建产品项目 → 写 PRD / 架构 → 列 BOM → 记原型 → 跑测试 →
过评审门 → 出发布包与路演提纲。判定都在这里做成可测试的纯函数，
界面只收集参数和展示结果；不内置 CAD / IDE，也不替用户编造产品内容。
"""

import csv
import datetime
import hashlib
import json
import os
import re
import shutil
import zipfile

SPEC_DEFAULTS = {
    "prd": ("背景与问题", "目标用户", "产品目标", "功能范围",
            "非目标与边界", "验收标准", "风险与依赖"),
    "arch": ("总体架构", "模块与接口", "数据与存储", "部署与依赖"),
}
SPEC_KIND_NAMES = {"prd": "需求文档", "arch": "架构说明"}
BOM_KINDS = ("物料", "模块", "接口", "外包", "其他")
PROTO_STATUS = ("待做", "进行中", "可用", "已冻结")
TEST_RESULTS = ("未测", "通过", "不通过", "阻塞")
TEST_SEVERITIES = ("高", "中", "低")
REVIEW_GATES = ("立项评审", "方案评审", "样机评审", "发布评审")
REVIEW_CONCLUSIONS = ("待评审", "通过", "有条件通过", "驳回")
PASS_CONCLUSIONS = ("通过", "有条件通过")
RELEASE_PREFIX = "_发布清单_"
RELEASE_NOTE = "_发布说明.md"
READINESS_NAME = "_上线检查.json"
ROADSHOW_NAME = "路演提纲.md"


# ---------- 通用 ----------
def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


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


def _safe_name(value, fallback="产品") -> str:
    name = re.sub(r'[<>:"/\\|?*\r\n\t]', "_", _clean(value)).strip(" .")
    return (name or fallback)[:80]


# ---------- PRD / 架构 ----------
def seed_project(repo, project_id) -> dict:
    """补默认 PRD / 架构小节与四道评审门；已有内容不覆盖。"""
    project = repo.find_project(project_id)
    if project is None:
        raise ValueError("项目不存在")
    added_specs = 0
    for kind, sections in SPEC_DEFAULTS.items():
        existing = {row.get("section") for row in repo.list_product_specs(project_id, kind)}
        for section in sections:
            if section in existing:
                continue
            repo.add_product_spec(project_id, {
                "kind": kind, "section": section, "content": "",
            })
            added_specs += 1
    added_reviews = 0
    existing_gates = {row.get("gate") for row in repo.list_product_reviews(project_id)}
    for gate in REVIEW_GATES:
        if gate in existing_gates:
            continue
        repo.add_product_review(project_id, {
            "gate": gate, "conclusion": "待评审", "reviewer": "", "date": "",
            "note": "评审结论与意见由负责人填写",
        })
        repo.set_project_gate(project_id, gate, "待检查", note="产品评审门")
        added_reviews += 1
    repo.add_project_run(project_id, {
        "tool": "产品模板", "params": "默认 PRD / 架构小节 + 四道评审门",
        "status": "成功", "started_at": _now(), "ended_at": _now(),
        "output": "", "log": "小节 %d 个、评审门 %d 道" % (added_specs, added_reviews),
    })
    return {"specs": added_specs, "reviews": added_reviews}


def spec_stats(repo, project_id) -> dict:
    """按 PRD / 架构分别算已填小节与整体完成度。"""
    kinds = {}
    overall_total = overall_filled = 0
    missing = []
    for kind, sections in SPEC_DEFAULTS.items():
        rows = {row.get("section"): row for row in repo.list_product_specs(project_id, kind)}
        total = len(sections)
        filled = sum(1 for s in sections if _clean((rows.get(s) or {}).get("content")))
        empty = [s for s in sections if s not in rows or not _clean(rows.get(s, {}).get("content"))]
        kinds[kind] = {
            "name": SPEC_KIND_NAMES[kind], "total": total, "filled": filled,
            "empty": empty, "complete": total > 0 and filled == total,
            "percent": int(round(filled * 100.0 / total)) if total else 0,
        }
        overall_total += total
        overall_filled += filled
        missing.extend("%s / %s" % (SPEC_KIND_NAMES[kind], s) for s in empty)
    return {
        "kinds": kinds, "total": overall_total, "filled": overall_filled,
        "missing": missing, "complete": overall_total > 0 and overall_filled == overall_total,
        "percent": int(round(overall_filled * 100.0 / overall_total)) if overall_total else 0,
    }


def spec_text(repo, project_id, kind) -> str:
    project = repo.find_project(project_id) or {}
    kind = kind if kind in SPEC_DEFAULTS else "prd"
    rows = {row.get("section"): row for row in repo.list_product_specs(project_id, kind)}
    lines = ["# %s · %s" % (project.get("name") or "产品项目", SPEC_KIND_NAMES[kind]),
             "", "生成时间：%s" % _now(), ""]
    if project.get("goal"):
        lines += ["> " + _clean(project.get("goal")), ""]
    for section in SPEC_DEFAULTS[kind]:
        row = rows.get(section) or {}
        lines += ["## " + section, "", _clean(row.get("content")) or "（待补）", ""]
    extras = [s for s in rows if s not in SPEC_DEFAULTS[kind]]
    for section in extras:
        lines += ["## " + section, "", _clean(rows[section].get("content")) or "（待补）", ""]
    return "\n".join(lines)


def export_spec(repo, project_id, kind, outdir) -> str:
    if not _clean(outdir):
        raise ValueError("先选导出目录")
    os.makedirs(outdir, exist_ok=True)
    project = repo.find_project(project_id) or {}
    base = _safe_name("%s_%s" % (project.get("name"), SPEC_KIND_NAMES.get(kind, "产品文档")))
    path = _unique_file(os.path.join(outdir, base + ".md"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(spec_text(repo, project_id, kind))
    repo.add_project_asset(project_id, {
        "name": os.path.basename(path), "path": path, "kind": "产品文档",
        "size": os.path.getsize(path), "sha256": _sha256(path),
        "note": SPEC_KIND_NAMES.get(kind, kind) + "导出",
    })
    return path


# ---------- BOM / 架构 ----------
def bom_stats(rows) -> dict:
    rows = rows or []
    total_cost = 0.0
    by_kind = {}
    missing_source = 0
    for row in rows:
        try:
            qty = float(row.get("qty") or 0)
            unit_cost = float(row.get("unit_cost") or 0)
        except (TypeError, ValueError):
            qty, unit_cost = 0, 0
        total_cost += qty * unit_cost
        kind = _clean(row.get("kind")) or "其他"
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if not _clean(row.get("source")):
            missing_source += 1
    return {
        "total": len(rows), "cost": round(total_cost, 2),
        "by_kind": by_kind, "missing_source": missing_source,
    }


def export_bom(repo, project_id, outdir) -> str:
    if not _clean(outdir):
        raise ValueError("先选导出目录")
    os.makedirs(outdir, exist_ok=True)
    rows = repo.list_product_bom(project_id)
    project = repo.find_project(project_id) or {}
    path = _unique_file(os.path.join(
        outdir, _safe_name("%s_BOM" % project.get("name")) + ".csv"))
    stat = bom_stats(rows)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["序号", "类型", "名称", "规格", "数量", "单位",
                         "单价", "小计", "来源", "备注"])
        for i, row in enumerate(rows, 1):
            try:
                qty = float(row.get("qty") or 0)
                unit_cost = float(row.get("unit_cost") or 0)
            except (TypeError, ValueError):
                qty, unit_cost = 0, 0
            writer.writerow([i, row.get("kind"), row.get("name"), row.get("spec"),
                             qty, row.get("unit"), "%.2f" % unit_cost,
                             "%.2f" % (qty * unit_cost), row.get("source"),
                             row.get("note")])
        writer.writerow([])
        writer.writerow(["合计", "%d 项" % stat["total"], "", "", "", "",
                         "", "%.2f" % stat["cost"], "", ""])
    repo.add_project_asset(project_id, {
        "name": os.path.basename(path), "path": path, "kind": "BOM",
        "size": os.path.getsize(path), "sha256": _sha256(path),
        "note": "BOM 导出，合计 %.2f" % stat["cost"],
    })
    return path


# ---------- 原型 ----------
def proto_stats(rows) -> dict:
    rows = rows or []
    usable = sum(1 for r in rows if r.get("status") in ("可用", "已冻结"))
    pending = sum(1 for r in rows if r.get("status") in ("待做", "进行中"))
    missing_path = 0
    missing_file = 0
    for row in rows:
        path = _clean(row.get("path"))
        if not path:
            missing_path += 1
        elif not os.path.exists(path):
            missing_file += 1
    return {
        "total": len(rows), "usable": usable, "pending": pending,
        "missing_path": missing_path, "missing_file": missing_file,
        "ready": bool(rows) and usable > 0 and missing_file == 0,
    }


def proto_note(row) -> str:
    path = _clean((row or {}).get("path"))
    if not path:
        return "未填路径"
    return "路径可达" if os.path.exists(path) else "路径不存在"


# ---------- 测试 ----------
def test_stats(rows) -> dict:
    rows = rows or []
    total = len(rows)
    passed = sum(1 for r in rows if r.get("result") == "通过")
    failed = sum(1 for r in rows if r.get("result") == "不通过")
    blocked = sum(1 for r in rows if r.get("result") == "阻塞")
    untested = sum(1 for r in rows if r.get("result") in ("", None, "未测"))
    high_open = sum(1 for r in rows
                    if r.get("result") in ("不通过", "阻塞", "未测", "", None)
                    and r.get("severity") == "高")
    return {
        "total": total, "passed": passed, "failed": failed,
        "blocked": blocked, "untested": untested, "high_open": high_open,
        "pass_rate": int(round(passed * 100.0 / total)) if total else 0,
        "ready": total > 0 and failed == 0 and blocked == 0 and untested == 0,
    }


# ---------- 评审门 ----------
def review_stats(rows) -> dict:
    rows = rows or []
    recorded = sum(1 for r in rows if r.get("conclusion") not in ("", None, "待评审"))
    passed = sum(1 for r in rows if r.get("conclusion") in PASS_CONCLUSIONS)
    rejected = sum(1 for r in rows if r.get("conclusion") == "驳回")
    pending = len(rows) - recorded
    gates = {r.get("gate"): r for r in rows}
    missing = [g for g in REVIEW_GATES if g not in gates]
    return {
        "total": len(rows), "recorded": recorded, "passed": passed,
        "rejected": rejected, "pending": pending, "missing": missing,
        "ready": not missing and pending == 0 and rejected == 0,
    }


def review_summary(rows) -> str:
    stat = review_stats(rows)
    return "评审门 %d 道：已记录 %d、通过 %d、驳回 %d、待评审 %d%s" % (
        stat["total"], stat["recorded"], stat["passed"], stat["rejected"],
        stat["pending"],
        ("；缺 " + "、".join(stat["missing"])) if stat["missing"] else "")


def sync_review_gate(repo, project_id, gate, conclusion, note="", reviewer="") -> str:
    """把评审结论同步到项目质量门，保证项目页也看得到记录。"""
    status = "待检查"
    if conclusion in PASS_CONCLUSIONS:
        status = "通过"
    elif conclusion == "驳回":
        status = "不通过"
    elif conclusion == "待评审":
        status = "待检查"
    repo.set_project_gate(project_id, gate, status,
                          note=note or ("评审结论：" + _clean(conclusion)),
                          checked_by=reviewer or "系统")
    return status


# ---------- 上线检查 / 发布包 ----------
def readiness(repo, project_id) -> dict:
    project = repo.find_project(project_id)
    if project is None:
        raise ValueError("项目不存在")
    spec = spec_stats(repo, project_id)
    bom = bom_stats(repo.list_product_bom(project_id))
    proto = proto_stats(repo.list_product_protos(project_id))
    test = test_stats(repo.list_product_tests(project_id))
    review = review_stats(repo.list_product_reviews(project_id))
    items = [
        {"name": "需求完整", "ok": spec["kinds"]["prd"]["complete"],
         "note": "PRD %d / %d 小节" % (spec["kinds"]["prd"]["filled"],
                                      spec["kinds"]["prd"]["total"])},
        {"name": "架构完整", "ok": spec["kinds"]["arch"]["complete"],
         "note": "架构 %d / %d 小节" % (spec["kinds"]["arch"]["filled"],
                                       spec["kinds"]["arch"]["total"])},
        {"name": "BOM 有明细", "ok": bom["total"] > 0,
         "note": "%d 项，合计 %.2f" % (bom["total"], bom["cost"])},
        {"name": "原型可用", "ok": proto["ready"],
         "note": "%d 个，可用/冻结 %d；缺路径 %d，路径失效 %d" % (
             proto["total"], proto["usable"], proto["missing_path"],
             proto["missing_file"])},
        {"name": "测试通过", "ok": test["ready"],
         "note": "共 %d：通过 %d、不通过 %d、阻塞 %d、未测 %d" % (
             test["total"], test["passed"], test["failed"],
             test["blocked"], test["untested"])},
        {"name": "评审门记录", "ok": review["ready"],
         "note": "已记录 %d / %d，驳回 %d" % (
             review["recorded"], len(REVIEW_GATES), review["rejected"])},
    ]
    ok = all(item["ok"] for item in items)
    failed = [item["name"] for item in items if not item["ok"]]
    return {
        "project": project, "spec": spec, "bom": bom, "proto": proto,
        "test": test, "review": review, "items": items, "ok": ok,
        "failed": failed, "summary": readiness_summary(items, ok),
    }


def readiness_summary(items, ok=None) -> str:
    if ok is None:
        ok = all(item.get("ok") for item in items or [])
    if not items:
        return "还没有做上线检查。"
    if ok:
        return "上线检查 6 项全通过。"
    failed = [item["name"] for item in items if not item.get("ok")]
    return "上线检查未通过：通过 %d / %d 项，卡在 %s。" % (
        len(items) - len(failed), len(items), "、".join(failed))


def release_summary(result) -> str:
    if not result:
        return "还没有生成发布包。"
    text = "发布包 %s：%d 个文件 / %s" % (
        result.get("version") or "?", result.get("count", 0),
        _human_size(result.get("total_bytes") or 0))
    if result.get("ready"):
        text += "；上线检查通过"
    else:
        text += "；上线检查未通过（%s）" % ("、".join(result.get("failed") or []) or "见报告")
    return text


def _mark_deliverable(repo, project_id, keyword, status="已通过"):
    rows = repo.list_deliverables(project_id)
    for row in rows:
        if keyword in (row.get("name") or ""):
            repo.update_deliverable(row["id"], {"status": status})
            return row.get("name")
    repo.add_deliverable(project_id, {
        "name": keyword, "stage": "交付", "status": status,
        "required": True, "note": "产品工作台补建",
    })
    return keyword


def _release_notes(project, version, notes, files, rr, reviews) -> str:
    lines = ["# %s · 发布说明" % (project.get("name") or "产品项目"), "",
             "- 版本：%s" % version,
             "- 生成时间：%s" % _now(),
             "- 项目状态：%s / %s" % (project.get("stage"), project.get("status")), ""]
    lines += ["## 本次发布", "", _clean(notes) or "（未填写发布说明）", "",
              "## 上线检查", ""]
    for item in rr["items"]:
        lines.append("- [%s] %s：%s" % (
            "x" if item["ok"] else " ", item["name"], item["note"]))
    lines += ["", "## 产品摘要", ""]
    lines.append("- 需求文档：%d / %d 小节" % (
        rr["spec"]["kinds"]["prd"]["filled"], rr["spec"]["kinds"]["prd"]["total"]))
    lines.append("- 架构说明：%d / %d 小节" % (
        rr["spec"]["kinds"]["arch"]["filled"], rr["spec"]["kinds"]["arch"]["total"]))
    lines.append("- BOM：%d 项，成本合计 %.2f" % (rr["bom"]["total"], rr["bom"]["cost"]))
    lines.append("- 原型：%d 个，可用/冻结 %d" % (rr["proto"]["total"], rr["proto"]["usable"]))
    lines.append("- 测试：共 %d，通过 %d，通过率 %d%%" % (
        rr["test"]["total"], rr["test"]["passed"], rr["test"]["pass_rate"]))
    lines.append("- " + review_summary(reviews))
    lines += ["", "## 包内文件", "", "| 文件 | 大小 | SHA256 |", "| --- | --- | --- |"]
    for item in files:
        lines.append("| %s | %s | `%s` |" % (
            item["name"], _human_size(item["size"]), item["sha256"]))
    lines.append("")
    return "\n".join(lines)


def make_release_package(repo, project_id, files, outdir, version="", notes="",
                         include_zip=True, operator="系统") -> dict:
    project = repo.find_project(project_id)
    if project is None:
        raise ValueError("项目不存在")
    version = _clean(version)
    if not version:
        raise ValueError("先填版本号，例如 v1.0")
    files = [os.path.abspath(_clean(f)) for f in (files or []) if _clean(f)]
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        raise ValueError("发布包至少要有一个文件")
    outdir = os.path.abspath(_clean(outdir))
    if not outdir:
        raise ValueError("先选发布包输出目录")
    os.makedirs(outdir, exist_ok=True)
    rr = readiness(repo, project_id)
    base = _safe_name("%s_%s_发布包" % (project.get("name"), version), "产品发布包")
    root = _unique_dir(os.path.join(outdir, base))
    os.makedirs(root)
    manifest = []
    copied = 0
    used = set()
    started = _now()
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
        size = os.path.getsize(dst)
        digest = _sha256(dst)
        if digest != _sha256(src):
            raise RuntimeError("复制后哈希不一致：%s" % raw)
        manifest.append({"name": dst_name, "src": src, "size": size,
                         "sha256": digest, "note": "已复制并校验"})
        copied += 1
    manifest_csv = os.path.join(root, RELEASE_PREFIX + "发布清单_%s.csv" % _stamp())
    with open(manifest_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["序号", "文件", "大小", "SHA256", "来源", "说明"])
        for i, item in enumerate(manifest, 1):
            writer.writerow([i, item["name"], _human_size(item["size"]),
                             item["sha256"], item["src"], item["note"]])
    readiness_json = os.path.join(root, READINESS_NAME)
    payload = {
        "kind": "product-release", "version": version, "project": project.get("name"),
        "generated_at": _now(), "ready": rr["ok"], "failed": rr["failed"],
        "items": rr["items"], "files": manifest,
        "total_bytes": sum(item["size"] for item in manifest),
    }
    with open(readiness_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    note_path = os.path.join(root, RELEASE_NOTE)
    with open(note_path, "w", encoding="utf-8") as f:
        f.write(_release_notes(project, version, notes, manifest, rr,
                               repo.list_product_reviews(project_id)))
    total_bytes = sum(item["size"] for item in manifest)
    zip_path = ""
    if include_zip:
        zip_path = _unique_file(os.path.join(outdir, os.path.basename(root) + ".zip"))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name in os.listdir(root):
                full = os.path.join(root, name)
                if os.path.isfile(full):
                    z.write(full, name)
    status = "通过" if rr["ok"] else "不通过"
    repo.add_project_run(project_id, {
        "tool": "发布包", "params": "版本 %s；%d 个文件" % (version, copied),
        "status": "成功" if rr["ok"] else "不通过",
        "started_at": started, "ended_at": _now(),
        "output": zip_path or root,
        "log": release_summary({"version": version, "count": copied,
                                "total_bytes": total_bytes,
                                "ready": rr["ok"], "failed": rr["failed"]}),
    })
    repo.set_project_gate(project_id, "上线检查", status,
                          note=readiness_summary(rr["items"], rr["ok"]),
                          checked_by=operator)
    repo.set_project_gate(project_id, "发布包", status,
                          note="版本 %s，%d 个文件" % (version, copied),
                          checked_by=operator)
    _mark_deliverable(repo, project_id, "发布包", "已通过" if rr["ok"] else "已驳回")
    zip_sha256 = _sha256(zip_path) if zip_path else ""
    repo.add_project_asset(project_id, {
        "name": os.path.basename(zip_path or root), "path": zip_path or root,
        "kind": "发布包", "size": os.path.getsize(zip_path) if zip_path else total_bytes,
        "sha256": zip_sha256,
        "note": "版本 %s；上线检查 %s" % (version, "通过" if rr["ok"] else "未通过"),
    })
    return {
        "version": version, "root": root, "zip": zip_path,
        "zip_sha256": zip_sha256,
        "zip_size": os.path.getsize(zip_path) if zip_path else 0,
        "manifest": manifest_csv, "notes": note_path,
        "readiness": readiness_json, "count": copied,
        "total_bytes": total_bytes, "ready": rr["ok"], "failed": rr["failed"],
        "summary": release_summary({"version": version, "count": copied,
                                    "total_bytes": total_bytes,
                                    "ready": rr["ok"], "failed": rr["failed"]}),
    }


# ---------- 路演 ----------
def roadshow_text(repo, project_id, release=None) -> str:
    project = repo.find_project(project_id) or {}
    rr = readiness(repo, project_id)
    prd = {row.get("section"): row for row in repo.list_product_specs(project_id, "prd")}
    bom = repo.list_product_bom(project_id)
    proto = repo.list_product_protos(project_id)
    tests = repo.list_product_tests(project_id)
    reviews = repo.list_product_reviews(project_id)
    bst = bom_stats(bom)
    tst = test_stats(tests)
    lines = ["# %s · 路演提纲" % (project.get("name") or "产品项目"), "",
             "生成时间：%s" % _now(), "",
             "## 一、开场（30 秒）", "",
             "问题：%s" % (_clean((prd.get("背景与问题") or {}).get("content")) or "待补"), "",
             "目标用户：%s" % (_clean((prd.get("目标用户") or {}).get("content")) or "待补"), "",
             "一句话产品：%s" % (_clean((prd.get("产品目标") or {}).get("content")) or "待补"),
             "", "## 二、方案（2 分钟）", ""]
    lines.append("功能范围：%s" % (_clean((prd.get("功能范围") or {}).get("content")) or "待补"))
    lines.append("")
    lines.append("架构要点：%s" % (_clean(
        (repo.list_product_specs(project_id, "arch") or [{}])[0].get("content")) or "待补"))
    lines.append("")
    lines.append("BOM %d 项，成本合计 %.2f；原型 %d 个，可用/冻结 %d。" % (
        bst["total"], bst["cost"], len(proto),
        sum(1 for p in proto if p.get("status") in ("可用", "已冻结"))))
    lines += ["", "## 三、证据（2 分钟）", "",
              "测试：共 %d，通过 %d，通过率 %d%%。" % (
                  tst["total"], tst["passed"], tst["pass_rate"]), ""]
    for test in tests[:8]:
        lines.append("- [%s] %s：%s" % (
            test.get("result"), test.get("name"),
            _clean(test.get("issue")) or "无遗留问题"))
    lines += ["", "## 四、评审结论", ""]
    for review in reviews:
        lines.append("- %s：%s（%s）%s" % (
            review.get("gate"), review.get("conclusion"),
            review.get("reviewer") or "未填评审人",
            "；" + _clean(review.get("note")) if _clean(review.get("note")) else ""))
    lines += ["", "## 五、发布与下一步", ""]
    if release:
        lines.append(release_summary(release))
        if release.get("zip"):
            lines.append("发布包：`%s`" % release["zip"])
    else:
        lines.append("本次未生成发布包；发布前在上线检查与发布包页跑一遍。")
    lines += ["", "上线检查：%s" % rr["summary"], "",
              "风险与边界：%s" % (_clean((prd.get("风险与依赖") or {}).get("content")) or "待补"),
              "", "## 六、演示脚本", "",
              "1. 用真实数据走一遍主路径，先跑通再讲细节。",
              "2. 展示一条失败/边界处理，说明不会静默丢数据。",
              "3. 展示发布包清单与哈希，证明可交付。",
              "", "## 七、可能被问", "",
              "- 为什么做这个而不是现有方案：回答目标用户与场景差异。",
              "- 成本与周期：引用 BOM 合计与里程碑。",
              "- 最大风险：引用风险小节，并给出兜底动作。"]
    return "\n".join(lines)


def export_roadshow(repo, project_id, outdir, release=None, operator="系统") -> str:
    if not _clean(outdir):
        raise ValueError("先选导出目录")
    os.makedirs(outdir, exist_ok=True)
    project = repo.find_project(project_id) or {}
    path = _unique_file(os.path.join(
        outdir, _safe_name("%s_路演提纲" % project.get("name")) + ".md"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(roadshow_text(repo, project_id, release))
    repo.add_project_run(project_id, {
        "tool": "路演提纲", "params": "从 PRD / BOM / 测试 / 评审生成",
        "status": "成功", "started_at": _now(), "ended_at": _now(),
        "output": path, "log": os.path.basename(path),
    })
    repo.set_project_gate(project_id, "路演材料", "通过",
                          note=os.path.basename(path), checked_by=operator)
    _mark_deliverable(repo, project_id, "路演", "已通过")
    repo.add_project_asset(project_id, {
        "name": os.path.basename(path), "path": path, "kind": "路演",
        "size": os.path.getsize(path), "sha256": _sha256(path),
        "note": "路演提纲导出",
    })
    return path


def project_summary(repo, project_id) -> str:
    spec = spec_stats(repo, project_id)
    bom = bom_stats(repo.list_product_bom(project_id))
    proto = proto_stats(repo.list_product_protos(project_id))
    test = test_stats(repo.list_product_tests(project_id))
    review = review_stats(repo.list_product_reviews(project_id))
    return ("需求 %d/%d · 架构 %d/%d · BOM %d 项 ¥%.2f · 原型 %d（可用 %d） · "
            "测试 %d（通过 %d） · 评审 %d/%d") % (
        spec["kinds"]["prd"]["filled"], spec["kinds"]["prd"]["total"],
        spec["kinds"]["arch"]["filled"], spec["kinds"]["arch"]["total"],
        bom["total"], bom["cost"], proto["total"], proto["usable"],
        test["total"], test["passed"], review["recorded"], len(REVIEW_GATES))

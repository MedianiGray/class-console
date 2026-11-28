# -*- coding: utf-8 -*-
"""v0.34 赛事模板验收：赛程、报名、评审矩阵、提交校验、答辩包。

跑完打印 COMPETITION OK；任一断言失败非零退出。
全部在临时目录生成，不碰本机真实数据。
"""

import csv
import datetime
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import competition as cp
from database import LocalRepository, RepositoryError, PROJECT_TEMPLATES


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def main():
    base = tempfile.mkdtemp(prefix="cc-comp-smoke-")
    db = os.path.join(base, "data.sqlite3")
    repo = LocalRepository(db)
    repo.restore([], [])
    pid = repo.add_project({
        "name": "2026 校赛 · 智慧植物工厂", "kind": "competition",
        "stage": "计划", "status": "进行中", "owner": "覃祖悦",
        "start_date": "2026-11-20", "due_date": "2026-12-05",
        "goal": "用一套可复现的植物工厂监测方案参加校赛。",
    })
    assert pid > 0
    template = PROJECT_TEMPLATES["competition"]
    assert len(template) == 5
    added = repo.apply_project_template(pid)
    assert added == 5, added
    print("1. 赛事项目/模板 OK")

    seed = cp.seed_project(repo, pid)
    assert seed["events"] == 3 and seed["rubric"] == 5, seed
    events = repo.list_competition_events(pid)
    assert len(events) == 3
    assert events[0]["date"] == "2026-11-20"
    assert events[1]["date"] == "2026-12-05"
    print("2. 默认赛程/矩阵 OK")

    st, left, days = cp.milestone_status("2026-12-05", today=datetime.date(2026, 12, 1))
    assert st == "临近" and days == 4 and "4" in left, (st, left, days)
    st, left, days = cp.milestone_status("2026-12-05", today=datetime.date(2026, 12, 6))
    assert st == "已过期" and days == -1, (st, left, days)
    assert cp.milestone_status("", done=True)[0] == "已完成"
    sorted_rows = cp.sorted_events(events, today=datetime.date(2026, 12, 1))
    assert sorted_rows[0]["state"] == "已过期"
    assert cp.event_stats(events, datetime.date(2026, 12, 1))["total"] == 3
    print("3. 赛程状态/排序 OK")

    eid = repo.add_competition_event(pid, {"title": "材料初审", "date": "2026/11/28", "note": "线上"})
    ev = [e for e in repo.list_competition_events(pid) if e["id"] == eid][0]
    assert ev["date"] == "2026-11-28", ev
    repo.update_competition_event(eid, {"done": True, "note": "已交"})
    ev = [e for e in repo.list_competition_events(pid) if e["id"] == eid][0]
    assert ev["done"] == 1 and ev["note"] == "已交"
    repo.remove_competition_event(eid)
    assert len(repo.list_competition_events(pid)) == 3
    print("4. 赛程增改删 OK")

    repo.add_roster("20250001", "张三")
    repo.add_roster("20250002", "李四")
    repo.add_roster("20250003", "王五")
    e1 = repo.add_competition_entry(pid, {"name": "张三", "sid": "20250001", "role": "队长",
                                        "contact": "13800000000", "confirmed": True})
    assert e1 > 0
    try:
        repo.add_competition_entry(pid, {"name": "张三重复", "sid": "20250001"})
        raise AssertionError("同学号应拦截")
    except RepositoryError:
        pass
    imported = cp.import_from_roster(repo, pid, repo.list_roster())
    assert imported["added"] == 2 and imported["skipped"] >= 1, imported
    rows = repo.list_competition_entries(pid)
    assert len(rows) == 3 and all(r["confirmed"] for r in rows)
    assert cp.entry_stats(rows)["leaders"] == 1
    out_csv = os.path.join(base, "报名.csv")
    cp.export_entries(repo, pid, out_csv)
    with open(out_csv, "r", encoding="utf-8-sig") as f:
        assert len(list(csv.reader(f))) == 4
    repo.update_competition_entry(e1, {"confirmed": False, "role": "队员"})
    assert not [r for r in repo.list_competition_entries(pid) if r["id"] == e1][0]["confirmed"]
    print("5. 报名/导入/去重/导出 OK")

    rubric = repo.list_competition_rubric(pid)
    assert len(rubric) == 5
    st = cp.rubric_stats(rubric)
    assert st["weight"] == 100 and st["weighted"] == 0.0, st
    for i, score in enumerate((85, 90, 80, 88, 92)):
        repo.update_competition_criterion(rubric[i]["id"], {"score": score,
                                                           "evidence": "证据 %d" % (i + 1)})
    st = cp.rubric_stats(repo.list_competition_rubric(pid))
    assert st["complete"] and st["weighted"] == 86.3, st
    rubric_csv = os.path.join(base, "评审矩阵.csv")
    cp.export_rubric(repo, pid, rubric_csv)
    with open(rubric_csv, "r", encoding="utf-8-sig") as f:
        assert "合计" in f.read()
    print("6. 评审矩阵/加权/导出 OK")

    pkg = os.path.join(base, "提交包")
    os.makedirs(pkg)
    write(os.path.join(pkg, "作品说明.pdf"), b"%PDF-1.4\n" + b"a" * 400)
    with zipfile.ZipFile(os.path.join(pkg, "源码.zip"), "w") as z:
        z.writestr("main.py", "print('ok')\n")
    res = cp.validate_submission(pkg, {"exts": ".pdf,.zip", "max_file_mb": 2,
                                       "max_total_mb": 5, "max_files": 10})
    assert res["ok"] and res["total"] == 2 and res["passed"] == 2, res
    assert os.path.exists(res["report_csv"]) and os.path.exists(res["report_json"])
    with open(res["report_json"], "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["rules"]["exts"] == [".pdf", ".zip"] and len(saved["rows"]) == 2
    print("7. 提交校验通过 OK")

    bad = os.path.join(base, "坏提交")
    os.makedirs(bad)
    write(os.path.join(bad, "作品说明.exe"), b"bad")
    write(os.path.join(bad, "超限.pdf"), b"y" * (1024 * 1024 + 100))
    write(os.path.join(bad, "有 空格.pdf"), b"z" * 100)
    bad_res = cp.validate_submission(bad, {"exts": ".pdf,.zip", "max_file_mb": 1,
                                           "max_total_mb": 3, "max_files": 5,
                                           "name_regex": r"[^ ]+"})
    assert not bad_res["ok"]
    assert bad_res["failed"] == 3
    assert any("格式" in r["note"] for r in bad_res["rows"])
    assert any("超过" in r["note"] or "大小" in r["note"] for r in bad_res["rows"])
    assert any("命名" in r["note"] or "正则" in r["note"] for r in bad_res["rows"])
    bad_checks = [c for c in bad_res["checks"] if not c["ok"]]
    assert any(c["name"] == "必需格式" for c in bad_checks)
    print("8. 格式/大小/命名拦截 OK")

    rec = cp.record_submission(repo, pid, bad_res, "测试员")
    assert rec["gate"] == "提交校验" and not rec["ok"]
    gate = [g for g in repo.list_project_gates(pid) if g["gate"] == "提交校验"][-1]
    assert gate["status"] == "不通过"
    good = cp.validate_submission(pkg, {"exts": ".pdf,.zip", "max_file_mb": 2,
                                        "max_total_mb": 5, "max_files": 10})
    rec = cp.record_submission(repo, pid, good, "测试员")
    gate = [g for g in repo.list_project_gates(pid) if g["gate"] == "提交校验"][-1]
    assert gate["status"] == "通过"
    d = [x for x in repo.list_deliverables(pid) if "提交校验" in x["name"]][0]
    assert d["status"] == "已通过"
    runs = [r for r in repo.list_project_runs(pid) if r["tool"] == "提交校验"]
    assert len(runs) == 2 and runs[0]["output"] == good["report_csv"]
    print("9. 校验收货/质量门/交付物 OK")

    src_pdf = os.path.join(pkg, "作品说明.pdf")
    src_zip = os.path.join(pkg, "源码.zip")
    before = {p: sha(p) for p in (src_pdf, src_zip)}
    defense_dir = os.path.join(base, "答辩输出")
    pack = cp.make_defense_package(repo, pid, [src_pdf, src_zip], defense_dir,
                                   name="校赛答辩包", include_zip=True,
                                   submission=good, operator="测试员")
    assert pack["total"] == 2 and os.path.isdir(pack["root"])
    assert os.path.exists(pack["manifest"]) and os.path.exists(pack["outline"])
    assert os.path.getsize(pack["zip"]) == pack["zip_size"]
    with zipfile.ZipFile(pack["zip"], "r") as z:
        names = z.namelist()
        assert "作品说明.pdf" in names and "_答辩包清单.csv" in names and "_答辩提纲.md" in names
    with open(pack["manifest"], "r", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
        assert len(rows) == 3
        assert rows[1][3] == before[src_pdf]
    with open(pack["outline"], "r", encoding="utf-8") as f:
        text = f.read()
    assert "智慧植物工厂" in text and "权重合计 100%" in text and "答辩结构" in text
    assert {p: sha(p) for p in (src_pdf, src_zip)} == before
    gate = [g for g in repo.list_project_gates(pid) if g["gate"] == "答辩包"][-1]
    assert gate["status"] == "通过"
    assets = [a for a in repo.list_project_assets(pid) if a["kind"] == "zip"]
    assert len(assets) == 1 and assets[0]["sha256"] == pack["zip_sha256"]
    print("10. 答辩包/清单/提纲/哈希 OK")

    pack2 = cp.make_defense_package(repo, pid, [src_pdf], defense_dir,
                                    name="校赛答辩包", include_zip=True,
                                    submission=good, operator="测试员")
    assert pack2["root"] != pack["root"] and pack2["zip"] != pack["zip"]
    assert os.path.exists(pack["zip"]) and os.path.exists(pack2["zip"])
    assert cp.project_summary(repo, pid)["entries"]["total"] == 3
    print("11. 同名不覆盖 OK")

    bak = repo.backup()
    assert bak["counts"]["competition_events"] == 3
    assert bak["counts"]["competition_entries"] == 3
    assert bak["counts"]["competition_rubric"] == 5
    db2 = os.path.join(base, "data2.sqlite3")
    repo2 = LocalRepository(db2)
    repo2.restore([], [], projects=bak["projects"],
                  project_deliverables=bak["project_deliverables"],
                  project_events=bak["project_events"],
                  competition_events=bak["competition_events"],
                  competition_entries=bak["competition_entries"],
                  competition_rubric=bak["competition_rubric"])
    pid2 = repo2.list_projects("competition")[0]["id"]
    assert len(repo2.list_competition_events(pid2)) == 3
    assert len(repo2.list_competition_entries(pid2)) == 3
    assert len(repo2.list_competition_rubric(pid2)) == 5
    print("12. 备份恢复携带赛事数据 OK")

    repo.remove_project(pid)
    assert not repo.list_competition_events(pid)
    assert not repo.list_competition_entries(pid)
    assert not repo.list_competition_rubric(pid)
    print("13. 删除项目级联清理 OK")

    print("COMPETITION OK")


if __name__ == "__main__":
    try:
        main()
    finally:
        pass

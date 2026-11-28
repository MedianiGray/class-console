# -*- coding: utf-8 -*-
"""v0.36 数据工作台与活动工作台闭环验收。

各造一个真实小项目：数据侧从 CSV 到报告包，活动侧从策划到结项包，
并把备份/恢复一并验证。
"""

import os
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import datalab
import events
from database import LocalRepository, PROJECT_TEMPLATES

CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))


def write_csv(path):
    text = (
        "姓名,班级,成绩,到场,备注\n"
        " 张三 ,2502,88,是,\n"
        "李四,2502,92,否,\n"
        "张三,2502,88,是,\n"
        "王五,2502,缺考,是,补录\n"
        "赵六,2510,77,是,\n"
        "孙七,2510,85,是, 后到 \n"
    )
    path.write_text(text, encoding="utf-8-sig")


def data_project(repo, tmp):
    csv_path = tmp / "sample.csv"
    write_csv(csv_path)
    pid = repo.add_project({"name": "2502 班成绩与到场统计", "kind": "data",
                            "stage": "采集", "owner": "覃祖悦",
                            "start_date": "2026-11-20",
                            "goal": "把成绩与到场名单清洗成一份可复核报告"})
    check("data:项目模板可应用", repo.apply_project_template(pid, "data") == 4,
          "四个交付物")
    check("data:说明小节补齐", datalab.seed_data(repo, pid) == 5, "5 个默认小节")
    check("data:重复执行不重复插入", datalab.seed_data(repo, pid) == 0)
    loaded = datalab.read_table(csv_path)
    check("data:CSV 编码识别", loaded["encoding"] == "UTF-8" and loaded["delimiter"] == ",",
          loaded["encoding"])
    prof = datalab.profile(loaded["headers"], loaded["rows"])
    check("data:重复行识别", prof["duplicate_rows"] == 1, prof["duplicate_rows"])
    grade = next(f for f in prof["fields"] if f["name"] == "成绩")
    check("data:数值类型识别", grade["dtype"] in ("整数", "数值"), grade["dtype"])
    choices = datalab.auto_choices(loaded["headers"], loaded["rows"], prof["fields"])
    check("data:自动分类字段", choices["category"] == "班级", choices["category"])
    check("data:自动数值字段", choices["numeric"] == "成绩", choices["numeric"])
    fields = [dict(f) for f in prof["fields"]]
    for f in fields:
        if f["name"] == "备注":
            f["action"] = "剔除"
    repo.set_data_source(pid, {"name": csv_path.name, "path": str(csv_path),
                               "encoding": loaded["encoding"],
                               "rows": len(loaded["rows"]), "cols": len(loaded["headers"]),
                               "trim": True, "dedupe": True, "numeric_guard": True,
                               "note": "课堂成绩与到场演练"}, fields)
    saved = repo.list_data_source(pid)
    check("data:数据源落库", saved.get("rows") == 6 and saved.get("cols") == 5,
          "%s 行" % saved.get("rows"))
    note_rows = repo.list_data_notes(pid)
    for n in note_rows:
        repo.update_data_note(n["id"], {"content": (n.get("content") or "") + " 已核对。"})
    ready = datalab.readiness(repo, pid)
    check("data:结项前置检查", ready["ok"], "；".join(ready["failed"]))
    pkg = datalab.make_package(repo, pid, str(tmp / "out"), category="班级",
                               numeric="成绩", note="演示数据，仅用于验收。")
    check("data:报告包生成", len(pkg["files"]) == 4, len(pkg["files"]))
    check("data:清洗行数正确", pkg["stats"]["rows_out"] == 5,
          pkg["stats"])
    check("data:非法数值置空", pkg["stats"]["blanked"] == 1, pkg["stats"])
    check("data:报告含图表", "<svg" in Path(pkg["files"][2]).read_text(encoding="utf-8"))
    check("data:ZIP 已生成", pkg["zip"] and Path(pkg["zip"]).exists() and pkg["zip_size"] > 0,
          pkg["zip_size"])
    gates = {g["gate"]: g for g in repo.list_project_gates(pid)}
    check("data:四道质量门", all(gates.get(g, {}).get("status") == "通过"
                              for g in ("清洗口径", "数据核对", "图表报告", "报告包")),
          sorted(gates))
    return pid


def event_project(repo, tmp):
    pid = repo.add_project({"name": "反诈宣传进班活动", "kind": "event",
                            "stage": "计划", "owner": "覃祖悦",
                            "start_date": "2026-11-26",
                            "goal": "完成一次可复盘的班级反诈宣传"})
    check("event:项目模板可应用", repo.apply_project_template(pid, "event") == 4,
          "四个交付物")
    check("event:策划与总结小节补齐", events.seed_event(repo, pid) == 12,
          "8 + 4")
    check("event:重复执行不重复插入", events.seed_event(repo, pid) == 0)
    plan_text = {
        "活动目标": "让同学识别三类高发诈骗话术。",
        "对象与规模": "2502 班全体 6 人，分两组。",
        "时间与地点": "2026-11-26 19:00，教室 302。",
        "流程安排": "签到、案例讲解、情景演练、总结。",
        "人员分工": "主持 1 人，记录 1 人，物资 1 人。",
        "预算与来源": "班费支出，控制在 100 元内。",
        "风险预案": "设备故障改纸质材料；有人缺席补录音。",
        "物料清单": "签到表、投影、案例卡片。",
    }
    for row in repo.list_event_plan(pid):
        repo.update_event_plan(row["id"], {"content": plan_text[row["section"]]})
    people = [
        ("张三", "2502001", "参与者", "已签到"),
        ("李四", "2502002", "参与者", "已签到"),
        ("王五", "2502003", "参与者", "已签到"),
        ("赵六", "2502004", "参与者", "已签到"),
        ("孙七", "2502005", "参与者", "已签到"),
        ("周八", "2502006", "参与者", "临时到场"),
        ("吴九", "2502007", "嘉宾", "缺席"),
        ("郑十", "2502008", "志愿者", "已报名"),
    ]
    for name, sid, role, status in people:
        repo.add_event_person(pid, {"name": name, "sid": sid, "role": role,
                                    "status": status, "contact": "", "note": ""})
    for item, budget, actual in (("打印签到表", 10, 8), ("案例卡片", 40, 36),
                                 ("饮用水", 20, 18)):
        repo.add_event_expense(pid, {"item": item, "budget": budget,
                                     "actual": actual, "note": ""})
    note_text = {
        "执行概况": "按计划完成，6 人参与，1 人缺席。",
        "签到与到场": "签到 5 人，临时到场 1 人，到场率 75%。",
        "预算结算": "预算 70 元，实付 62 元，结余 8 元。",
        "问题与改进": "案例卡片字号偏小，下次加大。",
    }
    for row in repo.list_event_notes(pid):
        repo.update_event_note(row["id"], {"content": note_text[row["section"]]})
    ready = events.readiness(repo, pid)
    check("event:结项前置检查", ready["ok"], "；".join(ready["failed"]))
    st = events.stats(repo, pid)
    check("event:到场率口径", round(st["people"]["rate"], 1) == 75.0,
          st["people"]["rate"])
    check("event:预算与实付", st["expense"]["budget"] == 70 and st["expense"]["actual"] == 62,
          (st["expense"]["budget"], st["expense"]["actual"]))
    pkg = events.make_package(repo, pid, str(tmp / "out"), note="验收演练。")
    check("event:结项包文件齐全", len(pkg["files"]) == 6, len(pkg["files"]))
    check("event:总结含签到表", "签到与到场" in Path(pkg["files"][4]).read_text(encoding="utf-8"))
    check("event:ZIP 已生成", pkg["zip"] and pkg["zip_size"] > 0, pkg["zip_size"])
    gates = {g["gate"]: g for g in repo.list_project_gates(pid)}
    check("event:四道质量门", all(gates.get(g, {}).get("status") == "通过"
                               for g in ("策划审批", "签到核对", "结算核对", "结项包")),
          sorted(gates))
    return pid


def backup_restore(repo, data_pid, event_pid, tmp):
    data = repo.backup()
    check("backup:七表入库", data["counts"]["data_sources"] == 1 and
          data["counts"]["data_fields"] == 5 and data["counts"]["data_notes"] == 5 and
          data["counts"]["event_plan"] == 8 and data["counts"]["event_people"] == 8 and
          data["counts"]["event_expenses"] == 3 and data["counts"]["event_notes"] == 4,
          data["counts"])
    new_repo = LocalRepository(tmp / "restored.db")
    payload = {k: data.get(k) for k in ("docs", "logs", "roster", "tasks", "attachments",
                                        "templates", "events", "exemptions", "followups",
                                        "projects", "project_deliverables", "project_events",
                                        "competition_events", "competition_entries",
                                        "competition_rubric", "product_specs", "product_bom",
                                        "product_protos", "product_tests", "product_reviews",
                                        "data_sources", "data_fields", "data_notes",
                                        "event_plan", "event_people", "event_expenses",
                                        "event_notes")}
    new_repo.restore(**payload)
    check("backup:恢复数据源", len(new_repo.list_all_data_sources()) == 1)
    check("backup:恢复字段", len(new_repo.list_all_data_fields()) == 5)
    check("backup:恢复名单", len(new_repo.list_all_event_people()) == 8)
    check("backup:恢复结算", len(new_repo.list_all_event_expenses()) == 3)
    check("backup:恢复数据说明", len(new_repo.list_all_data_notes()) == 5)
    check("backup:恢复活动策划", len(new_repo.list_all_event_plan()) == 8)
    return new_repo


def cascade(repo):
    data = next(p for p in repo.list_projects() if p["name"] == "2502 班成绩与到场统计")
    event = next(p for p in repo.list_projects() if p["name"] == "反诈宣传进班活动")
    repo.remove_project(data["id"])
    check("cascade:删数据项目清字段", len(repo.list_all_data_fields()) == 0,
          "剩余 %d" % len(repo.list_all_data_fields()))
    repo.remove_project(event["id"])
    check("cascade:删活动项目清名单", len(repo.list_all_event_people()) == 0)
    check("cascade:活动结算同步清理", len(repo.list_all_event_expenses()) == 0)


def main():
    if PROJECT_TEMPLATES["data"][0][0] != "数据源清单":
        raise SystemExit("data 模板不符合预期")
    tmp = Path(tempfile.mkdtemp(prefix="cc_v036_"))
    repo = LocalRepository(tmp / "probe.db")
    data_pid = data_project(repo, tmp)
    event_pid = event_project(repo, tmp)
    new_repo = backup_restore(repo, data_pid, event_pid, tmp)
    cascade(new_repo)
    failed = [c for c in CHECKS if not c[1]]
    for name, ok, detail in CHECKS:
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           (" · %s" % detail) if detail and not ok else ""))
    print("\nDATA/EVENT %s · %d 项 · 失败 %d" %
          ("OK" if not failed else "FAIL", len(CHECKS), len(failed)))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

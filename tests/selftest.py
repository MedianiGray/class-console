# -*- coding: utf-8 -*-
"""数据层回归自检（临时库，不读写本机真实数据）。

每次改动数据层或仓库方法后运行：
    py -3.14 tests/selftest.py
全部通过会打印 SELFTEST OK；任一断言失败会以非零退出码结束。
"""
import os
import sys
import tempfile
import datetime
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 设置文件改到临时目录，避免测试读写本机真实偏好
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="cc-appdata-")
from database import LocalRepository, RepositoryError, date_today  # noqa: E402
import database  # noqa: E402
import archive  # noqa: E402
import audit  # noqa: E402
import fileroom  # noqa: E402
import handover  # noqa: E402
import media  # noqa: E402
import docs_tools as dt  # noqa: E402
import competition as cp  # noqa: E402
import products as pp  # noqa: E402
import datalab as dl  # noqa: E402
import events as ev  # noqa: E402
import main as app_main  # noqa: E402
import service  # noqa: E402
from ui_main import old_user_should_skip_first_run  # noqa: E402


def main():
    tmp = Path(tempfile.mkdtemp()) / "selftest.db"
    r = LocalRepository(tmp)

    # 1. 正常提交与统计
    r.add_doc({"name": "证明", "cat": "学分材料", "who": "张三", "sid": "250201", "note": "n"})
    assert r.stats()["total"] == 8
    print("1. 正常提交/统计 OK")

    # 2. 缺关键字段被拦截
    for bad in ({}, {"name": "x"}, {"who": "z"}):
        try:
            r.add_doc(bad)
            raise SystemExit("应拦截 %s" % bad)
        except RepositoryError:
            pass
    print("2. 缺字段拦截 OK")

    # 3. 脏元素跳过，合法记录保留
    r.restore([
        {"name": "合法A", "cat": "班级事务", "who": "甲", "sid": "1"},
        "脏字符串", 123, None,
        {"who": "缺其他字段"},
    ], [{"act": "提交", "obj": "A"}, "脏日志", None])
    assert len(r.list_docs()) == 2
    assert len(r.list_logs()) == 1
    print("3. 脏数据跳过 OK")

    # 4. 通配符按字面匹配
    r.add_doc({"name": "百分%号", "cat": "班级事务", "who": "乙"})
    r.add_doc({"name": "下划_线", "cat": "班级事务", "who": "丙"})
    assert len(r.list_docs("%")) == 1
    assert len(r.list_docs("_")) == 1
    print("4. 通配符转义 OK")

    # 5. 特殊字符与超长文本往返
    sp = "<>&\"' 空格 中文"
    long_note = "说明" * 300
    r.add_doc({"name": "特殊", "cat": "奖助材料", "who": sp, "sid": "4", "note": long_note})
    row = [x for x in r.list_docs() if x["who"] == sp][0]
    assert row["note"] == long_note
    print("5. 特殊字符/长文本 OK")

    # 6. 空库
    r.restore([], [])
    assert r.stats() == {"total": 0, "pending": 0, "archived": 0, "rejected": 0}
    assert r.list_docs() == [] and r.list_logs() == []
    print("6. 空库 OK")

    # 7. 备份恢复往返
    r.add_doc({"name": "往返", "cat": "团务材料", "who": "丁", "sid": "5"})
    bak = r.backup()
    r.restore([], [])
    r.restore(bak["docs"], bak["logs"])
    assert r.stats()["total"] == 1
    print("7. 备份恢复往返 OK")

    # 8. 操作不存在记录返回 None
    assert r.archive_doc(99999) is None
    assert r.reject_doc(99999) is None
    print("8. 不存在记录 OK")

    # 9. 损坏结构拦截
    try:
        r.restore("x", [])
        raise SystemExit("应抛错")
    except RepositoryError:
        pass
    try:
        r.restore([], "x")
        raise SystemExit("应抛错")
    except RepositoryError:
        pass
    print("9. 损坏结构拦截 OK")

    # 10. 重复提交允许
    r.add_doc({"name": "往返", "cat": "团务材料", "who": "丁", "sid": "5"})
    assert r.stats()["total"] == 2
    print("10. 重复提交 OK")

    # 11. 非字符串搜索参数不崩；学号可检索
    r.add_doc({"name": "边界", "cat": "班级事务", "who": "己", "sid": "6"})
    r.list_docs(None, None)
    r.list_docs(123, 456)
    r.add_doc({"name": "学号检索", "cat": "班级事务", "who": "庚", "sid": "250299"})
    assert len(r.list_docs("250299")) == 1
    print("11. 非字符串搜索/学号检索 OK")

    # 12. 纯空白必填拦截；空备注 / 空附件读回为空串
    for bad in ({"name": "   ", "cat": "班级事务", "who": "x"},
                {"name": "y", "cat": "  ", "who": "x"},
                {"name": "y", "cat": "班级事务", "who": "  "}):
        try:
            r.add_doc(bad)
            raise SystemExit("应拦截 %s" % bad)
        except RepositoryError:
            pass
    r.add_doc({"name": "空备注", "cat": "班级事务", "who": "庚", "sid": "7",
               "note": "  ", "file": ""})
    row = [x for x in r.list_docs() if x["name"] == "空备注"][0]
    assert row["note"] == "" and row["file"] == ""
    print("12. 空白拦截/空值读回 OK")

    # 13. 日志字段 None 兜底为空，来源默认本机
    r.add_log("提交", None, None, None)
    last = r.list_logs()[0]
    assert last["who"] == "" and last["role"] == ""
    assert last["obj"] == "" and last["src"] == "本机"
    print("13. 日志空值兜底 OK")

    # 14. 归档 / 驳回状态流转一致
    rid = r.list_docs()[0]["id"]
    r.archive_doc(rid)
    assert [x for x in r.list_docs() if x["id"] == rid][0]["status"] == "已归档"
    r.reject_doc(rid)
    assert [x for x in r.list_docs() if x["id"] == rid][0]["status"] == "已驳回"
    print("14. 状态流转一致 OK")

    # 15. 名单 CRUD 与缺交核对
    r.add_roster("250230", "测试生")
    assert r.find_roster_by_sid("250230")["who"] == "测试生"
    for bad in (("250230", "重复"), ("abc", "非数字"), ("", "无名")):
        try:
            r.add_roster(*bad)
            raise SystemExit("应拦截 %s" % (bad,))
        except RepositoryError:
            pass
    chk = r.roster_check()
    assert chk["total"] == 1 and "absent" in chk and "extra" in chk
    # 只有已驳回不算已交，进入需补交
    r.add_roster("250240", "需补交生")
    did = r.add_doc({"name": "被驳回材料", "cat": "学分材料",
                     "who": "需补交生", "sid": "250240"})
    r.reject_doc(did)
    chk = r.roster_check()
    assert chk["total"] == 2 and chk["done"] == 0
    assert any(x["sid"] == "250240" for x in chk["resubmit"])
    r.remove_roster(r.find_roster_by_sid("250230")["id"])
    assert r.find_roster_by_sid("250230") is None
    print("15. 名单 CRUD/核对 OK")

    # 16. 任务 CRUD 与临期统计
    tid = r.add_task({"title": "冒烟任务", "cat": "宣传材料",
                      "deadline": date_today(), "scope": "全员"})
    assert r.find_task(tid) is not None
    assert r.task_stats()["due"] == 1
    r.toggle_task(tid)
    assert r.find_task(tid)["done"] is True
    r.update_task(tid, {"title": "改名任务"})
    assert r.find_task(tid)["title"] == "改名任务"
    # 日期只收 YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD，其余直接拦截
    for bad in ("明天", "2026-02-30", "2026-13-01"):
        try:
            r.add_task({"title": "坏日期", "deadline": bad})
            raise SystemExit("应拦截日期 %s" % bad)
        except RepositoryError:
            pass
    tfmt = r.add_task({"title": "格式任务", "deadline": "2026/12/01"})
    assert r.find_task(tfmt)["deadline"] == "2026-12-01"
    try:
        r.update_task(tid, {"deadline": "明天"})
        raise SystemExit("应拦截更新坏日期")
    except RepositoryError:
        pass
    r.remove_task(tfmt)
    r.remove_task(tid)
    assert r.find_task(tid) is None
    print("16. 任务 CRUD/统计 OK")

    # 17. 备份往返携带名单与任务
    r.add_roster("250231", "钱七")
    r.add_task({"title": "往返任务", "deadline": date_today()})
    bak = r.backup()
    assert "roster" in bak and "tasks" in bak
    r.restore([], [])
    r.restore(bak["docs"], bak["logs"], bak["roster"], bak["tasks"])
    assert r.find_roster_by_sid("250231") is not None
    assert any(t["title"] == "往返任务" for t in r.list_tasks())
    print("17. 备份携带名单/任务 OK")

    # 18. 归档 / 驳回备注留存
    rid = r.list_docs()[0]["id"]
    r.archive_doc(rid, "材料齐全")
    assert [x for x in r.list_docs() if x["id"] == rid][0]["reason"] == "材料齐全"
    r.reject_doc(rid, "证明缺失")
    assert [x for x in r.list_docs() if x["id"] == rid][0]["reason"] == "证明缺失"
    print("18. 备注留存 OK")

    # 19. 编号按类别递增、手动编号保留、路径随备份往返
    r.restore([], [])
    r.add_doc({"name": "甲", "cat": "团务材料", "who": "x"})
    r.add_doc({"name": "乙", "cat": "团务材料", "who": "x"})
    codes = sorted(d["code"] for d in r.list_docs())
    assert codes == ["团务-001", "团务-002"], codes
    r.add_doc({"name": "丙", "cat": "奖助材料", "who": "x",
               "code": "奖助-099", "path": "D:/a.pdf"})
    row = [d for d in r.list_docs() if d["name"] == "丙"][0]
    assert row["code"] == "奖助-099" and row["path"] == "D:/a.pdf"
    bak = r.backup()
    r.restore([], [])
    r.restore(bak["docs"], bak["logs"])
    row2 = [d for d in r.list_docs() if d["name"] == "丙"][0]
    assert row2["code"] == "奖助-099" and row2["path"] == "D:/a.pdf"
    print("19. 编号生成/手动保留/路径往返 OK")

    # 20. 模板材料：扩展内容与多附件往返
    r.add_doc({"name": "第一次班会", "cat": "团务材料", "who": "主持人",
               "form_type": "meeting",
               "extra": {"topic": "学风建设", "place": "301", "attended": "42"},
               "attachments": [{"name": "合影.jpg", "path": "D:/img/1.jpg", "kind": "照片"},
                               {"name": "记录.docx", "path": "D:/doc/1.docx"}]})
    row = [d for d in r.list_docs() if d["name"] == "第一次班会"][0]
    assert row["form_type"] == "meeting"
    assert row["extra"]["topic"] == "学风建设"
    assert len(row["attachments"]) == 2
    assert row["attachments"][0]["name"] == "合影.jpg"
    print("20. 模板扩展内容/多附件 OK")

    # 21. 模板编号前缀优先于类别前缀
    assert row["code"].startswith("班会-"), row["code"]
    print("21. 模板编号前缀 OK")

    # 22. 备份恢复：附件随记录映射往返
    bak = r.backup()
    assert len(bak["attachments"]) == 2
    r.restore([], [])
    r.restore(bak["docs"], bak["logs"], bak["roster"], bak["tasks"], bak["attachments"])
    row2 = [d for d in r.list_docs() if d["name"] == "第一次班会"][0]
    assert len(row2["attachments"]) == 2
    assert row2["attachments"][0]["path"] == "D:/img/1.jpg"
    print("22. 附件备份恢复往返 OK")

    # 23. 归档落盘：目录规则、复制、跳过与索引
    import archive
    tmp2 = tempfile.mkdtemp(prefix="cc-arch-")
    src = os.path.join(tmp2, "src", "体测成绩.pdf")
    os.makedirs(os.path.dirname(src), exist_ok=True)
    with open(src, "w", encoding="utf-8") as f:
        f.write("pdf")
    base = os.path.join(tmp2, "归档")
    doc = {"id": 1, "code": "团务-007", "name": "体测成绩统计表",
           "cat": "团务材料", "who": "刘一帆", "sid": "250222", "path": src,
           "status": "待审核"}
    res = archive.place(doc, base=base)
    assert res["copied"] is True, res
    assert os.path.isfile(res["path"]), res
    parts = os.path.normpath(res["path"]).split(os.sep)
    assert parts[-3] == "团务材料" and parts[-2] == "250222-刘一帆", parts
    assert os.path.basename(res["path"]) == "团务-007_体测成绩统计表.pdf"
    again = archive.place(doc, base=base)
    assert again["copied"] is False and "跳过" in again["note"], again
    assert archive.safe('a/b:c*?') == "a_b_c_", archive.safe('a/b:c*?')
    empty = archive.place({"id": 2, "name": "纸质材料", "cat": "学分材料",
                           "who": "李", "sid": ""}, base=base)
    assert empty["copied"] is False and "仅建目录" in empty["note"]
    assert os.path.isdir(empty["dir"]) and empty["dir"].endswith("学分材料" + os.sep + "李")
    any_id = r.list_docs()[0]["id"]
    r.set_arch(any_id, res["path"])
    assert [x for x in r.list_docs() if x["id"] == any_id][0]["arch"] == res["path"]
    idx = archive.write_index(r.list_docs(), base=base)
    assert idx and os.path.isfile(idx)
    print("23. 归档落盘/索引 OK")

    # 24. 同名不同内容：递进 _v2，不覆盖已有归档
    with open(src, "w", encoding="utf-8") as f:
        f.write("pdf-v2-different")
    before = open(res["path"], "r", encoding="utf-8").read()
    collision = archive.place(doc, base=base)
    assert collision["copied"] is True, collision
    assert collision["path"].endswith("_v2.pdf"), collision
    assert open(res["path"], "r", encoding="utf-8").read() == before
    print("24. 归档冲突不覆盖 OK")

    # 25. 归档规则：类别映射、目录/文件模板、预览与非法拦截
    default_preview = archive.preview_path(doc, base=base)
    assert default_preview.endswith(os.path.join("团务材料", "250222-刘一帆",
                                                  "团务-007_体测成绩统计表.pdf")), default_preview
    rule = archive.validate_rule({
        "dir_template": "{category}/{student}",
        "file_template": "{sid}-{name}{ext}",
        "category_map": {"团务材料": "01-团务/证明材料"},
    })
    custom_preview = archive.preview_path(doc, base=base, rules=rule)
    assert os.path.join("01-团务", "证明材料", "250222-刘一帆") in custom_preview, custom_preview
    assert custom_preview.endswith("250222-体测成绩统计表.pdf"), custom_preview
    archive.save_rule(rule)
    assert archive.load_rule() == rule
    mapped_place = archive.place(doc, base=base)
    assert mapped_place["copied"] is True, mapped_place
    assert os.path.join("01-团务", "证明材料", "250222-刘一帆") in mapped_place["path"], mapped_place
    assert os.path.basename(mapped_place["path"]) == "250222-体测成绩统计表.pdf", mapped_place
    archive.save_rule(archive.default_rule())
    assert archive.load_rule() == archive.default_rule()
    for bad in (
        {"dir_template": ""},
        {"file_template": ""},
        {"dir_template": "../越界"},
        {"dir_template": "C:\\abs"},
        {"file_template": "{name}/子目录"},
        {"file_template": "{unknown}"},
        {"category_map": {"团务材料": "../../越界"}},
    ):
        try:
            archive.validate_rule(bad)
            raise SystemExit("应拦截非法归档规则：%s" % bad)
        except ValueError:
            pass
    print("25. 归档规则/映射/非法拦截 OK")

    # 26. 模板附加字段：只增删附加，内置保留，随备份往返
    r.restore([], [], templates=[])
    base_meeting = len(r.form_template("meeting")["fields"])
    r.add_template_field("custom", "审核人", "text", True)
    assert len(r.template_custom("custom")) == 1
    assert len(r.form_template("custom")["fields"]) >= 1
    assert len(r.form_template("meeting")["fields"]) == base_meeting
    try:
        r.add_template_field("custom", "错误类型", "number")
        raise SystemExit("应拦截未知字段类型")
    except RepositoryError:
        pass
    try:
        r.add_template_field("custom", "空下拉", "select")
        raise SystemExit("应拦截空下拉")
    except RepositoryError:
        pass
    bak = r.backup()
    assert any(x["label"] == "审核人" for x in bak["templates"])
    r.restore([], [], templates=bak["templates"])
    rows = r.template_custom("custom")
    assert len(rows) == 1 and rows[0]["label"] == "审核人"
    r.remove_template_field(rows[0]["id"])
    assert r.template_custom("custom") == []
    print("26. 模板附加字段/备份往返 OK")

    # 27. 单据流转链：提交 / 归档 / 归位 / 驳回逐节点可回放，随备份往返
    r.restore([], [], templates=[])
    did = r.add_doc({"name": "流转证明", "cat": "学分材料", "who": "张三",
                     "sid": "250201", "note": "n", "actor": "李四",
                     "actor_role": "经办人"})
    doc = next(d for d in r.list_docs() if d["id"] == did)
    assert [e["act"] for e in r.doc_timeline(doc)] == ["提交"]
    assert r.doc_timeline(doc)[0]["who"] == "李四"
    r.archive_doc(did, "材料齐全", "王五", "审核人")
    arch_file = Path(tempfile.mkdtemp()) / "流转证明.pdf"
    arch_file.write_text("x", encoding="utf-8")
    r.set_arch(did, str(arch_file), "王五", "审核人")
    doc = next(d for d in r.list_docs() if d["id"] == did)
    acts = [e["act"] for e in r.doc_timeline(doc)]
    assert acts == ["提交", "归档", "归位"], acts
    assert r.doc_timeline(doc)[2]["detail"] == str(arch_file)
    rid = r.add_doc({"name": "驳回证明", "cat": "学分材料", "who": "张三",
                     "sid": "250201", "note": "n", "actor": "张三",
                     "actor_role": "申请人"})
    r.reject_doc(rid, "缺盖章", "王五", "审核人")
    rejected = next(d for d in r.list_docs() if d["id"] == rid)
    assert [e["act"] for e in r.doc_timeline(rejected)] == ["提交", "驳回"]
    bak = r.backup()
    assert bak.get("events") and len(bak["events"]) >= 5
    r.restore([], [], templates=[])
    assert r.list_all_events() == []
    r.restore(bak["docs"], bak["logs"], bak["roster"], bak["tasks"],
              bak["attachments"], bak["templates"], bak["events"])
    assert [e["act"] for e in r.doc_timeline(
        next(d for d in r.list_docs() if d.get("name") == "流转证明"))] == acts
    print("27. 单据流转链/备份往返 OK")

    # 28. 操作日志按关键词 / 动作 / 操作人筛选
    r.restore([], [])
    r.add_log("提交", "学分证明", "张三", "申请人")
    r.add_log("归档", "学分证明", "王五", "审核人")
    r.add_log("驳回", "志愿时长", "王五", "审核人")
    assert len(r.list_logs(q="证明")) == 2
    assert len(r.list_logs(act="驳回")) == 1
    assert len(r.list_logs(who="王五")) == 2
    assert len(r.list_logs(q="证明", act="归档", who="王五")) == 1
    assert len(r.list_logs(q="%")) == 0
    print("28. 日志筛选 OK")

    # 29. 完整性检查：缺文件 / 索引不一致 / 索引孤儿 / 磁盘孤儿，重建后收敛
    import archive
    import audit
    base = Path(tempfile.mkdtemp())
    f1 = base / "甲.pdf"
    f1.write_text("x", encoding="utf-8")
    docs = [{"id": 901, "code": "事务-901", "name": "甲", "cat": "团务材料",
             "who": "张三", "sid": "250201", "time": "2026-11-23 10:00",
             "status": "已归档", "arch": str(f1)}]
    audit.rebuild_index(docs, base=base)
    res = audit.check_integrity(docs, base=base)
    assert res["ok"], res["counts"]
    f1.unlink()
    res = audit.check_integrity(docs, base=base)
    assert len(res["missing_file"]) == 1 and not res["ok"]
    (base / "多出来的.txt").write_text("y", encoding="utf-8")
    res = audit.check_integrity(docs, base=base)
    assert len(res["orphan_file"]) == 1
    f1.write_text("x", encoding="utf-8")
    audit.rebuild_index([], base=base)
    res = audit.check_integrity(docs, base=base)
    assert len(res["index_missing"]) == 1
    audit.rebuild_index(docs, base=base)
    res = audit.check_integrity(docs, base=base)
    assert len(res["index_missing"]) == 0
    print("29. 完整性检查/索引重建 OK")

    # 30. 证据包：脱离软件可读，可选附带归档文件
    import zipfile
    archive.save_root(str(base))
    f1.write_text("x", encoding="utf-8")
    edid = r.add_doc({"name": "甲", "cat": "团务材料", "who": "张三",
                      "sid": "250201", "note": "证据", "path": str(f1)})
    r.archive_doc(edid, "通过", "王五", "审核人")
    r.set_arch(edid, str(f1), "王五", "审核人")
    audit.rebuild_index(r.list_docs(), base=base)
    zpath = base / "evidence.zip"
    exp = audit.export_evidence(r, str(zpath), include_files=True)
    assert zpath.exists() and exp["docs"] >= 1
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        for need in ("材料清单.csv", "归档索引.csv", "操作日志.csv",
                     "文件树.txt", "README.txt", "manifest.json"):
            assert need in names, need
        assert "归档文件/甲.pdf" in names
        readme = z.read("README.txt").decode("utf-8")
        assert "班级材料证据包" in readme
        rows = z.read("材料清单.csv").decode("utf-8-sig")
        assert "编号" in rows and "甲" in rows
        assert z.read("manifest.json").decode("utf-8").startswith("{")
    print("30. 证据包导出 OK")

    # 30b. 日期筛选容错与非法日期拦截
    assert audit._doc_day({"time": "2026-11-23 09:00"}, []) is not None
    assert audit._doc_day({"time": "11-23 09:00"}, []) is not None
    try:
        audit.export_evidence(r, str(base / "bad.zip"), start="2026-13-01")
        raise SystemExit("应拦截非法日期")
    except ValueError:
        pass
    print("30b. 证据包日期口径 OK")

    # 30c. 缺归档但源文件仍在：重新归位并补事件
    src = Path(tempfile.mkdtemp()) / "乙.pdf"
    src.write_text("y", encoding="utf-8")
    pid = r.add_doc({"name": "乙", "cat": "团务材料", "who": "张三",
                     "sid": "250201", "path": str(src)})
    r.archive_doc(pid, "通过", "王五", "审核人")
    missing = base / "资料" / "乙.pdf"
    r.set_arch(pid, str(missing), "王五", "审核人")
    assert not missing.exists()
    rr = audit.repair_placements(r, base=base)
    assert len(rr["placed"]) == 1 and rr["failed"] == [], rr
    rebuilt = next(d for d in r.list_docs() if d["id"] == pid)["arch"]
    assert os.path.isfile(rebuilt), rebuilt
    events = r.doc_timeline(next(d for d in r.list_docs() if d["id"] == pid))
    assert events[-1]["act"] == "归位" and events[-1]["who"] == "完整性检查"
    print("30c. 缺失文件重新归位 OK")

    # 31. 恢复预览：导入前看清数量与提醒，不直接覆盖
    preview = audit.backup_preview(r.backup(), r)
    assert preview["ok"] and "材料" in preview["text"]
    assert preview["counts"]["docs"] == len(r.list_docs())
    empty = audit.backup_preview({}, r)
    assert not empty["ok"] and "结构不正确" in empty["text"]
    print("31. 恢复预览 OK")

    # 32. 免交 / 延期登记与取消
    r.add_roster("259998", "服务同学")
    ex = r.set_exemption("259998", "服务同学", "团务材料", "免交", "校外已交",
                         actor="覃祖悦", role="经办人")
    assert ex["kind"] == "免交" and ex["active"] is True
    assert r.exemption_map()[("259998", "团务材料")]["reason"] == "校外已交"
    future = (datetime.date.today() + datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    r.set_exemption("259998", "服务同学", "团务材料", "延期", "住院",
                    future, actor="覃祖悦", role="经办人")
    assert r.exemption_map()[("259998", "团务材料")]["kind"] == "延期"
    assert r.remove_exemption("259998", "团务材料", "覃祖悦", "经办人")
    assert ("259998", "团务材料") not in r.exemption_map()
    try:
        r.set_exemption("259998", "服务同学", "团务材料", "延期", "住院",
                        "2000-01-01", actor="覃祖悦", role="经办人")
        raise SystemExit("应拦截过期延期")
    except RepositoryError:
        pass
    print("32. 免交 / 延期 OK")

    # 33. 催交话术与 24 小时限频（按人，不按类别）
    docs = r.list_docs()
    missing = service.missing_categories(docs, "259998")
    assert "团务材料" in missing
    msg = service.chase_message("服务同学", missing, future)
    assert msg.count("服务同学") == 1 and "这项还差你一份材料" in msg
    now = datetime.datetime.now().replace(second=0, microsecond=0)
    at = now.strftime("%Y-%m-%d %H:%M")
    r.add_followup("259998", "服务同学", "、".join(missing), msg,
                   "微信 / 群公告", "覃祖悦", "经办人", at=at)
    state = r.chase_state("259998", now=now)
    assert not state["allowed"] and state["last_act"] == "催交"
    try:
        r.add_followup("259998", "服务同学", "团务材料", msg,
                       "私聊", "覃祖悦", "经办人", at=at)
        raise SystemExit("应拦截 24 小时内重复催交")
    except RepositoryError:
        pass
    later = now + datetime.timedelta(hours=25)
    assert r.chase_state("259998", now=later)["allowed"]
    print("33. 催交 24 小时限频 OK")

    # 34. 回执登记与矩阵状态
    r.add_receipt("259998", "服务同学", "奖助材料", "已提交", "微信回执",
                  "覃祖悦", "经办人", at=at)
    rec = r.latest_receipts()[("259998", "奖助材料")]
    assert rec["response"] == "已提交"
    assert service.cell_status(r.list_docs(), "259998", "奖助材料",
                               r.exemption_map(), r.latest_receipts()) == "回执·已交"
    assert "奖助材料" not in service.missing_categories(
        r.list_docs(), "259998", r.exemption_map(), r.latest_receipts())
    r.add_receipt("259998", "服务同学", "团务材料", "校外交", "已在校外提交",
                  "覃祖悦", "经办人", at=at)
    assert service.receipt_suggestion("校外交").startswith("如确认校外已交")
    print("34. 回执与矩阵口径 OK")

    # 35. 服务留痕统计与动作过滤
    r.set_exemption("259998", "服务同学", "宣传材料", "免交", "免修",
                    actor="覃祖悦", role="经办人")
    feed = r.service_feed()
    kinds = {x["kind"] for x in feed}
    assert {"催交", "回执", "免交", "恢复应交"} <= kinds, kinds
    stats = r.service_stats()
    assert stats["chases"] >= 1 and stats["receipts"] >= 2
    assert r.nearest_deadline(["团务材料"]) == "" or r.nearest_deadline(["团务材料"])
    assert any(l["act"] == "催交" for l in r.list_logs(act="催交"))
    print("35. 服务留痕 OK")

    # 36. 服务数据随备份往返
    bak = r.backup()
    assert "exemptions" in bak and "followups" in bak
    r2 = LocalRepository(Path(tempfile.mkdtemp()) / "roundtrip.db")
    r2.restore(bak["docs"], bak["logs"], bak["roster"], bak["tasks"],
               bak["attachments"], bak["templates"], bak["events"],
               bak["exemptions"], bak["followups"])
    assert len(r2.list_followups()) == len(bak["followups"])
    assert len(r2.service_feed()) >= 2
    print("36. 服务数据备份往返 OK")

    # 37. 届别交接包：可读、可恢复、带清单
    pack = Path(tempfile.mkdtemp()) / "交接包.zip"
    info = handover.export_handover(r, pack, "覃祖悦", "经办人")
    assert info["size"] > 0 and info["counts"]["roster"] == len(r.list_roster())
    with zipfile.ZipFile(pack) as z:
        names = z.namelist()
        for need in ("数据备份.json", "交接说明.txt", "manifest.json"):
            assert need in names, need
        assert "原始材料" in z.read("交接说明.txt").decode("utf-8")
    data = handover.read_handover(pack)
    assert handover.handover_summary(data).startswith("交接包版本")
    r3 = LocalRepository(Path(tempfile.mkdtemp()) / "handover.db")
    r3.restore(data["docs"], data["logs"], data["roster"], data["tasks"],
               data["attachments"], data["templates"], data["events"],
               data["exemptions"], data["followups"])
    assert len(r3.list_exemptions()) == len(data["exemptions"])
    print("37. 届别交接包 OK")

    # 38. 文件室：扫描映射、缺失反查、拖入落位与冲突避让
    base = Path(tempfile.mkdtemp()) / "归档"
    archive.save_root(str(base))
    mate = base / "团务材料" / "250201-张三"
    mate.mkdir(parents=True)
    (mate / "已归档.txt").write_text("已归档", encoding="utf-8")
    (mate / "未登记.txt").write_text("待登记", encoding="utf-8")
    did = r.add_doc({"name": "已归档材料", "cat": "团务材料", "who": "张三",
                     "sid": "250201", "path": str(mate / "已归档.txt")})
    r.archive_doc(did, "通过", "覃祖悦", "审核人")
    r.set_arch(did, str(mate / "已归档.txt"), "覃祖悦", "审核人")
    missing_id = r.add_doc({"name": "丢失材料", "cat": "奖助材料",
                            "who": "李四", "sid": "250202"})
    r.archive_doc(missing_id, "通过", "覃祖悦", "审核人")
    r.set_arch(missing_id, str(base / "奖助材料" / "250202-李四" / "丢失.pdf"),
               "覃祖悦", "审核人")
    archive.write_index(r.list_docs(), base)

    maps = fileroom.build_status(r.list_docs(), base)
    assert len(maps["missing"]) == 1 and maps["missing"][0]["code"]
    assert fileroom.file_status(mate / "已归档.txt", maps)["state"] == "台账有"
    assert fileroom.file_status(mate / "未登记.txt", maps)["state"] == "未登记"
    ctx = fileroom.infer_context("团务材料/250201-张三", r.list_roster())
    assert (ctx["cat"], ctx["sid"], ctx["who"]) == ("团务材料", "250201", "张三")
    assert len(fileroom.list_files(base, "团务材料/250201-张三")) == 2
    assert fileroom.list_files(base, q="未登记")[0]["name"] == "未登记.txt"

    outside = Path(tempfile.mkdtemp()) / "新增材料.txt"
    outside.write_text("拖入内容", encoding="utf-8")
    res = fileroom.register_files(r, [str(outside)], base=base,
                                  rel="团务材料/250201-张三", cat="团务材料",
                                  sid="250201", who="张三", actor="覃祖悦",
                                  role="经办人")
    assert res["ok"] == 1 and os.path.isfile(res["targets"][0]["path"]), res
    assert open(res["targets"][0]["path"], encoding="utf-8").read() == "拖入内容"
    dup = fileroom.register_files(r, [str(outside)], base=base,
                                  rel="团务材料/250201-张三", cat="团务材料",
                                  sid="250201", who="张三", actor="覃祖悦",
                                  role="经办人")
    assert dup["ok"] == 1 and dup["targets"][0]["path"].endswith("_v2.txt")
    assert any(l["act"] == "文件室登记" for l in r.list_logs())
    print("38. 文件室扫描/缺失/拖入 OK")

    # 39. 首次引导：老库静默跳过只认“没写过标记且材料多于种子”
    assert old_user_should_skip_first_run(8, None, None)
    assert not old_user_should_skip_first_run(7, None, None)
    assert not old_user_should_skip_first_run(8, "0", None)
    assert not old_user_should_skip_first_run(8, None, "0")
    print("39. 首次引导老用户判定 OK")

    # 40. 备份元数据与条数校验：带 app/version/counts，可预览
    bak = r.backup()
    assert bak.get("app") == "class-console"
    assert bak.get("version") and bak.get("exportedAt")
    counts = bak.get("counts") or {}
    assert counts.get("docs") == len(bak["docs"])
    assert counts.get("logs") == len(bak["logs"])
    assert counts.get("roster") == len(bak["roster"])
    assert counts.get("tasks") == len(bak["tasks"])
    preview = audit.backup_preview(bak, r)
    assert preview["ok"], preview["text"]
    print("40. 备份元数据与条数 OK")

    # 41. 条数对不上 / 非本应用备份 / 脏记录均拒绝导入
    bad_counts = dict(bak)
    bad_counts["counts"] = dict(counts)
    bad_counts["counts"]["docs"] = counts["docs"] + 1
    assert not audit.backup_preview(bad_counts, r)["ok"]
    bad_app = dict(bak)
    bad_app["app"] = "other-app"
    assert not audit.backup_preview(bad_app, r)["ok"]
    bad_records = dict(bak)
    bad_records["docs"] = list(bak["docs"]) + ["脏记录"]
    bad_records["counts"] = dict(counts)
    bad_records["counts"]["docs"] = counts["docs"] + 1
    assert not audit.backup_preview(bad_records, r)["ok"]
    print("41. 备份结构拦截 OK")

    # 42. 归档写盘失败给可读原因，且不把路径/用户名拼进提示
    broken_base = Path(tempfile.mkdtemp()) / "这不是目录.txt"
    broken_base.write_text("x", encoding="utf-8")
    fail = archive.place({"name": "失败材料", "cat": "团务材料", "who": "张三",
                          "sid": "250201"}, base=broken_base)
    assert fail["ok"] is False and "建目录失败" in fail["note"], fail
    assert str(broken_base.parent) not in fail["note"]
    assert "Users" not in fail["note"] and "\\" not in fail["note"]
    ok_res = archive.place({"name": "仅目录材料", "cat": "团务材料",
                            "who": "张三", "sid": "250201"},
                           base=Path(tempfile.mkdtemp()) / "归档成功")
    assert ok_res["ok"] is True, ok_res
    print("42. 归档失败可读提示 OK")

    # 43. 损坏数据库被隔离改名，启动不中断并留下说明
    old_appdata = os.environ.get("APPDATA")
    old_home = os.environ.get("HOME")
    corrupt_appdata = tempfile.mkdtemp(prefix="cc-corrupt-")
    if os.name == "nt":
        os.environ["APPDATA"] = corrupt_appdata
        cc_dir = Path(corrupt_appdata) / "ClassConsole"
    else:
        os.environ["HOME"] = corrupt_appdata
        cc_dir = Path(corrupt_appdata) / ".class-console"
    cc_dir.mkdir(parents=True)
    (cc_dir / "console.db").write_bytes(b"this is not a sqlite database")
    try:
        repo = database.build_repository()
        assert repo.stats()["total"] >= 1
        issue = database.LAST_STARTUP_ISSUE
        assert issue and "损坏" in issue.what
        assert "没有被删除" in issue.impact
        assert list(cc_dir.glob("console.corrupt-*.db"))
    finally:
        if os.name == "nt":
            if old_appdata:
                os.environ["APPDATA"] = old_appdata
            else:
                os.environ.pop("APPDATA", None)
        else:
            if old_home:
                os.environ["HOME"] = old_home
            else:
                os.environ.pop("HOME", None)
    print("43. 损坏数据库隔离 OK")

    # 44. 未捕获异常写崩溃日志，且日志落在本机数据目录
    crash_appdata = tempfile.mkdtemp(prefix="cc-crash-")
    old_appdata = os.environ.get("APPDATA")
    old_home = os.environ.get("HOME")
    if os.name == "nt":
        os.environ["APPDATA"] = crash_appdata
    else:
        os.environ["HOME"] = crash_appdata
    try:
        try:
            raise RuntimeError("selftest-crash")
        except RuntimeError as e:
            log = app_main.record_crash(type(e), e, e.__traceback__)
        assert log and Path(log).exists()
        assert "selftest-crash" in Path(log).read_text(encoding="utf-8")
    finally:
        if os.name == "nt":
            if old_appdata:
                os.environ["APPDATA"] = old_appdata
            else:
                os.environ.pop("APPDATA", None)
        else:
            if old_home:
                os.environ["HOME"] = old_home
            else:
                os.environ.pop("HOME", None)
    print("44. 崩溃日志落盘 OK")

    # 45. 台账分页与 SQL 侧筛选：页大小、偏移、状态/类型条件与总数一致
    paged = LocalRepository(Path(tempfile.mkdtemp()) / "paged.db")
    for i in range(6):
        paged.add_doc({"name": "分页材料%d" % i, "cat": "团务材料",
                       "who": "分页同学", "sid": "2503%02d" % i,
                       "form_type": "meeting" if i % 2 else "general",
                       "status": "已归档" if i % 3 == 0 else "待审核"})
    base = len(paged.list_docs())
    page1 = paged.list_docs(limit=2)
    page2 = paged.list_docs(limit=2, offset=2)
    assert len(page1) == 2 and len(page2) == 2
    assert {d["id"] for d in page1}.isdisjoint({d["id"] for d in page2})
    assert paged.count_docs() == base
    assert paged.count_docs(status="待审核") == len(
        [d for d in paged.list_docs() if d.get("status") == "待审核"])
    assert paged.count_docs(form_type="meeting") == len(
        [d for d in paged.list_docs() if (d.get("form_type") or "general") == "meeting"])
    assert all(d.get("status") == "已归档"
               for d in paged.list_docs(status="已归档"))
    print("45. 台账分页/SQL 筛选 OK")

    # 46. 批量重命名：预览不落盘、同名避让、执行与撤销
    import filetools
    base2 = Path(tempfile.mkdtemp()) / "工具归档"
    (base2 / "未整理").mkdir(parents=True)
    for name in ("合影.png", "合影-2.png", "名单.txt"):
        (base2 / "未整理" / name).write_text(name, encoding="utf-8")
    outside2 = Path(tempfile.mkdtemp()) / "库外.txt"
    outside2.write_text("x", encoding="utf-8")
    plan = filetools.rename_plan(
        [str(base2 / "未整理" / n) for n in ("合影.png", "合影-2.png", "名单.txt")]
        + [str(outside2)],
        {"prefix": "2026-", "seq": True, "seq_pad": 2}, base=base2)
    assert len(list((base2 / "未整理").iterdir())) == 3, "预览不该改动磁盘"
    dropped = [r for r in plan["rows"] if r["state"] == "skip"]
    assert any("不在归档目录内" in (r.get("reason") or "") for r in dropped)
    first = [r for r in plan["rows"] if r["state"] == "ok"][0]
    assert first["new"].startswith("2026-") and first["new"].endswith("-01.png"), first
    res = filetools.rename_apply(plan["rows"])
    assert res["ok"] == 3 and not res["failed"], res
    assert sorted(x.name for x in (base2 / "未整理").iterdir()) == sorted(
        r["new"] for r in plan["rows"] if r["state"] == "ok")
    undo = filetools.undo_apply(res["undo"])
    assert undo["ok"] == 3 and not undo["failed"], undo
    assert sorted(x.name for x in (base2 / "未整理").iterdir()) == sorted(
        ("合影.png", "合影-2.png", "名单.txt"))
    print("46. 批量重命名预览/执行/撤销 OK")

    # 47. 互换名字不打架（a→b、b→a 走两阶段改名）
    ka, kb = base2 / "未整理" / "甲.txt", base2 / "未整理" / "乙.txt"
    ka.write_text("甲", encoding="utf-8")
    kb.write_text("乙", encoding="utf-8")
    swap = filetools.rename_apply([
        {"src": str(ka), "dst": str(kb), "state": "ok"},
        {"src": str(kb), "dst": str(ka), "state": "ok"}])
    assert swap["ok"] == 2 and not swap["failed"], swap
    assert ka.read_text(encoding="utf-8") == "乙" and kb.read_text(encoding="utf-8") == "甲"
    print("47. 互换改名两阶段 OK")

    # 48. 图片格式转换：新增文件、原件保留、非图片显式跳过
    try:
        from PIL import Image
        png = base2 / "未整理" / "图.png"
        Image.new("RGB", (120, 90), (30, 120, 200)).save(png)
        plan = filetools.convert_plan([str(png), str(base2 / "未整理" / "甲.txt")],
                                      "JPEG", base=base2)
        ok_row = [r for r in plan["rows"] if r["state"] == "ok"][0]
        assert ok_row["dst"].endswith(".jpg")
        assert any("不是图片" in (r.get("reason") or "") for r in plan["rows"])
        out = filetools.convert_apply(plan["rows"], quality=80, delete_original=False)
        assert out["ok"] == 1 and not out["failed"], out
        assert os.path.isfile(ok_row["dst"]) and os.path.isfile(png)
        with Image.open(ok_row["dst"]) as im:
            assert im.size == (120, 90) and im.format == "JPEG"
        again = filetools.convert_plan([str(png)], "JPEG", base=base2)
        assert any("同名" in (r.get("reason") or "") for r in again["rows"]
                   if r["state"] == "ok")
        print("48. 图片转换 OK")
    except ImportError:
        print("48. 图片转换（无 Pillow，跳过）")

    # 49. 按类别归位：台账有的按类别走，台账没有的老实跳过
    doc_id = r.add_doc({"name": "合影", "cat": "宣传材料", "who": "张三",
                        "sid": "250201", "path": str(base2 / "未整理" / "合影.png"),
                        "file": "合影.png"})
    r.set_arch(doc_id, str(base2 / "未整理" / "合影.png"), "覃祖悦", "经办人")
    r.archive_doc(doc_id, "通过", "覃祖悦", "审核人")
    plan = filetools.organize_plan([str(base2 / "未整理" / "合影.png"),
                                    str(base2 / "未整理" / "甲.txt")],
                                   r.list_docs(), base=base2)
    rows = [x for x in plan["rows"] if x["state"] == "ok"]
    assert len(rows) == 1 and "宣传材料" in rows[0]["dst"], plan
    assert any("先登记再归位" in (x.get("reason") or "") for x in plan["rows"])
    moved = filetools.organize_apply(plan["rows"])
    assert moved["ok"] == 1 and os.path.isfile(rows[0]["dst"])
    assert not os.path.exists(base2 / "未整理" / "合影.png")
    print("49. 按类别归位 OK")

    # 50. 语音朗读：只验探测口径与拒空，不真的发声
    import tts
    info = tts.probe()
    assert set(info) >= {"ok", "voice", "voices", "reason"}, info
    if info["ok"]:
        assert info["voice"] and info["voices"], info
        assert "可用语音" in tts.describe(), tts.describe()
        print("50. 语音朗读探测 OK（%s）" % info["voice"])
    else:
        assert info["reason"], "不可用时必须给出原因"
        print("50. 语音朗读探测（不可用，%s）" % info["reason"])
    ok, why = tts.speak("")
    assert ok is False and why == "没有可朗读的内容", (ok, why)
    ok2, why2 = tts.speak("   ")
    assert ok2 is False and why2, "空白文本同样应拒绝"
    assert tts.is_speaking() is False, "未朗读时不应处于朗读态"

    # 51. 助手路由：本地规则命中、动作边界、无 AI 时不联网
    import assistant
    switches = []
    a = assistant.Assistant(r, open_view=switches.append)
    assert a.handle("")["ok"] is False
    help_r = a.handle("你都能做什么")
    assert help_r["action"] == "help" and "台账概览" in help_r["text"], help_r
    ov = a.handle("现在台账什么情况")
    assert ov["action"] == "overview" and "待审" in ov["text"], ov
    assert a.handle("谁还没交材料")["action"] == "missing_people"
    pd = a.handle("有哪些待审的")
    assert pd["action"] == "pending" and "待审" in pd["text"], pd
    roster = r.list_roster()
    sid = roster[0]["sid"] if roster else "250201"
    st = a.handle("%s 还缺什么" % sid)
    assert st["action"] == "status" and "还缺" in st["text"], st
    if roster:
        st2 = a.handle("%s还缺什么" % roster[0]["who"])
        assert st2["action"] == "status", st2
    ch = a.handle("给%s写催交话术" % sid)
    assert ch["action"] == "chase" and "入口：" in ch["text"], ch
    op = a.handle("打开服务留痕")
    assert op["action"] == "open_view" and switches[-1] == "service", (op, switches)
    # 只读边界：说归档/删除也不会真写
    for risky in ("把这份材料直接归档", "帮我把台账清空"):
        res = a.handle(risky)
        assert res["ok"] is False and res["action"] == "unknown", (risky, res)
    assert a.handle("今天天气怎么样")["action"] == "unknown"
    # 未配 API 时一律本地，不发网络请求
    for q in ("台账概览", "谁还没交材料"):
        assert a.handle(q)["source"] == "local", q
    # 朗读入口在无语音层时给原因而不是崩
    said = assistant.Assistant(r).handle("念一下")
    assert said["action"] == "speak" and said["text"], said
    print("51. 助手路由 OK")

    # 52. 助手会话：跨轮指代、当前材料、写操作回绝、主动开场
    doc = (r.list_docs() or [{}])[0]
    ctx = {"view": "docs", "doc": dict(doc)}
    c = assistant.Assistant(r, context=lambda: dict(ctx))
    assert c.brief_text().startswith("今天："), c.brief_text()
    assert "AI 通道" in c.help_text(), c.help_text()
    sid2 = (r.list_roster() or [{}])[0].get("sid") or "250201"
    st3 = c.ask("%s 还缺什么" % sid2)
    assert st3["action"] == "status", st3
    follow = c.ask("他缺什么")
    assert follow["action"] == "status" and follow["text"].splitlines()[0] in st3["text"], (
        follow, st3["text"])
    chase2 = c.ask("给他写催交话术")
    assert chase2["action"] == "chase" and "入口：" in chase2["text"], chase2
    # 指代没有上文时不许猜人
    nc = assistant.Assistant(r)
    guess = nc.ask("他缺什么")
    assert guess["ok"] and "哪位" in guess["text"], guess
    # 当前材料
    if doc:
        di = c.ask("这份什么情况")
        assert di["action"] == "doc_info" and "这份：" in di["text"], di
        di2 = c.ask("这份材料能归档吗")
        assert di2["action"] == "doc_info" and "不替你做" in di2["text"], di2
    else:
        di = nc.ask("这份什么情况")
        assert di["action"] == "doc_info" and "没有选中" in di["text"], di
    # 写操作：认得出、明确回绝、且不动数据
    for risky in ("把这份材料直接归档", "帮我把台账清空", "替我驳回这份"):
        res = c.ask(risky)
        assert res["ok"] is False and res["action"] == "unknown", (risky, res)
    print("52. 助手会话 OK")

    # 53. 入口交代：热键状态如实进帮助，不吹「随时可用」
    assert "唤起：" in c.help_text(), c.help_text()
    assert "不猜" in c.help_text(), c.help_text()
    c.hotkey_note = "被其他软件占用，按不通；点我或用顶栏「✦ 助手」"
    hk = c.help_text()
    assert "占用" in hk and "唤起：" in hk, hk
    c2 = assistant.Assistant(r)
    assert "唤起：" in c2.help_text(), c2.help_text()
    print("53. 入口交代 OK")

    # 54. 位置交代：嵌右栏说得清，窄了浮着也说得清
    loc = c2.help_text()
    assert "窗口够宽" in loc and "不压" in loc, loc
    assert "浮在角上" in loc, loc
    print("54. 位置交代 OK")

    # 55. 项目底座：建项目、套模板、改交付物、统计、备份恢复
    pid = r.add_project({
        "name": "主题班会材料", "kind": "class", "stage": "采集",
        "owner": "覃祖悦", "due_date": date_today(),
        "goal": "把主题班会材料收齐归档", "note": "第一个项目模板",
    })
    assert r.find_project(pid)["name"] == "主题班会材料"
    added = r.apply_project_template(pid)
    assert added == 4, added
    assert len(r.list_deliverables(pid)) == 4
    # 重复套模板不重复添加
    assert r.apply_project_template(pid) == 0
    did = r.list_deliverables(pid)[0]["id"]
    r.update_deliverable(did, {"status": "已通过", "note": "已核对"})
    st = r.project_stats(pid)
    assert st["total"] == 4 and st["done"] == 1 and st["progress"] == 25, st
    assert st["missing"] == 3, st
    # 交付物校验与资产 / 执行 / 质量门留位
    try:
        r.add_deliverable(pid, {"name": "x", "status": "瞎写"})
        raise SystemExit("应拦截非法交付物状态")
    except RepositoryError:
        pass
    r.add_project_asset(pid, {"name": "名单.xlsx", "kind": "xlsx", "size": 12})
    r.add_project_run(pid, {"tool": "ffprobe", "status": "已结束", "output": "ok"})
    r.set_project_gate(pid, "输入可识别", "通过", did, "文件能打开")
    assert len(r.list_project_assets(pid)) == 1
    assert len(r.list_project_runs(pid)) == 1
    assert len(r.list_project_gates(pid)) == 1
    # 助手接项目层：列项目、查单个项目缺什么、能打开项目页
    pa = assistant.Assistant(r, open_view=switches.append)
    pl = pa.handle("现在有哪些项目")
    assert pl["action"] == "projects" and "主题班会材料" in pl["text"], pl
    pdet = pa.handle("主题班会材料还缺什么")
    assert pdet["action"] == "project_detail" and "交付物" in pdet["text"], pdet
    assert "3" in pdet["text"] and "必交缺" in pdet["text"], pdet
    pv2 = pa.handle("打开项目工作台")
    assert pv2["action"] == "open_view" and switches[-1] == "projects", (pv2, switches)
    mvv = pa.handle("打开媒体工作台")
    assert mvv["action"] == "open_view" and switches[-1] == "media", (mvv, switches)
    dvv = pa.handle("打开文档工作台")
    assert dvv["action"] == "open_view" and switches[-1] == "doctools", (dvv, switches)
    # 项目层只读：不让助手替它改状态
    refused_p = pa.handle("帮我把项目删除")
    assert refused_p["ok"] is False and refused_p["action"] == "unknown", refused_p
    # 备份包含项目，恢复到新库后 ID 能对上
    bak = r.backup()
    assert bak["counts"]["projects"] >= 1
    assert bak["counts"]["project_deliverables"] >= 4
    tmp2 = Path(tempfile.mkdtemp()) / "selftest-project.db"
    r2 = LocalRepository(tmp2)
    r2.restore(bak["docs"], bak["logs"], bak["roster"], bak["tasks"],
               bak["attachments"], bak["templates"], bak["events"],
               bak["exemptions"], bak["followups"], bak["projects"],
               bak["project_deliverables"], bak["project_events"])
    p2 = r2.find_project(pid)
    assert p2 and p2["name"] == "主题班会材料", p2
    assert len(r2.list_deliverables(pid)) == 4
    assert r2.project_stats(pid)["done"] == 1
    # 恢复预览要能报出项目条数
    pv = audit.backup_preview(bak, r)
    assert pv["ok"] and "项目：备份" in pv["text"], pv
    # 删除项目不碰材料台账
    before = r.stats()["total"]
    r.remove_project(pid)
    assert r.find_project(pid) is None
    assert r.list_deliverables(pid) == []
    assert r.stats()["total"] == before
    print("55. 项目底座/模板/统计/备份恢复 OK")

    # 56. 媒体层：预设、缺文件预检、摘要文案（不依赖 ffmpeg 也能跑）
    assert set(media.PRESETS) == {"mp3_192", "mp3_128", "m4a_128", "wav_16k"}
    wav = media.preset("wav_16k")
    assert wav["codec"] == "pcm_s16le" and wav["sample_rate"] == 16000
    assert wav["channels"] == 1, wav
    tempdir = Path(tempfile.mkdtemp())
    rows, out_root = media.plan([str(tempdir / "没有这个.wav")], tempdir)
    assert len(rows) == 1 and not rows[0]["ok"], rows
    assert "不存在" in rows[0]["reason"] or "读" in rows[0]["reason"], rows[0]
    txt = media.summary_text({"total": 3, "done": 2, "failed": 1,
                              "manifest_csv": "清单.csv"})
    assert "3" in txt and "2" in txt and "1" in txt and "清单" in txt, txt
    print("56. 媒体预设/预检/摘要 OK")

    # 57. 文档工具：四类工具、六道门字段、页码范围与预检（不跑 OCR / 不写文件）
    assert set(dt.TOOLS) == {"pdf_split", "pdf_merge", "ocr", "pdf_to_docx",
                             "docx_to_pdf", "image_batch"}, set(dt.TOOLS)
    for k in dt.TOOL_ORDER:
        assert dt.describe_params(k, dt.default_params(k)), k
        assert dt.normalize_params(k, {}), k
    assert dt.parse_ranges("1-3,5", 5) == [(1, 3, "第001-003页"),
                                          (5, 5, "第005页")]
    assert len(dt.parse_ranges("", 3)) == 3
    try:
        dt.parse_ranges("1-9", 3)
        raise SystemExit("应拦截越界页码")
    except ValueError:
        pass
    tmp_docs = Path(tempfile.mkdtemp())
    rows = dt.preflight("pdf_merge", [str(tmp_docs / "没有这个.pdf")], {})
    assert rows and not rows[0]["ok"] and "不存在" in rows[0]["reason"], rows
    assert dt.available("pdf_split")[0], "本机 PDF 工具应可用"
    assert dt.available("image_batch")[0], "本机图片工具应可用"
    assert len(dt.MANIFEST_HEAD) == 11, dt.MANIFEST_HEAD
    txt = dt.summary_text({"total": 3, "done": 2, "failed": 1,
                           "manifest_csv": "清单.csv"})
    assert "3" in txt and "2" in txt and "1" in txt and "清单" in txt, txt
    print("57. 文档工具/六道门/页码范围 OK")

    # 58. 赛事数据层：三张表、默认矩阵、校验、备份恢复与级联删除
    cr = LocalRepository(Path(tempfile.mkdtemp()) / "comp.db")
    cr.restore([], [])
    cpid = cr.add_project({"name": "自检赛事", "kind": "competition",
                           "stage": "计划", "start_date": "2026-12-01",
                           "due_date": "2026-12-05"})
    cr.apply_project_template(cpid)
    seeded = cp.seed_project(cr, cpid)
    assert seeded["events"] == 3 and seeded["rubric"] == 5, seeded
    assert len(cr.list_competition_events(cpid)) == 3
    rubric = cr.list_competition_rubric(cpid)
    assert cp.rubric_stats(rubric)["weight"] == 100
    cr.add_competition_entry(cpid, {"name": "张三", "sid": "250201", "role": "队长"})
    try:
        cr.add_competition_entry(cpid, {"name": "李四", "sid": "250201"})
        raise SystemExit("同学号应拦截")
    except RepositoryError:
        pass
    cr.add_competition_entry(cpid, {"name": "李四", "sid": "250202", "role": "队员"})
    assert cp.entry_stats(cr.list_competition_entries(cpid))["total"] == 2
    bak = cr.backup()
    assert bak["counts"]["competition_events"] == 3
    assert bak["counts"]["competition_entries"] == 2
    assert bak["counts"]["competition_rubric"] == 5
    cr2 = LocalRepository(Path(tempfile.mkdtemp()) / "comp2.db")
    cr2.restore([], [], projects=bak["projects"],
                competition_events=bak["competition_events"],
                competition_entries=bak["competition_entries"],
                competition_rubric=bak["competition_rubric"])
    assert len(cr2.list_all_competition_events()) == 3
    assert len(cr2.list_all_competition_entries()) == 2
    assert len(cr2.list_all_competition_rubric()) == 5
    cr.remove_project(cpid)
    assert cr.list_competition_events(cpid) == []
    assert cr.list_competition_entries(cpid) == []
    assert cr.list_competition_rubric(cpid) == []
    # 助手入口：认得出赛事工作台，也仍然只读
    csw = []
    ca = assistant.Assistant(cr, open_view=csw.append)
    ov = ca.handle("打开赛事工作台")
    assert ov["action"] == "open_view" and csw[-1] == "competition", (ov, csw)
    assert ca.handle("帮我把报名名单删掉")["ok"] is False
    print("58. 赛事数据层/备份/助手入口 OK")

    # 59. 产品数据层：五张表、默认 PRD/架构、评审门、上线检查、备份与级联删除
    pr = LocalRepository(Path(tempfile.mkdtemp()) / "prod.db")
    pr.restore([], [])
    ppid = pr.add_project({"name": "自检产品", "kind": "product",
                           "stage": "定义", "start_date": "2026-11-01",
                           "due_date": "2026-12-20"})
    pr.apply_project_template(ppid)
    ps = pp.seed_project(pr, ppid)
    assert ps["specs"] == 11 and ps["reviews"] == 4, ps
    assert len(pr.list_product_specs(ppid, "prd")) == 7
    assert len(pr.list_product_specs(ppid, "arch")) == 4
    assert len(pr.list_product_reviews(ppid)) == 4
    pr.update_product_spec(pr.list_product_specs(ppid, "prd")[0]["id"],
                           {"content": "人工记录容易漏。"})
    pr.add_product_bom(ppid, {"kind": "物料", "name": "传感器", "qty": 2,
                              "unit": "支", "unit_cost": 50, "source": "库存"})
    try:
        pr.add_product_bom(ppid, {"kind": "物料", "name": "零数量", "qty": 0})
        raise SystemExit("数量为 0 应拦截")
    except RepositoryError:
        pass
    pr.add_product_proto(ppid, {"name": "看板", "status": "可用", "path": __file__})
    pr.add_product_test(ppid, {"name": "读数", "result": "通过", "severity": "高"})
    assert pp.bom_stats(pr.list_product_bom(ppid))["cost"] == 100.0
    assert pp.test_stats(pr.list_product_tests(ppid))["ready"]
    rr = pp.readiness(pr, ppid)
    assert not rr["ok"] and len(rr["items"]) == 6, rr
    assert [i["name"] for i in rr["items"]][0] == "需求完整"
    bak = pr.backup()
    assert bak["counts"]["product_specs"] == 11
    assert bak["counts"]["product_bom"] == 1
    assert bak["counts"]["product_protos"] == 1
    assert bak["counts"]["product_tests"] == 1
    assert bak["counts"]["product_reviews"] == 4
    pr2 = LocalRepository(Path(tempfile.mkdtemp()) / "prod2.db")
    pr2.restore([], [], projects=bak["projects"],
                product_specs=bak["product_specs"],
                product_bom=bak["product_bom"],
                product_protos=bak["product_protos"],
                product_tests=bak["product_tests"],
                product_reviews=bak["product_reviews"])
    assert len(pr2.list_all_product_specs()) == 11
    assert len(pr2.list_all_product_bom()) == 1
    assert len(pr2.list_all_product_protos()) == 1
    assert len(pr2.list_all_product_tests()) == 1
    assert len(pr2.list_all_product_reviews()) == 4
    pr.remove_project(ppid)
    assert pr.list_product_specs(ppid) == []
    assert pr.list_product_bom(ppid) == []
    assert pr.list_product_protos(ppid) == []
    assert pr.list_product_tests(ppid) == []
    assert pr.list_product_reviews(ppid) == []
    psw = []
    pa = assistant.Assistant(pr, open_view=psw.append)
    ov = pa.handle("打开产品工作台")
    assert ov["action"] == "open_view" and psw[-1] == "product", (ov, psw)
    print("59. 产品数据层/上线检查/备份/助手入口 OK")

    # 60. 数据/活动：七表 CRUD、报告包、结项包、备份恢复与助手入口
    dr = LocalRepository(Path(tempfile.mkdtemp()) / "de.db")
    dr.restore([], [])
    dpid = dr.add_project({"name": "自检数据项目", "kind": "data", "stage": "采集",
                           "start_date": "2026-11-20"})
    dr.apply_project_template(dpid, "data")
    dl.seed_data(dr, dpid)
    csv_path = Path(tempfile.mkdtemp()) / "self.csv"
    csv_path.write_text("姓名,班级,分数\n甲,2502,80\n乙,2502,90\n甲,2502,80\n",
                        encoding="utf-8-sig")
    loaded = dl.read_table(csv_path)
    prof = dl.profile(loaded["headers"], loaded["rows"])
    dr.set_data_source(dpid, {"name": csv_path.name, "path": str(csv_path),
                              "encoding": loaded["encoding"], "rows": 3, "cols": 3},
                       [{"name": f["name"], "dtype": f["dtype"],
                         "missing": f["missing"], "unique_n": f["unique_n"]}
                        for f in prof["fields"]])
    assert dl.readiness(dr, dpid)["ok"]
    dpkg = dl.make_package(dr, dpid, str(Path(tempfile.mkdtemp()) / "out"))
    assert len(dpkg["files"]) == 4 and dpkg["stats"]["rows_out"] == 2
    assert "<svg" in Path(dpkg["files"][2]).read_text(encoding="utf-8")
    epid = dr.add_project({"name": "自检活动项目", "kind": "event", "stage": "计划",
                           "start_date": "2026-11-26"})
    dr.apply_project_template(epid, "event")
    ev.seed_event(dr, epid)
    for p in dr.list_event_plan(epid):
        dr.update_event_plan(p["id"], {"content": "按演练记录填写。"})
    for name, status in (("甲", "已签到"), ("乙", "已签到"), ("丙", "缺席")):
        dr.add_event_person(epid, {"name": name, "status": status})
    dr.add_event_expense(epid, {"item": "物料", "budget": 50, "actual": 42})
    for n in dr.list_event_notes(epid)[:3]:
        dr.update_event_note(n["id"], {"content": "按实际执行填写。"})
    assert ev.readiness(dr, epid)["ok"]
    epkg = ev.make_package(dr, epid, str(Path(tempfile.mkdtemp()) / "out"))
    assert len(epkg["files"]) == 6 and Path(epkg["zip"]).exists()
    bak = dr.backup()
    assert bak["counts"]["data_sources"] == 1
    assert bak["counts"]["data_fields"] == 3
    assert bak["counts"]["data_notes"] == 5
    assert bak["counts"]["event_plan"] == 8
    assert bak["counts"]["event_people"] == 3
    assert bak["counts"]["event_expenses"] == 1
    dr2 = LocalRepository(Path(tempfile.mkdtemp()) / "de2.db")
    dr2.restore([], [], projects=bak["projects"],
                data_sources=bak["data_sources"], data_fields=bak["data_fields"],
                data_notes=bak["data_notes"], event_plan=bak["event_plan"],
                event_people=bak["event_people"],
                event_expenses=bak["event_expenses"],
                event_notes=bak["event_notes"])
    assert len(dr2.list_all_data_sources()) == 1
    assert len(dr2.list_all_data_fields()) == 3
    assert len(dr2.list_all_event_people()) == 3
    dr2.remove_project(bak["projects"][0]["id"])
    assert dr2.list_all_data_fields() == []
    dr2.remove_project(bak["projects"][1]["id"])
    assert dr2.list_all_event_people() == []
    dsw = []
    da = assistant.Assistant(dr, open_view=dsw.append)
    ov = da.handle("打开数据工作台")
    assert ov["action"] == "open_view" and dsw[-1] == "data", (ov, dsw)
    ov = da.handle("打开活动工作台")
    assert ov["action"] == "open_view" and dsw[-1] == "event", (ov, dsw)
    print("60. 数据/活动七表、报告包、结项包、备份与助手入口 OK")

    print("SELFTEST OK")


if __name__ == "__main__":
    main()

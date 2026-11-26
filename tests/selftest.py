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

    print("SELFTEST OK")


if __name__ == "__main__":
    main()

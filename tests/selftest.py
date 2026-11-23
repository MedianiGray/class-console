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
import archive  # noqa: E402
import audit  # noqa: E402
import fileroom  # noqa: E402
import handover  # noqa: E402
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

    print("SELFTEST OK")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""数据层回归自检（临时库，不读写本机真实数据）。

每次改动数据层或仓库方法后运行：
    py -3.14 tests/selftest.py
全部通过会打印 SELFTEST OK；任一断言失败会以非零退出码结束。
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from database import LocalRepository, RepositoryError, date_today  # noqa: E402


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

    print("SELFTEST OK")


if __name__ == "__main__":
    main()

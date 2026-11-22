# -*- coding: utf-8 -*-
"""GUI 冒烟回归（需要图形界面环境；临时库，不读写本机真实数据）。

运行：
    py -3.14 tests/gui_smoke.py
覆盖：视图切换、角色切换、提交入库、留痕角色跟随、校验拦截、归档驳回、禁用联动、脏记录渲染、申请人学号过滤、日志备份附件恢复。
"""
import sys
import json
import os
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 设置文件走临时目录，避免测试改写本机真实偏好
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="cc-gui-appdata-")
import tkinter as tk  # noqa: E402
import ui_logs  # noqa: E402
from database import LocalRepository  # noqa: E402
from ui_main import MainWindow  # noqa: E402


def main():
    db = Path(tempfile.mkdtemp()) / "smoke.db"
    repo = LocalRepository(db)
    repo.restore(
        [{"who": "脏记录缺名称"},
         {"name": "正常材料", "cat": "学分材料", "who": "张三", "sid": "250201"}],
        [{"act": "提交", "obj": "正常材料"}])

    root = tk.Tk()
    app = MainWindow(root, repo)
    app.confirm = lambda title, msg: True
    root.update()

    for k in ("dashboard", "docs", "roster", "tasks", "submit", "logs"):
        app.switch(k)
        root.update()
    print("视图切换 OK")

    # 名单视图：添加 / 移除
    rv = app.views["roster"]
    repo.add_roster("250210", "孙倩")
    rv.refresh(); root.update()
    assert repo.find_roster_by_sid("250210") is not None
    chk = repo.roster_check()
    assert chk["total"] == 1
    print("名单视图 OK")

    # 任务视图：添加 / 切换完成 / 统计
    tv = app.views["tasks"]
    tid = repo.add_task({"title": "冒烟任务", "deadline": "2099-01-01"})
    tv.refresh(); root.update()
    assert repo.find_task(tid) is not None
    repo.toggle_task(tid)
    assert repo.find_task(tid)["done"] is True
    repo.remove_task(tid)
    print("任务视图 OK")

    sv = app.views["submit"]

    # 申请人视角提交：留痕角色跟随当前视角
    app.role_var.set("applicant"); app._toggle_role(); root.update()
    sv.var_title.set("申请人视角提交"); sv.var_name.set("王五"); sv.var_sid.set("250203")
    sv.var_cat.set("学分材料"); sv.submit(); root.update()
    last = repo.list_logs()[0]
    assert last["role"] == "申请人" and last["who"] == app.operator_name
    print("申请人视角留痕 OK")

    # 审核者视角提交：留痕角色切换为审核者
    app.role_var.set("reviewer"); app._toggle_role(); root.update()
    sv.var_title.set("复测材料"); sv.var_name.set("李四"); sv.var_sid.set("250202")
    sv.var_cat.set("奖助材料"); sv.submit(); root.update()
    last = repo.list_logs()[0]
    assert last["role"] == "审核者" and last["who"] == app.operator_name
    print("提交/角色跟随 OK")

    sv.var_title.set("拦截"); sv.var_name.set(""); sv.var_sid.set("abc"); sv.var_cat.set("")
    sv.submit(); root.update()
    assert sv.err_label.cget("text")
    print("校验 OK")

    dv = app.views["docs"]
    dv._reason_dialog = lambda title, prompt: {"ok": True, "reason": "冒烟备注"}
    first = dv.tree.get_children()[0]
    dv.tree.selection_set(first); dv.archive(); root.update()
    first = dv.tree.get_children()[0]
    dv.tree.selection_set(first); dv.reject(); root.update()
    dv.tree.selection_remove(*dv.tree.selection()); dv._update_actions()
    assert str(dv.btn_view.cget("state")) == "disabled"
    print("归档驳回/禁用 OK")

    # 桌面台账 0.14.2：多选批量与右侧审批节点详情
    dv.refresh(); root.update()
    ids_a = repo.add_doc({"name": "批量归档甲", "cat": "学分材料", "who": "甲",
                          "sid": "250211", "status": "待审核"})
    ids_b = repo.add_doc({"name": "批量归档乙", "cat": "奖助材料", "who": "乙",
                          "sid": "250212", "status": "待审核"})
    dv.refresh(); root.update()
    rows = [dv._row_iids[i] for i in (ids_a, ids_b) if i in dv._row_iids]
    assert len(rows) == 2, "批量测试材料未进入台账"
    dv.tree.selection_set(rows)
    dv._update_actions(); root.update()
    assert len(dv._selected_ids()) == 2
    assert "批量归档 (2)" in dv.btn_archive.cget("text")
    detail = dv.detail_text.get("1.0", "end")
    assert "审批节点" in detail and "提交" in detail and "批量" in detail
    dv.archive(); root.update()
    by_id = {d["id"]: d for d in repo.list_docs()}
    assert all(by_id[i]["status"] == "已归档" for i in (ids_a, ids_b))

    ids_c = repo.add_doc({"name": "批量驳回丙", "cat": "学分材料", "who": "丙",
                          "sid": "250213", "status": "待审核"})
    ids_d = repo.add_doc({"name": "批量驳回丁", "cat": "学分材料", "who": "丁",
                          "sid": "250214", "status": "待审核"})
    dv.refresh(); root.update()
    rows = [dv._row_iids[i] for i in (ids_c, ids_d) if i in dv._row_iids]
    dv.tree.selection_set(rows)
    dv._update_actions()
    assert "批量驳回 (2)" in dv.btn_reject.cget("text")
    dv.reject(); root.update()
    by_id = {d["id"]: d for d in repo.list_docs()}
    assert all(by_id[i]["status"] == "已驳回" for i in (ids_c, ids_d))
    print("多选批量/审批节点 OK")

    # 提醒中心：顶栏常驻入口、角标按待办计数、对话框可打开
    snap = app.reminder_snapshot()
    assert snap["total"] > 0
    app.refresh_reminders(); root.update()
    assert app.reminder_btn.winfo_ismapped(), "顶栏提醒入口应常驻"
    assert app.reminder_badge.cget("text") == str(snap["total"])
    dlg = app._open_reminders(); root.update()
    assert dlg.top.winfo_exists() and dlg.top.title() == "提醒中心"
    dlg.close(); root.update()
    print("提醒中心 OK")

    # 模板字段最小配置：设置里增删，提交表单即时重建
    from ui_settings import SettingsDialog
    sd = SettingsDialog(app); root.update()
    assert sd.tpl_tree.winfo_exists(), "设置里应有材料模板分区"
    sd.tpl_type_var.set("自定义材料"); sd._reload_template_fields()
    sd.tpl_label_var.set("抽检备注"); sd.tpl_kind_var.set("下拉")
    sd.tpl_opts_var.set("合格,待补"); sd.tpl_req_var.set(True)
    sd._add_template_field(); root.update()
    assert any(f["label"] == "抽检备注"
               for f in repo.template_custom("custom")), "设置添加字段未入库"
    sv.var_type.set("自定义材料"); sv._on_type(); root.update()
    assert any(k.startswith("cf_") for k in sv.extra_vars), "提交表单未重建附加字段"
    sd.close(); root.update()
    print("模板字段配置 OK")

    # 归档规则：设置页保存、映射生效、恢复默认
    import archive
    import ui_settings
    ui_settings.messagebox.showwarning = lambda *a, **k: None
    sd2 = SettingsDialog(app); root.update()
    sd2.rule_dir_var.set("{category}/{student}")
    sd2.rule_file_var.set("{sid}-{name}")
    sd2.rule_map_text.delete("1.0", "end")
    sd2.rule_map_text.insert("1.0", "学分材料=01-学分")
    sd2._save_archive_rule(); root.update()
    saved = archive.load_rule()
    assert saved["file_template"] == "{sid}-{name}", saved
    assert saved["category_map"].get("学分材料") == "01-学分", saved
    assert "01-学分" in sd2.rule_preview_var.get(), sd2.rule_preview_var.get()
    sd2.rule_dir_var.set("")
    sd2._preview_archive_rule(); root.update()
    assert sd2.rule_preview_var.get().startswith("试算失败"), sd2.rule_preview_var.get()
    archive.save_rule(archive.default_rule())
    sd2.close(); root.update()
    print("归档规则配置 OK")

    # 看板岗位显隐：申请人隐藏名单/任务 chip 与近期动态，审核者恢复
    dash = app.views["dashboard"]
    app.applicant_sid = "250203"
    app.role_var.set("applicant"); app._toggle_role(); root.update()
    app.switch("dashboard"); root.update_idletasks()
    assert not dash.roster_hint.winfo_ismapped(), "申请人不应显示名单提示"
    assert not dash.task_hint.winfo_ismapped(), "申请人不应显示任务提示"
    assert not dash.log_card.winfo_ismapped(), "申请人不应显示近期动态"
    assert "关注" in dash.bottom_title.cget("text")

    # 申请人只看本人：看板与台账都按学号过滤
    own = [d for d in repo.list_docs() if d.get("sid") == "250203"]
    own_focus = [d for d in own if d.get("status") in ("待审核", "已驳回")]
    assert dash.hero_num.cget("text") == str(len(own_focus))
    assert len(dash.doc_tree.get_children()) == min(len(own_focus), 5)
    dv.refresh(); root.update()
    assert len(dv.tree.get_children()) == len(own), "申请人台账应只显示本人材料"

    # 未填学号：不展示任何人的材料
    app.applicant_sid = ""
    dash.refresh(); root.update()
    assert dash.hero_num.cget("text") == "0"
    assert len(dash.doc_tree.get_children()) == 0
    assert "学号" in dash.hero_hint.cget("text")
    app.applicant_sid = "250203"
    print("申请人学号过滤 OK")

    # 操作日志导入备份：附件必须随记录恢复，不能被清空
    repo.add_doc({"name": "附件恢复测试", "cat": "学分材料", "who": "赵六",
                  "sid": "250204",
                  "attachments": [{"name": "a.pdf", "path": "D:/a.pdf", "kind": "材料"}]})
    backup_path = Path(tempfile.mkdtemp()) / "logs-backup.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(repo.backup(), f, ensure_ascii=False)
    ui_logs.filedialog.askopenfilename = lambda **kw: str(backup_path)
    app.views["logs"].import_backup()
    restored = [d for d in repo.list_docs() if d["name"] == "附件恢复测试"][0]
    assert len(restored["attachments"]) == 1, restored
    print("日志备份附件恢复 OK")

    app.role_var.set("reviewer"); app._toggle_role(); root.update()
    app.switch("dashboard"); root.update()
    assert dash.roster_hint.winfo_ismapped(), "审核者应显示名单提示"
    assert dash.task_hint.winfo_ismapped(), "审核者应显示任务提示"
    assert dash.log_card.winfo_ismapped(), "审核者应显示近期动态"
    assert "待处理" in dash.bottom_title.cget("text")
    print("看板岗位显隐 OK")

    # 主题切换：深色 / 浅色各重建一次，数据与视图保持不变
    import theme
    for m in ("dark", "light"):
        theme.apply(m)
        app._restyle()
        root.update()
        assert theme.resolved() == m, "主题未按预期生效：%s" % m
        assert app.current in app.views, "切主题后当前视图丢失"
        for k in ("dashboard", "docs", "roster", "tasks", "submit", "logs"):
            app.switch(k)
            root.update()
        assert app.views["docs"].tree.get_children(), "切主题后台账为空"
        assert app.views["dashboard"].card_values["total"].cget("text") != "0", "切主题后看板未刷新"
    theme.apply("light")
    print("主题切换 OK")

    root.destroy()
    print("GUI SMOKE OK")


if __name__ == "__main__":
    main()

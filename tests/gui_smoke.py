# -*- coding: utf-8 -*-
"""GUI 冒烟回归（需要图形界面环境；临时库，不读写本机真实数据）。

运行：
    py -3.14 tests/gui_smoke.py
覆盖：视图切换、角色切换、提交入库、留痕角色跟随、校验拦截、归档驳回、禁用联动、脏记录渲染、申请人学号过滤、文件室目录/预览/缺失反查、日志备份附件恢复。
"""
import sys
import json
import os
import tempfile
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 设置文件走临时目录，避免测试改写本机真实偏好
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="cc-gui-appdata-")
import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402
import ui_logs  # noqa: E402
from ui_empty import EmptyState  # noqa: E402
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
    root.geometry("1220x820+30+30")
    app = MainWindow(root, repo)
    app.confirm = lambda title, msg: True
    root.update()

    # 首次引导：卡片可收起、可重显、完成前两步自动收起
    dash = app.views["dashboard"]
    assert app.first_run_visible(), "首次引导应默认可见"
    assert dash.first_card.winfo_ismapped(), "首次引导卡未显示"
    assert dash.fr_count.cget("text") == "0 / 3", dash.fr_count.cget("text")
    assert dash.fr_rows[0][1].cget("text") == "录入或收集第一份材料"
    dash.fr_dismiss.invoke(); root.update()
    assert not app.first_run_visible() and not dash.first_card.winfo_ismapped()
    app.reset_first_run(); root.update()
    assert app.first_run_visible() and dash.first_card.winfo_ismapped()
    app.mark_first_run(1); app.mark_first_run(2); root.update()
    assert not app.first_run_visible(), "完成前两步后首导应收起"
    app.reset_first_run(); root.update()
    print("首次引导卡 OK")

    for k in ("dashboard", "docs", "files", "roster", "tasks", "submit", "logs"):
        app.switch(k)
        root.update()
        assert app.views[k].winfo_manager() == "pack", (k, app.views[k].winfo_manager())
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
    assert "流转时间线" in detail and "提交" in detail and "批量" in detail
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

    # 台账效率层：列宽持久化、表头排序、命名保存视图、命令面板、完成矩阵
    import ui_docs
    dv._widths["name"] = 300
    dv._apply_widths(); dv._save_widths()
    assert dv._load_widths()["name"] == 300, "列宽未持久化"
    dv._sort_key = "time"; dv._sort_dir = "desc"; dv._sync_headings()
    assert "▼" in dv.tree.heading("time")["text"], "表头未显示排序箭头"
    dv.reset_widths(); root.update()
    assert dv._load_widths()["name"] == dv.WIDTHS["name"], "重置列宽未落盘"
    dv.q.set(""); dv.cat.set("全部"); dv.type.set("全部"); dv.status.set("全部")
    dv._widths["name"] = 260; dv._apply_widths()
    dv._sort_key = "name"; dv._sort_dir = "asc"; dv._sync_headings()
    ui_docs.simpledialog.askstring = lambda *a, **k: "冒烟视图"
    dv.save_current_view()
    saved_views = dv._load_views()
    assert saved_views and saved_views[-1]["name"] == "冒烟视图", "保存视图未落库"
    dv.q.set("不存在"); dv._widths["name"] = 180; dv._apply_widths()
    dv._apply_view("冒烟视图"); root.update()
    assert dv.q.get() == "" and dv._widths["name"] == 260, "套用视图未还原筛选或列宽"
    assert dv._sort_key == "name" and dv._sort_dir == "asc", "套用视图未还原排序"
    app.confirm = lambda title, msg: True
    dv._delete_view("冒烟视图")
    assert not any(v["name"] == "冒烟视图" for v in dv._load_views()), "删除视图失败"
    dv.reset_widths(); root.update()

    app.switch("docs"); root.update()
    app._open_cmdk(); root.update()
    pal = app.cmdk
    assert pal.top.winfo_exists(), "Ctrl+K 命令面板未打开"
    pal.entry.delete(0, "end"); pal.entry.insert(0, ">归档")
    pal._load(">归档"); root.update()
    assert pal.items and all(it.get("kind") == "动作" for it in pal.items), ">归档 不应混入材料"
    assert any("归档" in it["title"] for it in pal.items), ">归档 未命中归档动作"
    pal.close(); root.update()

    rv.nb.select(1); root.update()
    assert rv.nb.index(rv.nb.select()) == 1, "完成矩阵标签未选中"
    assert len(rv.matrix.get_children()) == len(repo.list_roster()), "完成矩阵行数与名单不一致"
    assert rv.matrix_summary.cget("text").startswith("已交"), "完成矩阵汇总缺失"
    print("台账效率层/命令面板/完成矩阵 OK")


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
    import ai
    import ui_settings
    ui_settings.messagebox.showwarning = lambda *a, **k: None
    sd2 = SettingsDialog(app); root.update()
    assert sd2.ai_status.winfo_exists(), "设置里应有 AI 建议分区"
    sd2.ai_enabled.set(False)
    sd2.ai_base_var.set("https://api.siliconflow.cn/v1/")
    sd2.ai_model_var.set("Qwen/Qwen2.5-7B-Instruct")
    sd2.ai_key_var.set("sk-gui-test-not-real")
    sd2.ai_timeout_var.set("60")
    sd2._save_ai(); root.update()
    cfg = ai.load_config()
    assert cfg["enabled"] is False, cfg
    assert cfg["base_url"] == "https://api.siliconflow.cn/v1", cfg
    assert cfg["timeout"] == 40, cfg
    assert cfg["api_key"] == "sk-gui-test-not-real", "AI Key 未落本机临时设置"
    sd2._toggle_ai_key(); root.update()
    assert sd2.ai_key_entry.cget("show") == "", "显示按钮没有切换 Key 掩码"
    sd2._toggle_ai_key(); root.update()
    assert sd2.ai_key_entry.cget("show") == "•", "再次点击没有恢复 Key 掩码"
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

    # v0.18 服务层：延期/回执进矩阵、催交限频、服务留痕视图
    import service
    app.role_var.set("handler"); app._toggle_role(); root.update()
    repo.add_roster("269998", "服务测试")
    future = (datetime.date.today() + datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    repo.set_exemption("269998", "服务测试", "奖助材料", "延期", "材料在校外",
                       future, actor="覃祖悦", role="经办人")
    missing = service.missing_categories(repo.list_docs(), "269998")
    msg = service.chase_message("服务测试", missing, future)
    repo.add_followup("269998", "服务测试", "、".join(missing), msg,
                      "微信 / 群公告", "覃祖悦", "经办人")
    assert repo.chase_state("269998")["allowed"] is False, "催交后应进入 24 小时冷却"
    repo.add_receipt("269998", "服务测试", "团务材料", "校外交", "已在校外提交",
                     "覃祖悦", "经办人")
    rv.refresh(); root.update()
    def _mrow(sid):
        for i in rv.matrix.get_children():
            vals = rv.matrix.item(i, "values")
            if vals and vals[0] == sid:
                return i
        return ""
    mid = _mrow("269998")
    assert mid, "矩阵未找到新增同学"
    rv.matrix.selection_set(mid); rv.matrix.focus(mid); rv.svc_cat.set("奖助材料")
    rv._update_matrix_actions(); root.update()
    assert "延期" in rv.matrix_target.cget("text"), rv.matrix_target.cget("text")
    assert str(rv.btn_exempt.cget("state")) == "normal", "延期学生仍可修改登记"
    app.switch("service"); root.update()
    svc = app.views["service"]
    svc.refresh(); root.update()
    assert len(svc.tree.get_children()) >= 3, "服务留痕条数不足"
    assert svc.summary.cget("text").startswith("共 "), svc.summary.cget("text")
    # 语音朗读入口：只验存在与启用态，不真的发声（避免测试时出声）
    assert svc.btn_speak.cget("text") == "朗读内容", svc.btn_speak.cget("text")
    assert str(svc.btn_speak.cget("state")) == "normal", "有记录时朗读应可用"
    fav = svc.tree.get_children()[0]
    svc.tree.selection_set(fav); svc.tree.focus(fav); root.update()
    assert svc._rows.get(fav), "服务记录映射丢失"
    assert hasattr(app.views["docs"], "btn_speak"), "材料详情缺朗读入口"
    print("服务入口/留痕视图 OK")

    # v0.17 审计界面：日志筛选、证据包入口、完整性弹窗均可构建
    app.role_var.set("handler"); app._toggle_role(); root.update()
    app.switch("logs"); lv = app.views["logs"]; root.update()
    repo.add_log("提交", "筛选命中甲", "甲", "申请人")
    repo.add_log("归档", "筛选命中乙", "乙", "审核人")
    repo.add_log("驳回", "筛选落空丙", "丙", "审核人")
    lv.var_q.set("筛选命中"); lv.refresh(); root.update()
    assert "匹配" in lv.count.cget("text"), lv.count.cget("text")
    lv.var_q.set(""); lv.var_act.set("驳回"); lv.var_who.set("丙")
    lv.refresh(); root.update()
    assert "匹配 1 / 共" in lv.count.cget("text"), lv.count.cget("text")
    lv._clear_filters(); root.update()
    assert lv.btn_evidence.winfo_ismapped(), "管理层应能看到证据包入口"

    import archive
    import audit
    import ui_audit
    archive.save_root(str(Path(tempfile.mkdtemp()) / "archive"))
    ed = ui_audit.EvidenceDialog(lv, repo, app)
    root.update()
    assert "全部" in ed.cat.get() or ed.cat.get() == "全部"
    assert ed.with_files.get() is False
    ed.top.destroy(); root.update()

    iv = ui_audit.IntegrityDialog(lv, repo, app)
    root.update()
    assert "归档根" in iv.summary.cget("text")
    assert iv.text.get("1.0", "end").strip(), "完整性检查应有结果文本"
    iv.top.destroy(); root.update()
    print("审计界面 OK")

    app.role_var.set("reviewer"); app._toggle_role(); root.update()
    app.switch("dashboard"); root.update()
    assert dash.roster_hint.winfo_ismapped(), "审核者应显示名单提示"
    assert dash.task_hint.winfo_ismapped(), "审核者应显示任务提示"
    assert dash.log_card.winfo_ismapped(), "审核者应显示近期动态"
    assert "待处理" in dash.bottom_title.cget("text")
    print("看板岗位显隐 OK")

    # v0.19 文件室：目录树、文件状态、文本预览、缺失反查与登记弹窗
    base = archive.root()
    mate = base / "团务材料" / "250201-张三"
    mate.mkdir(parents=True, exist_ok=True)
    (mate / "文件室材料.txt").write_text("文件室预览内容", encoding="utf-8")
    fid = repo.add_doc({"name": "文件室材料", "cat": "团务材料", "who": "张三",
                        "sid": "250201", "path": str(mate / "文件室材料.txt")})
    repo.archive_doc(fid, "通过", "覃祖悦", "审核人")
    repo.set_arch(fid, str(mate / "文件室材料.txt"), "覃祖悦", "审核人")
    mid2 = repo.add_doc({"name": "文件室缺失", "cat": "奖助材料",
                         "who": "李四", "sid": "250202"})
    repo.archive_doc(mid2, "通过", "覃祖悦", "审核人")
    repo.set_arch(mid2, str(base / "奖助材料" / "250202-李四" / "没有这份.pdf"),
                  "覃祖悦", "审核人")
    audit.rebuild_index(repo.list_docs(), base)
    app.switch("files"); root.update()
    fv = app.views["files"]
    fv.refresh(); root.update()
    assert fv._dir_iids.get("团务材料/250201-张三"), "文件室目录树缺材料目录"
    assert fv.tree_dirs.get_children("root"), "文件室目录树为空"
    fv.rel = "团务材料/250201-张三"
    fv._build_tree(); fv._load_files(); root.update()
    assert fv.files.get_children(), "文件室当前目录未列出文件"
    first_file = fv.files.get_children()[0]
    fv.files.selection_set(first_file); fv.files.focus(first_file)
    fv._on_file(); root.update()
    assert "文件室材料" in fv.preview_title.cget("text"), fv.preview_title.cget("text")
    texts = [w.get("1.0", "end") for w in fv.preview_body.winfo_children()
             if isinstance(w, tk.Text)]
    assert any("文件室预览内容" in t for t in texts), "文本预览未显示文件内容"
    assert len(fv.maps["missing"]) >= 1, "缺失文件未进入反查清单"
    import ui_files
    md = ui_files.MissingDialog(fv, repo, app)
    root.update()
    assert len(md.rows) >= 1 and md.tree.get_children(), "缺失弹窗列表为空"
    md.top.destroy(); root.update()
    rd = ui_files.RegisterDialog(fv, repo, app, [str(mate / "文件室材料.txt")],
                                 current_rel="团务材料/250201-张三")
    root.update()
    assert rd.var_cat.get() == "团务材料" and rd.var_who.get() == "张三"
    assert "落点" in rd.target_var.get()
    rd.top.destroy(); root.update()
    kids = fv.files.get_children()[:2]
    fv.files.selection_set(kids)
    fd = fv.open_filetools()
    root.update()
    assert fd is not None and fd.paths, "批量工具入口没拿到选中文件"
    fd.do_rename_preview(); root.update()
    assert fd.tree.get_children(), "批量改名预览为空"
    fd._switch("convert"); fd.do_convert_preview(); root.update()
    fd._switch("organize"); fd.do_organize_preview(); root.update()
    fd.close(); root.update()
    fv.files.selection_set(first_file); fv.files.focus(first_file); root.update()
    print("文件室视图/预览/缺失反查 OK")
    print("批量文件工具入口/三页预览 OK")

    # Windows 原生拖入：仅 Windows 注册 WM_DROPFILES，其他平台明确跳过
    if sys.platform != "win32":
        print("Windows 原生拖入 SKIP（非 Windows 平台）")
    else:
        # Windows 原生拖入：真实 WM_DROPFILES 消息应触发当前文件室登记回调
        import ctypes
        import time
        from ctypes import wintypes
        import drop_target
        if app._drop_ready in (None, False, "pending"):
            app._install_file_drop()
            root.update()
        assert app._drop_ready is True, "拖入注册失败"
        got = []
        fv.accept_drop = lambda paths: got.extend(paths)
        drop_file = base / "拖入消息.txt"
        drop_file.write_text("drop", encoding="utf-8")
        class DROPFILES(ctypes.Structure):
            _fields_ = [("pFiles", wintypes.DWORD), ("pt", wintypes.POINT),
                        ("fNC", wintypes.BOOL), ("fWide", wintypes.BOOL)]
        text = (str(drop_file) + "\0\0").encode("utf-16-le")
        size = ctypes.sizeof(DROPFILES) + len(text)
        k32 = ctypes.windll.kernel32
        k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        k32.GlobalAlloc.restype = wintypes.HGLOBAL
        k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        hdrop = k32.GlobalAlloc(0x42, size)
        ptr = k32.GlobalLock(hdrop)
        df = DROPFILES()
        df.pFiles = ctypes.sizeof(DROPFILES)
        df.fWide = True
        ctypes.memmove(ptr, ctypes.byref(df), ctypes.sizeof(DROPFILES))
        ctypes.memmove(ptr + ctypes.sizeof(DROPFILES), text, len(text))
        k32.GlobalUnlock(hdrop)
        ctypes.windll.user32.SendMessageW(
            drop_target._state["hwnd"], drop_target.WM_DROPFILES,
            wintypes.WPARAM(hdrop), 0)
        root.update()
        time.sleep(0.1)
        root.update()
        assert got and os.path.normcase(got[0]) == os.path.normcase(str(drop_file)), got
        print("Windows 原生拖入 OK")

    # 主题切换：深色 / 浅色各重建一次，数据与视图保持不变
    import theme
    for m in ("dark", "light"):
        theme.apply(m)
        app._restyle()
        root.update()
        assert theme.resolved() == m, "主题未按预期生效：%s" % m
        assert app.current in app.views, "切主题后当前视图丢失"
        for k in ("dashboard", "docs", "files", "collect", "roster", "tasks", "service", "submit", "logs"):
            app.switch(k)
            root.update()
        assert app.views["docs"].tree.get_children(), "切主题后台账为空"
        assert app.views["dashboard"].card_values["total"].cget("text") != "0", "切主题后看板未刷新"
    theme.apply("light")
    print("主题切换 OK")

    # A2 空态组件：标题 + 说明 + 一个真实主动作；看板内容可滚动到底部
    probe = EmptyState(root, wraplength=320)
    fired = {"n": 0}
    probe.set("还没有测试数据", "这里解释为什么为空，以及下一步能做什么。",
              "去做第一步", lambda: fired.__setitem__("n", fired["n"] + 1))
    probe.show_place()
    root.update()
    assert probe._title.cget("text") == "还没有测试数据"
    assert probe._desc.cget("text").startswith("这里解释为什么为空")
    assert probe.action_text == "去做第一步" and probe._btn.winfo_ismapped()
    probe._btn.invoke()
    root.update()
    assert fired["n"] == 1, "空态主动作未真正执行"
    probe.hide()
    root.update()

    app.switch("dashboard")
    root.update()
    dash = app.views["dashboard"]
    box = dash.canvas.bbox("all")
    assert box and box[3] > dash.canvas.winfo_height(), "看板内容未形成可滚动区域"
    dash.canvas.yview_moveto(1.0)
    root.update()
    assert dash.canvas.yview()[1] >= 0.99, "看板未滚到底部"
    print("空态组件/看板滚动 OK")

    # A3 错误对话框：四段齐全 + 恢复动作，不把堆栈或路径塞进正文
    from ui_error import ErrorDialog
    hit = {"n": 0}
    dlg = ErrorDialog(
        root, "归档文件没有复制完成",
        "台账已标记为已归档，但复制到归档文件夹时失败（权限被拒绝）。",
        "台账记录还在；归档目录里可能缺少文件，原文件没有被移动。",
        "先打开归档目录检查磁盘空间与写入权限，再重新归档。",
        "原文件仍在原位置，失败文件不会自动删除。",
        actions=[("重试归档", lambda: hit.__setitem__("n", hit["n"] + 1))])
    root.update()

    def texts(widget):
        found = []
        for child in widget.winfo_children():
            if isinstance(child, tk.Label):
                found.append(child.cget("text"))
            found.extend(texts(child))
        return found

    body = texts(dlg.top)
    for key in ("发生了什么", "影响范围", "下一步", "兜底"):
        assert key in body, "错误弹窗缺少 %s" % key
    assert any("权限被拒绝" in t for t in body)
    assert not any("Traceback" in t or "C:\\Users" in t for t in body)
    buttons = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Button):
                buttons.append(child)
            walk(child)

    walk(dlg.top)
    assert any(b.cget("text") == "重试归档" for b in buttons), "错误恢复动作缺失"
    for b in buttons:
        if b.cget("text") == "重试归档":
            b.invoke()
    assert hit["n"] == 1, "错误恢复动作未真正执行"
    dlg.close()
    root.update()
    print("错误四段对话框 OK")

    # A5 更多功能：主流程收口、低频入口合一行、折叠三点、权限显隐
    if app.collapsed:
        app.toggle_sidebar()
        root.update()
    app.role_var.set("handler"); app._toggle_role(); root.update()
    assert "collect" not in app.nav_items and "logs" not in app.nav_items, \
        "文件夹收集/操作日志不应再平铺在侧栏"
    assert "docs" in app.nav_items and "roster" in app.nav_items
    assert app.more_btn is not None and app.more_btn.winfo_ismapped(), \
        (app.collapsed, app.more_btn, app.more_count, app.current, app.role,
         [it[0] for it in app.more_items()], root.winfo_ismapped(), root.geometry())
    assert app.more_count.cget("text") == "3", app.more_count.cget("text")
    nav_texts = texts(app.nav_box)
    for label in ("办理材料", "跟进核对", "更多"):
        assert label in nav_texts, "侧栏缺少分组：%s" % label

    app.switch("logs"); root.update()
    assert app.current == "logs"
    assert app.more_btn.cget("fg") == theme.C["primary"], "当前页在三项内时更多入口未高亮"
    assert app.eyebrow_label.cget("text") == "工作台 · 更多"

    md = app._open_more(); root.update()
    assert md.top.winfo_exists() and md.top.title() == "更多功能"
    assert set(md.item_buttons) == {"collect", "logs", "ai"}, md.item_buttons.keys()
    md.item_buttons["ai"].invoke(); root.update()
    adv = getattr(app, "ai_dialog", None)
    assert adv is not None and adv.top.winfo_exists(), "AI 建议入口没有打开面板"
    assert adv.top.title() == "AI 建议 · 材料分类"
    adv.close(); root.update()

    md = app._open_more(); root.update()
    md.top.event_generate("<Button-1>", x=-30, y=-10)
    root.update()
    assert not md.top.winfo_exists(), "点击弹窗外空白应关闭"

    md = app._open_more(); root.update()
    md.item_buttons["collect"].invoke(); root.update()
    assert app.current == "collect", "更多功能里的入口未真正跳转"
    assert not md.top.winfo_exists()

    app.role_var.set("manager"); app._toggle_role(); root.update()
    assert [it[0] for it in app.more_items()] == ["collect", "logs", "ai"], \
        "汇总者应看到收集、日志与 AI 建议"
    assert app.more_count.cget("text") == "3"
    app.role_var.set("applicant"); app._toggle_role(); root.update()
    assert app.more_items() == [], "申请人不应看到文件夹收集与操作日志"
    assert app.more_btn is None, "申请人没有更多项时不应保留空入口"

    app.role_var.set("handler"); app._toggle_role(); root.update()
    app.switch("collect"); root.update()
    cv = app.views["collect"]
    folder = tempfile.mkdtemp(prefix="cc-collect-ai-")
    for name in ("250219_团日活动记录.docx", "体测成绩统计表.xlsx",
                 "国家奖学金申请表.pdf"):
        Path(folder, name).write_text("x", encoding="utf-8")
    cv.folder = folder
    cv.scan(); root.update()
    assert len(cv.items) == 3 and all(x["checked"] for x in cv.items)
    cv.suggest_categories(); root.update()
    adv = getattr(app, "ai_dialog", None)
    assert adv is not None and adv.top.winfo_exists()
    import time
    deadline = time.time() + 3
    while time.time() < deadline and not adv.results:
        root.update()
        time.sleep(0.05)
    assert adv.results, "本地规则应在 3 秒内给出建议"
    assert str(adv.btn_copy.cget("state")) == "normal"
    assert str(adv.btn_apply.cget("state")) == "normal"
    adv.apply(); root.update()
    cats = {x["name"]: x["cat"] for x in cv.items}
    assert cats["250219_团日活动记录.docx"] == "团务材料", cats
    assert cats["体测成绩统计表.xlsx"] == "学分材料", cats
    assert cats["国家奖学金申请表.pdf"] == "奖助材料", cats
    for it in cv.items:
        assert cv.tree.set(it["iid"], "cat") == it["cat"], "建议未回填到表格"

    app.toggle_sidebar(); root.update()
    assert app.collapsed
    assert app.more_btn.cget("text") == "···", app.more_btn.cget("text")
    assert app.more_count is None, "折叠侧栏后数量角标应隐藏"
    assert app.more_btn.winfo_ismapped(), "折叠后三点入口应常驻"
    assert app.more_btn.cget("fg") == theme.C["primary"], "折叠态当前页未联动高亮"
    print("更多功能/折叠导航 OK")

    # 悬浮助手：顶栏入口 → 展开 → 本地问答 → 切页面 → 收起 → 关闭
    app.assistant_btn.invoke()
    root.update()
    pet = app.assistant_pet
    assert pet is not None and pet.alive(), "顶栏助手入口没有拉起悬浮窗"
    assert pet.expanded and pet.win.winfo_width() >= 300, (
        pet.expanded, pet.win.winfo_width())
    pet._ask("谁还没交材料")
    deadline = time.time() + 4
    while time.time() < deadline and pet.busy:
        root.update()
        time.sleep(0.05)
    assert not pet.busy, "助手问答没有在 4 秒内返回"
    assert pet.last_reply and ("人" in pet.last_reply or "交" in pet.last_reply), pet.last_reply
    assert "你：" in pet.text.get("1.0", "end"), "对话没有落到面板里"
    before = app.current
    pet._ask("打开服务留痕")
    deadline = time.time() + 4
    while time.time() < deadline and pet.busy:
        root.update()
        time.sleep(0.05)
    assert app.current == "service", (before, app.current)
    pet.collapse()
    root.update()
    assert not pet.expanded and pet.win.winfo_height() <= 90, (
        pet.expanded, pet.win.winfo_height())
    texts = [pet.canvas.itemcget(i, "text") for i in pet.canvas.find_all()
             if pet.canvas.type(i) == "text"]
    assert any(pet.last_reply[:6] in t for t in texts), (pet.last_reply[:6], texts)
    pet.destroy()
    root.update()
    assert getattr(app, "assistant_pet", None) is pet and not pet.alive()
    print("悬浮助手问答/切页/收起 OK")

    root.destroy()
    print("GUI SMOKE OK")


if __name__ == "__main__":
    main()

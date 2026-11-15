# -*- coding: utf-8 -*-
"""GUI 冒烟回归（需要图形界面环境；临时库，不读写本机真实数据）。

运行：
    py -3.14 tests/gui_smoke.py
覆盖：视图切换、角色切换、提交入库、留痕角色跟随、校验拦截、归档驳回、禁用联动、脏记录渲染。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tkinter as tk  # noqa: E402
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

    # 同学视角提交：留痕角色跟随当前视角
    app.role_var.set("同学"); app._toggle_role(); root.update()
    sv.var_title.set("同学视角提交"); sv.var_name.set("王五"); sv.var_sid.set("250203")
    sv.var_cat.set("学分材料"); sv.submit(); root.update()
    last = repo.list_logs()[0]
    assert last["role"] == "同学" and last["who"] == app.operator_name
    print("同学视角留痕 OK")

    # 管理员视角提交：留痕角色切换为管理员
    app.role_var.set("管理员"); app._toggle_role(); root.update()
    sv.var_title.set("复测材料"); sv.var_name.set("李四"); sv.var_sid.set("250202")
    sv.var_cat.set("奖助材料"); sv.submit(); root.update()
    last = repo.list_logs()[0]
    assert last["role"] == "管理员" and last["who"] == app.operator_name
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

    root.destroy()
    print("GUI SMOKE OK")


if __name__ == "__main__":
    main()

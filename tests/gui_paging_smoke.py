# -*- coding: utf-8 -*-
"""台账分页冒烟：300 条首屏、加载更多、筛选回到首屏。

运行：py -3.14 tests/gui_paging_smoke.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="cc-paging-")

import tkinter as tk  # noqa: E402
from database import LocalRepository  # noqa: E402
from ui_main import MainWindow  # noqa: E402


def main():
    repo = LocalRepository(Path(tempfile.mkdtemp()) / "paging.db")
    docs = [{"name": "分页材料%03d" % i, "cat": "团务材料",
             "who": "分页同学", "sid": "2601%02d" % (i % 100),
             "status": "已归档" if i % 5 == 0 else "待审核"} for i in range(700)]
    repo.restore(docs, [])
    base = len(repo.list_docs())
    assert base == 700, base
    root = tk.Tk()
    root.withdraw()
    app = MainWindow(root, repo)
    app.switch("docs")
    root.update_idletasks()
    dv = app.views["docs"]
    assert dv.winfo_manager() == "pack", dv.winfo_manager()

    assert dv._total == 700, dv._total
    assert len(dv.tree.get_children()) == 300, len(dv.tree.get_children())
    assert dv.btn_more_rows.winfo_manager(), "加载更多入口未出现"
    print("首屏 300 / 共 700 OK")

    dv.load_more()
    root.update_idletasks()
    assert len(dv.tree.get_children()) == 600
    dv.load_more()
    root.update_idletasks()
    assert len(dv.tree.get_children()) == 700
    assert not dv.btn_more_rows.winfo_manager(), "全部加载后入口未收起"
    print("加载更多 600 → 700 OK")

    dv.q.set("分页材料699")
    root.update_idletasks()
    assert len(dv.tree.get_children()) == 1, len(dv.tree.get_children())
    assert dv._shown == dv.PAGE_SIZE
    print("筛选回到首屏 OK")

    dv.q.set("")
    dv.status.set("已归档")
    dv._filter_refresh()
    root.update_idletasks()
    archived = repo.count_docs(status="已归档")
    assert dv._total == archived, dv._total
    assert len(dv.tree.get_children()) == min(300, archived)
    print("状态筛选与总数一致 OK")

    root.destroy()
    print("GUI PAGING SMOKE OK")


if __name__ == "__main__":
    main()

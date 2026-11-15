# -*- coding: utf-8 -*-
"""班级操作台 · 本地桌面版 入口。

运行：python main.py
打包 exe：在 Windows 上执行 build_exe.bat（详见说明.txt）。
"""

import sys
import traceback
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from database import build_repository, app_data_dir
from ui_main import MainWindow
from theme import FONT, C
from version import VERSION, VERSION_LABEL


def _install_error_logger():
    """未捕获异常写入本机 crash.log，便于出问题后回查；不影响默认报错。"""
    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        try:
            log = app_data_dir() / "crash.log"
            with open(log, "a", encoding="utf-8") as f:
                f.write("\n===== %s =====\n" %
                        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                traceback.print_exception(exc_type, exc, tb, file=f)
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = hook


def setup_style(root):
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", font=(FONT, 11), foreground=C["text"])
    style.configure("TLabel", font=(FONT, 11))
    style.configure("Muted.TLabel", foreground=C["muted"], font=(FONT, 10))
    style.configure("Title.TLabel", font=(FONT, 17, "bold"), foreground=C["text"])
    style.configure("Sub.TLabel", font=(FONT, 10), foreground=C["muted"])

    # 按钮：默认 / 主要 / 危险
    style.configure("TButton", padding=(14, 8), relief="flat", background="#F1F4F8",
                    foreground=C["text"], bordercolor=C["line"], borderwidth=1,
                    font=(FONT, 11))
    style.map("TButton",
              background=[("active", "#E9EEF4"), ("disabled", "#F1F5F9")],
              foreground=[("disabled", "#9AA5B1")],
              bordercolor=[("disabled", "#EDF0F4")])
    style.configure("Accent.TButton", background=C["primary"], foreground="#FFFFFF",
                    padding=(14, 8), relief="flat", borderwidth=0, font=(FONT, 11, "bold"))
    style.map("Accent.TButton",
              background=[("active", C["primary_hover"]), ("disabled", "#B9C2F5")],
              foreground=[("disabled", "#FFFFFF")])
    style.configure("Danger.TButton", background="#FFFFFF", foreground=C["red"],
                    bordercolor="#FBD5D5", padding=(14, 8), relief="flat")
    style.map("Danger.TButton", background=[("active", "#FEF2F2")])

    # 输入控件：聚焦时边框变强调色
    style.configure("TEntry", padding=(9, 7), bordercolor=C["line"], borderwidth=1)
    style.map("TEntry", bordercolor=[("focus", C["primary"])])
    style.configure("TCombobox", padding=(7, 5), bordercolor=C["line"], borderwidth=1)
    style.map("TCombobox", bordercolor=[("focus", C["primary"])])
    style.configure("TRadiobutton", font=(FONT, 11))

    # 表格
    style.configure("Treeview", rowheight=30, background=C["card"], fieldbackground=C["card"],
                    bordercolor=C["line"], borderwidth=1, font=(FONT, 11))
    style.configure("Treeview.Heading", font=(FONT, 10, "bold"), foreground=C["muted"],
                    background="#F7F9FC", padding=(10, 7))
    style.map("Treeview",
              background=[("selected", C["select"])],
              foreground=[("selected", C["text"])])


def center_window(root, w, h):
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 3)
    root.geometry("%dx%d+%d+%d" % (w, h, x, y))


def main():
    _install_error_logger()
    root = tk.Tk()
    root.title("班级操作台 · v%s %s" % (VERSION, VERSION_LABEL))
    try:
        setup_style(root)
        repo = build_repository()
        MainWindow(root, repo)
        center_window(root, 1080, 680)
        root.minsize(960, 600)
        root.mainloop()
    except Exception as e:
        messagebox.showerror("启动失败", "程序初始化失败：%s\n请确认本机数据目录可正常读写。" % e)


if __name__ == "__main__":
    main()

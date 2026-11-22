# -*- coding: utf-8 -*-
"""班级操作台 · 本地桌面版 入口。

运行：python main.py
打包 exe：在 Windows 上执行 build_exe.bat（详见说明.txt）。
"""

import sys
import ctypes
import traceback
import datetime
import tkinter as tk
from tkinter import messagebox

from database import build_repository, app_data_dir
from ui_main import MainWindow
import theme
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


def enable_dpi_awareness():
    """声明 DPI 感知，避免 125%/150% 缩放下 Tk 按 100% 排布导致右侧被裁。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def center_window(root, w, h):
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 3)
    root.geometry("%dx%d+%d+%d" % (w, h, x, y))


def main():
    _install_error_logger()
    enable_dpi_awareness()
    theme.init_from_settings()
    root = tk.Tk()
    root.title("班级操作台 · v%s %s" % (VERSION, VERSION_LABEL))
    try:
        root.configure(bg=theme.C["bg"])
        theme.apply_tk_defaults(root)
        theme.setup_ttk(root)
        repo = build_repository()
        MainWindow(root, repo)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        center_window(root, min(1220, max(960, sw - 80)),
                      min(860, max(620, sh - 70)))
        root.minsize(960, 640)
        root.mainloop()
    except Exception as e:
        messagebox.showerror("启动失败", "程序初始化失败：%s\n请确认本机数据目录可正常读写。" % e)


if __name__ == "__main__":
    main()

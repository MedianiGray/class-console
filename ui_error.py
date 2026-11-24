# -*- coding: utf-8 -*-
"""统一的错误对话框。

四段固定口径：发生了什么 / 影响范围 / 下一步 / 兜底。
只承接需要用户做决定的错误；瞬时错误仍走状态栏 toast。
"""

import tkinter as tk
from tkinter import ttk

from theme import FONT, C


def _wrap(parent, text, fg, size=9, weight="normal", pad=(0, 0), wrap=480):
    label = tk.Label(parent, text=text, bg=C["card"], fg=fg,
                     font=(FONT, size, weight), anchor="w", justify="left",
                     wraplength=wrap)
    label.pack(fill="x", pady=pad)
    return label


class ErrorDialog:
    """模态错误说明；按钮必须由调用方传入真实可执行命令。"""

    def __init__(self, window, title, what, impact, next_step, fallback,
                 actions=None):
        self.window = window
        self.top = tk.Toplevel(window.winfo_toplevel())
        self.top.title(title)
        self.top.transient(window.winfo_toplevel())
        self.top.resizable(False, False)
        self._center(560, 430)
        self.top.configure(bg=C["bg"])
        try:
            self.top.grab_set()
        except tk.TclError:
            pass
        self.top.bind("<Escape>", lambda e: self.close())

        card = tk.Frame(self.top, bg=C["card"], highlightthickness=1,
                        highlightbackground=C["line"])
        card.pack(fill="both", expand=True, padx=18, pady=(18, 8))

        head = tk.Frame(card, bg=C["card"])
        head.pack(fill="x", padx=16, pady=(14, 10))
        tk.Label(head, text="!", bg=C["primary_soft"], fg=C["primary"],
                 font=(FONT, 11, "bold"), width=2, height=1).pack(side="left")
        tk.Label(head, text=title, bg=C["card"], fg=C["text"],
                 font=(FONT, 12, "bold"), anchor="w").pack(
            side="left", padx=(10, 0), fill="x", expand=True)

        body = tk.Frame(card, bg=C["card"])
        body.pack(fill="both", expand=True, padx=16)
        rows = (("发生了什么", what, C["text"]),
                ("影响范围", impact, C["text"]),
                ("下一步", next_step, C["text"]),
                ("兜底", fallback, C["sub"]))
        for key, text, fg in rows:
            row = tk.Frame(body, bg=C["card"])
            row.pack(fill="x", pady=(0, 10))
            tk.Label(row, text=key, bg=C["card"], fg=C["sub"],
                     font=(FONT, 8), width=7, anchor="nw").pack(side="left")
            _wrap(row, text, fg, size=9, wrap=430).pack(
                side="left", fill="x", expand=True)

        footer = tk.Frame(self.top, bg=C["bg"])
        footer.pack(side="bottom", fill="x", padx=20, pady=(0, 14))
        for item in (actions or []):
            label, command = item[0], item[1]
            style = item[2] if len(item) > 2 else "TButton"
            ttk.Button(footer, text=label, command=command,
                       style=style).pack(side="right", padx=(8, 0))
        if not actions:
            ttk.Button(footer, text="关闭", command=self.close).pack(side="right")

    def _center(self, w, h):
        top = self.window.winfo_toplevel()
        top.update_idletasks()
        x = top.winfo_rootx() + max(0, (top.winfo_width() - w) // 2)
        y = top.winfo_rooty() + max(0, (top.winfo_height() - h) // 3)
        self.top.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def close(self):
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        self.top.destroy()


def show_error(window, title, what, impact, next_step, fallback,
               actions=None):
    return ErrorDialog(window, title, what, impact, next_step, fallback,
                       actions=actions)

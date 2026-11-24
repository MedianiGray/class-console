# -*- coding: utf-8 -*-
"""桌面端「更多功能」：低频、辅助入口统一收在这里。

侧栏主流程只保留办理与跟进；文件夹收集、操作日志不再平铺。
不为了对齐网页硬塞 AI，当前有几项就显示几项。
"""

import tkinter as tk
from tkinter import ttk

from theme import FONT, C

MORE_DESC = {
    "collect": "扫描本地文件夹，按名单比对并批量登记",
    "logs": "查看提交、审核、归档与备份留痕",
}


class MoreDialog:
    """低频功能的统一入口；每一项都跳到真实视图。"""

    def __init__(self, window):
        self.window = window
        self.items = window.more_items()
        self.item_buttons = {}
        self.top = tk.Toplevel(window.winfo_toplevel())
        self.top.title("更多功能")
        self.top.transient(window.winfo_toplevel())
        self.top.resizable(False, False)
        self._center(520, 340)
        self.top.configure(bg=C["bg"])
        self._build()
        self.top.bind("<Escape>", lambda e: self.close())
        self.top.bind("<Button-1>", self._outside_click, add="+")
        try:
            self.top.grab_set()
        except tk.TclError:
            pass

    def _center(self, w, h):
        top = self.window.winfo_toplevel()
        top.update_idletasks()
        x = top.winfo_rootx() + max(0, (top.winfo_width() - w) // 2)
        y = top.winfo_rooty() + max(0, (top.winfo_height() - h) // 3)
        self.top.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def _build(self):
        head = tk.Frame(self.top, bg=C["bg"])
        head.pack(fill="x", padx=22, pady=(18, 2))
        tk.Label(head, text="···", bg=C["primary_soft"], fg=C["primary"],
                 font=(FONT, 12, "bold"), padx=8, pady=2).pack(side="left")
        tk.Label(head, text="更多功能", bg=C["bg"], fg=C["text"],
                 font=(FONT, 15, "bold"), anchor="w").pack(side="left", padx=(9, 0))
        tk.Label(self.top,
                 text="主流程只保留办理与跟进；低频能力收在这里，按需打开，不占侧栏。",
                 bg=C["bg"], fg=C["muted"], font=(FONT, 9), anchor="w",
                 justify="left", wraplength=460).pack(fill="x", padx=22, pady=(4, 10))

        body = tk.Frame(self.top, bg=C["card"], highlightthickness=1,
                       highlightbackground=C["line"])
        body.pack(fill="both", expand=True, padx=22, pady=(0, 10))
        if not self.items:
            tk.Label(body, text="当前视角没有可用的扩展工具。",
                     bg=C["card"], fg=C["muted"], font=(FONT, 9),
                     anchor="w").pack(fill="x", padx=16, pady=18)
        for i, (key, label, _perm, icon, _group) in enumerate(self.items):
            if i:
                tk.Frame(body, bg=C["line"], height=1).pack(fill="x", padx=16)
            self._row(body, key, label, icon)

        foot = tk.Frame(self.top, bg=C["bg"])
        foot.pack(fill="x", padx=22, pady=(0, 16))
        ttk.Button(foot, text="关闭", command=self.close).pack(side="right")

    def _row(self, parent, key, label, icon):
        active = self.window.current == key
        row = tk.Frame(parent, bg=C["card"], cursor="hand2")
        row.pack(fill="x", padx=8, pady=3)
        box = tk.Frame(row, bg=C["primary_soft"] if active else C["bg_soft"],
                       width=30, height=30)
        box.pack(side="left", padx=(8, 10), pady=8)
        box.pack_propagate(False)
        ico = tk.Label(box, text=icon, bg=C["primary_soft"] if active else C["bg_soft"],
                       fg=C["primary"] if active else C["muted"],
                       font=(FONT, 11, "bold"))
        ico.pack(expand=True)
        txt = tk.Frame(row, bg=C["card"])
        txt.pack(side="left", fill="x", expand=True, pady=7)
        title_row = tk.Frame(txt, bg=C["card"])
        title_row.pack(fill="x")
        title = tk.Label(title_row, text=label, bg=C["card"], fg=C["text"],
                         font=(FONT, 10, "bold"), anchor="w")
        title.pack(side="left")
        if active:
            tk.Label(title_row, text="当前", bg=C["primary_soft"], fg=C["primary"],
                     font=(FONT, 8, "bold"), padx=6, pady=0).pack(
                         side="left", padx=(8, 0))
        desc = tk.Label(txt, text=MORE_DESC.get(key, "按需打开"),
                        bg=C["card"], fg=C["muted"], font=(FONT, 9), anchor="w")
        desc.pack(fill="x", pady=(1, 0))
        go = ttk.Button(row, text="打开", width=6,
                        command=lambda k=key: self._pick(k))
        go.pack(side="right", padx=(6, 8))
        self.item_buttons[key] = go
        for w in (row, box, ico, txt, title_row, title, desc):
            w.bind("<Button-1>", lambda e, k=key: self._pick(k))

    def _outside_click(self, event):
        """点弹窗外的空白关闭；点条目仍按条目自身动作跳转。"""
        try:
            left = self.top.winfo_rootx()
            top = self.top.winfo_rooty()
            right = left + self.top.winfo_width()
            bottom = top + self.top.winfo_height()
            if not (left <= event.x_root < right and top <= event.y_root < bottom):
                self.close()
        except tk.TclError:
            pass

    def _pick(self, key):
        self.close()
        self.window.switch(key)

    def close(self):
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        try:
            self.top.destroy()
        except tk.TclError:
            pass


def open_more(window):
    old = getattr(window, "more_dialog", None)
    if old is not None:
        try:
            if old.top.winfo_exists():
                old.close()
        except Exception:
            pass
    window.more_dialog = MoreDialog(window)
    return window.more_dialog

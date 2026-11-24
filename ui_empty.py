# -*- coding: utf-8 -*-
"""统一的空态组件。

标题说清「这一屏还没有什么」，说明解释为什么空、空代表什么，
主动作只留一个，必须由调用方传入真实可执行的命令。
"""

import tkinter as tk
from tkinter import ttk

from theme import FONT, C


class EmptyState(tk.Frame):
    """可复用的空态卡片：标题 + 说明 + 一个实心主动作。"""

    def __init__(self, parent, wraplength=440):
        super().__init__(parent, bg=C["card"])
        self._title = tk.Label(
            self, text="", bg=C["card"], fg=C["text"],
            font=(FONT, 12, "bold"), anchor="center")
        self._title.pack(fill="x")
        self._desc = tk.Label(
            self, text="", bg=C["card"], fg=C["sub"], font=(FONT, 9),
            wraplength=wraplength, justify="center", anchor="center")
        self._desc.pack(fill="x", pady=(5, 0))
        self._action = None
        self._btn = ttk.Button(self, text="", style="Accent.TButton")

    def set(self, title, desc, action=None, command=None):
        self._title.config(text=title)
        self._desc.config(text=desc)
        self._btn.pack_forget()
        self._action = action if (action and command) else None
        if self._action:
            self._btn.config(text=self._action, command=command)
            self._btn.pack(pady=(11, 0))

    def show_place(self, relx=0.5, rely=0.4):
        self.place(relx=relx, rely=rely, anchor="center")

    def hide(self):
        self.place_forget()

    def show_pack(self, **kwargs):
        self.pack(**kwargs)

    def hide_pack(self):
        self.pack_forget()

    @property
    def action_text(self):
        return self._action or ""

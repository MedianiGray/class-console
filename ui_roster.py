# -*- coding: utf-8 -*-
"""名单核对视图：学号—姓名名单、应交/已交/未交核对、添加与移除。"""

import tkinter as tk
from tkinter import ttk, messagebox

from theme import FONT, C


class RosterView(ttk.Frame):
    COLS = ("sid", "who")
    HEADS = {"sid": "学号", "who": "姓名"}
    WIDTHS = {"sid": 140, "who": 160}

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(16, 10))
        ttk.Label(top, text="班级名单与缺交核对", style="Title.TLabel").pack(side="left")
        self.summary = ttk.Label(top, text="", style="Muted.TLabel")
        self.summary.pack(side="right")

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=18)
        self.tree = ttk.Treeview(wrap, columns=self.COLS, show="headings",
                                 selectmode="browse")
        for c in self.COLS:
            self.tree.heading(c, text=self.HEADS[c])
            self.tree.column(c, width=self.WIDTHS[c], anchor="w", stretch=True)
        self.tree.tag_configure("zebra", background=C["zebra"])
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

        self.empty = ttk.Label(wrap, text="名单为空，可在下方添加成员", style="Muted.TLabel")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=12)
        self.btn_add = ttk.Button(bar, text="添加成员", command=self.add_dialog)
        self.btn_remove = ttk.Button(bar, text="移除选中", command=self.remove_selected)
        self.btn_clear = ttk.Button(bar, text="清空名单", command=self.clear_all)

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(self.tree.item(sel[0])["tags"][0])
        except (ValueError, IndexError, KeyError):
            return None

    def refresh(self):
        rows = self.repo.list_roster()
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(rows):
            tag = "zebra" if i % 2 else ""
            self.tree.insert("", "end", tags=(r["id"], tag),
                             values=(r.get("sid", ""), r.get("who", "")))
        chk = self.repo.roster_check()
        self.summary.config(
            text="应交 %d · 已交 %d · 未交 %d" % (chk["total"], chk["done"], len(chk["absent"])))
        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.4, anchor="center")

        # 名单维护仅管理员可见
        is_admin = self.window.role == "admin"
        for b in (self.btn_add, self.btn_remove, self.btn_clear):
            b.pack_forget()
        if is_admin:
            self.btn_add.pack(side="left")
            self.btn_remove.pack(side="left", padx=8)
            self.btn_clear.pack(side="left")

    def add_dialog(self):
        if self.window.role != "admin":
            self.window.toast("当前视角无权执行该操作")
            return
        dlg = tk.Toplevel(self)
        dlg.title("添加成员")
        dlg.transient(self)
        dlg.resizable(False, False)
        sid_var, who_var = tk.StringVar(), tk.StringVar()
        err = ttk.Label(dlg, text="", foreground=C["red"], font=(FONT, 10))

        ttk.Label(dlg, text="学号 *").grid(row=0, column=0, sticky="w", padx=16, pady=10)
        ttk.Entry(dlg, textvariable=sid_var, width=20).grid(row=0, column=1, padx=16, pady=10)
        ttk.Label(dlg, text="姓名 *").grid(row=1, column=0, sticky="w", padx=16, pady=10)
        ttk.Entry(dlg, textvariable=who_var, width=20).grid(row=1, column=1, padx=16, pady=10)
        err.grid(row=2, column=0, columnspan=2, sticky="w", padx=16)

        def submit():
            try:
                self.repo.add_roster(sid_var.get(), who_var.get())
            except Exception as e:
                err.config(text=str(e))
                return
            dlg.destroy()
            self.window.refresh_all()
            self.window.toast("已添加成员")

        btns = ttk.Frame(dlg)
        btns.grid(row=3, column=0, columnspan=2, pady=(6, 14))
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="保存", style="Accent.TButton", command=submit).pack(side="right")
        dlg.bind("<Return>", lambda e: submit())

    def remove_selected(self):
        if self.window.role != "admin":
            self.window.toast("当前视角无权执行该操作")
            return
        rid = self._selected()
        if rid is None:
            self.window.toast("请先在列表中选择一名成员")
            return
        if not self.window.confirm("移除确认", "确定移除该成员吗？"):
            return
        self.repo.remove_roster(rid)
        self.window.refresh_all()
        self.window.toast("成员已移除")

    def clear_all(self):
        if self.window.role != "admin":
            self.window.toast("当前视角无权执行该操作")
            return
        rows = self.repo.list_roster()
        if not rows:
            self.window.toast("名单已是空的")
            return
        if not self.window.confirm("清空名单", "确定清空全部 %d 名成员吗？此操作不可撤销。" % len(rows)):
            return
        for r in rows:
            self.repo.remove_roster(r["id"])
        self.window.refresh_all()
        self.window.toast("名单已清空")

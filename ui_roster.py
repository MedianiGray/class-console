# -*- coding: utf-8 -*-
"""名单核对视图：学号—姓名名单、应交/已交/未交核对、添加与移除。"""

import tkinter as tk
from tkinter import ttk, messagebox

from theme import FONT, C


class RosterView(ttk.Frame):
    COLS = ("sid", "who", "status")
    HEADS = {"sid": "学号", "who": "姓名", "status": "材料状态"}
    WIDTHS = {"sid": 140, "who": 160, "status": 90}

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(4, 10))
        self.summary = ttk.Label(top, text="", style="Muted.TLabel")
        self.summary.pack(side="right")

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=18)
        wrap.columnconfigure(0, weight=3)
        wrap.columnconfigure(1, weight=1)
        wrap.rowconfigure(0, weight=1)

        table_box = tk.Frame(wrap, bg=C["card"], highlightthickness=1,
                             highlightbackground=C["line"])
        table_box.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.tree = ttk.Treeview(table_box, columns=self.COLS, show="headings",
                                 selectmode="browse")
        for c in self.COLS:
            self.tree.heading(c, text=self.HEADS[c], anchor="w")
            self.tree.column(c, width=self.WIDTHS[c], anchor="w", stretch=True)
        self.tree.tag_configure("zebra", background=C["zebra"])
        ysb = ttk.Scrollbar(table_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        ysb.pack(side="right", fill="y", padx=(0, 1), pady=1)

        self.empty = ttk.Label(table_box, text="名单为空，可在下方添加成员", style="Muted.TLabel")

        # 右侧核对面板：三个数字 + 未交名单，补足「谁没交」的信息
        panel = tk.Frame(wrap, bg=C["card"], highlightthickness=1,
                         highlightbackground=C["line"])
        panel.grid(row=0, column=1, sticky="nsew")
        tk.Label(panel, text="核对概况", bg=C["card"], fg=C["text"],
                 font=(FONT, 10, "bold"), anchor="w").pack(fill="x", padx=16, pady=(14, 8))
        self.stat_labels = {}
        for key, label, color in (("total", "应交", C["muted"]),
                                  ("done", "已交", C["green"]),
                                  ("absent", "未交", C["orange"])):
            row = tk.Frame(panel, bg=C["card"])
            row.pack(fill="x", padx=16, pady=2)
            tk.Frame(row, bg=color, width=4, height=4).pack(side="left", pady=(6, 0))
            tk.Label(row, text=label, bg=C["card"], fg=C["sub"],
                     font=(FONT, 9)).pack(side="left", padx=(8, 0))
            num = tk.Label(row, text="0", bg=C["card"], fg=C["text"],
                           font=(FONT, 15, "bold"))
            num.pack(side="right")
            self.stat_labels[key] = num
        tk.Frame(panel, bg=C["line"], height=1).pack(fill="x", padx=16, pady=(10, 8))
        tk.Label(panel, text="未交名单", bg=C["card"], fg=C["sub"],
                 font=(FONT, 9), anchor="w").pack(fill="x", padx=16)
        self.absent_box = tk.Frame(panel, bg=C["card"])
        self.absent_box.pack(fill="both", expand=True, padx=16, pady=(6, 14))

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=12)
        self.btn_add = ttk.Button(bar, text="添加成员", style="Accent.TButton",
                                  command=self.add_dialog)
        self.btn_remove = ttk.Button(bar, text="移除选中", style="Ghost.TButton",
                                     command=self.remove_selected)
        self.btn_clear = ttk.Button(bar, text="清空名单", style="Ghost.TButton",
                                    command=self.clear_all)

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
        docs = self.repo.list_docs()
        submitted = {d.get("sid") for d in docs
                     if d.get("sid") and d.get("status") in ("待审核", "已归档")}
        rejected = {d.get("sid") for d in docs
                    if d.get("sid") and d.get("status") == "已驳回"}
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(rows):
            tag = "zebra" if i % 2 else ""
            sid = r.get("sid")
            if sid in submitted:
                status = "已交"
            elif sid in rejected:
                status = "需补交"
            else:
                status = "未交"
            self.tree.insert("", "end", tags=(r["id"], tag),
                             values=(r.get("sid", ""), r.get("who", ""), status))
        chk = self.repo.roster_check()
        self.summary.config(text="名单共 %d 人" % chk["total"])
        for key, val in (("total", chk["total"]), ("done", chk["done"]),
                         ("absent", len(chk["absent"]))):
            if key in self.stat_labels:
                self.stat_labels[key].config(text=str(val))
        for w in self.absent_box.winfo_children():
            w.destroy()
        absent = chk["absent"]
        if not absent:
            tk.Label(self.absent_box, text="全部已交，核对完成", bg=C["card"],
                     fg=C["green"], font=(FONT, 9), anchor="w").pack(fill="x")
        else:
            for r in absent[:12]:
                row = tk.Frame(self.absent_box, bg=C["card"])
                row.pack(fill="x", pady=2)
                tk.Label(row, text=r.get("who", ""), bg=C["card"], fg=C["text"],
                         font=(FONT, 9), anchor="w").pack(side="left")
                tk.Label(row, text=r.get("sid", ""), bg=C["card"], fg=C["sub"],
                         font=(FONT, 9), anchor="e").pack(side="right")
            if len(absent) > 12:
                tk.Label(self.absent_box, text="另有 %d 人…" % (len(absent) - 12),
                         bg=C["card"], fg=C["sub"], font=(FONT, 9),
                         anchor="w").pack(fill="x")
        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.4, anchor="center")

        # 名单维护按 roster:manage 权限点显隐
        can_manage = self.window.can("roster:manage")
        for b in (self.btn_add, self.btn_remove, self.btn_clear):
            b.pack_forget()
        if can_manage:
            self.btn_add.pack(side="left")
            self.btn_remove.pack(side="left", padx=8)
            self.btn_clear.pack(side="left")

    def add_dialog(self):
        if not self.window.can("roster:manage"):
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
        if not self.window.can("roster:manage"):
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
        if not self.window.can("roster:manage"):
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

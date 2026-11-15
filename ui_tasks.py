# -*- coding: utf-8 -*-
"""任务跟踪视图：待办台账、截止临期/逾期标记、完成切换与增删改。"""

import tkinter as tk
from tkinter import ttk, messagebox

from theme import FONT, C
from database import days_until


class TasksView(ttk.Frame):
    CATS = ["团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]
    SCOPES = ["全员", "班委"]
    COLS = ("title", "cat", "deadline", "status", "note")
    HEADS = {"title": "任务标题", "cat": "类别", "deadline": "截止日期",
             "status": "状态", "note": "备注"}
    WIDTHS = {"title": 240, "cat": 110, "deadline": 120, "status": 110, "note": 220}

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(16, 10))
        ttk.Label(top, text="任务与截止跟踪", style="Title.TLabel").pack(side="left")
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
        self.tree.tag_configure("green", foreground=C["green"])
        self.tree.tag_configure("orange", foreground=C["orange"])
        self.tree.tag_configure("red", foreground=C["red"])
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

        self.empty = ttk.Label(wrap, text="暂无任务，点下方「添加任务」登记待办事项",
                               style="Muted.TLabel")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=12)
        self.btn_add = ttk.Button(bar, text="添加任务", style="Accent.TButton",
                                  command=lambda: self.edit_dialog(None))
        self.btn_edit = ttk.Button(bar, text="编辑", command=self.edit_selected)
        self.btn_toggle = ttk.Button(bar, text="完成 / 还原", command=self.toggle_selected)
        self.btn_del = ttk.Button(bar, text="删除", command=self.remove_selected)

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(self.tree.item(sel[0])["tags"][0])
        except (ValueError, IndexError, KeyError):
            return None

    def refresh(self):
        rows = self.repo.list_tasks()
        self.tree.delete(*self.tree.get_children())
        for i, t in enumerate(rows):
            left = days_until(t.get("deadline", ""))
            if t["done"]:
                status, tag = "已完成", "green"
            elif left is not None and left < 0:
                status, tag = "已逾期 %d 天" % (-left), "red"
            elif left is not None and left <= 2:
                status, tag = "临期", "orange"
            else:
                status, tag = "进行中", "zebra"
            self.tree.insert("", "end", tags=(t["id"], "zebra" if i % 2 else "", tag),
                             values=(t.get("title", ""), t.get("cat", ""),
                                     t.get("deadline", ""), status, t.get("note", "")))
        st = self.repo.task_stats()
        self.summary.config(
            text="进行中 %d · 临期 %d · 逾期 %d · 已完成 %d" %
            (st["ongoing"], st["due"], st["overdue"], st["done"]))
        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.4, anchor="center")

        # 任务增删改仅管理员；完成 / 还原各视角可用
        is_admin = self.window.role == "admin"
        for b in (self.btn_add, self.btn_edit, self.btn_del):
            b.pack_forget()
        self.btn_toggle.pack(side="left")
        if is_admin:
            self.btn_add.pack(side="left")
            self.btn_edit.pack(side="left", padx=8)
            self.btn_del.pack(side="left", padx=8)

    def edit_dialog(self, task):
        if self.window.role != "admin":
            self.window.toast("当前视角无权执行该操作")
            return
        dlg = tk.Toplevel(self)
        dlg.title("编辑任务" if task else "添加任务")
        dlg.transient(self)
        dlg.resizable(False, False)

        v_title = tk.StringVar(value=task["title"] if task else "")
        v_cat = tk.StringVar(value=task.get("cat", "") if task else "")
        v_deadline = tk.StringVar(value=task.get("deadline", "") if task else "")
        v_scope = tk.StringVar(value=task.get("scope", "全员") if task else "全员")
        note = tk.Text(dlg, height=3, font=(FONT, 11))
        if task:
            note.insert("1.0", task.get("note", ""))
        err = ttk.Label(dlg, text="", foreground=C["red"], font=(FONT, 10))

        ttk.Label(dlg, text="任务标题 *").grid(row=0, column=0, sticky="w", padx=16, pady=10)
        ttk.Entry(dlg, textvariable=v_title, width=24).grid(row=0, column=1, padx=16, pady=10)
        ttk.Label(dlg, text="关联类别").grid(row=1, column=0, sticky="w", padx=16, pady=10)
        ttk.Combobox(dlg, textvariable=v_cat, values=self.CATS, state="readonly",
                     width=22).grid(row=1, column=1, padx=16, pady=10)
        ttk.Label(dlg, text="截止日期 *").grid(row=2, column=0, sticky="w", padx=16, pady=10)
        ttk.Entry(dlg, textvariable=v_deadline, width=24).grid(row=2, column=1, padx=16, pady=10)
        ttk.Label(dlg, text="应交范围").grid(row=3, column=0, sticky="w", padx=16, pady=10)
        ttk.Combobox(dlg, textvariable=v_scope, values=self.SCOPES, state="readonly",
                     width=22).grid(row=3, column=1, padx=16, pady=10)
        ttk.Label(dlg, text="备注").grid(row=4, column=0, sticky="nw", padx=16, pady=10)
        note.grid(row=4, column=1, padx=16, pady=10)
        err.grid(row=5, column=0, columnspan=2, sticky="w", padx=16)

        def submit():
            data = {"title": v_title.get(), "cat": v_cat.get(),
                    "deadline": v_deadline.get(), "scope": v_scope.get(),
                    "note": note.get("1.0", "end").strip()}
            try:
                if task:
                    self.repo.update_task(task["id"], data)
                else:
                    self.repo.add_task(data)
            except Exception as e:
                err.config(text=str(e))
                return
            dlg.destroy()
            self.window.refresh_all()
            self.window.toast("任务已保存")

        btns = ttk.Frame(dlg)
        btns.grid(row=6, column=0, columnspan=2, pady=(6, 14))
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="保存", style="Accent.TButton", command=submit).pack(side="right")

    def edit_selected(self):
        if self.window.role != "admin":
            self.window.toast("当前视角无权执行该操作")
            return
        tid = self._selected()
        if tid is None:
            self.window.toast("请先选择一条任务")
            return
        task = self.repo.find_task(tid)
        if task:
            self.edit_dialog(task)

    def toggle_selected(self):
        tid = self._selected()
        if tid is None:
            self.window.toast("请先选择一条任务")
            return
        self.repo.toggle_task(tid)
        self.window.refresh_all()

    def remove_selected(self):
        if self.window.role != "admin":
            self.window.toast("当前视角无权执行该操作")
            return
        tid = self._selected()
        if tid is None:
            self.window.toast("请先选择一条任务")
            return
        task = self.repo.find_task(tid)
        if not self.window.confirm("删除任务", "确定删除任务「%s」吗？" % (task["title"] if task else "")):
            return
        self.repo.remove_task(tid)
        self.window.refresh_all()
        self.window.toast("任务已删除")

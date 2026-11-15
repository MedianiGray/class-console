# -*- coding: utf-8 -*-
"""操作日志视图：留痕列表 + 本地备份导出 / 导入恢复。"""

import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from theme import FONT, C


class LogsView(ttk.Frame):
    COLS = ("time", "who", "role", "act", "obj", "src")
    HEADS = {"time": "时间", "who": "操作人", "role": "角色", "act": "动作",
             "obj": "对象", "src": "来源"}
    WIDTHS = {"time": 130, "who": 100, "role": 90, "act": 80, "obj": 300, "src": 80}
    ACT_TAG = {"提交": "green", "归档": "green", "驳回": "red", "查看": "muted"}

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(16, 10))
        ttk.Label(top, text="操作日志", style="Title.TLabel").pack(side="left")
        self.count = ttk.Label(top, text="", style="Muted.TLabel")
        self.count.pack(side="right")

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=18)
        self.tree = ttk.Treeview(wrap, columns=self.COLS, show="headings",
                                 selectmode="browse")
        for c in self.COLS:
            self.tree.heading(c, text=self.HEADS[c])
            self.tree.column(c, width=self.WIDTHS[c], anchor="w", stretch=True)
        self.tree.tag_configure("zebra", background=C["zebra"])
        self.tree.tag_configure("green", foreground=C["green"])
        self.tree.tag_configure("red", foreground=C["red"])
        self.tree.tag_configure("orange", foreground=C["orange"])
        self.tree.tag_configure("muted", foreground=C["muted"])

        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")

        self.empty = ttk.Label(wrap, text="暂无操作记录，提交、归档、驳回等操作会自动记录在这里",
                                style="Muted.TLabel")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=12)
        self.btn_export = ttk.Button(bar, text="导出备份", command=self.export_backup)
        self.btn_import = ttk.Button(bar, text="导入备份", command=self.import_backup)
        self.btn_export.pack(side="left")

    def refresh(self):
        rows = self.repo.list_logs()
        self.tree.delete(*self.tree.get_children())
        for i, l in enumerate(rows):
            row_tag = "zebra" if i % 2 else ""
            act_tag = self.ACT_TAG.get(l.get("act", ""), "orange")
            self.tree.insert("", "end", tags=(row_tag, act_tag), values=(
                l.get("time", ""), l.get("who", ""), l.get("role", ""),
                l.get("act", ""), l.get("obj", ""), l.get("src", "本机")))
        self.count.config(text="共 %d 条记录" % len(rows))
        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.4, anchor="center")

        # 导入备份仅管理员可见
        self.btn_import.pack_forget()
        if self.window.role == "admin":
            self.btn_import.pack(side="left", padx=8)

    def export_backup(self):
        path = filedialog.asksaveasfilename(
            title="导出备份", defaultextension=".json",
            filetypes=[("JSON 备份", "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.repo.backup(), f, ensure_ascii=False, indent=2)
            self.window.toast("备份已导出")
        except OSError as e:
            messagebox.showerror("导出失败", str(e))

    def import_backup(self):
        if self.window.role != "admin":
            self.window.toast("当前视角无权执行该操作")
            return
        path = filedialog.askopenfilename(title="选择备份文件",
                                         filetypes=[("JSON 备份", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            messagebox.showerror("导入失败", "备份文件无法读取，或不是有效的 JSON 文件")
            return

        if not isinstance(data, dict):
            messagebox.showerror("导入失败", "备份文件结构不正确，缺少 docs / logs 数据段")
            return
        docs, logs = data.get("docs", []), data.get("logs", [])
        if not isinstance(docs, list) or not isinstance(logs, list):
            messagebox.showerror("导入失败", "备份文件结构不正确，docs / logs 应为列表")
            return

        if not self.window.confirm(
                "导入确认",
                "导入将覆盖本机当前全部材料与操作日志，且不可撤销。\n确定继续导入吗？"):
            return

        try:
            self.repo.restore(docs, logs,
                              data.get("roster", []), data.get("tasks", []))
        except Exception as e:
            messagebox.showerror("导入失败", str(e))
            return
        self.window.refresh_all()
        self.window.toast("备份数据已导入")

# -*- coding: utf-8 -*-
"""操作日志视图：留痕筛选 + 证据包 + 本地备份导出 / 恢复。"""

import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import audit
from ui_audit import open_evidence
from theme import FONT, C
from ui_empty import EmptyState


class LogsView(ttk.Frame):
    COLS = ("time", "who", "role", "act", "obj", "src")
    HEADS = {"time": "时间", "who": "操作人", "role": "角色", "act": "动作",
             "obj": "对象", "src": "来源"}
    WIDTHS = {"time": 130, "who": 100, "role": 90, "act": 80, "obj": 300, "src": 80}
    ACT_TAG = {"提交": "green", "归档": "green", "驳回": "red", "查看": "muted",
               "证据包": "orange", "完整性检查": "orange", "催交": "orange",
               "回执": "green", "免交": "muted", "延期": "muted",
               "恢复应交": "green", "交接包": "orange", "文件室登记": "orange"}
    ACTS = ["全部", "提交", "归档", "驳回", "归位", "查看", "收集入账",
            "文件室登记", "证据包", "完整性检查", "催交", "回执", "免交",
            "延期", "恢复应交", "交接包"]

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self.var_q = tk.StringVar()
        self.var_act = tk.StringVar(value="全部")
        self.var_who = tk.StringVar()
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(4, 8))
        tk.Label(top, text="筛选", bg=C["bg"], fg=C["muted"],
                 font=(FONT, 9)).pack(side="left", padx=(0, 6))
        ent_q = ttk.Entry(top, textvariable=self.var_q, width=24)
        ent_q.pack(side="left")
        ent_q.bind("<KeyRelease>", lambda e: self.refresh())
        cb_act = ttk.Combobox(top, textvariable=self.var_act, values=self.ACTS,
                              state="readonly", width=10)
        cb_act.pack(side="left", padx=8)
        cb_act.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        tk.Label(top, text="操作人", bg=C["bg"], fg=C["muted"],
                 font=(FONT, 8)).pack(side="left", padx=(0, 6))
        ent_who = ttk.Entry(top, textvariable=self.var_who, width=10)
        ent_who.pack(side="left")
        ent_who.bind("<KeyRelease>", lambda e: self.refresh())
        ttk.Button(top, text="清空", style="Ghost.TButton",
                   command=self._clear_filters).pack(side="left", padx=8)
        self.count = ttk.Label(top, text="", style="Muted.TLabel")
        self.count.pack(side="right")

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=18)
        self.tree = ttk.Treeview(wrap, columns=self.COLS, show="headings",
                                 selectmode="browse")
        for c in self.COLS:
            self.tree.heading(c, text=self.HEADS[c], anchor="w")
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

        self.empty = EmptyState(wrap, wraplength=380)

        bar = ttk.Frame(self)
        bar.pack(side="bottom", fill="x", padx=18, pady=(6, 12), before=wrap)
        self.btn_evidence = ttk.Button(bar, text="导出证据包", style="Accent.TButton",
                                       command=self.export_evidence)
        self.btn_export = ttk.Button(bar, text="导出备份", style="Ghost.TButton",
                                     command=self.export_backup)
        self.btn_import = ttk.Button(bar, text="导入备份", style="Ghost.TButton",
                                     command=self.import_backup)
        self.btn_export.pack(side="left")
        self._binding = False

    def _clear_filters(self):
        self.var_q.set("")
        self.var_act.set("全部")
        self.var_who.set("")
        self.refresh()

    def refresh(self):
        rows = self.repo.list_logs(self.var_q.get(), self.var_act.get(),
                                   self.var_who.get())
        total = len(self.repo.list_logs())
        self.tree.delete(*self.tree.get_children())
        for i, l in enumerate(rows):
            row_tag = "zebra" if i % 2 else ""
            act_tag = self.ACT_TAG.get(l.get("act", ""), "orange")
            self.tree.insert("", "end", tags=(row_tag, act_tag), values=(
                l.get("time", ""), l.get("who", ""), l.get("role", ""),
                l.get("act", ""), l.get("obj", ""), l.get("src", "本机")))
        if len(rows) == total:
            self.count.config(text="共 %d 条记录" % total)
        else:
            self.count.config(text="匹配 %d / 共 %d 条" % (len(rows), total))
        if rows:
            self.empty.hide()
        elif total == 0:
            self.empty.set("还没有操作记录",
                           "提交、审核、归档、驳回都会自动写在这里，作为材料流转的依据。",
                           "查看材料台账" if not self.window.can("docs:create") else "提交第一份材料",
                           (lambda: self.window.switch("docs")) if not self.window.can("docs:create")
                           else (lambda: self.window.switch("submit")))
            self.empty.show_place()
        else:
            self.empty.set("没有匹配的记录",
                           "现有记录被关键词或动作筛选挡住了，清空筛选即可看到全部。",
                           "清空筛选", self._clear_filters)
            self.empty.show_place()

        # 证据包 / 恢复入口按权限点显隐
        for b in (self.btn_evidence, self.btn_import):
            b.pack_forget()
        if self.window.can("docs:export"):
            self.btn_evidence.pack(side="left", before=self.btn_export)
        if self.window.can("backup:restore"):
            self.btn_import.pack(side="left", padx=8)

    def export_evidence(self):
        if not self.window.can("docs:export"):
            self.window.toast("当前视角无权导出证据包")
            return
        open_evidence(self, self.repo, self.window, on_done=self.refresh)

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
        if not self.window.can("backup:restore"):
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

        preview = audit.backup_preview(data, self.repo)
        if not preview["ok"]:
            messagebox.showerror("导入失败", preview["text"])
            return
        if not self.window.confirm("导入确认", preview["text"]):
            return

        try:
            self.repo.restore(data.get("docs", []), data.get("logs", []),
                              data.get("roster", []), data.get("tasks", []),
                              data.get("attachments", []), data.get("templates"),
                              data.get("events", []), data.get("exemptions", []),
                              data.get("followups", []),
                              data.get("projects", []),
                              data.get("project_deliverables", []),
                              data.get("project_events", []))
        except Exception as e:
            messagebox.showerror("导入失败", str(e))
            return
        self.window.refresh_all()
        self.window.toast("备份数据已导入")

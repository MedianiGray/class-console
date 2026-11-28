# -*- coding: utf-8 -*-
"""v0.34 赛事工作台：赛程、报名、评审矩阵、提交校验与答辩包。

界面不做赛事资讯聚合，也不替用户填赛事规则；它只围绕一个赛事项目，
把报名到提交这条线走通，并把每次动作写回项目资产、执行记录与质量门。
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import competition as cp
from database import COMPETITION_ROLES
from theme import C


class CompetitionView(ttk.Frame):
    PERM = "comp:run"
    ECOLS = ("title", "date", "left", "state", "note")
    EHEADS = {"title": "赛程事项", "date": "日期", "left": "剩余",
              "state": "状态", "note": "备注"}
    EWIDTHS = {"title": 200, "date": 100, "left": 110, "state": 76, "note": 300}
    NCOLS = ("name", "sid", "role", "contact", "confirmed", "note")
    NHEADS = {"name": "姓名", "sid": "学号", "role": "角色",
              "contact": "联系方式", "confirmed": "确认", "note": "备注"}
    NWIDTHS = {"name": 110, "sid": 110, "role": 86, "contact": 140,
               "confirmed": 58, "note": 260}
    RCOLS = ("criterion", "weight", "score", "weighted", "evidence", "note")
    RHEADS = {"criterion": "评分项", "weight": "权重", "score": "自评",
              "weighted": "加权", "evidence": "证据 / 对照", "note": "备注"}
    RWIDTHS = {"criterion": 180, "weight": 64, "score": 60, "weighted": 70,
               "evidence": 280, "note": 150}
    SCOLS = ("file", "ext", "size", "format", "naming", "result", "note")
    SHEADS = {"file": "文件", "ext": "格式", "size": "大小",
              "format": "格式校验", "naming": "命名校验",
              "result": "结论", "note": "说明"}
    SWIDTHS = {"file": 250, "ext": 80, "size": 74, "format": 80,
               "naming": 80, "result": 64, "note": 300}

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self.current_pid = None
        self.project_map = {}
        self.events = []
        self.entries = []
        self.rubric = []
        self.last_submission = None
        self.last_folder = ""
        self.defense_files = []
        self.last_output = ""
        self.pm_buttons = []
        self._build()

    # ---------- 外壳 ----------
    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill="x", padx=18, pady=(4, 6))
        ttk.Label(head, text="赛事工作台", style="H2.TLabel").pack(side="left")
        self.summary = ttk.Label(head, text="", style="Muted.TLabel")
        self.summary.pack(side="right")

        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(0, 8))
        ttk.Label(top, text="赛事项目", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.project_var = tk.StringVar(value="")
        self.project_cb = ttk.Combobox(top, textvariable=self.project_var,
                                       state="readonly", width=46)
        self.project_cb.grid(row=0, column=1, sticky="w", padx=(8, 8))
        self.project_cb.bind("<<ComboboxSelected>>", lambda e: self._on_project())
        self.btn_new = ttk.Button(top, text="新建赛事项目", style="Accent.TButton",
                                  command=lambda: self.project_dialog(None))
        self.btn_new.grid(row=0, column=2, padx=2)
        self.btn_edit = ttk.Button(top, text="编辑项目", style="Ghost.TButton",
                                   command=lambda: self.project_dialog("edit"))
        self.btn_edit.grid(row=0, column=3, padx=2)
        ttk.Button(top, text="刷新", style="Ghost.TButton",
                   command=self.refresh).grid(row=0, column=4, padx=(2, 12))
        self.project_hint = ttk.Label(top, text="", style="Muted.TLabel")
        self.project_hint.grid(row=1, column=1, columnspan=4, sticky="w", padx=(8, 0), pady=(4, 0))
        top.columnconfigure(1, weight=1)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=18, pady=(0, 4))
        self.tab_cal = ttk.Frame(self.nb)
        self.tab_entry = ttk.Frame(self.nb)
        self.tab_rubric = ttk.Frame(self.nb)
        self.tab_submit = ttk.Frame(self.nb)
        self.tab_defense = ttk.Frame(self.nb)
        self.nb.add(self.tab_cal, text="赛程日历")
        self.nb.add(self.tab_entry, text="报名清单")
        self.nb.add(self.tab_rubric, text="评审矩阵")
        self.nb.add(self.tab_submit, text="提交校验")
        self.nb.add(self.tab_defense, text="答辩包")
        self._build_calendar()
        self._build_entries()
        self._build_rubric()
        self._build_submit()
        self._build_defense()
        self.after(50, self.refresh)

    def _mk_tree(self, parent, cols, heads, widths, selectmode="browse"):
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True, padx=14, pady=(6, 0))
        tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode=selectmode)
        for c in cols:
            tree.heading(c, text=heads[c], anchor="w")
            tree.column(c, width=widths[c], anchor="w", stretch=(c in ("note", "evidence", "file")))
        tree.tag_configure("zebra", background=C["zebra"])
        tree.tag_configure("green", foreground=C["green"])
        tree.tag_configure("orange", foreground=C["orange"])
        tree.tag_configure("red", foreground=C["red"])
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ysb.set)
        tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        return tree

    def _mk_bar(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(side="bottom", fill="x", padx=14, pady=(6, 10))
        return bar

    def _button(self, parent, text, cmd, style="Ghost.TButton", track=True):
        btn = ttk.Button(parent, text=text, style=style, command=cmd)
        btn.pack(side="left", padx=(0, 6))
        if track:
            self.pm_buttons.append(btn)
        return btn

    # ---------- 赛程 ----------
    def _build_calendar(self):
        self.cal_summary = ttk.Label(self.tab_cal, text="", style="Muted.TLabel")
        self.cal_summary.pack(anchor="w", padx=14, pady=(8, 0))
        self.cal_tree = self._mk_tree(self.tab_cal, self.ECOLS, self.EHEADS, self.EWIDTHS)
        self.cal_tree.bind("<Double-1>", lambda e: self.event_dialog("edit"))
        bar = self._mk_bar(self.tab_cal)
        self._button(bar, "添加赛程", lambda: self.event_dialog(None), "Accent.TButton")
        self._button(bar, "编辑赛程", lambda: self.event_dialog("edit"))
        self._button(bar, "标记完成 / 取消", self.toggle_event)
        self._button(bar, "删除赛程", self.remove_event, "Danger.TButton")

    # ---------- 报名 ----------
    def _build_entries(self):
        self.entry_summary = ttk.Label(self.tab_entry, text="", style="Muted.TLabel")
        self.entry_summary.pack(anchor="w", padx=14, pady=(8, 0))
        self.entry_tree = self._mk_tree(self.tab_entry, self.NCOLS, self.NHEADS, self.NWIDTHS)
        self.entry_tree.bind("<Double-1>", lambda e: self.entry_dialog("edit"))
        bar = self._mk_bar(self.tab_entry)
        self._button(bar, "添加报名", lambda: self.entry_dialog(None), "Accent.TButton")
        self._button(bar, "编辑报名", lambda: self.entry_dialog("edit"))
        self._button(bar, "确认 / 取消", self.toggle_entry)
        self._button(bar, "从名单导入…", self.import_roster)
        self._button(bar, "导出 CSV", self.export_entries)
        self._button(bar, "删除报名", self.remove_entry, "Danger.TButton")

    # ---------- 评审矩阵 ----------
    def _build_rubric(self):
        self.rubric_summary = ttk.Label(self.tab_rubric, text="", style="Muted.TLabel")
        self.rubric_summary.pack(anchor="w", padx=14, pady=(8, 0))
        self.rubric_tree = self._mk_tree(self.tab_rubric, self.RCOLS, self.RHEADS, self.RWIDTHS)
        self.rubric_tree.bind("<Double-1>", lambda e: self.criterion_dialog("edit"))
        bar = self._mk_bar(self.tab_rubric)
        self._button(bar, "添加评分项", lambda: self.criterion_dialog(None), "Accent.TButton")
        self._button(bar, "编辑评分项", lambda: self.criterion_dialog("edit"))
        self._button(bar, "补默认矩阵", self.seed_rubric)
        self._button(bar, "导出 CSV", self.export_rubric)
        self._button(bar, "删除评分项", self.remove_criterion, "Danger.TButton")

    # ---------- 提交校验 ----------
    def _build_submit(self):
        form = ttk.Frame(self.tab_submit)
        form.pack(fill="x", padx=14, pady=(8, 4))
        ttk.Label(form, text="提交目录", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.sub_folder_var = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.sub_folder_var, width=52).grid(
            row=0, column=1, columnspan=2, sticky="we", padx=(8, 8))
        ttk.Button(form, text="选目录…", style="Ghost.TButton",
                   command=self.pick_submit_folder).grid(row=0, column=3, padx=2)
        ttk.Button(form, text="开始校验", style="Accent.TButton",
                   command=self.run_submission).grid(row=0, column=4, padx=(2, 8))
        self.btn_open_report = ttk.Button(form, text="打开报告", style="Ghost.TButton",
                                          command=self.open_report, state="disabled")
        self.btn_open_report.grid(row=0, column=5, padx=2)

        self.ext_var = tk.StringVar(value=".pdf,.zip")
        self.max_file_var = tk.StringVar(value=str(cp.DEFAULT_MAX_FILE_MB))
        self.max_total_var = tk.StringVar(value=str(cp.DEFAULT_MAX_TOTAL_MB))
        self.max_files_var = tk.StringVar(value=str(cp.DEFAULT_MAX_FILES))
        self.regex_var = tk.StringVar(value="")
        self.keyword_var = tk.StringVar(value="")
        fields = [
            ("必需格式", self.ext_var, 18),
            ("单文件 MB", self.max_file_var, 8),
            ("总大小 MB", self.max_total_var, 8),
            ("文件数上限", self.max_files_var, 8),
            ("命名正则", self.regex_var, 24),
            ("文件名必须含", self.keyword_var, 16),
        ]
        for idx, (label, var, width) in enumerate(fields):
            r, c = 1 + idx // 3, (idx % 3) * 2
            ttk.Label(form, text=label, style="Muted.TLabel").grid(
                row=r, column=c, sticky="w", pady=(6, 0), padx=(0, 6))
            ttk.Entry(form, textvariable=var, width=width).grid(
                row=r, column=c + 1, sticky="w", pady=(6, 0), padx=(0, 16))
        ttk.Label(form, text="默认只收 PDF + ZIP；命名正则留空即不启用。",
                  style="Muted.TLabel").grid(row=3, column=0, columnspan=6,
                                             sticky="w", pady=(8, 0))
        form.columnconfigure(1, weight=1)

        self.sub_summary = ttk.Label(self.tab_submit, text="先选提交目录，再校验。",
                                     style="Muted.TLabel")
        self.sub_summary.pack(anchor="w", padx=14, pady=(4, 0))
        self.sub_tree = self._mk_tree(self.tab_submit, self.SCOLS, self.SHEADS, self.SWIDTHS)
        bar = self._mk_bar(self.tab_submit)
        self._button(bar, "把通过文件加入答辩包", self.use_submission_files)
        self._button(bar, "重新校验", self.run_submission)

    # ---------- 答辩包 ----------
    def _build_defense(self):
        form = ttk.Frame(self.tab_defense)
        form.pack(fill="x", padx=14, pady=(8, 4))
        ttk.Label(form, text="包内文件", style="Muted.TLabel").grid(row=0, column=0, sticky="nw")
        self.defense_list = tk.Listbox(form, height=6, activestyle="none")
        self.defense_list.grid(row=0, column=1, rowspan=3, sticky="we", padx=(8, 8))
        btns = ttk.Frame(form)
        btns.grid(row=0, column=2, rowspan=3, sticky="n")
        ttk.Button(btns, text="添加文件…", style="Ghost.TButton",
                   command=self.add_defense_files).pack(fill="x", pady=(0, 4))
        ttk.Button(btns, text="移除选中", style="Ghost.TButton",
                   command=self.remove_defense_files).pack(fill="x", pady=(0, 4))
        ttk.Button(btns, text="清空", style="Ghost.TButton",
                   command=self.clear_defense_files).pack(fill="x")

        ttk.Label(form, text="输出目录", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.def_out_var = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.def_out_var, width=52).grid(
            row=3, column=1, sticky="we", padx=(8, 8), pady=(8, 0))
        ttk.Button(form, text="选目录…", style="Ghost.TButton",
                   command=self.pick_defense_out).grid(row=3, column=2, sticky="we", pady=(8, 0))

        ttk.Label(form, text="包名", style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.def_name_var = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.def_name_var, width=36).grid(
            row=4, column=1, sticky="w", padx=(8, 8), pady=(8, 0))
        self.def_zip_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="同时打 ZIP", variable=self.def_zip_var).grid(
            row=4, column=2, sticky="w", pady=(8, 0))
        form.columnconfigure(1, weight=1)

        self.def_summary = ttk.Label(self.tab_defense,
                                     text="答辩包会复制文件、写清单与提纲；源文件不动。",
                                     style="Muted.TLabel")
        self.def_summary.pack(anchor="w", padx=14, pady=(6, 0))
        bar = self._mk_bar(self.tab_defense)
        self._button(bar, "生成答辩包", self.make_defense, "Accent.TButton")
        self.btn_open_output = ttk.Button(bar, text="打开输出目录", style="Ghost.TButton",
                                          command=self.open_output, state="disabled")
        self.btn_open_output.pack(side="left", padx=(0, 6))
        self._button(bar, "清空列表", self.clear_defense_files)

    # ---------- 项目 ----------
    def refresh(self, select_pid=None):
        try:
            projects = self.repo.list_projects("competition")
        except Exception:
            projects = []
        self.project_map = {}
        labels = []
        for p in projects:
            base = "%s（%s）" % (p.get("name") or "未命名", p.get("status") or "")
            label = base
            if label in self.project_map:
                label = "%s #%d" % (base, p["id"])
            self.project_map[label] = p["id"]
            labels.append(label)
        self.project_cb["values"] = labels
        ids = [p["id"] for p in projects]
        wanted = select_pid if select_pid in ids else self.current_pid
        if wanted not in ids:
            wanted = ids[0] if ids else None
        if wanted is None:
            self.project_var.set("")
            self.current_pid = None
            self._load_project(None)
            self.summary.configure(text="还没有赛事项目")
            self.project_hint.configure(text="先新建赛事项目，再排赛程、拉报名、对标准；不联网抓赛事信息。")
            return
        label = [k for k, v in self.project_map.items() if v == wanted][0]
        self.project_var.set(label)
        self.current_pid = wanted
        self._load_project(wanted)

    def _on_project(self):
        pid = self.project_map.get(self.project_var.get())
        self.current_pid = pid
        self._load_project(pid)

    def _load_project(self, pid):
        enabled = "normal" if pid else "disabled"
        for btn in self.pm_buttons:
            try:
                btn.configure(state=enabled)
            except tk.TclError:
                pass
        if pid is None:
            for tree in (self.cal_tree, self.entry_tree, self.rubric_tree, self.sub_tree):
                tree.delete(*tree.get_children())
            self.defense_list.delete(0, "end")
            self.cal_summary.configure(text="")
            self.entry_summary.configure(text="")
            self.rubric_summary.configure(text="")
            self.project_hint.configure(text="")
            self.def_summary.configure(text="答辩包会复制文件、写清单与提纲；源文件不动。")
            return
        project = self.repo.find_project(pid)
        if project is None:
            self.current_pid = None
            return
        self.events = self.repo.list_competition_events(pid)
        self.entries = self.repo.list_competition_entries(pid)
        self.rubric = self.repo.list_competition_rubric(pid)
        self._fill_events()
        self._fill_entries()
        self._fill_rubric()
        self.sub_tree.delete(*self.sub_tree.get_children())
        self.last_submission = None
        self.btn_open_report.configure(state="disabled")
        self.sub_summary.configure(text="先选提交目录，再校验。")
        self.def_name_var.set((project.get("name") or "赛事") + "_答辩包")
        self.defense_files = []
        self._refresh_defense_list()
        self.def_summary.configure(text="答辩包会复制文件、写清单与提纲；源文件不动。")
        self.btn_open_output.configure(state="disabled")
        summary = cp.project_summary(self.repo, pid)
        self.summary.configure(text=summary["text"])
        meta = "%s · %s · 截止 %s" % (
            project.get("stage"), project.get("status"),
            project.get("due_date") or "未定")
        self.project_hint.configure(text=meta + "；每次校验与答辩包都会写回项目记录。")

    def project_dialog(self, mode=None):
        editing = mode == "edit" and self.current_pid
        project = self.repo.find_project(self.current_pid) if editing else None
        top = tk.Toplevel(self)
        top.title("编辑赛事项目" if editing else "新建赛事项目")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        vars_ = {
            "name": tk.StringVar(value=(project or {}).get("name", "")),
            "owner": tk.StringVar(value=(project or {}).get("owner", "")),
            "start_date": tk.StringVar(value=(project or {}).get("start_date", "")),
            "due_date": tk.StringVar(value=(project or {}).get("due_date", "")),
        }
        rows = [("项目名称", "name", 36), ("负责人", "owner", 24),
                ("开始日期", "start_date", 16), ("截止日期", "due_date", 16)]
        for i, (label, key, width) in enumerate(rows):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(
                row=i, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=vars_[key], width=width).grid(
                row=i, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="目标", style="Muted.TLabel").grid(row=4, column=0, sticky="nw", pady=4)
        goal = tk.Text(body, width=42, height=4, wrap="word")
        goal.insert("1.0", (project or {}).get("goal", ""))
        goal.grid(row=4, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="日期写 2026-12-05；新建时会自动套 5 项交付物与默认赛程/矩阵。",
                  style="Muted.TLabel").grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def save():
            name = vars_["name"].get().strip()
            if not name:
                messagebox.showwarning("赛事项目", "项目名称不能为空。", parent=top)
                return
            data = {
                "name": name, "kind": "competition", "owner": vars_["owner"].get().strip(),
                "start_date": vars_["start_date"].get().strip(),
                "due_date": vars_["due_date"].get().strip(),
                "goal": goal.get("1.0", "end").strip(),
            }
            try:
                if editing:
                    self.repo.update_project(self.current_pid, data)
                    pid = self.current_pid
                    self._log("更新赛事项目", name)
                else:
                    data.update({"stage": "计划", "status": "进行中"})
                    pid = self.repo.add_project(data)
                    added = self.repo.apply_project_template(pid)
                    seeded = cp.seed_project(self.repo, pid)
                    self._log("新建赛事项目", "%s；模板 %d 项、赛程 %d、矩阵 %d" % (
                        name, added, seeded["events"], seeded["rubric"]))
            except Exception as e:
                messagebox.showerror("赛事项目", str(e), parent=top)
                return
            top.destroy()
            self.refresh(pid)
            if not editing:
                messagebox.showinfo("赛事项目",
                                    "已建项目并排好默认赛程与评审矩阵；\n"
                                    "先改报名截止与提交截止，再拉报名。", parent=self)

        bar = ttk.Frame(body)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton", command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton", command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    def _log(self, act, obj):
        try:
            self.repo.add_log(act, obj, getattr(self.window, "operator_name", "系统"),
                              self.window.role_label())
        except Exception:
            pass

    # ---------- 赛程 ----------
    def _fill_events(self):
        self.cal_tree.delete(*self.cal_tree.get_children())
        rows = cp.sorted_events(self.events)
        for i, row in enumerate(rows):
            tag = "zebra"
            if row.get("state") == "已过期":
                tag = "red"
            elif row.get("state") in ("今天", "临近"):
                tag = "orange"
            elif row.get("done"):
                tag = "green"
            self.cal_tree.insert("", "end", tags=(str(row["id"]), "zebra" if i % 2 else "", tag),
                                 values=(row["title"], row.get("date") or "未定",
                                         row.get("left"), row.get("state"),
                                         row.get("note")))
        st = cp.event_stats(self.events)
        self.cal_summary.configure(
            text="赛程 %d 项 · 已完成 %d · 临近/今天 %d · 已过期 %d · 未定日期 %d" % (
                st["total"], st["done"], st["soon"], st["overdue"], st["undated"]))

    def _selected_id(self, tree):
        sel = tree.selection()
        if not sel:
            return None
        try:
            return int(tree.item(sel[0])["tags"][0])
        except (ValueError, IndexError, KeyError):
            return None

    def event_dialog(self, mode=None):
        if not self.current_pid:
            return
        editing = mode == "edit"
        event = None
        if editing:
            eid = self._selected_id(self.cal_tree)
            if eid is None:
                messagebox.showinfo("赛程", "先在表里选一项。", parent=self)
                return
            event = [e for e in self.events if e["id"] == eid][0]
        top = tk.Toplevel(self)
        top.title("编辑赛程" if editing else "添加赛程")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        title_var = tk.StringVar(value=(event or {}).get("title", ""))
        date_var = tk.StringVar(value=(event or {}).get("date", ""))
        done_var = tk.BooleanVar(value=bool((event or {}).get("done")))
        for i, (label, var, width) in enumerate((("事项", title_var, 28), ("日期", date_var, 16))):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(row=i, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=var, width=width).grid(
                row=i, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Checkbutton(body, text="已完成", variable=done_var).grid(
            row=2, column=1, sticky="w", padx=(8, 0))
        ttk.Label(body, text="备注", style="Muted.TLabel").grid(row=3, column=0, sticky="nw", pady=4)
        note = tk.Text(body, width=34, height=3, wrap="word")
        note.insert("1.0", (event or {}).get("note", ""))
        note.grid(row=3, column=1, sticky="we", padx=(8, 0), pady=4)

        def save():
            if not title_var.get().strip():
                messagebox.showwarning("赛程", "事项不能为空。", parent=top)
                return
            data = {"title": title_var.get(), "date": date_var.get().strip(),
                    "note": note.get("1.0", "end").strip(), "done": done_var.get()}
            try:
                if editing:
                    self.repo.update_competition_event(event["id"], data)
                else:
                    self.repo.add_competition_event(self.current_pid, data)
            except Exception as e:
                messagebox.showerror("赛程", str(e), parent=top)
                return
            self._log("更新赛程" if editing else "添加赛程", data["title"])
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton", command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton", command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    def toggle_event(self):
        eid = self._selected_id(self.cal_tree)
        if eid is None:
            return
        event = [e for e in self.events if e["id"] == eid][0]
        self.repo.update_competition_event(eid, {"done": not event.get("done")})
        self._load_project(self.current_pid)

    def remove_event(self):
        eid = self._selected_id(self.cal_tree)
        if eid is None:
            return
        event = [e for e in self.events if e["id"] == eid][0]
        if not messagebox.askyesno("赛程", "删除「%s」？" % event["title"], parent=self):
            return
        self.repo.remove_competition_event(eid)
        self._load_project(self.current_pid)

    # ---------- 报名 ----------
    def _fill_entries(self):
        self.entry_tree.delete(*self.entry_tree.get_children())
        for i, row in enumerate(self.entries):
            tag = "green" if row.get("confirmed") else "orange"
            if row.get("role") == "队长":
                tag = "green" if row.get("confirmed") else "orange"
            self.entry_tree.insert("", "end", tags=(str(row["id"]), "zebra" if i % 2 else "", tag),
                                   values=(row.get("name"), row.get("sid"), row.get("role"),
                                           row.get("contact"),
                                           "已确认" if row.get("confirmed") else "待确认",
                                           row.get("note")))
        st = cp.entry_stats(self.entries)
        self.entry_summary.configure(
            text="报名 %d 人 · 已确认 %d · 待确认 %d · 队长 %d · 队员 %d · 指导教师 %d" % (
                st["total"], st["confirmed"], st["pending"], st["leaders"],
                st["members"], st["teachers"]))

    def entry_dialog(self, mode=None):
        if not self.current_pid:
            return
        editing = mode == "edit"
        entry = None
        if editing:
            eid = self._selected_id(self.entry_tree)
            if eid is None:
                messagebox.showinfo("报名", "先在表里选一条。", parent=self)
                return
            entry = [e for e in self.entries if e["id"] == eid][0]
        top = tk.Toplevel(self)
        top.title("编辑报名" if editing else "添加报名")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        name_var = tk.StringVar(value=(entry or {}).get("name", ""))
        sid_var = tk.StringVar(value=(entry or {}).get("sid", ""))
        role_var = tk.StringVar(value=(entry or {}).get("role", "队员"))
        contact_var = tk.StringVar(value=(entry or {}).get("contact", ""))
        confirmed_var = tk.BooleanVar(value=bool((entry or {}).get("confirmed")))
        rows = [("姓名", name_var, "entry"), ("学号", sid_var, "entry"), ("联系方式", contact_var, "entry")]
        for i, (label, var, _) in enumerate(rows):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(row=i, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=var, width=26).grid(
                row=i, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="角色", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(body, textvariable=role_var, values=list(COMPETITION_ROLES),
                     state="readonly", width=16).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=4)
        ttk.Checkbutton(body, text="已确认参赛", variable=confirmed_var).grid(
            row=4, column=1, sticky="w", padx=(8, 0))
        ttk.Label(body, text="备注", style="Muted.TLabel").grid(row=5, column=0, sticky="nw", pady=4)
        note = tk.Text(body, width=30, height=3, wrap="word")
        note.insert("1.0", (entry or {}).get("note", ""))
        note.grid(row=5, column=1, sticky="we", padx=(8, 0), pady=4)

        def save():
            if not name_var.get().strip():
                messagebox.showwarning("报名", "姓名不能为空。", parent=top)
                return
            data = {"name": name_var.get(), "sid": sid_var.get().strip(),
                    "role": role_var.get(), "contact": contact_var.get().strip(),
                    "confirmed": confirmed_var.get(), "note": note.get("1.0", "end").strip()}
            try:
                if editing:
                    self.repo.update_competition_entry(entry["id"], data)
                else:
                    self.repo.add_competition_entry(self.current_pid, data)
            except Exception as e:
                messagebox.showerror("报名", str(e), parent=top)
                return
            self._log("更新报名" if editing else "添加报名", data["name"])
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton", command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton", command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    def toggle_entry(self):
        eid = self._selected_id(self.entry_tree)
        if eid is None:
            return
        entry = [e for e in self.entries if e["id"] == eid][0]
        self.repo.update_competition_entry(eid, {"confirmed": not entry.get("confirmed")})
        self._load_project(self.current_pid)

    def remove_entry(self):
        eid = self._selected_id(self.entry_tree)
        if eid is None:
            return
        entry = [e for e in self.entries if e["id"] == eid][0]
        if not messagebox.askyesno("报名", "删除「%s」的报名？" % entry["name"], parent=self):
            return
        self.repo.remove_competition_entry(eid)
        self._load_project(self.current_pid)

    def import_roster(self):
        if not self.current_pid:
            return
        students = self.repo.list_roster()
        if not students:
            messagebox.showinfo("报名", "班级名单还是空的，先去名单页加人。", parent=self)
            return
        top = tk.Toplevel(self)
        top.title("从班级名单导入报名")
        top.transient(self.winfo_toplevel())
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="按学号去重；导入后默认已确认、角色为队员。",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        frame = ttk.Frame(body)
        frame.pack(fill="both", expand=True)
        lb = tk.Listbox(frame, selectmode="extended", width=46, height=12)
        for s in students:
            lb.insert("end", "%s    %s" % (s.get("who"), s.get("sid")))
        lb.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(10, 0))

        def select_all():
            lb.selection_set(0, "end")

        def do_import():
            idx = lb.curselection()
            if not idx:
                messagebox.showinfo("报名", "先选至少一个学生。", parent=top)
                return
            chosen = [students[i] for i in idx]
            result = cp.import_from_roster(self.repo, self.current_pid, chosen)
            self._log("导入报名", "新增 %d，跳过 %d" % (result["added"], result["skipped"]))
            top.destroy()
            self._load_project(self.current_pid)
            messagebox.showinfo("报名", "新增 %d 人，跳过 %d 人。" % (
                result["added"], result["skipped"]), parent=self)

        ttk.Button(bar, text="全选", style="Ghost.TButton", command=select_all).pack(side="left")
        ttk.Button(bar, text="导入选中", style="Accent.TButton", command=do_import).pack(side="right")
        ttk.Button(bar, text="取消", style="Ghost.TButton", command=top.destroy).pack(
            side="right", padx=(0, 8))
        top.wait_window()

    def export_entries(self):
        if not self.current_pid:
            return
        project = self.repo.find_project(self.current_pid) or {}
        default = "%s_报名清单.csv" % cp._safe_name(project.get("name") or "赛事", "赛事")
        path = filedialog.asksaveasfilename(parent=self, title="导出报名清单",
                                           defaultextension=".csv",
                                           initialfile=default.replace("_答辩包", ""),
                                           filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            res = cp.export_entries(self.repo, self.current_pid, path)
        except Exception as e:
            messagebox.showerror("报名", "导出失败：%s" % e, parent=self)
            return
        self._log("导出报名清单", "%d 人" % res["count"])

    # ---------- 评审矩阵 ----------
    def _fill_rubric(self):
        self.rubric_tree.delete(*self.rubric_tree.get_children())
        for i, row in enumerate(self.rubric):
            weighted = ""
            try:
                if row.get("score") is not None:
                    weighted = "%.1f" % (float(row["score"]) * float(row.get("weight") or 0) / 100.0)
            except (TypeError, ValueError):
                weighted = ""
            self.rubric_tree.insert("", "end", tags=(str(row["id"]), "zebra" if i % 2 else ""),
                                    values=(row.get("criterion"), "%d%%" % int(row.get("weight") or 0),
                                            "" if row.get("score") is None else row.get("score"),
                                            weighted, row.get("evidence"), row.get("note")))
        self.rubric_summary.configure(text=cp.rubric_text(self.rubric))

    def criterion_dialog(self, mode=None):
        if not self.current_pid:
            return
        editing = mode == "edit"
        row = None
        if editing:
            cid = self._selected_id(self.rubric_tree)
            if cid is None:
                messagebox.showinfo("评审矩阵", "先在表里选一项。", parent=self)
                return
            row = [r for r in self.rubric if r["id"] == cid][0]
        top = tk.Toplevel(self)
        top.title("编辑评分项" if editing else "添加评分项")
        top.transient(self.winfo_toplevel())
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        criterion_var = tk.StringVar(value=(row or {}).get("criterion", ""))
        weight_var = tk.StringVar(value=str((row or {}).get("weight", 0)))
        score_var = tk.StringVar(value="" if (row or {}).get("score") is None else str(row.get("score")))
        for i, (label, var, width) in enumerate((("评分项", criterion_var, 28),
                                                 ("权重（0–100）", weight_var, 10),
                                                 ("自评（0–100，可空）", score_var, 10))):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(row=i, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=var, width=width).grid(
                row=i, column=1, sticky="w", padx=(8, 0), pady=4)
        ttk.Label(body, text="证据 / 对照", style="Muted.TLabel").grid(row=3, column=0, sticky="nw", pady=4)
        evidence = tk.Text(body, width=34, height=3, wrap="word")
        evidence.insert("1.0", (row or {}).get("evidence", ""))
        evidence.grid(row=3, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="备注", style="Muted.TLabel").grid(row=4, column=0, sticky="nw", pady=4)
        note = tk.Text(body, width=34, height=2, wrap="word")
        note.insert("1.0", (row or {}).get("note", ""))
        note.grid(row=4, column=1, sticky="we", padx=(8, 0), pady=4)

        def save():
            if not criterion_var.get().strip():
                messagebox.showwarning("评审矩阵", "评分项不能为空。", parent=top)
                return
            data = {"criterion": criterion_var.get(), "weight": weight_var.get().strip(),
                    "score": score_var.get().strip() or None,
                    "evidence": evidence.get("1.0", "end").strip(),
                    "note": note.get("1.0", "end").strip()}
            try:
                if editing:
                    self.repo.update_competition_criterion(row["id"], data)
                else:
                    self.repo.add_competition_criterion(self.current_pid, data)
            except Exception as e:
                messagebox.showerror("评审矩阵", str(e), parent=top)
                return
            self._log("更新评分项" if editing else "添加评分项", data["criterion"])
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton", command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton", command=save).pack(side="right", padx=(0, 8))
        top.wait_window()

    def seed_rubric(self):
        if not self.current_pid:
            return
        seeded = cp.seed_project(self.repo, self.current_pid)
        self._load_project(self.current_pid)
        messagebox.showinfo("评审矩阵", "已补齐 %d 项默认评分项。" % seeded["rubric"], parent=self)

    def remove_criterion(self):
        cid = self._selected_id(self.rubric_tree)
        if cid is None:
            return
        row = [r for r in self.rubric if r["id"] == cid][0]
        if not messagebox.askyesno("评审矩阵", "删除「%s」？" % row["criterion"], parent=self):
            return
        self.repo.remove_competition_criterion(cid)
        self._load_project(self.current_pid)

    def export_rubric(self):
        if not self.current_pid:
            return
        project = self.repo.find_project(self.current_pid) or {}
        default = "%s_评审矩阵.csv" % cp._safe_name(project.get("name") or "赛事", "赛事")
        path = filedialog.asksaveasfilename(parent=self, title="导出评审矩阵",
                                           defaultextension=".csv", initialfile=default,
                                           filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            res = cp.export_rubric(self.repo, self.current_pid, path)
        except Exception as e:
            messagebox.showerror("评审矩阵", "导出失败：%s" % e, parent=self)
            return
        self._log("导出评审矩阵", "%d 项" % res["count"])

    # ---------- 提交校验 ----------
    def pick_submit_folder(self):
        folder = filedialog.askdirectory(parent=self, title="选择待提交目录")
        if folder:
            self.sub_folder_var.set(folder)
            if not self.def_out_var.get().strip():
                self.def_out_var.set(os.path.dirname(folder.rstrip(os.sep)))

    def _rules(self):
        return {
            "exts": self.ext_var.get(), "max_file_mb": self.max_file_var.get(),
            "max_total_mb": self.max_total_var.get(), "max_files": self.max_files_var.get(),
            "name_regex": self.regex_var.get(), "keyword": self.keyword_var.get(),
        }

    def run_submission(self):
        if not self.current_pid:
            messagebox.showinfo("提交校验", "先建或选一个赛事项目。", parent=self)
            return
        folder = self.sub_folder_var.get().strip()
        if not folder:
            messagebox.showinfo("提交校验", "先选提交目录。", parent=self)
            return
        try:
            result = cp.validate_submission(folder, self._rules())
        except Exception as e:
            messagebox.showerror("提交校验", str(e), parent=self)
            return
        self.last_submission = result
        self.last_folder = folder
        self._fill_submission(result)
        self.btn_open_report.configure(state="normal")
        try:
            cp.record_submission(self.repo, self.current_pid, result,
                                 getattr(self.window, "operator_name", "系统"))
        except Exception:
            pass
        self._log("提交校验", result["summary"])
        self._load_project_summary_only()
        if result["ok"]:
            messagebox.showinfo("提交校验", result["summary"], parent=self)
        else:
            messagebox.showwarning("提交校验", result["summary"], parent=self)

    def _fill_submission(self, result):
        self.sub_tree.delete(*self.sub_tree.get_children())
        for i, row in enumerate(result.get("rows") or []):
            tag = "green" if row["result"] == "通过" else "red"
            self.sub_tree.insert("", "end", tags=("zebra" if i % 2 else "", tag),
                                 values=(row["file"], row["ext"], cp._human_size(row["size"]),
                                         row["format"], row["naming"], row["result"], row["note"]))
        checks = "；".join("%s %s" % (c["name"], "通过" if c["ok"] else "不通过")
                          for c in result.get("checks") or [])
        self.sub_summary.configure(text=result["summary"] + "\n" + checks)

    def _load_project_summary_only(self):
        if not self.current_pid:
            return
        self.summary.configure(text=cp.project_summary(self.repo, self.current_pid)["text"])

    def open_report(self):
        path = (self.last_submission or {}).get("report_csv") or ""
        self._open(path)

    def use_submission_files(self):
        result = self.last_submission
        if not result or not result.get("rows"):
            messagebox.showinfo("答辩包", "先跑一次提交校验。", parent=self)
            return
        folder = self.last_folder or result.get("folder") or ""
        added = 0
        for row in result.get("rows") or []:
            if row.get("result") != "通过":
                continue
            full = os.path.abspath(os.path.join(folder, row["file"]))
            if full not in self.defense_files and os.path.isfile(full):
                self.defense_files.append(full)
                added += 1
        self._refresh_defense_list()
        if added:
            self._log("提交物料转答辩包", "%d 个文件" % added)
            self.def_summary.configure(text="已从提交校验带入 %d 个通过文件。" % added)
            messagebox.showinfo("答辩包", "已带入 %d 个通过文件；可继续补 PPT、视频。" % added,
                                parent=self)
        else:
            messagebox.showinfo("答辩包", "没有可带入的通过文件。", parent=self)

    # ---------- 答辩包 ----------
    def _refresh_defense_list(self):
        self.defense_list.delete(0, "end")
        for path in self.defense_files:
            self.defense_list.insert("end", os.path.basename(path))

    def add_defense_files(self):
        paths = filedialog.askopenfilenames(parent=self, title="选择答辩包文件")
        if not paths:
            return
        for p in paths:
            full = os.path.abspath(p)
            if full not in self.defense_files:
                self.defense_files.append(full)
        self._refresh_defense_list()
        self.def_summary.configure(text="已选 %d 个文件；生成后会写清单与答辩提纲。" % len(self.defense_files))

    def remove_defense_files(self):
        idx = list(self.defense_list.curselection())
        for i in reversed(idx):
            if 0 <= i < len(self.defense_files):
                self.defense_files.pop(i)
        self._refresh_defense_list()

    def clear_defense_files(self):
        self.defense_files = []
        self._refresh_defense_list()
        self.def_summary.configure(text="答辩包会复制文件、写清单与提纲；源文件不动。")

    def pick_defense_out(self):
        folder = filedialog.askdirectory(parent=self, title="选择答辩包输出目录")
        if folder:
            self.def_out_var.set(folder)

    def make_defense(self):
        if not self.current_pid:
            messagebox.showinfo("答辩包", "先建或选一个赛事项目。", parent=self)
            return
        if not self.defense_files:
            messagebox.showinfo("答辩包", "先加至少一个文件。", parent=self)
            return
        outdir = self.def_out_var.get().strip()
        if not outdir:
            messagebox.showinfo("答辩包", "先选输出目录。", parent=self)
            return
        try:
            result = cp.make_defense_package(
                self.repo, self.current_pid, self.defense_files, outdir,
                name=self.def_name_var.get().strip() or "答辩包",
                include_zip=self.def_zip_var.get(), submission=self.last_submission,
                operator=getattr(self.window, "operator_name", "系统"))
        except Exception as e:
            messagebox.showerror("答辩包", str(e), parent=self)
            return
        self.last_output = result["zip"] or result["root"]
        self.btn_open_output.configure(state="normal")
        self.def_summary.configure(
            text="%s\n目录：%s\n%s" % (result["summary"], result["root"],
                                      ("ZIP：" + result["zip"]) if result["zip"] else "未打 ZIP"))
        self._log("生成答辩包", result["summary"])
        self._load_project_summary_only()
        messagebox.showinfo("答辩包", result["summary"], parent=self)

    def open_output(self):
        self._open(os.path.dirname(self.last_output) if os.path.isfile(self.last_output)
                   else self.last_output)

    def _open(self, path):
        if not path or not os.path.exists(path):
            messagebox.showinfo("赛事工作台", "还没有可打开的文件或目录。", parent=self)
            return
        try:
            os.startfile(path)  # noqa: S606 - Windows 桌面程序的标准打开方式
        except OSError as e:
            messagebox.showwarning("赛事工作台", "打开失败：%s" % e, parent=self)

# -*- coding: utf-8 -*-
"""项目工作台 v0.31：项目、交付物、进度与项目记录。

这一版只做最小闭环：建项目、按模板挂交付物、改状态、看完成率与缺项。
资产、执行记录、质量门先在数据层留位，等后续版本再接界面。
"""

import tkinter as tk
from tkinter import ttk

from theme import FONT, C
from database import (PROJECT_KINDS, PROJECT_KIND_ORDER, PROJECT_STAGES,
                      PROJECT_STATUS, DELIVERABLE_STATUS)
from ui_empty import EmptyState


class ProjectsView(ttk.Frame):
    PERM = "task:manage"
    COLS = ("name", "kind", "stage", "progress", "due")
    HEADS = {"name": "项目", "kind": "类型", "stage": "阶段",
             "progress": "完成", "due": "截止日期"}
    WIDTHS = {"name": 220, "kind": 90, "stage": 80, "progress": 70, "due": 110}
    DCOLS = ("name", "stage", "status", "required", "note")
    DHEADS = {"name": "交付物", "stage": "阶段", "status": "状态",
              "required": "必交", "note": "备注"}
    DWIDTHS = {"name": 220, "stage": 80, "status": 90,
               "required": 54, "note": 180}

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self.current_id = None
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(4, 10))
        self.summary = ttk.Label(top, text="", style="Muted.TLabel")
        self.summary.pack(side="right")

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=18)

        # 左侧项目列表
        left = ttk.Frame(pane)
        pane.add(left, weight=2)
        self.tree = ttk.Treeview(left, columns=self.COLS, show="headings",
                                 selectmode="browse")
        for c in self.COLS:
            self.tree.heading(c, text=self.HEADS[c], anchor="w")
            self.tree.column(c, width=self.WIDTHS[c], anchor="w", stretch=True)
        self.tree.tag_configure("zebra", background=C["zebra"])
        ysb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._select_project())
        self.tree.bind("<Double-1>", lambda e: self.edit_project())
        self.empty = EmptyState(left, wraplength=320)

        # 右侧项目详情
        right = ttk.Frame(pane)
        pane.add(right, weight=3)
        self.detail_title = ttk.Label(right, text="选择一个项目",
                                      style="H2.TLabel")
        self.detail_title.pack(anchor="w", pady=(0, 2))
        self.detail_meta = ttk.Label(right, text="左侧选择项目后查看交付物与进度",
                                     style="Muted.TLabel")
        self.detail_meta.pack(anchor="w")
        self.detail_goal = ttk.Label(right, text="", style="Muted.TLabel",
                                     wraplength=620, justify="left")
        self.detail_goal.pack(anchor="w", pady=(6, 4))
        self.detail_stats = ttk.Label(right, text="", style="Muted.TLabel")
        self.detail_stats.pack(anchor="w", pady=(0, 8))

        dwtree_wrap = ttk.Frame(right)
        dwtree_wrap.pack(fill="both", expand=True)
        self.dtree = ttk.Treeview(dwtree_wrap, columns=self.DCOLS,
                                  show="headings", selectmode="browse")
        for c in self.DCOLS:
            self.dtree.heading(c, text=self.DHEADS[c], anchor="w")
            self.dtree.column(c, width=self.DWIDTHS[c], anchor="w", stretch=True)
        self.dtree.tag_configure("zebra", background=C["zebra"])
        self.dtree.tag_configure("green", foreground=C["green"])
        self.dtree.tag_configure("orange", foreground=C["orange"])
        self.dtree.tag_configure("red", foreground=C["red"])
        dysb = ttk.Scrollbar(dwtree_wrap, orient="vertical",
                             command=self.dtree.yview)
        self.dtree.configure(yscrollcommand=dysb.set)
        self.dtree.pack(side="left", fill="both", expand=True)
        dysb.pack(side="right", fill="y")
        self.dtree.bind("<Double-1>", lambda e: self.edit_deliverable())
        self.dtree.bind("<<TreeviewSelect>>", lambda e: self._update_buttons())
        self.dhint = ttk.Label(right, text="", style="Muted.TLabel")
        self.dhint.pack(anchor="w", pady=(6, 0))

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=12)
        self.btn_new = ttk.Button(bar, text="新建项目", style="Accent.TButton",
                                  command=lambda: self.project_dialog(None))
        self.btn_edit = ttk.Button(bar, text="编辑项目", style="Ghost.TButton",
                                   command=self.edit_project)
        self.btn_del = ttk.Button(bar, text="删除项目", style="Danger.TButton",
                                  command=self.remove_project)
        self.btn_tpl = ttk.Button(bar, text="套用模板", style="Ghost.TButton",
                                  command=self.apply_template)
        self.btn_add_d = ttk.Button(bar, text="添加交付物", style="Ghost.TButton",
                                    command=lambda: self.deliverable_dialog(None))
        self.btn_pass = ttk.Button(bar, text="标记通过", style="Ghost.TButton",
                                   command=lambda: self.mark_deliverable("已通过"))
        self.btn_reject = ttk.Button(bar, text="标记驳回", style="Ghost.TButton",
                                     command=lambda: self.mark_deliverable("已驳回"))
        self.btn_del_d = ttk.Button(bar, text="删除交付物", style="Danger.TButton",
                                    command=self.remove_deliverable)

    # ---------- 读取与刷新 ----------
    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(self.tree.item(sel[0])["tags"][0])
        except (ValueError, IndexError, KeyError):
            return None

    def _selected_deliverable(self):
        sel = self.dtree.selection()
        if not sel:
            return None
        try:
            return int(self.dtree.item(sel[0])["tags"][0])
        except (ValueError, IndexError, KeyError):
            return None

    def refresh(self):
        projects = self.repo.list_projects()
        old = self.current_id
        self.tree.delete(*self.tree.get_children())
        for i, p in enumerate(projects):
            tags = (str(p["id"]), "zebra" if i % 2 else "")
            self.tree.insert("", "end", tags=tags,
                             values=(p["name"], PROJECT_KINDS.get(p["kind"], p["kind"]),
                                     p["stage"], "%d/%d" % (p["done"], p["total"]),
                                     p.get("due_date", "")))
        total_deliv = sum(p["total"] for p in projects)
        done_deliv = sum(p["done"] for p in projects)
        ongoing = sum(1 for p in projects if p["status"] == "进行中")
        self.summary.config(text="项目 %d · 进行中 %d · 交付物 %d 项 · 已通过 %d" %
                            (len(projects), ongoing, total_deliv, done_deliv))
        if projects:
            self.empty.hide()
        else:
            self.empty.set("还没有项目",
                           "项目是这一版的新容器：先建一个项目，再按模板挂交付物；"
                           "材料台账仍是执行层，不会被替代。",
                           "新建项目", lambda: self.project_dialog(None))
            self.empty.show_place()
        if not projects:
            self.current_id = None
            self._show_detail(None)
            self._update_buttons()
            return
        ids = [p["id"] for p in projects]
        if old not in ids:
            old = ids[0]
        self.current_id = old
        iid = str(old)
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
        self._show_detail(self.repo.find_project(old))
        self._update_buttons()

    def _show_detail(self, project):
        self.dtree.delete(*self.dtree.get_children())
        if project is None:
            self.detail_title.config(text="选择一个项目")
            self.detail_meta.config(text="左侧选择项目后查看交付物与进度")
            self.detail_goal.config(text="")
            self.detail_stats.config(text="")
            self.dhint.config(text="")
            return
        self.detail_title.config(text=project["name"])
        meta = "%s · %s · %s" % (
            PROJECT_KINDS.get(project["kind"], project["kind"]),
            project["stage"], project["status"])
        if project.get("owner"):
            meta += " · 负责人 " + project["owner"]
        if project.get("due_date"):
            meta += " · 截止 " + project["due_date"]
        self.detail_meta.config(text=meta)
        self.detail_goal.config(text=project.get("goal") or "还没有写目标；编辑项目时可以补一句。")
        self.detail_stats.config(
            text="交付物 %d 项 · 已通过 %d · 缺项 %d · 完成率 %d%%" %
                 (project["total"], project["done"], project["missing"],
                  project["progress"]))
        rows = self.repo.list_deliverables(project["id"])
        for i, d in enumerate(rows):
            tag = "zebra"
            if d["status"] == "已通过":
                tag = "green"
            elif d["status"] == "待评审":
                tag = "orange"
            elif d["status"] == "已驳回":
                tag = "red"
            self.dtree.insert("", "end", tags=(str(d["id"]), "zebra" if i % 2 else "", tag),
                              values=(d["name"], d["stage"], d["status"],
                                      "是" if d["required"] else "否",
                                      d.get("note", "")))
        if rows:
            self.dhint.config(text="双击交付物可编辑；状态改为「已通过」才会计入完成率。")
        else:
            self.dhint.config(text="还没有交付物。点「套用模板」按项目类型生成，或手动添加。")

    def _update_buttons(self):
        has_project = self.current_id is not None
        has_deliv = self._selected_deliverable() is not None
        for b in (self.btn_new, self.btn_edit, self.btn_del, self.btn_tpl,
                  self.btn_add_d, self.btn_pass, self.btn_reject, self.btn_del_d):
            b.pack_forget()
        self.btn_new.pack(side="left")
        if self.window.can(self.PERM):
            if has_project:
                self.btn_edit.pack(side="left", padx=8)
                self.btn_tpl.pack(side="left", padx=8)
                self.btn_add_d.pack(side="left", padx=8)
                self.btn_del.pack(side="left", padx=8)
            if has_deliv:
                self.btn_pass.pack(side="left", padx=8)
                self.btn_reject.pack(side="left", padx=8)
                self.btn_del_d.pack(side="left", padx=8)
        self.btn_new.config(state="normal" if self.window.can(self.PERM) else "disabled")

    def _select_project(self):
        pid = self._selected()
        if pid is None or pid == self.current_id:
            self._update_buttons()
            return
        self.current_id = pid
        self._show_detail(self.repo.find_project(pid))
        self._update_buttons()

    # ---------- 项目增删改 ----------
    def _require_perm(self):
        if not self.window.can(self.PERM):
            self.window.toast("当前视角无权执行该操作")
            return False
        return True

    def project_dialog(self, project):
        if not self._require_perm():
            return
        dlg = tk.Toplevel(self)
        dlg.title("编辑项目" if project else "新建项目")
        dlg.transient(self)
        dlg.resizable(False, False)

        v_name = tk.StringVar(value=project["name"] if project else "")
        kind_label = PROJECT_KINDS.get(project["kind"], "班级材料") if project else "班级材料"
        v_kind = tk.StringVar(value=kind_label)
        v_stage = tk.StringVar(value=project["stage"] if project else "定义")
        v_status = tk.StringVar(value=project["status"] if project else "进行中")
        v_owner = tk.StringVar(value=project.get("owner", "") if project else "")
        v_start = tk.StringVar(value=project.get("start_date", "") if project else "")
        v_due = tk.StringVar(value=project.get("due_date", "") if project else "")
        v_tpl = tk.BooleanVar(value=not bool(project))
        goal = tk.Text(dlg, height=3, font=(FONT, 11), width=42)
        note = tk.Text(dlg, height=2, font=(FONT, 11), width=42)
        if project:
            goal.insert("1.0", project.get("goal", ""))
            note.insert("1.0", project.get("note", ""))
        err = ttk.Label(dlg, text="", foreground=C["red"], font=(FONT, 10))

        rows = [
            ("项目名称 *", ttk.Entry(dlg, textvariable=v_name, width=36)),
            ("项目类型", ttk.Combobox(dlg, textvariable=v_kind, state="readonly",
                                      values=[PROJECT_KINDS[k] for k in PROJECT_KIND_ORDER],
                                      width=33)),
            ("当前阶段", ttk.Combobox(dlg, textvariable=v_stage, state="readonly",
                                      values=list(PROJECT_STAGES), width=33)),
            ("项目状态", ttk.Combobox(dlg, textvariable=v_status, state="readonly",
                                      values=list(PROJECT_STATUS), width=33)),
            ("负责人", ttk.Entry(dlg, textvariable=v_owner, width=36)),
            ("开始日期（YYYY-MM-DD）", ttk.Entry(dlg, textvariable=v_start, width=36)),
            ("截止日期（YYYY-MM-DD）", ttk.Entry(dlg, textvariable=v_due, width=36)),
        ]
        for i, (label, widget) in enumerate(rows):
            ttk.Label(dlg, text=label).grid(row=i, column=0, sticky="w", padx=16, pady=8)
            widget.grid(row=i, column=1, padx=16, pady=8)
        r = len(rows)
        ttk.Label(dlg, text="项目目标").grid(row=r, column=0, sticky="nw", padx=16, pady=8)
        goal.grid(row=r, column=1, padx=16, pady=8)
        ttk.Label(dlg, text="备注").grid(row=r+1, column=0, sticky="nw", padx=16, pady=8)
        note.grid(row=r+1, column=1, padx=16, pady=8)
        if not project:
            ttk.Checkbutton(dlg, text="按项目类型生成默认交付物", variable=v_tpl).grid(
                row=r+2, column=1, sticky="w", padx=16)
        err.grid(row=r+3, column=0, columnspan=2, sticky="w", padx=16)

        def submit():
            kind_key = next((k for k, v in PROJECT_KINDS.items() if v == v_kind.get()), "class")
            data = {"name": v_name.get(), "kind": kind_key,
                    "stage": v_stage.get(), "status": v_status.get(),
                    "owner": v_owner.get(), "start_date": v_start.get(),
                    "due_date": v_due.get(),
                    "goal": goal.get("1.0", "end").strip(),
                    "note": note.get("1.0", "end").strip()}
            try:
                if project:
                    self.repo.update_project(project["id"], data)
                    pid = project["id"]
                else:
                    pid = self.repo.add_project(data)
                    if v_tpl.get():
                        self.repo.apply_project_template(pid, kind_key)
            except Exception as e:
                err.config(text=str(e))
                return
            dlg.destroy()
            self.current_id = pid
            self.window.refresh_all()
            self.window.toast("项目已保存")

        btns = ttk.Frame(dlg)
        btns.grid(row=r+4, column=0, columnspan=2, pady=(4, 14))
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="保存", style="Accent.TButton",
                   command=submit).pack(side="right")

    def edit_project(self):
        if self.current_id is None:
            self.window.toast("请先选择一个项目")
            return
        p = self.repo.find_project(self.current_id)
        if p:
            self.project_dialog(p)

    def remove_project(self):
        if not self._require_perm():
            return
        if self.current_id is None:
            self.window.toast("请先选择一个项目")
            return
        p = self.repo.find_project(self.current_id)
        if not self.window.confirm(
                "删除项目",
                "确定删除项目「%s」及其 %d 项交付物吗？材料台账不会被删除。" %
                (p["name"] if p else "", p["total"] if p else 0)):
            return
        self.repo.remove_project(self.current_id)
        self.current_id = None
        self.window.refresh_all()
        self.window.toast("项目已删除")

    def apply_template(self):
        if not self._require_perm():
            return
        if self.current_id is None:
            self.window.toast("请先选择一个项目")
            return
        added = self.repo.apply_project_template(self.current_id)
        self.window.refresh_all()
        self.window.toast("已补 %d 项交付物" % added)

    # ---------- 交付物增删改 ----------
    def deliverable_dialog(self, deliverable):
        if not self._require_perm():
            return
        if self.current_id is None:
            self.window.toast("请先选择一个项目")
            return
        dlg = tk.Toplevel(self)
        dlg.title("编辑交付物" if deliverable else "添加交付物")
        dlg.transient(self)
        dlg.resizable(False, False)
        v_name = tk.StringVar(value=deliverable["name"] if deliverable else "")
        v_stage = tk.StringVar(value=deliverable["stage"] if deliverable else "生产")
        v_status = tk.StringVar(value=deliverable["status"] if deliverable else "待开始")
        v_req = tk.BooleanVar(value=deliverable["required"] if deliverable else True)
        note = tk.Text(dlg, height=3, font=(FONT, 11), width=36)
        if deliverable:
            note.insert("1.0", deliverable.get("note", ""))
        err = ttk.Label(dlg, text="", foreground=C["red"], font=(FONT, 10))

        ttk.Label(dlg, text="交付物名称 *").grid(row=0, column=0, sticky="w", padx=16, pady=8)
        ttk.Entry(dlg, textvariable=v_name, width=30).grid(row=0, column=1, padx=16, pady=8)
        ttk.Label(dlg, text="阶段").grid(row=1, column=0, sticky="w", padx=16, pady=8)
        ttk.Combobox(dlg, textvariable=v_stage, values=list(PROJECT_STAGES),
                     state="readonly", width=27).grid(row=1, column=1, padx=16, pady=8)
        ttk.Label(dlg, text="状态").grid(row=2, column=0, sticky="w", padx=16, pady=8)
        ttk.Combobox(dlg, textvariable=v_status, values=list(DELIVERABLE_STATUS),
                     state="readonly", width=27).grid(row=2, column=1, padx=16, pady=8)
        ttk.Checkbutton(dlg, text="必交（计入缺项）", variable=v_req).grid(
            row=3, column=1, sticky="w", padx=16, pady=6)
        ttk.Label(dlg, text="备注").grid(row=4, column=0, sticky="nw", padx=16, pady=8)
        note.grid(row=4, column=1, padx=16, pady=8)
        err.grid(row=5, column=0, columnspan=2, sticky="w", padx=16)

        def submit():
            data = {"name": v_name.get(), "stage": v_stage.get(),
                    "status": v_status.get(), "required": v_req.get(),
                    "note": note.get("1.0", "end").strip()}
            try:
                if deliverable:
                    self.repo.update_deliverable(deliverable["id"], data)
                else:
                    self.repo.add_deliverable(self.current_id, data)
            except Exception as e:
                err.config(text=str(e))
                return
            dlg.destroy()
            self.window.refresh_all()
            self.window.toast("交付物已保存")

        btns = ttk.Frame(dlg)
        btns.grid(row=6, column=0, columnspan=2, pady=(4, 14))
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="保存", style="Accent.TButton",
                   command=submit).pack(side="right")

    def edit_deliverable(self):
        did = self._selected_deliverable()
        if did is None:
            return
        rows = self.repo.list_deliverables(self.current_id)
        d = next((x for x in rows if x["id"] == did), None)
        if d:
            self.deliverable_dialog(d)

    def mark_deliverable(self, status):
        if not self._require_perm():
            return
        did = self._selected_deliverable()
        if did is None:
            self.window.toast("请先选择一项交付物")
            return
        self.repo.update_deliverable(did, {"status": status})
        self.window.refresh_all()

    def remove_deliverable(self):
        if not self._require_perm():
            return
        did = self._selected_deliverable()
        if did is None:
            self.window.toast("请先选择一项交付物")
            return
        self.repo.remove_deliverable(did)
        self.window.refresh_all()
        self.window.toast("交付物已删除")

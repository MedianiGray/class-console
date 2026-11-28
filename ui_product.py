# -*- coding: utf-8 -*-
"""v0.35 产品工作台：PRD、架构 / BOM、原型、测试、发布包、评审与路演。

界面不内置 CAD / IDE，也不替用户写产品内容；它把一个产品项目从立项
到发布包这条线串起来，并把每次动作写回项目资产、执行记录与质量门。
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import products as pp
from database import PRODUCT_REVIEW_CONCLUSIONS
from theme import C, FONT


class ProductView(ttk.Frame):
    PERM = "prod:run"
    PRD_COLS = ("section", "content", "state")
    PRD_HEADS = {"section": "小节", "content": "内容", "state": "状态"}
    PRD_WIDTHS = {"section": 170, "content": 620, "state": 80}
    BOM_COLS = ("kind", "name", "spec", "qty", "unit", "cost", "subtotal", "source")
    BOM_HEADS = {"kind": "类型", "name": "名称", "spec": "规格",
                 "qty": "数量", "unit": "单位", "cost": "单价",
                 "subtotal": "小计", "source": "来源"}
    BOM_WIDTHS = {"kind": 68, "name": 150, "spec": 240, "qty": 56,
                  "unit": 52, "cost": 70, "subtotal": 80, "source": 130}
    PROTO_COLS = ("name", "version", "status", "path", "note")
    PROTO_HEADS = {"name": "原型", "version": "版本", "status": "状态",
                   "path": "路径", "note": "备注"}
    PROTO_WIDTHS = {"name": 170, "version": 80, "status": 80,
                    "path": 360, "note": 200}
    TEST_COLS = ("name", "severity", "result", "method", "issue")
    TEST_HEADS = {"name": "测试项", "severity": "级别", "result": "结果",
                  "method": "方法", "issue": "问题 / 说明"}
    TEST_WIDTHS = {"name": 210, "severity": 56, "result": 76,
                   "method": 250, "issue": 320}
    REV_COLS = ("gate", "conclusion", "reviewer", "date", "note")
    REV_HEADS = {"gate": "评审门", "conclusion": "结论", "reviewer": "评审人",
                 "date": "日期", "note": "意见"}
    REV_WIDTHS = {"gate": 120, "conclusion": 100, "reviewer": 120,
                  "date": 100, "note": 380}
    CHK_COLS = ("name", "ok", "note")
    CHK_HEADS = {"name": "检查项", "ok": "结论", "note": "说明"}
    CHK_WIDTHS = {"name": 150, "ok": 76, "note": 620}

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self.current_pid = None
        self.project_map = {}
        self.specs = []
        self.arch = []
        self.bom = []
        self.protos = []
        self.tests = []
        self.reviews = []
        self.release_files = []
        self.last_release = None
        self.last_roadshow = ""
        self.pm_buttons = []
        self._loaded_pid = None
        self._build()

    # ---------- 外壳 ----------
    def _build(self):
        style = ttk.Style(self)
        style.configure("Section.TLabel", font=(FONT, 10, "bold"),
                        background=C["bg"], foreground=C["text"])
        head = ttk.Frame(self)
        head.pack(fill="x", padx=18, pady=(4, 6))
        ttk.Label(head, text="产品工作台", style="H2.TLabel").pack(side="left")
        self.summary = ttk.Label(head, text="", style="Muted.TLabel")
        self.summary.pack(side="right")

        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(0, 8))
        ttk.Label(top, text="产品项目", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.project_var = tk.StringVar(value="")
        self.project_cb = ttk.Combobox(top, textvariable=self.project_var,
                                       state="readonly", width=46)
        self.project_cb.grid(row=0, column=1, sticky="w", padx=(8, 8))
        self.project_cb.bind("<<ComboboxSelected>>", lambda e: self._on_project())
        self.btn_new = ttk.Button(top, text="新建产品项目", style="Accent.TButton",
                                  command=lambda: self.project_dialog(None))
        self.btn_new.grid(row=0, column=2, padx=2)
        self.btn_edit = ttk.Button(top, text="编辑项目", style="Ghost.TButton",
                                   command=lambda: self.project_dialog("edit"))
        self.btn_edit.grid(row=0, column=3, padx=2)
        ttk.Button(top, text="刷新", style="Ghost.TButton",
                   command=self.refresh).grid(row=0, column=4, padx=(2, 12))
        self.project_hint = ttk.Label(top, text="", style="Muted.TLabel")
        self.project_hint.grid(row=1, column=1, columnspan=4, sticky="w",
                               padx=(8, 0), pady=(4, 0))
        top.columnconfigure(1, weight=1)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=18, pady=(0, 4))
        self.tab_prd = ttk.Frame(self.nb)
        self.tab_bom = ttk.Frame(self.nb)
        self.tab_proto = ttk.Frame(self.nb)
        self.tab_test = ttk.Frame(self.nb)
        self.tab_release = ttk.Frame(self.nb)
        self.tab_review = ttk.Frame(self.nb)
        self.nb.add(self.tab_prd, text="需求 PRD")
        self.nb.add(self.tab_bom, text="架构 / BOM")
        self.nb.add(self.tab_proto, text="原型")
        self.nb.add(self.tab_test, text="测试")
        self.nb.add(self.tab_release, text="发布包")
        self.nb.add(self.tab_review, text="评审 / 路演")
        self._build_prd()
        self._build_bom()
        self._build_proto()
        self._build_test()
        self._build_release()
        self._build_review()
        self.after(50, self.refresh)

    def _mk_tree(self, parent, cols, heads, widths, selectmode="browse",
                 height=10, expand=True):
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both" if expand else "x", expand=expand,
                  padx=14, pady=(6, 0))
        tree = ttk.Treeview(wrap, columns=cols, show="headings",
                            selectmode=selectmode, height=height)
        for c in cols:
            tree.heading(c, text=heads[c], anchor="w")
            tree.column(c, width=widths[c], anchor="w",
                        stretch=(c in ("content", "note", "issue", "path", "spec"))
                        or c == cols[-1])
        tree.tag_configure("zebra", background=C["zebra"])
        tree.tag_configure("green", foreground=C["green"])
        tree.tag_configure("orange", foreground=C["orange"])
        tree.tag_configure("red", foreground=C["red"])
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ysb.set)
        tree.pack(side="left", fill="both", expand=expand)
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

    # ---------- PRD ----------
    def _build_prd(self):
        self.prd_summary = ttk.Label(self.tab_prd, text="", style="Muted.TLabel")
        self.prd_summary.pack(anchor="w", padx=14, pady=(8, 0))
        self.prd_tree = self._mk_tree(self.tab_prd, self.PRD_COLS,
                                      self.PRD_HEADS, self.PRD_WIDTHS)
        self.prd_tree.bind("<Double-1>", lambda e: self.spec_dialog("prd", "edit"))
        bar = self._mk_bar(self.tab_prd)
        self._button(bar, "添加小节", lambda: self.spec_dialog("prd", None),
                     "Accent.TButton")
        self._button(bar, "编辑小节", lambda: self.spec_dialog("prd", "edit"))
        self._button(bar, "导出 PRD", lambda: self.export_spec("prd"))
        self._button(bar, "删除小节", lambda: self.remove_spec("prd"),
                     "Danger.TButton")

    # ---------- 架构 / BOM ----------
    def _build_bom(self):
        arch_head = ttk.Frame(self.tab_bom)
        arch_head.pack(fill="x", padx=14, pady=(8, 0))
        ttk.Label(arch_head, text="架构说明", style="Section.TLabel").pack(side="left")
        self.arch_summary = ttk.Label(arch_head, text="", style="Muted.TLabel")
        self.arch_summary.pack(side="right")
        self.arch_tree = self._mk_tree(self.tab_bom, self.PRD_COLS,
                                       self.PRD_HEADS, self.PRD_WIDTHS,
                                       height=4, expand=False)
        self.arch_tree.bind("<Double-1>", lambda e: self.spec_dialog("arch", "edit"))
        arch_bar = ttk.Frame(self.tab_bom)
        arch_bar.pack(fill="x", padx=14, pady=(4, 6))
        self._button(arch_bar, "编辑架构", lambda: self.spec_dialog("arch", "edit"))
        self._button(arch_bar, "添加架构小节",
                     lambda: self.spec_dialog("arch", None))
        self._button(arch_bar, "导出架构", lambda: self.export_spec("arch"))

        bom_head = ttk.Frame(self.tab_bom)
        bom_head.pack(fill="x", padx=14, pady=(2, 0))
        ttk.Label(bom_head, text="BOM 清单", style="Section.TLabel").pack(side="left")
        self.bom_summary = ttk.Label(bom_head, text="", style="Muted.TLabel")
        self.bom_summary.pack(side="right")
        self.bom_tree = self._mk_tree(self.tab_bom, self.BOM_COLS,
                                      self.BOM_HEADS, self.BOM_WIDTHS)
        self.bom_tree.bind("<Double-1>", lambda e: self.bom_dialog("edit"))
        bar = self._mk_bar(self.tab_bom)
        self._button(bar, "添加 BOM", lambda: self.bom_dialog(None), "Accent.TButton")
        self._button(bar, "编辑 BOM", lambda: self.bom_dialog("edit"))
        self._button(bar, "导出 BOM CSV", self.export_bom)
        self._button(bar, "删除 BOM", self.remove_bom, "Danger.TButton")

    # ---------- 原型 ----------
    def _build_proto(self):
        self.proto_summary = ttk.Label(self.tab_proto, text="", style="Muted.TLabel")
        self.proto_summary.pack(anchor="w", padx=14, pady=(8, 0))
        self.proto_tree = self._mk_tree(self.tab_proto, self.PROTO_COLS,
                                        self.PROTO_HEADS, self.PROTO_WIDTHS)
        self.proto_tree.bind("<Double-1>", lambda e: self.proto_dialog("edit"))
        bar = self._mk_bar(self.tab_proto)
        self._button(bar, "添加原型", lambda: self.proto_dialog(None), "Accent.TButton")
        self._button(bar, "编辑原型", lambda: self.proto_dialog("edit"))
        self._button(bar, "标为可用", lambda: self.set_proto_status("可用"))
        self._button(bar, "冻结版本", lambda: self.set_proto_status("已冻结"))
        self._button(bar, "打开路径", self.open_proto)
        self._button(bar, "删除原型", self.remove_proto, "Danger.TButton")

    # ---------- 测试 ----------
    def _build_test(self):
        self.test_summary = ttk.Label(self.tab_test, text="", style="Muted.TLabel")
        self.test_summary.pack(anchor="w", padx=14, pady=(8, 0))
        self.test_tree = self._mk_tree(self.tab_test, self.TEST_COLS,
                                       self.TEST_HEADS, self.TEST_WIDTHS)
        self.test_tree.bind("<Double-1>", lambda e: self.test_dialog("edit"))
        bar = self._mk_bar(self.tab_test)
        self._button(bar, "添加测试项", lambda: self.test_dialog(None), "Accent.TButton")
        self._button(bar, "编辑测试项", lambda: self.test_dialog("edit"))
        self._button(bar, "标记通过", lambda: self.set_test_result("通过"))
        self._button(bar, "标记不通过", lambda: self.set_test_result("不通过"))
        self._button(bar, "删除测试项", self.remove_test, "Danger.TButton")

    # ---------- 发布包 ----------
    def _build_release(self):
        head = ttk.Frame(self.tab_release)
        head.pack(fill="x", padx=14, pady=(8, 0))
        ttk.Label(head, text="上线检查", style="Section.TLabel").pack(side="left")
        self.readiness_summary = ttk.Label(head, text="", style="Muted.TLabel")
        self.readiness_summary.pack(side="right")

        bar = self._mk_bar(self.tab_release)
        self._button(bar, "刷新上线检查", self.refresh_readiness)
        self._button(bar, "生成发布包", self.make_release, "Accent.TButton")
        self.btn_open_release = ttk.Button(bar, text="打开发布包", style="Ghost.TButton",
                                           command=self.open_release, state="disabled")
        self.btn_open_release.pack(side="left", padx=(0, 6))
        self.release_summary = ttk.Label(
            self.tab_release, text="先补齐 PRD / 架构 / BOM / 原型 / 测试 / 评审，再看上线检查。",
            style="Muted.TLabel")
        self.release_summary.pack(side="bottom", anchor="w", padx=14, pady=(6, 0))

        self.check_tree = self._mk_tree(self.tab_release, self.CHK_COLS,
                                        self.CHK_HEADS, self.CHK_WIDTHS,
                                        height=6, expand=False)

        form = ttk.Frame(self.tab_release)
        form.pack(fill="both", expand=True, padx=14, pady=(6, 0))
        left = ttk.Frame(form)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="包内文件", style="Muted.TLabel").pack(anchor="w")
        list_wrap = ttk.Frame(left)
        list_wrap.pack(fill="both", expand=True, pady=(4, 0))
        self.release_list = tk.Listbox(list_wrap, height=4, activestyle="none")
        self.release_list.pack(side="left", fill="both", expand=True)
        ysb = ttk.Scrollbar(list_wrap, orient="vertical",
                            command=self.release_list.yview)
        self.release_list.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        file_bar = ttk.Frame(left)
        file_bar.pack(fill="x", pady=(4, 0))
        ttk.Button(file_bar, text="添加文件…", style="Ghost.TButton",
                   command=self.add_release_files).pack(side="left", padx=(0, 4))
        ttk.Button(file_bar, text="移除选中", style="Ghost.TButton",
                   command=self.remove_release_files).pack(side="left", padx=(0, 4))
        ttk.Button(file_bar, text="清空", style="Ghost.TButton",
                   command=self.clear_release_files).pack(side="left")

        right = ttk.Frame(form)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))
        ttk.Label(right, text="版本号", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", pady=3)
        self.release_version_var = tk.StringVar(value="v1.0")
        ttk.Entry(right, textvariable=self.release_version_var, width=24).grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=3)
        ttk.Label(right, text="输出目录", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=3)
        self.release_out_var = tk.StringVar(value="")
        ttk.Entry(right, textvariable=self.release_out_var, width=32).grid(
            row=1, column=1, sticky="we", padx=(8, 0), pady=3)
        ttk.Button(right, text="选…", style="Ghost.TButton",
                   command=self.pick_release_out).grid(row=1, column=2, padx=(6, 0))
        ttk.Label(right, text="发布说明", style="Muted.TLabel").grid(
            row=2, column=0, sticky="nw", pady=3)
        self.release_notes = tk.Text(right, width=34, height=3, wrap="word")
        self.release_notes.grid(row=2, column=1, columnspan=2,
                                sticky="we", padx=(8, 0), pady=3)
        self.release_zip_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="同时打 ZIP", variable=self.release_zip_var).grid(
            row=3, column=1, sticky="w", padx=(8, 0), pady=3)
        ttk.Label(right, text="发布包会复制文件、写清单 / 说明 / 上线检查；源文件不动。",
                  style="Muted.TLabel").grid(row=4, column=0, columnspan=3,
                                             sticky="w", pady=(4, 0))
        right.columnconfigure(1, weight=1)

    # ---------- 评审 / 路演 ----------
    def _build_review(self):
        self.review_summary = ttk.Label(self.tab_review, text="", style="Muted.TLabel")
        self.review_summary.pack(anchor="w", padx=14, pady=(8, 0))
        self.review_tree = self._mk_tree(self.tab_review, self.REV_COLS,
                                         self.REV_HEADS, self.REV_WIDTHS)
        self.review_tree.bind("<Double-1>", lambda e: self.review_dialog("edit"))
        self.roadshow_label = ttk.Label(self.tab_review, text="", style="Muted.TLabel")
        self.roadshow_label.pack(anchor="w", padx=14, pady=(4, 0))
        bar = self._mk_bar(self.tab_review)
        self._button(bar, "填写评审结论", lambda: self.review_dialog("edit"),
                     "Accent.TButton")
        self._button(bar, "新增评审门", lambda: self.review_dialog(None))
        self._button(bar, "导出路演提纲", self.export_roadshow)
        self._button(bar, "删除评审门", self.remove_review, "Danger.TButton")

    # ---------- 项目 ----------
    def refresh(self, select_pid=None):
        try:
            projects = self.repo.list_projects("product")
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
            self.summary.configure(text="还没有产品项目")
            self.project_hint.configure(
                text="先新建产品项目，再写 PRD、列 BOM、记原型与测试；不内置 CAD / IDE。")
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
            self._loaded_pid = None
            self.release_files = []
            self.last_release = None
            for tree in (self.prd_tree, self.arch_tree, self.bom_tree,
                         self.proto_tree, self.test_tree, self.review_tree,
                         self.check_tree):
                tree.delete(*tree.get_children())
            self.release_list.delete(0, "end")
            for label in (self.prd_summary, self.arch_summary, self.bom_summary,
                          self.proto_summary, self.test_summary,
                          self.review_summary, self.roadshow_label):
                label.configure(text="")
            self.readiness_summary.configure(text="")
            self.release_summary.configure(
                text="先补齐 PRD / 架构 / BOM / 原型 / 测试 / 评审，再看上线检查。")
            self.project_hint.configure(text="")
            self.btn_open_release.configure(state="disabled")
            return
        project = self.repo.find_project(pid)
        if project is None:
            self.current_pid = None
            return
        self.specs = self.repo.list_product_specs(pid, "prd")
        self.arch = self.repo.list_product_specs(pid, "arch")
        self.bom = self.repo.list_product_bom(pid)
        self.protos = self.repo.list_product_protos(pid)
        self.tests = self.repo.list_product_tests(pid)
        self.reviews = self.repo.list_product_reviews(pid)
        self._fill_specs(self.prd_tree, self.specs, "prd")
        self._fill_specs(self.arch_tree, self.arch, "arch")
        self._fill_bom()
        self._fill_protos()
        self._fill_tests()
        self._fill_reviews()
        if self._loaded_pid != pid:
            self.release_files = []
            self.last_release = None
            self.btn_open_release.configure(state="disabled")
            self.release_version_var.set("v1.0")
            self.release_notes.delete("1.0", "end")
            self.last_roadshow = ""
        self._loaded_pid = pid
        self._refresh_release_list()
        self.refresh_readiness()
        self.summary.configure(text=pp.project_summary(self.repo, pid))
        meta = "%s · %s · 截止 %s" % (
            project.get("stage"), project.get("status"),
            project.get("due_date") or "未定")
        self.project_hint.configure(
            text=meta + "；发布包与路演导出都会写回项目记录。")

    def project_dialog(self, mode=None):
        editing = mode == "edit" and self.current_pid
        project = self.repo.find_project(self.current_pid) if editing else None
        top = tk.Toplevel(self)
        top.title("编辑产品项目" if editing else "新建产品项目")
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
        ttk.Label(body, text="产品目标", style="Muted.TLabel").grid(
            row=4, column=0, sticky="nw", pady=4)
        goal = tk.Text(body, width=42, height=4, wrap="word")
        goal.insert("1.0", (project or {}).get("goal", ""))
        goal.grid(row=4, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="新建自动套 6 项交付物、PRD / 架构小节与四道评审门。",
                  style="Muted.TLabel").grid(row=5, column=0, columnspan=2,
                                             sticky="w", pady=(6, 0))

        def save():
            name = vars_["name"].get().strip()
            if not name:
                messagebox.showwarning("产品项目", "项目名称不能为空。", parent=top)
                return
            data = {
                "name": name, "kind": "product",
                "owner": vars_["owner"].get().strip(),
                "start_date": vars_["start_date"].get().strip(),
                "due_date": vars_["due_date"].get().strip(),
                "goal": goal.get("1.0", "end").strip(),
            }
            try:
                if editing:
                    self.repo.update_project(self.current_pid, data)
                    pid = self.current_pid
                    self._log("更新产品项目", name)
                else:
                    data.update({"stage": "定义", "status": "进行中"})
                    pid = self.repo.add_project(data)
                    added = self.repo.apply_project_template(pid)
                    seeded = pp.seed_project(self.repo, pid)
                    self._log("新建产品项目", "%s；模板 %d 项、小节 %d、评审门 %d" % (
                        name, added, seeded["specs"], seeded["reviews"]))
            except Exception as e:
                messagebox.showerror("产品项目", str(e), parent=top)
                return
            top.destroy()
            self.refresh(pid)
            if not editing:
                messagebox.showinfo(
                    "产品项目",
                    "已建项目并套好交付物、PRD / 架构小节与四道评审门。\n"
                    "先写需求与目标用户，再列 BOM。", parent=self)

        bar = ttk.Frame(body)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    def _log(self, act, obj):
        try:
            self.repo.add_log(act, obj, getattr(self.window, "operator_name", "系统"),
                              self.window.role_label())
        except Exception:
            pass

    def _selected_id(self, tree):
        sel = tree.selection()
        if not sel:
            return None
        try:
            return int(tree.item(sel[0])["tags"][0])
        except (ValueError, IndexError, KeyError):
            return None

    # ---------- PRD / 架构 ----------
    def _fill_specs(self, tree, rows, kind):
        tree.delete(*tree.get_children())
        by_section = {r.get("section"): r for r in rows}
        order = list(pp.SPEC_DEFAULTS[kind])
        order += [r.get("section") for r in rows if r.get("section") not in order]
        for i, section in enumerate(order):
            row = by_section.get(section) or {}
            content = (row.get("content") or "").replace("\n", " ")
            preview = content[:90] + ("…" if len(content) > 90 else "")
            state = "已填" if content.strip() else "待补"
            tag = "green" if content.strip() else "orange"
            tags = (str(row.get("id") or 0), "zebra" if i % 2 else "", tag)
            tree.insert("", "end", tags=tags,
                        values=(section, preview or "（空，双击填写）", state))
        stat = pp.spec_stats(self.repo, self.current_pid)
        sub = stat["kinds"][kind]
        label = self.prd_summary if kind == "prd" else self.arch_summary
        label.configure(text="%s %d / %d 小节已填（%d%%）%s" % (
            sub["name"], sub["filled"], sub["total"], sub["percent"],
            "" if not sub["empty"] else "；待补 " + "、".join(sub["empty"])))

    def spec_dialog(self, kind, mode=None):
        if not self.current_pid:
            return
        editing = mode == "edit"
        row = None
        tree = self.prd_tree if kind == "prd" else self.arch_tree
        if editing:
            rid = self._selected_id(tree)
            if rid is None:
                messagebox.showinfo("产品文档", "先在表里选一个小节。", parent=self)
                return
            rows = self.specs if kind == "prd" else self.arch
            row = next((r for r in rows if r["id"] == rid), None)
            if row is None:
                return
        top = tk.Toplevel(self)
        top.title("编辑%s" % pp.SPEC_KIND_NAMES[kind] if editing
                  else "添加%s小节" % pp.SPEC_KIND_NAMES[kind])
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="小节", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", pady=4)
        section_var = tk.StringVar(value=(row or {}).get("section", ""))
        section_cb = ttk.Combobox(body, textvariable=section_var, width=30,
                                  values=list(pp.SPEC_DEFAULTS[kind]))
        section_cb.grid(row=0, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="内容", style="Muted.TLabel").grid(
            row=1, column=0, sticky="nw", pady=4)
        content = tk.Text(body, width=52, height=12, wrap="word")
        content.insert("1.0", (row or {}).get("content", ""))
        content.grid(row=1, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="写清事实与取舍；这里不替你编产品信息。",
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=2,
                                             sticky="w", pady=(4, 0))

        def save():
            section = section_var.get().strip()
            if not section:
                messagebox.showwarning("产品文档", "小节不能为空。", parent=top)
                return
            data = {"kind": kind, "section": section,
                    "content": content.get("1.0", "end").strip()}
            try:
                if editing:
                    self.repo.update_product_spec(row["id"], data)
                else:
                    self.repo.add_product_spec(self.current_pid, data)
            except Exception as e:
                messagebox.showerror("产品文档", str(e), parent=top)
                return
            self._log("更新产品文档" if editing else "添加产品文档", section)
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    def remove_spec(self, kind):
        if not self.current_pid:
            return
        tree = self.prd_tree if kind == "prd" else self.arch_tree
        rid = self._selected_id(tree)
        if rid is None:
            return
        rows = self.specs if kind == "prd" else self.arch
        row = next((r for r in rows if r["id"] == rid), None)
        if row is None:
            return
        if not messagebox.askyesno("产品文档", "删除「%s」？" % row.get("section"),
                                   parent=self):
            return
        try:
            self.repo.remove_product_spec(rid)
        except Exception as e:
            messagebox.showerror("产品文档", str(e), parent=self)
            return
        self._load_project(self.current_pid)

    def export_spec(self, kind):
        if not self.current_pid:
            return
        folder = filedialog.askdirectory(title="导出到目录", parent=self)
        if not folder:
            return
        try:
            path = pp.export_spec(self.repo, self.current_pid, kind, folder)
        except Exception as e:
            messagebox.showerror("导出", str(e), parent=self)
            return
        self._log("导出产品文档", os.path.basename(path))
        messagebox.showinfo("导出", "已导出：\n%s" % path, parent=self)
        self._load_project(self.current_pid)

    # ---------- BOM ----------
    def _fill_bom(self):
        self.bom_tree.delete(*self.bom_tree.get_children())
        for i, row in enumerate(self.bom):
            try:
                qty = float(row.get("qty") or 0)
                unit_cost = float(row.get("unit_cost") or 0)
            except (TypeError, ValueError):
                qty, unit_cost = 0, 0
            tags = (str(row["id"]), "zebra" if i % 2 else "")
            self.bom_tree.insert("", "end", tags=tags, values=(
                row.get("kind"), row.get("name"), row.get("spec"),
                "%g" % qty, row.get("unit"), "%.2f" % unit_cost,
                "%.2f" % (qty * unit_cost), row.get("source") or "未填"))
        st = pp.bom_stats(self.bom)
        self.bom_summary.configure(
            text="BOM %d 项 · 成本合计 %.2f%s" % (
                st["total"], st["cost"],
                "" if not st["missing_source"] else " · 缺来源 %d 项" % st["missing_source"]))

    def bom_dialog(self, mode=None):
        if not self.current_pid:
            return
        editing = mode == "edit"
        row = None
        if editing:
            bid = self._selected_id(self.bom_tree)
            if bid is None:
                messagebox.showinfo("BOM", "先在表里选一项。", parent=self)
                return
            row = next((r for r in self.bom if r["id"] == bid), None)
            if row is None:
                return
        top = tk.Toplevel(self)
        top.title("编辑 BOM" if editing else "添加 BOM")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        kind_var = tk.StringVar(value=(row or {}).get("kind", "物料"))
        name_var = tk.StringVar(value=(row or {}).get("name", ""))
        spec_var = tk.StringVar(value=(row or {}).get("spec", ""))
        qty_var = tk.StringVar(value=str((row or {}).get("qty", "1")))
        unit_var = tk.StringVar(value=(row or {}).get("unit", "件"))
        cost_var = tk.StringVar(value=str((row or {}).get("unit_cost", "0")))
        source_var = tk.StringVar(value=(row or {}).get("source", ""))
        fields = [
            ("类型", "kind", kind_var, list(pp.BOM_KINDS), 18),
            ("名称", "name", name_var, None, 28),
            ("规格", "spec", spec_var, None, 28),
            ("数量", "qty", qty_var, None, 10),
            ("单位", "unit", unit_var, None, 10),
            ("单价", "cost", cost_var, None, 10),
            ("来源", "source", source_var, None, 24),
        ]
        for i, (label, key, var, values, width) in enumerate(fields):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(
                row=i, column=0, sticky="w", pady=3)
            if values:
                widget = ttk.Combobox(body, textvariable=var, values=values,
                                      state="readonly", width=width)
            else:
                widget = ttk.Entry(body, textvariable=var, width=width)
            widget.grid(row=i, column=1, sticky="we", padx=(8, 0), pady=3)
        ttk.Label(body, text="备注", style="Muted.TLabel").grid(
            row=7, column=0, sticky="nw", pady=3)
        note = tk.Text(body, width=34, height=3, wrap="word")
        note.insert("1.0", (row or {}).get("note", ""))
        note.grid(row=7, column=1, sticky="we", padx=(8, 0), pady=3)
        ttk.Label(body, text="数量必须大于 0；单价可为 0，不能为负。",
                  style="Muted.TLabel").grid(row=8, column=0, columnspan=2,
                                             sticky="w", pady=(4, 0))

        def save():
            if not name_var.get().strip():
                messagebox.showwarning("BOM", "名称不能为空。", parent=top)
                return
            data = {"kind": kind_var.get(), "name": name_var.get().strip(),
                    "spec": spec_var.get().strip(), "qty": qty_var.get().strip(),
                    "unit": unit_var.get().strip(), "unit_cost": cost_var.get().strip(),
                    "source": source_var.get().strip(),
                    "note": note.get("1.0", "end").strip()}
            try:
                if editing:
                    self.repo.update_product_bom(row["id"], data)
                else:
                    self.repo.add_product_bom(self.current_pid, data)
            except Exception as e:
                messagebox.showerror("BOM", str(e), parent=top)
                return
            self._log("更新 BOM" if editing else "添加 BOM", data["name"])
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=9, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    def remove_bom(self):
        if not self.current_pid:
            return
        bid = self._selected_id(self.bom_tree)
        if bid is None:
            return
        row = next((r for r in self.bom if r["id"] == bid), None)
        if row is None:
            return
        if not messagebox.askyesno("BOM", "删除「%s」？" % row.get("name"), parent=self):
            return
        try:
            self.repo.remove_product_bom(bid)
        except Exception as e:
            messagebox.showerror("BOM", str(e), parent=self)
            return
        self._load_project(self.current_pid)

    def export_bom(self):
        if not self.current_pid:
            return
        folder = filedialog.askdirectory(title="导出 BOM 到目录", parent=self)
        if not folder:
            return
        try:
            path = pp.export_bom(self.repo, self.current_pid, folder)
        except Exception as e:
            messagebox.showerror("导出 BOM", str(e), parent=self)
            return
        self._log("导出 BOM", os.path.basename(path))
        messagebox.showinfo("导出 BOM", "已导出：\n%s" % path, parent=self)
        self._load_project(self.current_pid)

    # ---------- 原型 ----------
    def _fill_protos(self):
        self.proto_tree.delete(*self.proto_tree.get_children())
        for i, row in enumerate(self.protos):
            note = pp.proto_note(row)
            tag = "green" if row.get("status") in ("可用", "已冻结") else "orange"
            if note == "路径不存在":
                tag = "red"
            self.proto_tree.insert("", "end",
                                   tags=(str(row["id"]), "zebra" if i % 2 else "", tag),
                                   values=(row.get("name"), row.get("version") or "-",
                                           row.get("status"), row.get("path") or "未填",
                                           (row.get("note") or "") + " · " + note))
        st = pp.proto_stats(self.protos)
        self.proto_summary.configure(
            text="原型 %d 个 · 可用/冻结 %d · 待做/进行中 %d · 未填路径 %d · 路径失效 %d" % (
                st["total"], st["usable"], st["pending"],
                st["missing_path"], st["missing_file"]))

    def proto_dialog(self, mode=None):
        if not self.current_pid:
            return
        editing = mode == "edit"
        row = None
        if editing:
            rid = self._selected_id(self.proto_tree)
            if rid is None:
                messagebox.showinfo("原型", "先在表里选一个原型。", parent=self)
                return
            row = next((r for r in self.protos if r["id"] == rid), None)
            if row is None:
                return
        top = tk.Toplevel(self)
        top.title("编辑原型" if editing else "添加原型")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        name_var = tk.StringVar(value=(row or {}).get("name", ""))
        version_var = tk.StringVar(value=(row or {}).get("version", ""))
        status_var = tk.StringVar(value=(row or {}).get("status", "待做"))
        path_var = tk.StringVar(value=(row or {}).get("path", ""))
        for i, (label, var, width) in enumerate((
                ("原型名称", name_var, 32), ("版本", version_var, 16),
                ("路径", path_var, 40))):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(
                row=i, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=var, width=width).grid(
                row=i, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="状态", style="Muted.TLabel").grid(
            row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(body, textvariable=status_var, values=list(pp.PROTO_STATUS),
                     state="readonly", width=16).grid(
            row=3, column=1, sticky="w", padx=(8, 0), pady=4)
        ttk.Button(body, text="选文件…", style="Ghost.TButton",
                   command=lambda: self._pick_into(path_var, top)).grid(
            row=2, column=2, padx=(6, 0))
        ttk.Label(body, text="路径可填原型文件、设计稿或说明文档；不打开外部编辑器。",
                  style="Muted.TLabel").grid(row=4, column=0, columnspan=2,
                                             sticky="w", pady=(4, 0))
        ttk.Label(body, text="备注", style="Muted.TLabel").grid(
            row=5, column=0, sticky="nw", pady=4)
        note = tk.Text(body, width=36, height=3, wrap="word")
        note.insert("1.0", (row or {}).get("note", ""))
        note.grid(row=5, column=1, sticky="we", padx=(8, 0), pady=4)

        def save():
            if not name_var.get().strip():
                messagebox.showwarning("原型", "名称不能为空。", parent=top)
                return
            data = {"name": name_var.get().strip(),
                    "version": version_var.get().strip(),
                    "status": status_var.get(), "path": path_var.get().strip(),
                    "note": note.get("1.0", "end").strip()}
            try:
                if editing:
                    self.repo.update_product_proto(row["id"], data)
                else:
                    self.repo.add_product_proto(self.current_pid, data)
            except Exception as e:
                messagebox.showerror("原型", str(e), parent=top)
                return
            self._log("更新原型" if editing else "添加原型", data["name"])
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    def _pick_into(self, var, parent):
        path = filedialog.askopenfilename(title="选择原型文件", parent=parent)
        if path:
            var.set(path)

    def set_proto_status(self, status):
        rid = self._selected_id(self.proto_tree)
        if rid is None:
            return
        try:
            self.repo.update_product_proto(rid, {"status": status})
        except Exception as e:
            messagebox.showerror("原型", str(e), parent=self)
            return
        self._load_project(self.current_pid)

    def open_proto(self):
        rid = self._selected_id(self.proto_tree)
        if rid is None:
            return
        row = next((r for r in self.protos if r["id"] == rid), None)
        if row is None:
            return
        path = (row.get("path") or "").strip()
        if not path:
            messagebox.showinfo("原型", "这条原型没有填路径。", parent=self)
            return
        if not os.path.exists(path):
            messagebox.showwarning("原型", "路径不存在：\n%s" % path, parent=self)
            return
        try:
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("打开原型", str(e), parent=self)

    def remove_proto(self):
        rid = self._selected_id(self.proto_tree)
        if rid is None:
            return
        row = next((r for r in self.protos if r["id"] == rid), None)
        if row is None:
            return
        if not messagebox.askyesno("原型", "删除「%s」？" % row.get("name"), parent=self):
            return
        try:
            self.repo.remove_product_proto(rid)
        except Exception as e:
            messagebox.showerror("原型", str(e), parent=self)
            return
        self._load_project(self.current_pid)

    # ---------- 测试 ----------
    def _fill_tests(self):
        self.test_tree.delete(*self.test_tree.get_children())
        for i, row in enumerate(self.tests):
            result = row.get("result") or "未测"
            tag = {"通过": "green", "不通过": "red", "阻塞": "red"}.get(result, "orange")
            self.test_tree.insert("", "end",
                                  tags=(str(row["id"]), "zebra" if i % 2 else "", tag),
                                  values=(row.get("name"), row.get("severity"),
                                          result, row.get("method"),
                                          row.get("issue") or row.get("note")))
        st = pp.test_stats(self.tests)
        self.test_summary.configure(
            text="测试 %d 项 · 通过 %d · 不通过 %d · 阻塞 %d · 未测 %d · 通过率 %d%%" % (
                st["total"], st["passed"], st["failed"], st["blocked"],
                st["untested"], st["pass_rate"]))

    def test_dialog(self, mode=None):
        if not self.current_pid:
            return
        editing = mode == "edit"
        row = None
        if editing:
            rid = self._selected_id(self.test_tree)
            if rid is None:
                messagebox.showinfo("测试", "先在表里选一项。", parent=self)
                return
            row = next((r for r in self.tests if r["id"] == rid), None)
            if row is None:
                return
        top = tk.Toplevel(self)
        top.title("编辑测试项" if editing else "添加测试项")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        name_var = tk.StringVar(value=(row or {}).get("name", ""))
        method_var = tk.StringVar(value=(row or {}).get("method", ""))
        expected_var = tk.StringVar(value=(row or {}).get("expected", ""))
        result_var = tk.StringVar(value=(row or {}).get("result", "未测"))
        severity_var = tk.StringVar(value=(row or {}).get("severity", "中"))
        for i, (label, var, values, width) in enumerate((
                ("测试项", name_var, None, 34), ("方法", method_var, None, 34),
                ("预期", expected_var, None, 34))):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(
                row=i, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=var, width=width).grid(
                row=i, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="结果", style="Muted.TLabel").grid(
            row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(body, textvariable=result_var, values=list(pp.TEST_RESULTS),
                     state="readonly", width=14).grid(
            row=3, column=1, sticky="w", padx=(8, 0), pady=4)
        ttk.Label(body, text="级别", style="Muted.TLabel").grid(
            row=4, column=0, sticky="w", pady=4)
        ttk.Combobox(body, textvariable=severity_var,
                     values=list(pp.TEST_SEVERITIES), state="readonly", width=8).grid(
            row=4, column=1, sticky="w", padx=(8, 0), pady=4)
        ttk.Label(body, text="问题 / 说明", style="Muted.TLabel").grid(
            row=5, column=0, sticky="nw", pady=4)
        issue = tk.Text(body, width=36, height=3, wrap="word")
        issue.insert("1.0", (row or {}).get("issue", ""))
        issue.grid(row=5, column=1, sticky="we", padx=(8, 0), pady=4)

        def save():
            if not name_var.get().strip():
                messagebox.showwarning("测试", "测试项不能为空。", parent=top)
                return
            data = {"name": name_var.get().strip(),
                    "method": method_var.get().strip(),
                    "expected": expected_var.get().strip(),
                    "result": result_var.get(), "severity": severity_var.get(),
                    "issue": issue.get("1.0", "end").strip()}
            try:
                if editing:
                    self.repo.update_product_test(row["id"], data)
                else:
                    self.repo.add_product_test(self.current_pid, data)
            except Exception as e:
                messagebox.showerror("测试", str(e), parent=top)
                return
            self._log("更新测试项" if editing else "添加测试项", data["name"])
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    def set_test_result(self, result):
        rid = self._selected_id(self.test_tree)
        if rid is None:
            return
        try:
            self.repo.update_product_test(rid, {"result": result})
        except Exception as e:
            messagebox.showerror("测试", str(e), parent=self)
            return
        self._load_project(self.current_pid)

    def remove_test(self):
        rid = self._selected_id(self.test_tree)
        if rid is None:
            return
        row = next((r for r in self.tests if r["id"] == rid), None)
        if row is None:
            return
        if not messagebox.askyesno("测试", "删除「%s」？" % row.get("name"), parent=self):
            return
        try:
            self.repo.remove_product_test(rid)
        except Exception as e:
            messagebox.showerror("测试", str(e), parent=self)
            return
        self._load_project(self.current_pid)

    # ---------- 发布包 ----------
    def refresh_readiness(self):
        if not self.current_pid:
            return None
        try:
            rr = pp.readiness(self.repo, self.current_pid)
        except Exception as e:
            self.readiness_summary.configure(text=str(e))
            return None
        self.check_tree.delete(*self.check_tree.get_children())
        for i, item in enumerate(rr["items"]):
            tag = "green" if item["ok"] else "red"
            self.check_tree.insert("", "end",
                                   tags=("chk-%d" % i, "zebra" if i % 2 else "", tag),
                                   values=(item["name"],
                                           "通过" if item["ok"] else "未通过",
                                           item["note"]))
        self.readiness_summary.configure(
            text="%s%s" % (rr["summary"],
                           " 可以出包。" if rr["ok"] else " 仍可出包，但质量门会记为不通过。"))
        return rr

    def add_release_files(self):
        paths = filedialog.askopenfilenames(title="选择发布包文件", parent=self)
        for path in paths or []:
            if path and path not in self.release_files:
                self.release_files.append(path)
        self._refresh_release_list()

    def remove_release_files(self):
        idx = self.release_list.curselection()
        if idx:
            del self.release_files[idx[0]]
        self._refresh_release_list()

    def clear_release_files(self):
        self.release_files = []
        self._refresh_release_list()

    def _refresh_release_list(self):
        self.release_list.delete(0, "end")
        for path in self.release_files:
            try:
                size = pp._human_size(os.path.getsize(path))
            except OSError:
                size = "?"
            self.release_list.insert("end", "%s  ·  %s" % (os.path.basename(path), size))

    def pick_release_out(self):
        folder = filedialog.askdirectory(title="选择发布包输出目录", parent=self)
        if folder:
            self.release_out_var.set(folder)

    def make_release(self):
        if not self.current_pid:
            return
        if not self.release_files:
            messagebox.showinfo("发布包", "先添加至少一个包内文件。", parent=self)
            return
        version = self.release_version_var.get().strip()
        if not version:
            messagebox.showinfo("发布包", "先填版本号。", parent=self)
            return
        outdir = self.release_out_var.get().strip()
        if not outdir:
            messagebox.showinfo("发布包", "先选输出目录。", parent=self)
            return
        try:
            result = pp.make_release_package(
                self.repo, self.current_pid, self.release_files, outdir,
                version=version, notes=self.release_notes.get("1.0", "end").strip(),
                include_zip=self.release_zip_var.get(),
                operator=getattr(self.window, "operator_name", "系统"))
        except Exception as e:
            messagebox.showerror("发布包", str(e), parent=self)
            return
        self.last_release = result
        self.btn_open_release.configure(state="normal")
        self.release_summary.configure(text=result["summary"])
        self._log("生成发布包", "%s · %s" % (version, result["summary"]))
        messagebox.showinfo(
            "发布包",
            "%s\n目录：%s%s" % (
                result["summary"], result["root"],
                ("\nZIP：%s" % result["zip"]) if result["zip"] else ""),
            parent=self)
        self._load_project(self.current_pid)

    def open_release(self):
        if not self.last_release:
            return
        path = self.last_release.get("zip") or self.last_release.get("root")
        if not path or not os.path.exists(path):
            messagebox.showwarning("发布包", "输出不存在，可能已被移动。", parent=self)
            return
        try:
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("打开发布包", str(e), parent=self)

    # ---------- 评审 / 路演 ----------
    def _fill_reviews(self):
        self.review_tree.delete(*self.review_tree.get_children())
        for i, row in enumerate(self.reviews):
            conclusion = row.get("conclusion") or "待评审"
            tag = "green" if conclusion in ("通过", "有条件通过") else (
                "red" if conclusion == "驳回" else "orange")
            self.review_tree.insert("", "end",
                                    tags=(str(row["id"]), "zebra" if i % 2 else "", tag),
                                    values=(row.get("gate"), conclusion,
                                            row.get("reviewer") or "未填",
                                            row.get("date") or "未定",
                                            row.get("note")))
        stat = pp.review_stats(self.reviews)
        self.review_summary.configure(
            text="%s%s" % (pp.review_summary(self.reviews),
                           " 评审门已齐。" if stat["ready"] else " 尚未齐。"))
        self.roadshow_label.configure(
            text=("路演提纲：%s" % self.last_roadshow) if self.last_roadshow
            else "路演提纲从 PRD / BOM / 测试 / 评审结论生成。")

    def review_dialog(self, mode=None):
        if not self.current_pid:
            return
        editing = mode == "edit"
        row = None
        if editing:
            rid = self._selected_id(self.review_tree)
            if rid is None:
                messagebox.showinfo("评审门", "先在表里选一道评审门。", parent=self)
                return
            row = next((r for r in self.reviews if r["id"] == rid), None)
            if row is None:
                return
        top = tk.Toplevel(self)
        top.title("填写评审结论" if editing else "新增评审门")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        gate_var = tk.StringVar(value=(row or {}).get("gate", pp.REVIEW_GATES[0]))
        conclusion_var = tk.StringVar(
            value=(row or {}).get("conclusion", "待评审"))
        reviewer_var = tk.StringVar(value=(row or {}).get("reviewer", ""))
        date_var = tk.StringVar(value=(row or {}).get("date", ""))
        ttk.Label(body, text="评审门", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", pady=4)
        if editing:
            ttk.Combobox(body, textvariable=gate_var, values=list(pp.REVIEW_GATES),
                         state="readonly", width=18).grid(
                row=0, column=1, sticky="w", padx=(8, 0), pady=4)
        else:
            ttk.Combobox(body, textvariable=gate_var, values=list(pp.REVIEW_GATES),
                         state="readonly", width=18).grid(
                row=0, column=1, sticky="w", padx=(8, 0), pady=4)
        ttk.Label(body, text="结论", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(body, textvariable=conclusion_var,
                     values=list(PRODUCT_REVIEW_CONCLUSIONS),
                     state="readonly", width=18).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=4)
        ttk.Label(body, text="评审人", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", pady=4)
        ttk.Entry(body, textvariable=reviewer_var, width=24).grid(
            row=2, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="日期", style="Muted.TLabel").grid(
            row=3, column=0, sticky="w", pady=4)
        ttk.Entry(body, textvariable=date_var, width=18).grid(
            row=3, column=1, sticky="w", padx=(8, 0), pady=4)
        ttk.Label(body, text="意见", style="Muted.TLabel").grid(
            row=4, column=0, sticky="nw", pady=4)
        note = tk.Text(body, width=36, height=4, wrap="word")
        note.insert("1.0", (row or {}).get("note", ""))
        note.grid(row=4, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="日期写 2026-11-28；结论会同步到项目质量门。",
                  style="Muted.TLabel").grid(row=5, column=0, columnspan=2,
                                             sticky="w", pady=(4, 0))

        def save():
            data = {"gate": gate_var.get(), "conclusion": conclusion_var.get(),
                    "reviewer": reviewer_var.get().strip(),
                    "date": date_var.get().strip(),
                    "note": note.get("1.0", "end").strip()}
            try:
                if editing:
                    self.repo.update_product_review(row["id"], data)
                else:
                    self.repo.add_product_review(self.current_pid, data)
                pp.sync_review_gate(self.repo, self.current_pid, data["gate"],
                                    data["conclusion"], note=data["note"],
                                    reviewer=data["reviewer"])
            except Exception as e:
                messagebox.showerror("评审门", str(e), parent=top)
                return
            self._log("更新评审门" if editing else "添加评审门",
                      "%s · %s" % (data["gate"], data["conclusion"]))
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    def remove_review(self):
        rid = self._selected_id(self.review_tree)
        if rid is None:
            return
        row = next((r for r in self.reviews if r["id"] == rid), None)
        if row is None:
            return
        if not messagebox.askyesno("评审门", "删除「%s」？" % row.get("gate"), parent=self):
            return
        try:
            self.repo.remove_product_review(rid)
        except Exception as e:
            messagebox.showerror("评审门", str(e), parent=self)
            return
        self._load_project(self.current_pid)

    def export_roadshow(self):
        if not self.current_pid:
            return
        folder = filedialog.askdirectory(title="导出路演提纲到目录", parent=self)
        if not folder:
            return
        try:
            path = pp.export_roadshow(
                self.repo, self.current_pid, folder, release=self.last_release,
                operator=getattr(self.window, "operator_name", "系统"))
        except Exception as e:
            messagebox.showerror("路演提纲", str(e), parent=self)
            return
        self.last_roadshow = path
        self._log("导出路演提纲", os.path.basename(path))
        messagebox.showinfo("路演提纲", "已导出：\n%s" % path, parent=self)
        self._load_project(self.current_pid)

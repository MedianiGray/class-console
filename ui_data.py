# -*- coding: utf-8 -*-
"""v0.36 数据工作台：CSV 导入、字段处理、清洗图表与报告包。

界面只编排本地能力：导入、画像、清洗、图表、报告包与质量门。不替用户
解释数据结论，也不编字段含义。
"""

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import datalab as dl
from database import DATA_FIELD_ACTIONS, DATA_NOTE_SECTIONS
from theme import C, FONT


class DataView(ttk.Frame):
    PERM = "data:run"
    FIELD_COLS = ("name", "dtype", "missing", "unique", "action", "target")
    FIELD_HEADS = {"name": "字段", "dtype": "类型", "missing": "缺失",
                   "unique": "唯一值", "action": "处理", "target": "输出名"}
    FIELD_WIDTHS = {"name": 180, "dtype": 70, "missing": 56,
                    "unique": 62, "action": 66, "target": 170}
    NOTE_COLS = ("section", "content", "state")
    NOTE_HEADS = {"section": "小节", "content": "内容", "state": "状态"}
    NOTE_WIDTHS = {"section": 100, "content": 290, "state": 56}
    CHK_COLS = ("name", "ok", "note")
    CHK_HEADS = {"name": "检查项", "ok": "结论", "note": "说明"}
    CHK_WIDTHS = {"name": 120, "ok": 58, "note": 270}

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self.current_pid = None
        self.project_map = {}
        self.source = {}
        self.fields = []
        self.notes = []
        self.table = None
        self.cat_items = []
        self.num_stats = {}
        self.last_report = None
        self.buttons = []
        self._loaded_pid = None
        self._build()

    def _build(self):
        style = ttk.Style(self)
        style.configure("Section.TLabel", font=(FONT, 10, "bold"),
                        background=C["bg"], foreground=C["text"])
        head = ttk.Frame(self)
        head.pack(fill="x", padx=18, pady=(4, 6))
        ttk.Label(head, text="数据工作台", style="H2.TLabel").pack(side="left")
        self.summary = ttk.Label(head, text="", style="Muted.TLabel")
        self.summary.pack(side="right")

        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(0, 8))
        ttk.Label(top, text="数据项目", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.project_var = tk.StringVar(value="")
        self.project_cb = ttk.Combobox(top, textvariable=self.project_var,
                                       state="readonly", width=44)
        self.project_cb.grid(row=0, column=1, sticky="w", padx=(8, 8))
        self.project_cb.bind("<<ComboboxSelected>>", lambda e: self._on_project())
        self.btn_new = ttk.Button(top, text="新建数据项目", style="Accent.TButton",
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
        self.tab_source = ttk.Frame(self.nb)
        self.tab_report = ttk.Frame(self.nb)
        self.nb.add(self.tab_source, text="数据源 / 清洗")
        self.nb.add(self.tab_report, text="图表 / 报告包")
        self._build_source()
        self._build_report()
        self.after(50, self.refresh)

    def _mk_tree(self, parent, cols, heads, widths, height=8, expand=True):
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both" if expand else "x", expand=expand,
                  padx=14, pady=(6, 0))
        tree = ttk.Treeview(wrap, columns=cols, show="headings",
                            selectmode="browse", height=height)
        for c in cols:
            tree.heading(c, text=heads[c], anchor="w")
            tree.column(c, width=widths[c], anchor="w",
                        stretch=(c in ("content", "note", "target") or c == cols[-1]))
        tree.tag_configure("zebra", background=C["zebra"])
        tree.tag_configure("green", foreground=C["green"])
        tree.tag_configure("orange", foreground=C["orange"])
        tree.tag_configure("red", foreground=C["red"])
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ysb.set)
        tree.pack(side="left", fill="both", expand=expand)
        ysb.pack(side="right", fill="y")
        return tree

    def _button(self, parent, text, cmd, style="Ghost.TButton", track=True):
        btn = ttk.Button(parent, text=text, style=style, command=cmd)
        btn.pack(side="left", padx=(0, 6))
        if track:
            self.buttons.append(btn)
        return btn

    # ---------- 数据源 / 清洗 ----------
    def _build_source(self):
        info = ttk.Frame(self.tab_source)
        info.pack(fill="x", padx=14, pady=(8, 0))
        ttk.Label(info, text="数据源", style="Section.TLabel").pack(side="left")
        self.source_label = ttk.Label(info, text="尚未导入 CSV", style="Muted.TLabel")
        self.source_label.pack(side="left", padx=(10, 0))
        self.source_note = ttk.Label(info, text="", style="Muted.TLabel")
        self.source_note.pack(side="right")

        options = ttk.Frame(self.tab_source)
        options.pack(fill="x", padx=14, pady=(6, 0))
        self.trim_var = tk.BooleanVar(value=True)
        self.dedupe_var = tk.BooleanVar(value=True)
        self.guard_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="去首尾空格", variable=self.trim_var).pack(side="left")
        ttk.Checkbutton(options, text="整行去重", variable=self.dedupe_var).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(options, text="数值非法置空", variable=self.guard_var).pack(side="left", padx=(12, 0))
        self._button(options, "保存清洗选项", self.save_options)
        ttk.Label(options, text="原文件只读，清洗只作用在输出副本。",
                  style="Muted.TLabel").pack(side="right")

        self.field_tree = self._mk_tree(self.tab_source, self.FIELD_COLS,
                                        self.FIELD_HEADS, self.FIELD_WIDTHS)
        self.field_tree.bind("<Double-1>", lambda e: self.field_dialog())
        bar = ttk.Frame(self.tab_source)
        bar.pack(side="bottom", fill="x", padx=14, pady=(6, 10))
        self._button(bar, "导入 CSV…", self.import_csv, "Accent.TButton")
        self._button(bar, "重算字段画像", self.reimport_profile)
        self._button(bar, "字段处理 / 改名", self.field_dialog)
        self._button(bar, "恢复为全部保留", self.reset_fields)
        self.footer = ttk.Label(bar, text="", style="Muted.TLabel")
        self.footer.pack(side="right")

    # ---------- 图表 / 报告 ----------
    def _build_report(self):
        top = ttk.Frame(self.tab_report)
        top.pack(fill="x", padx=14, pady=(8, 0))
        ttk.Label(top, text="分类字段", style="Muted.TLabel").pack(side="left")
        self.cat_var = tk.StringVar(value="")
        self.cat_cb = ttk.Combobox(top, textvariable=self.cat_var, state="readonly", width=18)
        self.cat_cb.pack(side="left", padx=(6, 12))
        ttk.Label(top, text="数值字段", style="Muted.TLabel").pack(side="left")
        self.num_var = tk.StringVar(value="")
        self.num_cb = ttk.Combobox(top, textvariable=self.num_var, state="readonly", width=18)
        self.num_cb.pack(side="left", padx=(6, 12))
        ttk.Button(top, text="刷新预览", style="Ghost.TButton",
                   command=self.refresh_preview).pack(side="left")

        body = ttk.Frame(self.tab_report)
        body.pack(fill="both", expand=True, padx=14, pady=(6, 0))
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        self.cat_canvas = tk.Canvas(left, height=160, bg=C["card"],
                                    highlightthickness=1,
                                    highlightbackground=C["line"])
        self.cat_canvas.pack(fill="x", pady=(0, 6))
        self.num_canvas = tk.Canvas(left, height=160, bg=C["card"],
                                    highlightthickness=1,
                                    highlightbackground=C["line"])
        self.num_canvas.pack(fill="x")
        self.preview_note = ttk.Label(left, text="选择字段后刷新预览。", style="Muted.TLabel")
        self.preview_note.pack(anchor="w", pady=(4, 0))

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))
        self.note_tree = self._mk_tree(right, self.NOTE_COLS,
                                       self.NOTE_HEADS, self.NOTE_WIDTHS,
                                       height=3, expand=False)
        self.note_tree.bind("<Double-1>", lambda e: self.note_dialog())
        nbar = ttk.Frame(right)
        nbar.pack(fill="x", pady=(4, 0))
        ttk.Button(nbar, text="编辑说明", style="Ghost.TButton",
                   command=self.note_dialog).pack(side="left", padx=(0, 6))

        self.chk_tree = self._mk_tree(right, self.CHK_COLS,
                                      self.CHK_HEADS, self.CHK_WIDTHS,
                                      height=5, expand=False)
        self.chk_summary = ttk.Label(right, text="", style="Muted.TLabel")
        self.chk_summary.pack(anchor="w", pady=(2, 0))

        bottom = ttk.Frame(self.tab_report)
        bottom.pack(side="bottom", fill="x", padx=14, pady=(6, 10), before=body)
        ttk.Label(bottom, text="输出目录", style="Muted.TLabel").pack(side="left")
        self.out_var = tk.StringVar(value=str(Path.home() / "Documents" / "班级操作台交付"))
        ttk.Entry(bottom, textvariable=self.out_var, width=38).pack(side="left", padx=(6, 6))
        ttk.Button(bottom, text="选…", style="Ghost.TButton",
                   command=self.pick_out).pack(side="left", padx=(0, 8))
        self.btn_make = ttk.Button(bottom, text="生成数据报告包", style="Accent.TButton",
                                   command=self.make_package)
        self.btn_make.pack(side="left", padx=(0, 6))
        self.btn_open = ttk.Button(bottom, text="打开报告", style="Ghost.TButton",
                                   command=self.open_report, state="disabled")
        self.btn_open.pack(side="left", padx=(0, 6))
        ttk.Button(bottom, text="打开目录", style="Ghost.TButton",
                   command=self.open_folder).pack(side="left")

    # ---------- 项目 ----------
    def refresh(self, select_pid=None):
        try:
            projects = self.repo.list_projects("data")
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
            self.summary.configure(text="还没有数据项目")
            self.project_hint.configure(text="先新建数据项目，再导入 CSV；报告包会写回项目记录。")
            return
        label = [k for k, v in self.project_map.items() if v == wanted][0]
        self.project_var.set(label)
        self.current_pid = wanted
        self._load_project(wanted)

    def _on_project(self):
        self.current_pid = self.project_map.get(self.project_var.get())
        self._load_project(self.current_pid)

    def _load_project(self, pid):
        if pid != self._loaded_pid:
            self.last_report = None
            self.btn_open.configure(state="disabled")
        self._loaded_pid = pid
        state = "normal" if pid else "disabled"
        for btn in self.buttons + [self.btn_make, self.btn_open]:
            try:
                btn.configure(state=state)
            except tk.TclError:
                pass
        self.field_tree.delete(*self.field_tree.get_children())
        self.note_tree.delete(*self.note_tree.get_children())
        self.chk_tree.delete(*self.chk_tree.get_children())
        self.cat_items, self.num_stats, self.table = [], {}, None
        self.cat_canvas.delete("all")
        self.num_canvas.delete("all")
        if pid is None:
            self.source = {}
            self.fields, self.notes = [], []
            self.source_label.configure(text="尚未导入 CSV")
            self.source_note.configure(text="")
            self.footer.configure(text="")
            self.chk_summary.configure(text="")
            self.btn_open.configure(state="disabled")
            self.preview_note.configure(text="选择字段后刷新预览。")
            return
        project = self.repo.find_project(pid)
        if project is None:
            return
        self.source = self.repo.list_data_source(pid) or {}
        self.fields = self.repo.list_data_fields(pid)
        self.notes = self.repo.list_data_notes(pid)
        self.trim_var.set(bool(self.source.get("trim", 1)))
        self.dedupe_var.set(bool(self.source.get("dedupe", 1)))
        self.guard_var.set(bool(self.source.get("numeric_guard", 1)))
        self._fill_fields()
        self._fill_notes()
        self._refresh_readiness()
        self._fill_choices()
        self._load_table()
        self.summary.configure(text="%d 行 × %d 列 · %d 字段 · 报告包可导出" % (
            int(self.source.get("rows") or 0), int(self.source.get("cols") or 0),
            len(self.fields)) if self.source else "尚未导入数据源")
        self.source_label.configure(
            text=("%s · %s · %d 行 × %d 列" % (
                self.source.get("name") or "数据源",
                self.source.get("encoding") or "UTF-8",
                int(self.source.get("rows") or 0), int(self.source.get("cols") or 0))
            if self.source else "尚未导入 CSV"))
        self.source_note.configure(
            text=("原文件：%s" % self.source.get("path", "")) if self.source else "")
        self.project_hint.configure(
            text="%s · %s · 数据源 %s" % (
                project.get("stage"), project.get("status"),
                "已导入" if self.source else "待导入"))
        self.after(80, self.refresh_preview)

    def _fill_fields(self):
        self.field_tree.delete(*self.field_tree.get_children())
        for i, f in enumerate(self.fields):
            action = f.get("action") or "保留"
            tag = "orange" if action == "剔除" else ("green" if f.get("target") else "")
            self.field_tree.insert("", "end",
                                   tags=(str(f["id"]), "zebra" if i % 2 else "", tag),
                                   values=(f.get("name"), f.get("dtype"),
                                           f.get("missing"), f.get("unique_n"),
                                           action, f.get("target")))
        self.footer.configure(text="%d 个字段；双击一行改处理方式或输出名。" % len(self.fields))

    def _fill_notes(self):
        self.note_tree.delete(*self.note_tree.get_children())
        by_section = {n.get("section"): n for n in self.notes}
        for i, section in enumerate(DATA_NOTE_SECTIONS):
            row = by_section.get(section) or {}
            content = (row.get("content") or "").replace("\n", " ")
            preview = content[:80] + ("…" if len(content) > 80 else "")
            state = "已填" if content.strip() else "待补"
            self.note_tree.insert("", "end",
                                  tags=(str(row.get("id") or 0), "zebra" if i % 2 else "",
                                        "green" if content.strip() else "orange"),
                                  values=(section, preview or "（空，双击填写）", state))

    def _refresh_readiness(self):
        self.chk_tree.delete(*self.chk_tree.get_children())
        if not self.current_pid:
            self.chk_summary.configure(text="")
            return
        ready = dl.readiness(self.repo, self.current_pid)
        for i, (name, ok, note) in enumerate(ready["checks"]):
            self.chk_tree.insert("", "end",
                                 tags=(str(i), "zebra" if i % 2 else "",
                                       "green" if ok else "orange"),
                                 values=(name, "通过" if ok else "待补", note))
        self.chk_summary.configure(
            text="可以生成报告包。" if ready["ok"] else
            "还有 %d 项待补：%s" % (len(ready["failed"]), "；".join(ready["failed"])))

    # ---------- 字段 ----------
    def _selected_id(self, tree):
        sel = tree.selection()
        if not sel:
            return None
        try:
            return int(tree.item(sel[0])["tags"][0])
        except (ValueError, IndexError, KeyError):
            return None

    def _log(self, act, obj):
        try:
            self.repo.add_log(act, obj, getattr(self.window, "operator_name", "系统"),
                              self.window.role_label())
        except Exception:
            pass

    def import_csv(self):
        if not self.current_pid:
            return
        path = filedialog.askopenfilename(
            title="选择 CSV 数据源",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")], parent=self)
        if not path:
            return
        try:
            dl.seed_data(self.repo, self.current_pid)
            loaded = dl.read_table(path)
            prof = dl.profile(loaded["headers"], loaded["rows"])
            fields = [{"name": f["name"], "dtype": f["dtype"],
                       "missing": f["missing"], "unique_n": f["unique_n"],
                       "action": "保留", "target": "", "note": ""}
                      for f in prof["fields"]]
            self.repo.set_data_source(self.current_pid, {
                "name": os.path.basename(path), "path": path,
                "encoding": loaded["encoding"], "rows": len(loaded["rows"]),
                "cols": len(loaded["headers"]), "trim": True, "dedupe": True,
                "numeric_guard": True, "note": ""}, fields)
        except Exception as e:
            messagebox.showerror("导入 CSV", str(e), parent=self)
            return
        self._log("导入数据源", os.path.basename(path))
        self._load_project(self.current_pid)
        messagebox.showinfo(
            "导入 CSV",
            "已识别 %d 行 × %d 列，编码 %s。\n下一步：核对字段处理，再生成报告包。" % (
                len(loaded["rows"]), len(loaded["headers"]), loaded["encoding"]),
            parent=self)

    def reimport_profile(self):
        if not self.current_pid or not self.source:
            return
        path = self.source.get("path")
        if not path or not os.path.exists(path):
            messagebox.showwarning("字段画像", "原文件已不在原路径。", parent=self)
            return
        try:
            loaded = dl.read_table(path)
            prof = dl.profile(loaded["headers"], loaded["rows"])
        except Exception as e:
            messagebox.showerror("字段画像", str(e), parent=self)
            return
        old = {f["name"]: f for f in self.fields}
        fields = []
        for f in prof["fields"]:
            prev = old.get(f["name"], {})
            fields.append({"name": f["name"], "dtype": f["dtype"],
                           "missing": f["missing"], "unique_n": f["unique_n"],
                           "action": prev.get("action") or "保留",
                           "target": prev.get("target") or "",
                           "note": prev.get("note") or ""})
        try:
            self.repo.set_data_source(self.current_pid, dict(self.source, rows=len(loaded["rows"]),
                                                             cols=len(loaded["headers"]),
                                                             encoding=loaded["encoding"]), fields)
        except Exception as e:
            messagebox.showerror("字段画像", str(e), parent=self)
            return
        self._load_project(self.current_pid)

    def field_dialog(self):
        rid = self._selected_id(self.field_tree)
        if rid is None:
            messagebox.showinfo("字段处理", "先在表里选一个字段。", parent=self)
            return
        row = next((f for f in self.fields if f["id"] == rid), None)
        if row is None:
            return
        top = tk.Toplevel(self)
        top.title("字段处理 · %s" % row.get("name"))
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="字段", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(body, text="%s（%s）" % (row.get("name"), row.get("dtype")),
                  style="Section.TLabel").grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(body, text="缺失 / 唯一值", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=4)
        ttk.Label(body, text="%d / %d" % (row.get("missing") or 0, row.get("unique_n") or 0)).grid(
            row=1, column=1, sticky="w", padx=(8, 0))
        ttk.Label(body, text="处理", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        action_var = tk.StringVar(value=row.get("action") or "保留")
        ttk.Combobox(body, textvariable=action_var, values=list(DATA_FIELD_ACTIONS),
                     state="readonly", width=12).grid(row=2, column=1, sticky="w",
                                                      padx=(8, 0), pady=4)
        ttk.Label(body, text="输出名", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        target_var = tk.StringVar(value=row.get("target") or "")
        ttk.Entry(body, textvariable=target_var, width=32).grid(
            row=3, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="备注", style="Muted.TLabel").grid(row=4, column=0, sticky="nw", pady=4)
        note = tk.Text(body, width=34, height=4, wrap="word")
        note.insert("1.0", row.get("note") or "")
        note.grid(row=4, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="剔除只在输出副本生效；原 CSV 不动。输出名留空则沿用原名。",
                  style="Muted.TLabel", wraplength=360).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def save():
            try:
                self.repo.update_data_field(rid, {
                    "action": action_var.get(), "target": target_var.get().strip(),
                    "note": note.get("1.0", "end").strip()})
            except Exception as e:
                messagebox.showerror("字段处理", str(e), parent=top)
                return
            self._log("更新字段处理", "%s · %s" % (row.get("name"), action_var.get()))
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    def reset_fields(self):
        if not self.current_pid or not self.fields:
            return
        if not messagebox.askyesno("字段处理", "把所有字段恢复为保留、清空输出名？", parent=self):
            return
        for f in self.fields:
            self.repo.update_data_field(f["id"], {"action": "保留", "target": ""})
        self._load_project(self.current_pid)

    def save_options(self):
        if not self.current_pid:
            return
        try:
            self.repo.update_data_options(self.current_pid, trim=self.trim_var.get(),
                                          dedupe=self.dedupe_var.get(),
                                          numeric_guard=self.guard_var.get())
        except Exception as e:
            messagebox.showerror("清洗选项", str(e), parent=self)
            return
        self._log("更新清洗选项", "去空格 %s / 去重 %s / 数值保护 %s" % (
            self.trim_var.get(), self.dedupe_var.get(), self.guard_var.get()))
        self._load_project(self.current_pid)

    # ---------- 报告 ----------
    def _fill_choices(self):
        self.cat_var.set("")
        self.num_var.set("")
        if not self.fields:
            self.cat_cb["values"] = []
            self.num_cb["values"] = []
            return
        texts, nums = [], []
        for f in self.fields:
            if f.get("action") == "剔除":
                continue
            if f.get("dtype") in ("整数", "数值"):
                nums.append(f["name"])
            elif f.get("dtype") == "文本":
                texts.append(f["name"])
        self.cat_cb["values"] = texts
        self.num_cb["values"] = nums
        self.cat_var.set(texts[0] if texts else "")
        self.num_var.set(nums[0] if nums else "")

    def _load_table(self):
        self.table = None
        path = self.source.get("path")
        if not path or not os.path.exists(path):
            self.preview_note.configure(
                text="原文件不在原路径，无法预览；仍可只读已存的字段画像。" if self.source else
                "尚未导入 CSV。")
            return
        try:
            loaded = dl.read_table(path)
        except Exception as e:
            self.preview_note.configure(text="读取失败：%s" % e)
            return
        prof = dl.profile(loaded["headers"], loaded["rows"])
        choices = dl.auto_choices(loaded["headers"], loaded["rows"], prof["fields"])
        self.table = loaded
        if choices["category"]:
            self.cat_var.set(choices["category"])
        if choices["numeric"]:
            self.num_var.set(choices["numeric"])

    def refresh_preview(self):
        if not self.table:
            self.cat_canvas.delete("all")
            self.num_canvas.delete("all")
            self.cat_canvas.create_text(16, 22, anchor="w", fill=C["muted"],
                                        text="导入 CSV 后可预览图表。")
            return
        headers, rows = self.table["headers"], self.table["rows"]
        cat_name, num_name = self.cat_var.get(), self.num_var.get()
        self.cat_items, cat_total = dl.category_stats(headers, rows, cat_name)
        self.num_stats = dl.numeric_stats(headers, rows, num_name)
        if self.num_stats:
            self.num_stats["name"] = num_name
        self._draw_cat()
        self._draw_num()
        parts = []
        if self.cat_items:
            parts.append("「%s」%d 组 / %d 行" % (cat_name, len(self.cat_items), cat_total))
        if self.num_stats:
            parts.append("「%s」样本 %d，中位 %s" % (
                num_name, self.num_stats["count"],
                dl._fmt_num(self.num_stats["median"])))
        self.preview_note.configure(text="；".join(parts) or "没有可画的字段。")

    def _draw_cat(self):
        cv = self.cat_canvas
        cv.delete("all")
        w = max(320, cv.winfo_width())
        if not self.cat_items:
            cv.create_text(16, 22, anchor="w", fill=C["muted"],
                           text="选择一个分类字段。")
            return
        top = max(v for _, v in self.cat_items) or 1
        row_h = min(24, max(16, int((cv.winfo_height() - 40) / max(1, len(self.cat_items)))))
        left, right = 118, 40
        cv.create_text(10, 12, anchor="w", fill=C["text"],
                       text="分类分布 · %s" % self.cat_var.get(),
                       font=(FONT, 10, "bold"))
        for i, (label, value) in enumerate(self.cat_items):
            y = 32 + i * row_h
            cv.create_text(10, y + row_h / 2, anchor="w", fill=C["muted"],
                           text=str(label)[:12], font=(FONT, 8))
            bw = max(2, (value / top) * (w - left - right))
            cv.create_rectangle(left, y + 3, left + bw, y + row_h - 3,
                                fill=C["primary"], width=0)
            cv.create_text(left + bw + 5, y + row_h / 2, anchor="w",
                           fill=C["text"], text=str(value), font=(FONT, 8))

    def _draw_num(self):
        cv = self.num_canvas
        cv.delete("all")
        w, h = max(320, cv.winfo_width()), max(120, cv.winfo_height())
        if not self.num_stats:
            cv.create_text(16, 22, anchor="w", fill=C["muted"],
                           text="选择一个数值字段。")
            return
        hist = self.num_stats["hist"]
        top = max(x["count"] for x in hist) or 1
        left, bottom, top_m = 46, 28, 30
        plot_w, plot_h = w - left - 16, h - bottom - top_m
        bw = plot_w / max(1, len(hist))
        cv.create_text(10, 12, anchor="w", fill=C["text"],
                       text="数值分布 · %s" % self.num_stats.get("name"),
                       font=(FONT, 10, "bold"))
        cv.create_line(left, top_m + plot_h, w - 16, top_m + plot_h, fill=C["line"])
        for i, item in enumerate(hist):
            bh = (item["count"] / top) * plot_h
            x = left + i * bw + 3
            cv.create_rectangle(x, top_m + plot_h - bh, x + max(3, bw - 6),
                                top_m + plot_h, fill=C["green"], width=0)
            cv.create_text(x + (bw - 6) / 2, h - 12, fill=C["muted"],
                           text=item["label"], font=(FONT, 7))

    def note_dialog(self):
        rid = self._selected_id(self.note_tree)
        if rid is None:
            messagebox.showinfo("口径说明", "先在表里选一个小节。", parent=self)
            return
        row = next((n for n in self.notes if n["id"] == rid), None)
        if row is None:
            return
        top = tk.Toplevel(self)
        top.title("编辑 · %s" % row.get("section"))
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=row.get("section"), style="Section.TLabel").pack(anchor="w")
        text = tk.Text(body, width=56, height=12, wrap="word")
        text.insert("1.0", row.get("content") or "")
        text.pack(fill="both", expand=True, pady=(8, 0))
        ttk.Label(body, text="写事实、口径与限制；报告包会原样带入。",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        def save():
            try:
                self.repo.update_data_note(rid, {"content": text.get("1.0", "end").strip()})
            except Exception as e:
                messagebox.showerror("口径说明", str(e), parent=top)
                return
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        top.wait_window()

    def pick_out(self):
        folder = filedialog.askdirectory(title="选择报告包输出目录", parent=self)
        if folder:
            self.out_var.set(folder)

    def make_package(self):
        if not self.current_pid:
            return
        if not self.source:
            messagebox.showinfo("数据报告包", "先导入 CSV 数据源。", parent=self)
            return
        outdir = self.out_var.get().strip()
        if not outdir:
            messagebox.showinfo("数据报告包", "先选输出目录。", parent=self)
            return
        ready = dl.readiness(self.repo, self.current_pid)
        if not ready["ok"] and not messagebox.askyesno(
                "数据报告包", "前置检查还有待补项，仍要生成吗？\n%s" %
                "；".join(ready["failed"]), parent=self):
            return
        try:
            result = dl.make_package(self.repo, self.current_pid, outdir,
                                     category=self.cat_var.get(),
                                     numeric=self.num_var.get())
        except Exception as e:
            messagebox.showerror("数据报告包", str(e), parent=self)
            return
        self.last_report = result["files"][2] if len(result["files"]) > 2 else ""
        self.btn_open.configure(state="normal")
        self._log("生成数据报告包", result["summary"])
        self._load_project(self.current_pid)
        messagebox.showinfo(
            "数据报告包",
            "%s\n目录：%s%s" % (result["summary"], result["package"],
                               ("\nZIP：%s" % result["zip"]) if result["zip"] else ""),
            parent=self)

    def open_report(self):
        try:
            dl.open_report(self.last_report)
        except Exception as e:
            messagebox.showwarning("打开报告", str(e), parent=self)

    def open_folder(self):
        folder = self.out_var.get().strip()
        if folder and os.path.isdir(folder):
            try:
                os.startfile(folder)
            except Exception as e:
                messagebox.showerror("打开目录", str(e), parent=self)
        else:
            messagebox.showinfo("打开目录", "输出目录还不存在，先生成一次报告包。", parent=self)

    # ---------- 新建 / 编辑 ----------
    def project_dialog(self, mode=None):
        editing = mode == "edit" and self.current_pid
        project = self.repo.find_project(self.current_pid) if editing else None
        top = tk.Toplevel(self)
        top.title("编辑数据项目" if editing else "新建数据项目")
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
        for i, (label, key, width) in enumerate((
                ("项目名称", "name", 36), ("负责人", "owner", 24),
                ("开始日期", "start_date", 16), ("截止日期", "due_date", 16))):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(
                row=i, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=vars_[key], width=width).grid(
                row=i, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="分析目标", style="Muted.TLabel").grid(
            row=4, column=0, sticky="nw", pady=4)
        goal = tk.Text(body, width=42, height=4, wrap="word")
        goal.insert("1.0", (project or {}).get("goal", ""))
        goal.grid(row=4, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="新建自动套 4 项交付物和 5 个口径小节；数据从 CSV 导入。",
                  style="Muted.TLabel").grid(row=5, column=0, columnspan=2,
                                             sticky="w", pady=(6, 0))

        def save():
            name = vars_["name"].get().strip()
            if not name:
                messagebox.showwarning("数据项目", "项目名称不能为空。", parent=top)
                return
            data = {"name": name, "kind": "data",
                    "owner": vars_["owner"].get().strip(),
                    "start_date": vars_["start_date"].get().strip(),
                    "due_date": vars_["due_date"].get().strip(),
                    "goal": goal.get("1.0", "end").strip()}
            try:
                if editing:
                    self.repo.update_project(self.current_pid, data)
                    pid = self.current_pid
                else:
                    data.update({"stage": "采集", "status": "进行中"})
                    pid = self.repo.add_project(data)
                    added = self.repo.apply_project_template(pid, "data")
                    dl.seed_data(self.repo, pid)
                    self._log("新建数据项目", "%s；交付物 %d" % (name, added))
            except Exception as e:
                messagebox.showerror("数据项目", str(e), parent=top)
                return
            top.destroy()
            self.refresh(pid)

        bar = ttk.Frame(body)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

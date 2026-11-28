# -*- coding: utf-8 -*-
"""v0.33 文档工作台：四类文档工具的界面壳。

界面只负责选工具、选输入/输出、解释参数、预检、开始/停止/重试、撤销，
执行与质检全在 docs_tools.py。产物可选登记到项目资产。
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import docs_tools as dt
from theme import FONT, C


class DocToolsView(ttk.Frame):
    PERM = "doc:run"
    COLS = ("name", "state", "in", "out", "qc", "note")
    HEADS = {"name": "输入", "state": "预检", "in": "输入信息",
             "out": "输出", "qc": "质检", "note": "说明"}
    WIDTHS = {"name": 200, "state": 64, "in": 150, "out": 200,
              "qc": 64, "note": 340}

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self.paths = []
        self.rows = []
        self.result = None
        self.busy = False
        self.cancel_event = threading.Event()
        self.q = queue.Queue()
        self.polling = False
        self.project_map = {}
        self.tool_keys = [k for k, _ in dt.tool_items()]
        self.tool_labels = [label for _, label in dt.tool_items()]
        self.param_vars = {}
        self._build()

    # ---------- 搭界面 ----------
    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill="x", padx=18, pady=(4, 8))
        ttk.Label(head, text="文档工作台", style="H2.TLabel").pack(side="left")
        self.summary = ttk.Label(head, text="", style="Muted.TLabel")
        self.summary.pack(side="right")

        form = ttk.Frame(self)
        form.pack(fill="x", padx=18, pady=(0, 6))
        ttk.Label(form, text="工具", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.tool_var = tk.StringVar(value=self.tool_labels[0])
        self.tool_cb = ttk.Combobox(form, textvariable=self.tool_var,
                                    values=self.tool_labels, state="readonly", width=46)
        self.tool_cb.grid(row=0, column=1, sticky="w", padx=(8, 10))
        self.tool_cb.bind("<<ComboboxSelected>>", lambda e: self._on_tool_change())
        self.tool_note = ttk.Label(form, text="", style="Muted.TLabel")
        self.tool_note.grid(row=0, column=2, columnspan=4, sticky="w")

        ttk.Label(form, text="输入", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.path_label = ttk.Label(form, text="还没有选文件", style="Muted.TLabel")
        self.path_label.grid(row=1, column=1, sticky="w", padx=(8, 10), pady=(8, 0))
        ttk.Button(form, text="选文件…", style="Ghost.TButton",
                   command=self.pick_files).grid(row=1, column=2, padx=2, pady=(8, 0))
        ttk.Button(form, text="选文件夹…", style="Ghost.TButton",
                   command=self.pick_folder).grid(row=1, column=3, padx=2, pady=(8, 0))
        ttk.Button(form, text="清空", style="Ghost.TButton",
                   command=self.clear_inputs).grid(row=1, column=4, padx=(2, 12), pady=(8, 0))

        ttk.Label(form, text="输出", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.out_var = tk.StringVar(value="")
        self.out_entry = ttk.Entry(form, textvariable=self.out_var, width=48)
        self.out_entry.grid(row=2, column=1, columnspan=2, sticky="we", padx=(8, 10), pady=(8, 0))
        ttk.Button(form, text="选目录…", style="Ghost.TButton",
                   command=self.pick_outdir).grid(row=2, column=3, padx=2, pady=(8, 0))
        self.open_out_btn = ttk.Button(form, text="打开", style="Ghost.TButton",
                                       command=self.open_outdir)
        self.open_out_btn.grid(row=2, column=4, padx=(2, 12), pady=(8, 0))

        ttk.Label(form, text="参数", style="Muted.TLabel").grid(row=3, column=0, sticky="nw", pady=(8, 0))
        self.param_frame = ttk.Frame(form)
        self.param_frame.grid(row=3, column=1, columnspan=4, sticky="w", padx=(8, 10), pady=(8, 0))
        self.param_hint = ttk.Label(form, text="", style="Muted.TLabel")
        self.param_hint.grid(row=4, column=1, columnspan=4, sticky="w", padx=(8, 10), pady=(4, 0))

        ttk.Label(form, text="项目", style="Muted.TLabel").grid(row=5, column=0, sticky="w", pady=(8, 0))
        self.project_var = tk.StringVar(value="不挂项目")
        self.project_cb = ttk.Combobox(form, textvariable=self.project_var,
                                       state="readonly", width=46)
        self.project_cb.grid(row=5, column=1, sticky="w", padx=(8, 10), pady=(8, 0))
        self.project_cb.bind("<<ComboboxSelected>>", lambda e: self._project_hint())
        self.project_hint = ttk.Label(form, text="", style="Muted.TLabel")
        self.project_hint.grid(row=5, column=2, columnspan=3, sticky="w", pady=(8, 0))
        form.columnconfigure(1, weight=1)

        # 底部按钮条先钉住，表格再吃剩余空间。
        bar = ttk.Frame(self)
        bar.pack(side="bottom", fill="x", padx=18, pady=(0, 8))
        self.btn_pre = ttk.Button(bar, text="预检", style="Ghost.TButton", command=self.preflight)
        self.btn_pre.pack(side="left", padx=(0, 6))
        self.btn_start = ttk.Button(bar, text="开始", style="Accent.TButton", command=self.start)
        self.btn_start.pack(side="left", padx=(0, 6))
        self.btn_stop = ttk.Button(bar, text="停止", style="Danger.TButton",
                                   command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=(0, 6))
        self.btn_retry = ttk.Button(bar, text="重试失败", style="Ghost.TButton",
                                    command=self.retry_failed, state="disabled")
        self.btn_retry.pack(side="left", padx=(0, 6))
        self.btn_manifest = ttk.Button(bar, text="打开清单", style="Ghost.TButton",
                                       command=self.open_manifest, state="disabled")
        self.btn_manifest.pack(side="left", padx=(0, 6))
        self.btn_undo = ttk.Button(bar, text="撤销本次产物", style="Ghost.TButton",
                                   command=self.undo_last, state="disabled")
        self.btn_undo.pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="刷新项目", style="Ghost.TButton",
                   command=self.refresh).pack(side="right")

        foot = ttk.Frame(self)
        foot.pack(side="bottom", fill="x", padx=18, pady=(6, 8))
        self.progress = ttk.Progressbar(foot, mode="determinate", length=220)
        self.progress.pack(side="left")
        self.status = ttk.Label(foot, text="先选工具和文件，再预检。", style="Muted.TLabel")
        self.status.pack(side="left", padx=(10, 0))

        table_wrap = ttk.Frame(self)
        table_wrap.pack(fill="both", expand=True, padx=18, pady=(4, 0))
        self.tree = ttk.Treeview(table_wrap, columns=self.COLS, show="headings",
                                 selectmode="browse")
        for c in self.COLS:
            self.tree.heading(c, text=self.HEADS[c], anchor="w")
            self.tree.column(c, width=self.WIDTHS[c], anchor="w",
                             stretch=(c in ("name", "out", "note")))
        self.tree.tag_configure("zebra", background=C["zebra"])
        self.tree.tag_configure("green", foreground=C["green"])
        self.tree.tag_configure("orange", foreground=C["orange"])
        self.tree.tag_configure("red", foreground=C["red"])
        ysb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self._build_params()
        self._update_tool_note()

    def _current_key(self):
        try:
            return self.tool_keys[self.tool_labels.index(self.tool_var.get())]
        except (ValueError, IndexError):
            return self.tool_keys[0]

    def _build_params(self):
        for w in self.param_frame.winfo_children():
            w.destroy()
        self.param_vars = {}
        k = self._current_key()
        p = dt.default_params(k)
        row = 0
        if k == "pdf_split":
            self.param_vars["pages"] = tk.StringVar(value=p.get("pages") or "")
            ttk.Entry(self.param_frame, textvariable=self.param_vars["pages"],
                      width=28).grid(row=row, column=0, sticky="w")
            ttk.Label(self.param_frame, text="如 1-3,5；留空=每页一个",
                      style="Muted.TLabel").grid(row=row, column=1, sticky="w", padx=(8, 0))
        elif k == "pdf_merge":
            self.param_vars["filename"] = tk.StringVar(value=p.get("filename") or "")
            ttk.Entry(self.param_frame, textvariable=self.param_vars["filename"],
                      width=34).grid(row=row, column=0, sticky="w")
            ttk.Label(self.param_frame, text="可留空，自动按时间命名",
                      style="Muted.TLabel").grid(row=row, column=1, sticky="w", padx=(8, 0))
        elif k == "ocr":
            self.param_vars["dpi"] = tk.StringVar(value=str(p.get("dpi") or 200))
            ttk.Label(self.param_frame, text="DPI").grid(row=row, column=0, sticky="w")
            ttk.Combobox(self.param_frame, textvariable=self.param_vars["dpi"],
                         values=["150", "200", "300"], state="readonly",
                         width=8).grid(row=row, column=1, sticky="w", padx=(6, 14))
            self.param_vars["keep_pages"] = tk.BooleanVar(value=bool(p.get("keep_pages")))
            ttk.Checkbutton(self.param_frame, text="保留「第 N 页」分页标记",
                            variable=self.param_vars["keep_pages"]).grid(row=row, column=2, sticky="w")
        elif k == "pdf_to_docx":
            self.param_vars["ocr_scanned"] = tk.BooleanVar(value=bool(p.get("ocr_scanned")))
            ttk.Checkbutton(self.param_frame, text="扫描页自动走 OCR（慢一些，但扫描件能出字）",
                            variable=self.param_vars["ocr_scanned"]).grid(row=row, column=0, sticky="w")
        elif k == "docx_to_pdf":
            self.param_vars["keep_tables"] = tk.BooleanVar(value=bool(p.get("keep_tables")))
            ttk.Checkbutton(self.param_frame, text="保留表格",
                            variable=self.param_vars["keep_tables"]).grid(row=row, column=0, sticky="w")
            ttk.Label(self.param_frame, text="复杂版式、浮动图片不保证与 Word 一致",
                      style="Muted.TLabel").grid(row=row, column=1, sticky="w", padx=(8, 0))
        elif k == "image_batch":
            self.param_vars["format"] = tk.StringVar(value=str(p.get("format") or "jpg").upper())
            ttk.Label(self.param_frame, text="格式").grid(row=0, column=0, sticky="w")
            ttk.Combobox(self.param_frame, textvariable=self.param_vars["format"],
                         values=["JPG", "PNG", "WEBP"], state="readonly",
                         width=8).grid(row=0, column=1, sticky="w", padx=(6, 14))
            self.param_vars["max_edge"] = tk.StringVar(value=str(p.get("max_edge") or 0))
            ttk.Label(self.param_frame, text="最长边").grid(row=0, column=2, sticky="w")
            ttk.Entry(self.param_frame, textvariable=self.param_vars["max_edge"],
                      width=8).grid(row=0, column=3, sticky="w", padx=(6, 14))
            self.param_vars["quality"] = tk.StringVar(value=str(p.get("quality") or 85))
            ttk.Label(self.param_frame, text="质量").grid(row=0, column=4, sticky="w")
            ttk.Spinbox(self.param_frame, from_=30, to=98, width=6,
                        textvariable=self.param_vars["quality"]).grid(row=0, column=5, sticky="w", padx=(6, 0))
        self.param_hint.configure(text=dt.tool(k)["hint"])

    def _get_params(self):
        k = self._current_key()
        raw = {}
        for name, var in self.param_vars.items():
            try:
                raw[name] = var.get()
            except tk.TclError:
                raw[name] = ""
        return dt.normalize_params(k, raw)

    def _update_tool_note(self):
        k = self._current_key()
        ok, why = dt.available(k, self._get_params())
        if ok:
            extra = ""
            if k in ("ocr", "pdf_to_docx"):
                extra = " · OCR 语言 %s" % dt.ocr_lang()
            self.tool_note.configure(text="本机可用" + extra)
            self.summary.configure(text="%s · %s" % (dt.tool(k)["accept"], "可用" + extra))
        else:
            self.tool_note.configure(text="不可用：%s" % why)
            self.summary.configure(text="不可用：%s" % why)

    def _on_tool_change(self):
        if self.busy:
            self.tool_var.set(self.tool_labels[self.tool_keys.index(self._current_key())])
            return
        self.clear_inputs()
        self.result = None
        self.btn_retry.configure(state="disabled")
        self.btn_manifest.configure(state="disabled")
        self.btn_undo.configure(state="disabled")
        self._build_params()
        self._update_tool_note()

    # ---------- 输入与项目 ----------
    def refresh(self):
        try:
            projects = self.repo.list_projects()
        except Exception:
            projects = []
        self.project_map = {"不挂项目": None}
        names = ["不挂项目"]
        for p in projects:
            label = "%s（%s）" % (p.get("name") or "未命名", p.get("status") or "")
            self.project_map[label] = p.get("id")
            names.append(label)
        self.project_cb["values"] = names
        if self.project_var.get() not in names:
            self.project_var.set("不挂项目")
        self._project_hint()

    def _project_hint(self):
        pid = self.project_map.get(self.project_var.get())
        if not pid:
            self.project_hint.configure(text="不挂项目：产物照常输出，但不进项目资产。")
            return
        try:
            st = self.repo.project_stats(pid)
            self.project_hint.configure(
                text="必交 %d，已完成 %d，缺 %d；跑完会登记资产、执行记录与质量门。" % (
                    st.get("required", 0), st.get("required_done", 0),
                    st.get("missing", 0)))
        except Exception:
            self.project_hint.configure(text="项目读取失败，不影响文档处理。")

    def _set_paths(self, paths):
        seen, clean = set(), []
        for p in paths or []:
            try:
                full = os.path.abspath(str(p))
            except (TypeError, ValueError):
                continue
            key = os.path.normcase(full)
            if key in seen:
                continue
            seen.add(key)
            clean.append(full)
        self.paths = clean
        k = self._current_key()
        self.path_label.configure(text="%d 个%s文件" % (len(clean), dt.tool(k)["accept"])
                                  if clean else "还没有选文件")
        if clean and not self.out_var.get().strip():
            self.out_var.set(os.path.join(os.path.dirname(clean[0]), "文档输出"))
        self._fill_rows(dt.plan(k, clean, self.out_var.get().strip(), self._get_params())[0]
                        if clean and self.out_var.get().strip() else
                        (dt.preflight(k, clean, self._get_params()) if clean else []))
        self._update_tool_note()

    def pick_files(self):
        k = self._current_key()
        exts = sorted(dt.tool(k)["exts"])
        pattern = " ".join("*" + e for e in exts)
        paths = filedialog.askopenfilenames(
            parent=self, title="选择%s文件" % dt.tool(k)["accept"],
            filetypes=[(dt.tool(k)["accept"], pattern), ("全部文件", "*.*")])
        if paths:
            self._set_paths(list(self.paths) + list(paths))

    def pick_folder(self):
        folder = filedialog.askdirectory(parent=self, title="选择文件夹")
        if not folder:
            return
        k = self._current_key()
        exts = dt.tool(k)["exts"]
        found = []
        for root, _, files in os.walk(folder):
            for name in files:
                if os.path.splitext(name)[1].lower() in exts:
                    found.append(os.path.join(root, name))
        if found:
            self._set_paths(list(self.paths) + found)
        else:
            self.status.configure(text="这个文件夹里没有%s文件。" % dt.tool(k)["accept"])

    def clear_inputs(self):
        self.paths = []
        self.rows = []
        self.path_label.configure(text="还没有选文件")
        self.status.configure(text="先选工具和文件，再预检。")
        self._fill_rows([])

    def pick_outdir(self):
        folder = filedialog.askdirectory(parent=self, title="选择输出目录")
        if folder:
            self.out_var.set(folder)

    def open_outdir(self):
        self._open_path(self.out_var.get().strip())

    def open_manifest(self):
        path = (self.result or {}).get("manifest_csv") or ""
        self._open_path(path)

    def _open_path(self, path):
        if not path or not os.path.exists(path):
            messagebox.showinfo("文档工作台", "还没有可打开的目录或清单。", parent=self)
            return
        try:
            os.startfile(path)  # noqa: S606 - Windows 桌面程序的标准打开方式
        except AttributeError:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        except OSError as e:
            messagebox.showwarning("文档工作台", "打开失败：%s" % e, parent=self)

    # ---------- 预检与执行 ----------
    def preflight(self):
        if self.busy:
            return
        if not self.paths:
            self.status.configure(text="先选文件。")
            return
        k = self._current_key()
        p = self._get_params()
        out = self.out_var.get().strip()
        rows = dt.plan(k, self.paths, out, p)[0] if out else dt.preflight(k, self.paths, p)
        self.rows = rows
        self._fill_rows(rows)
        ok = sum(1 for r in rows if r.get("ok"))
        self.status.configure(text="预检：%d 项可处理，%d 项有问题。" % (ok, len(rows) - ok))
        self.btn_retry.configure(state="disabled")
        self.btn_undo.configure(state="disabled")

    def start(self):
        if self.busy:
            return
        k = self._current_key()
        p = self._get_params()
        ok, why = dt.available(k, p)
        if not ok:
            messagebox.showerror("文档工作台", "这个工具现在不可用：\n%s" % why, parent=self)
            return
        if not self.paths:
            self.status.configure(text="先选文件。")
            return
        out = self.out_var.get().strip()
        if not out:
            self.status.configure(text="先选输出目录。")
            return
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            messagebox.showerror("文档工作台", "输出目录建不了：%s" % e, parent=self)
            return
        self.preflight()
        runnable = sum(1 for r in self.rows if r.get("ok"))
        if not runnable:
            self.status.configure(text="预检没有可处理项，先处理问题。")
            return
        self.busy = True
        self.cancel_event.clear()
        self.btn_start.configure(state="disabled")
        self.btn_pre.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_retry.configure(state="disabled")
        self.btn_manifest.configure(state="disabled")
        self.btn_undo.configure(state="disabled")
        self.progress.configure(maximum=max(1, len(self.rows)), value=0)
        self.status.configure(text="开始处理 %d 项…" % runnable)
        threading.Thread(target=self._worker,
                         args=(k, list(self.paths), out, p), daemon=True).start()
        self._start_poll()

    def _worker(self, key, paths, out, params):
        def progress(i, total, row):
            self.q.put(("progress", i, total, row))
        try:
            result = dt.run_batch(key, paths, out, params, progress=progress,
                                  cancel=self.cancel_event.is_set)
        except Exception as e:
            result = {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                      "rows": self.rows, "total": len(self.rows), "done": 0,
                      "failed": len(self.rows), "stopped": 0}
        self.q.put(("finish", result))

    def _start_poll(self):
        if self.polling:
            return
        self.polling = True
        self.after(80, self._poll_queue)

    def _poll_queue(self):
        self.polling = False
        finished = False
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "progress":
                    _, i, total, row = msg
                    self._progress(i, total, row)
                elif msg[0] == "finish":
                    finished = True
                    self._finish(msg[1])
        except queue.Empty:
            pass
        except tk.TclError:
            return
        if self.busy and not finished:
            self.polling = True
            self.after(80, self._poll_queue)

    def _progress(self, i, total, row):
        if not self.winfo_exists():
            return
        self.progress.configure(maximum=max(1, total), value=i)
        self.status.configure(text="%d / %d · %s" % (i, total, row.get("qc") or "处理中"))
        self._update_row(i - 1, row)

    def stop(self):
        self.cancel_event.set()
        self.btn_stop.configure(state="disabled")
        self.status.configure(text="已请求停止：当前文件跑完就停。")

    def _finish(self, result):
        self.busy = False
        self.result = result
        self.rows = result.get("rows") or self.rows
        self._fill_rows(self.rows)
        self.btn_start.configure(state="normal")
        self.btn_pre.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        if result.get("manifest_csv"):
            self.btn_manifest.configure(state="normal")
            self.btn_undo.configure(state="normal")
        if result.get("retry_paths"):
            self.btn_retry.configure(state="normal")
        self.status.configure(text=dt.summary_text(result))
        if result.get("rows") and result.get("done"):
            self._register_to_project(result)
        try:
            self.repo.add_log("文档工具",
                              "%s：%d 项，通过 %d，失败/跳过 %d" % (
                                  result.get("tool_label") or "文档处理",
                                  result.get("total", 0), result.get("done", 0),
                                  result.get("failed", 0)),
                              self.window.operator_name, self.window.role_label())
        except Exception:
            pass
        if result.get("error"):
            messagebox.showwarning("文档工作台", result["error"], parent=self)

    def retry_failed(self):
        if self.busy:
            return
        paths = (self.result or {}).get("retry_paths") or []
        if not paths:
            self.status.configure(text="没有可重试的失败项。")
            return
        self.paths = list(paths)
        self.path_label.configure(text="%d 个待重试文件" % len(paths))
        self.status.configure(text="只重试上次失败/需复核的输入。")
        self.start()

    def undo_last(self):
        if self.busy:
            return
        manifest = (self.result or {}).get("manifest_json") or ""
        if not manifest or not os.path.isfile(manifest):
            self.status.configure(text="没有本次清单，无法撤销。")
            return
        if not messagebox.askyesno("撤销本次产物",
                                   "只删本次清单里记录的产物，不动源文件。继续？",
                                   parent=self):
            return
        res = dt.undo(manifest)
        if res.get("ok"):
            self.status.configure(text="已撤销：删掉 %d 个产物。" % res.get("removed", 0))
            self.btn_manifest.configure(state="disabled")
            self.btn_undo.configure(state="disabled")
            self.result = None
            self._fill_rows([])
            try:
                self.repo.add_log("文档工具",
                                  "撤销本次产物 %d 个；源文件保留" % res.get("removed", 0),
                                  self.window.operator_name, self.window.role_label())
            except Exception:
                pass
        else:
            messagebox.showwarning("撤销未完成", res.get("error") or "未知原因", parent=self)

    def _register_to_project(self, result):
        pid = self.project_map.get(self.project_var.get())
        if not pid:
            return
        added = 0
        seen = set()
        for r in result.get("rows") or []:
            if r.get("qc") != "通过" or not r.get("out"):
                continue
            out = os.path.normcase(os.path.abspath(r["out"]))
            if out in seen:
                continue
            seen.add(out)
            try:
                self.repo.add_project_asset(pid, {
                    "name": os.path.basename(r["out"]),
                    "path": r["out"],
                    "kind": os.path.splitext(r["out"])[1].lstrip(".").lower(),
                    "size": r.get("out_size") or 0,
                    "sha256": r.get("sha256") or "",
                    "note": "文档工具 · %s" % (result.get("tool_label") or ""),
                })
                added += 1
            except Exception:
                continue
        try:
            self.repo.add_project_run(pid, {
                "tool": result.get("tool_label") or "文档工具",
                "params": "%s；输入 %d；输出目录 %s" % (
                    result.get("params_text") or "", result.get("total") or 0,
                    result.get("outdir") or ""),
                "status": "成功" if result.get("ok") else "部分失败",
                "started_at": result.get("started_at") or "",
                "ended_at": result.get("ended_at") or "",
                "output": result.get("manifest_csv") or "",
                "log": dt.summary_text(result),
            })
        except Exception:
            pass
        try:
            if result.get("done"):
                self.repo.set_project_gate(pid, "输出可质检",
                                           "通过" if result.get("ok") else "待复核",
                                           note=dt.summary_text(result),
                                           checked_by=self.window.operator_name)
            if result.get("total"):
                self.repo.set_project_gate(pid, "输入可识别", "通过",
                                           note=result.get("params_text") or "",
                                           checked_by=self.window.operator_name)
                self.repo.set_project_gate(pid, "产物有清单",
                                           "通过" if result.get("manifest_csv") else "待检查",
                                           note=os.path.basename(result.get("manifest_csv") or ""),
                                           checked_by=self.window.operator_name)
        except Exception:
            pass
        if added:
            self.project_hint.configure(text="本次已登记 %d 个产物；执行记录与质量门已写入项目。" % added)
        self._project_hint()

    # ---------- 表格 ----------
    def _fill_rows(self, rows):
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(rows):
            self.tree.insert("", "end", iid=str(i + 1), values=self._values(row, i),
                             tags=self._tags(row, i))
        self.progress.configure(maximum=max(1, len(rows)), value=0)

    def _update_row(self, index, row):
        iid = str(index + 1)
        if self.tree.exists(iid):
            self.tree.item(iid, values=self._values(row, index), tags=self._tags(row, index))

    def _values(self, row, index):
        state = "可处理" if row.get("ok") and not row.get("qc") else (row.get("qc") or "跳过")
        return (
            row.get("name") or os.path.basename(row.get("src") or ""),
            state,
            row.get("meta") or row.get("detail_out") or "",
            os.path.basename(row.get("out") or ""),
            row.get("qc") or "",
            row.get("note") or row.get("reason") or "",
        )

    def _tags(self, row, index):
        tags = []
        if index % 2:
            tags.append("zebra")
        if row.get("qc") == "通过":
            tags.append("green")
        elif row.get("qc") in ("需复核", "失败"):
            tags.append("red")
        elif row.get("qc") == "跳过" or row.get("reason"):
            tags.append("orange")
        return tuple(tags)

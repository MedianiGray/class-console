# -*- coding: utf-8 -*-
"""v0.32 媒体工作台：音频批量转码的界面壳。

界面只做四个动作：选输入、选输出与预设、预检、开始。执行逻辑全在
media.py，界面负责展示每一步结果，并把产物登记到选中的媒体项目。
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import media
from theme import FONT, C


class MediaView(ttk.Frame):
    PERM = "media:run"
    COLS = ("name", "state", "in", "out", "qc", "note")
    HEADS = {"name": "输入", "state": "预检", "in": "源时长 / 源参数",
             "out": "输出", "qc": "质检", "note": "说明"}
    WIDTHS = {"name": 220, "state": 72, "in": 150, "out": 210,
              "qc": 70, "note": 300}

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
        self._build()

    # ---------- 搭界面 ----------
    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill="x", padx=18, pady=(4, 8))
        ttk.Label(head, text="媒体工作台", style="H2.TLabel").pack(side="left")
        self.summary = ttk.Label(head, text="", style="Muted.TLabel")
        self.summary.pack(side="right")

        form = ttk.Frame(self)
        form.pack(fill="x", padx=18, pady=(0, 8))
        ttk.Label(form, text="输入", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.path_label = ttk.Label(form, text="还没有选音频", style="Muted.TLabel")
        self.path_label.grid(row=0, column=1, sticky="w", padx=(8, 10))
        ttk.Button(form, text="选音频…", style="Ghost.TButton",
                   command=self.pick_files).grid(row=0, column=2, padx=2)
        ttk.Button(form, text="选文件夹…", style="Ghost.TButton",
                   command=self.pick_folder).grid(row=0, column=3, padx=2)
        ttk.Button(form, text="清空", style="Ghost.TButton",
                   command=self.clear_inputs).grid(row=0, column=4, padx=(2, 12))

        ttk.Label(form, text="输出", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.out_var = tk.StringVar(value="")
        self.out_entry = ttk.Entry(form, textvariable=self.out_var, width=48)
        self.out_entry.grid(row=1, column=1, columnspan=2, sticky="we", padx=(8, 10), pady=(8, 0))
        ttk.Button(form, text="选目录…", style="Ghost.TButton",
                   command=self.pick_outdir).grid(row=1, column=3, padx=2, pady=(8, 0))
        self.open_out_btn = ttk.Button(form, text="打开", style="Ghost.TButton",
                                       command=self.open_outdir)
        self.open_out_btn.grid(row=1, column=4, padx=(2, 12), pady=(8, 0))

        ttk.Label(form, text="预设", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.preset_labels = [label for _, label in media.preset_items()]
        self.preset_keys = [key for key, _ in media.preset_items()]
        self.preset_var = tk.StringVar(value=self.preset_labels[0])
        self.preset_cb = ttk.Combobox(form, textvariable=self.preset_var,
                                      values=self.preset_labels, state="readonly",
                                      width=42)
        self.preset_cb.grid(row=2, column=1, sticky="w", padx=(8, 10), pady=(8, 0))
        ttk.Label(form, text="源文件只读，输出同名不覆盖", style="Muted.TLabel").grid(
            row=2, column=2, columnspan=3, sticky="w", pady=(8, 0))

        ttk.Label(form, text="项目", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.project_var = tk.StringVar(value="不挂项目")
        self.project_cb = ttk.Combobox(form, textvariable=self.project_var,
                                       state="readonly", width=42)
        self.project_cb.grid(row=3, column=1, sticky="w", padx=(8, 10), pady=(8, 0))
        self.project_cb.bind("<<ComboboxSelected>>", lambda e: self._project_hint())
        self.project_hint = ttk.Label(form, text="", style="Muted.TLabel")
        self.project_hint.grid(row=3, column=2, columnspan=3, sticky="w", pady=(8, 0))
        form.columnconfigure(1, weight=1)

        # 先把底部条钉住，再让表格吃剩余空间；否则窗口偏矮时按钮会被表格挤掉。
        bar = ttk.Frame(self)
        bar.pack(side="bottom", fill="x", padx=18, pady=(0, 12))
        self.btn_pre = ttk.Button(bar, text="预检", style="Ghost.TButton", command=self.preflight)
        self.btn_pre.pack(side="left", padx=(0, 6))
        self.btn_start = ttk.Button(bar, text="开始转码", style="Accent.TButton", command=self.start)
        self.btn_start.pack(side="left", padx=(0, 6))
        self.btn_stop = ttk.Button(bar, text="停止", style="Danger.TButton",
                                   command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=(0, 6))
        self.btn_manifest = ttk.Button(bar, text="打开清单", style="Ghost.TButton",
                                       command=self.open_manifest, state="disabled")
        self.btn_manifest.pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="刷新项目", style="Ghost.TButton",
                   command=self.refresh).pack(side="right")

        foot = ttk.Frame(self)
        foot.pack(side="bottom", fill="x", padx=18, pady=(10, 10))
        self.progress = ttk.Progressbar(foot, mode="determinate", length=220)
        self.progress.pack(side="left")
        self.status = ttk.Label(foot, text="先选输入，再预检。", style="Muted.TLabel")
        self.status.pack(side="left", padx=(10, 0))

        table_wrap = ttk.Frame(self)
        table_wrap.pack(fill="both", expand=True, padx=18, pady=(6, 0))
        self.tree = ttk.Treeview(table_wrap, columns=self.COLS, show="headings",
                                 selectmode="browse")
        for c in self.COLS:
            self.tree.heading(c, text=self.HEADS[c], anchor="w")
            self.tree.column(c, width=self.WIDTHS[c], anchor="w", stretch=(c in ("name", "out", "note")))
        self.tree.tag_configure("zebra", background=C["zebra"])
        self.tree.tag_configure("green", foreground=C["green"])
        self.tree.tag_configure("orange", foreground=C["orange"])
        self.tree.tag_configure("red", foreground=C["red"])
        ysb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

    # ---------- 输入与项目 ----------
    def refresh(self):
        try:
            projects = self.repo.list_projects("media")
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
                text="必交 %d，已完成 %d，缺 %d；转完会登记资产与执行记录。" % (
                    st.get("required", 0), st.get("required_done", 0),
                    st.get("missing", 0)))
        except Exception:
            self.project_hint.configure(text="项目读取失败，不影响转码。")

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
        self.path_label.configure(
            text="%d 个音频文件" % len(clean) if clean else "还没有选音频")
        self.summary.configure(text="%d 个输入；%s" % (
            len(clean), "ffmpeg 可用" if media.available() else "找不到 ffmpeg"))
        self._fill_rows(media.preflight(clean) if clean else [])

    def pick_files(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="选择音频",
            filetypes=[("音频", "*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.aiff *.ape"),
                       ("全部文件", "*.*")])
        if paths:
            self._set_paths(list(self.paths) + list(paths))

    def pick_folder(self):
        folder = filedialog.askdirectory(parent=self, title="选择音频文件夹")
        if not folder:
            return
        found = []
        for root, _, files in os.walk(folder):
            for name in files:
                if os.path.splitext(name)[1].lower() in media.AUDIO_EXTS:
                    found.append(os.path.join(root, name))
        self._set_paths(list(self.paths) + found)

    def clear_inputs(self):
        self.paths = []
        self.rows = []
        self.path_label.configure(text="还没有选音频")
        self.summary.configure(text="")
        self.status.configure(text="先选输入，再预检。")
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
            messagebox.showinfo("媒体工作台", "还没有可打开的目录或清单。", parent=self)
            return
        try:
            os.startfile(path)  # noqa: S606 - Windows 桌面程序的标准打开方式
        except AttributeError:
            import subprocess
            subprocess.Popen(["xdg-open", path])
        except OSError as e:
            messagebox.showwarning("媒体工作台", "打开失败：%s" % e, parent=self)

    # ---------- 预检与执行 ----------
    def _preset_key(self):
        try:
            return self.preset_keys[self.preset_labels.index(self.preset_var.get())]
        except (ValueError, IndexError):
            return "mp3_192"

    def preflight(self):
        if self.busy:
            return
        if not self.paths:
            self.status.configure(text="先选音频。")
            return
        out = self.out_var.get().strip()
        rows = media.plan(self.paths, out, self._preset_key())[0] if out \
            else media.preflight(self.paths)
        self.rows = rows
        self._fill_rows(rows)
        ok = sum(1 for r in rows if r.get("ok"))
        self.status.configure(text="预检：%d 个可转，%d 个有问题。" % (ok, len(rows) - ok))

    def start(self):
        if self.busy:
            return
        if not media.available():
            messagebox.showerror("媒体工作台", "找不到 ffmpeg / ffprobe。\n"
                                              "请安装 ffmpeg 并加入 PATH，或在环境变量里指定 FFMPEG_BIN、FFPROBE_BIN。",
                                 parent=self)
            return
        if not self.paths:
            self.status.configure(text="先选音频。")
            return
        out = self.out_var.get().strip()
        if not out:
            self.status.configure(text="先选输出目录。")
            return
        try:
            os.makedirs(out, exist_ok=True)
        except OSError as e:
            messagebox.showerror("媒体工作台", "输出目录建不了：%s" % e, parent=self)
            return
        self.preflight()
        runnable = sum(1 for r in self.rows if r.get("ok"))
        if not runnable:
            self.status.configure(text="预检没有可转文件，先处理问题。")
            return
        self.busy = True
        self.cancel_event.clear()
        self.btn_start.configure(state="disabled")
        self.btn_pre.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_manifest.configure(state="disabled")
        self.progress.configure(maximum=max(1, len(self.paths)), value=0)
        self.status.configure(text="开始转码 %d 个文件…" % runnable)
        self._fill_rows(self.rows)
        args = (list(self.paths), out, self._preset_key())
        threading.Thread(target=self._worker, args=args, daemon=True).start()
        self._start_poll()

    def _worker(self, paths, out, key):
        def progress(i, total, row):
            self.q.put(("progress", i, total, row))
        try:
            result = media.run_batch(paths, out, key, progress=progress,
                                     cancel=self.cancel_event.is_set)
        except Exception as e:
            result = {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                      "rows": self.rows, "total": len(paths), "done": 0,
                      "failed": len(paths)}
        self.q.put(("finish", result))

    # Tk 只能在主线程动；后台线程把消息塞队列，主线程轮询取。
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
        self.status.configure(text=media.summary_text(result))
        if result.get("rows") and result.get("done"):
            self._register_to_project(result)
        try:
            self.repo.add_log("媒体转码",
                              "%d 个音频，通过 %d，失败/跳过 %d" % (
                                  result.get("total", 0), result.get("done", 0),
                                  result.get("failed", 0)),
                              self.window.operator_name, self.window.role_label())
        except Exception:
            pass
        if result.get("error"):
            messagebox.showwarning("媒体工作台", result["error"], parent=self)

    def _register_to_project(self, result):
        pid = self.project_map.get(self.project_var.get())
        if not pid:
            return
        added = 0
        for r in result.get("rows") or []:
            if r.get("qc") != "通过" or not r.get("out"):
                continue
            try:
                self.repo.add_project_asset(pid, {
                    "name": os.path.basename(r["out"]),
                    "path": r["out"],
                    "kind": os.path.splitext(r["out"])[1].lstrip(".").lower(),
                    "size": r.get("out_size") or 0,
                    "sha256": r.get("sha256") or "",
                    "note": "媒体转码 · %s" % (result.get("preset_label") or ""),
                })
                added += 1
            except Exception:
                continue
        try:
            self.repo.add_project_run(pid, {
                "tool": "媒体转码",
                "params": "%s；输入 %d；输出目录 %s" % (
                    result.get("preset_label") or result.get("preset") or "",
                    result.get("total") or 0, result.get("outdir") or ""),
                "status": "成功" if result.get("ok") else "部分失败",
                "started_at": result.get("started_at") or "",
                "ended_at": result.get("ended_at") or "",
                "output": result.get("manifest_csv") or "",
                "log": media.summary_text(result),
            })
        except Exception:
            pass
        try:
            if result.get("done"):
                self.repo.set_project_gate(pid, "输出可质检",
                                           "通过" if result.get("ok") else "待复核",
                                           note=media.summary_text(result),
                                           checked_by=self.window.operator_name)
            if result.get("total"):
                self.repo.set_project_gate(pid, "输入可识别", "通过",
                                           note="预检、转码与清单均完成",
                                           checked_by=self.window.operator_name)
        except Exception:
            pass
        if added:
            self.project_hint.configure(text="本次已登记 %d 个产物；执行记录与质量门已写入项目。" % added)
        self._project_hint()

    # ---------- 表格 ----------
    def _fmt_in(self, row):
        dur = row.get("duration") or 0
        return "%s · %sHz/%s" % (_fmt_dur(dur), row.get("sample_rate") or "?",
                                 row.get("channels") or "?")

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
        state = "可转" if row.get("ok") and not row.get("qc") else (row.get("qc") or "跳过")
        return (
            row.get("name") or os.path.basename(row.get("src") or ""),
            state,
            self._fmt_in(row) if row.get("duration") else "",
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


def _fmt_dur(seconds):
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "0:00"
    minutes = int(seconds // 60)
    return "%d:%04.1f" % (minutes, seconds - minutes * 60)

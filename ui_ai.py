# -*- coding: utf-8 -*-
"""桌面端 AI 分类建议面板：只读文件名，给类别、置信度与理由。

两种打开方式：
- 「更多功能 → AI 建议」直接选文件 / 文件夹；
- 文件夹收集视图带入已扫描文件，采用建议后回填每行类别，再人工确认入账。
"""

import os
import queue
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from tkinter import ttk, filedialog

import ai
from theme import FONT, C

CATS = ["团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]
SKIP_PREFIX = (".", "~$")
MAX_FILES = 40


class AdvisorDialog:
    def __init__(self, window, items=None, on_apply=None):
        self.window = window
        self.on_apply = on_apply
        self.items = list(items or [])
        self.results = []
        self.busy = False
        self._queue = queue.Queue()
        self._poll_id = None

        self.top = tk.Toplevel(window.winfo_toplevel())
        self.top.title("AI 建议 · 材料分类")
        self.top.transient(window.winfo_toplevel())
        self.top.minsize(760, 520)
        self.top.configure(bg=C["bg"])
        self.top.geometry("860x620")
        self._center(860, 620)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        try:
            self.top.grab_set()
        except tk.TclError:
            pass
        if self.items:
            self.top.after(220, self.analyze)

    def _center(self, w, h):
        top = self.window.winfo_toplevel()
        top.update_idletasks()
        x = top.winfo_rootx() + max(0, (top.winfo_width() - w) // 2)
        y = top.winfo_rooty() + max(0, (top.winfo_height() - h) // 3)
        self.top.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def _build(self):
        head = tk.Frame(self.top, bg=C["bg"])
        head.pack(fill="x", padx=20, pady=(16, 4))
        left = tk.Frame(head, bg=C["bg"])
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="AI 建议 · 材料分类", bg=C["bg"], fg=C["text"],
                 font=(FONT, 15, "bold"), anchor="w").pack(fill="x")
        tk.Label(left, text="只发送文件名与类别列表，不读正文；只给建议，不改台账。",
                 bg=C["bg"], fg=C["muted"], font=(FONT, 9), anchor="w",
                 wraplength=620, justify="left").pack(fill="x", pady=(3, 0))

        status, kind = ai.status_text()
        badge_text = "API 已启用" if kind == "api" else "本地规则"
        self.badge = tk.Label(head, text=badge_text, bg=C["primary_soft"] if kind == "api" else C["bg_soft"],
                              fg=C["primary"] if kind == "api" else C["muted"],
                              font=(FONT, 9, "bold"), padx=8, pady=3)
        self.badge.pack(side="right", padx=(12, 0))

        bar = tk.Frame(self.top, bg=C["bg"])
        bar.pack(fill="x", padx=20, pady=(4, 6))
        self.btn_files = ttk.Button(bar, text="选择文件", style="Ghost.TButton",
                                    command=self.choose_files)
        self.btn_files.pack(side="left")
        self.btn_folder = ttk.Button(bar, text="选择文件夹", style="Ghost.TButton",
                                     command=self.choose_folder)
        self.btn_folder.pack(side="left", padx=(8, 0))
        self.btn_analyze = ttk.Button(bar, text="生成分类建议", style="Accent.TButton",
                                      command=self.analyze)
        self.btn_analyze.pack(side="left", padx=(8, 0))
        self.btn_clear = ttk.Button(bar, text="清空", style="Ghost.TButton",
                                    command=self.clear)
        self.btn_clear.pack(side="left", padx=(8, 0))
        self.hint = ttk.Label(bar, text="一次最多 %d 份" % MAX_FILES, style="Muted.TLabel")
        self.hint.pack(side="right")

        foot = tk.Frame(self.top, bg=C["bg"])
        foot.pack(side="bottom", fill="x", padx=20, pady=(0, 14))
        self.status = ttk.Label(foot, text="先选择文件，再生成建议。", style="Muted.TLabel")
        self.status.pack(side="left")
        self.btn_apply = ttk.Button(foot, text="采用建议", style="Accent.TButton",
                                    command=self.apply, state="disabled")
        self.btn_apply.pack(side="right")
        self.btn_copy = ttk.Button(foot, text="复制清单", style="Ghost.TButton",
                                   command=self.copy_all, state="disabled")
        self.btn_copy.pack(side="right", padx=(0, 8))
        ttk.Button(foot, text="关闭", command=self.close).pack(side="right", padx=(0, 8))

        wrap = tk.Frame(self.top, bg=C["card"], highlightthickness=1,
                        highlightbackground=C["line"])
        wrap.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        cols = ("file", "cat", "conf", "source", "reason")
        heads = {"file": "文件", "cat": "建议类别", "conf": "置信度",
                 "source": "来源", "reason": "依据"}
        widths = {"file": 210, "cat": 100, "conf": 80, "source": 80, "reason": 320}
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 selectmode="browse")
        for c in cols:
            self.tree.heading(c, text=heads[c], anchor="w")
            self.tree.column(c, width=widths[c], anchor="w",
                             stretch=c in ("file", "reason"))
        self.tree.tag_configure("zebra", background=C["zebra"])
        self.tree.tag_configure("api", foreground=C["primary"])
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._copy_one)

    # ---------- 选文件 ----------
    def _merge_names(self, names):
        known = [x.get("name") for x in self.items]
        added = 0
        for name in names:
            if not name or name in known:
                continue
            if len(self.items) >= MAX_FILES:
                break
            self.items.append({"name": name})
            known.append(name)
            added += 1
        if added:
            self.results = []
            self.status.config(text="已加入 %d 份文件，点「生成分类建议」。" % added)
        return added

    def choose_files(self):
        paths = filedialog.askopenfilenames(parent=self.top, title="选择要判断类别的材料文件")
        if not paths:
            return
        self._merge_names([os.path.basename(p) for p in paths])

    def choose_folder(self):
        folder = filedialog.askdirectory(parent=self.top, title="选择材料文件夹")
        if not folder:
            return
        try:
            names = sorted(n for n in os.listdir(folder)
                           if os.path.isfile(os.path.join(folder, n))
                           and not n.startswith(SKIP_PREFIX))
        except OSError:
            self.status.config(text="这个文件夹暂时读不了，换一个或直接选择文件。")
            return
        added = self._merge_names(names[:MAX_FILES])
        if not added:
            self.status.config(text="没有新的文件可加入；当前已到上限或都已选择。")

    def clear(self):
        if self.busy:
            return
        self.items = []
        self.results = []
        self._render([])
        self.status.config(text="先选择文件，再生成建议。")
        self.btn_copy.config(state="disabled")
        self.btn_apply.config(state="disabled")

    # ---------- 分析 ----------
    def analyze(self):
        if self.busy:
            return
        if not self.items:
            self.choose_files()
            if not self.items:
                return
        self.busy = True
        self.btn_analyze.config(state="disabled")
        self.btn_files.config(state="disabled")
        self.btn_folder.config(state="disabled")
        self.btn_clear.config(state="disabled")
        self.btn_copy.config(state="disabled")
        self.btn_apply.config(state="disabled")
        cfg = ai.load_config()
        if ai.api_ready(cfg):
            self.status.config(text="正在调用 API 分析 %d 份文件，每份最多 %d 秒…" %
                               (len(self.items), cfg.get("timeout", 20)))
        else:
            self.status.config(text="正在用本地规则分析 %d 份文件…" % len(self.items))
        names = [x.get("name", "") for x in self.items]
        threading.Thread(target=self._worker, args=(names, cfg), daemon=True).start()
        self._poll()

    def _worker(self, names, cfg):
        results = [None] * len(names)
        workers = max(1, min(4, len(names)))
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future = {pool.submit(ai.suggest_category, n, CATS, cfg): i
                          for i, n in enumerate(names)}
                for f in as_completed(future):
                    i = future[f]
                    try:
                        results[i] = f.result()
                    except Exception:
                        results[i] = ai.local_suggest(names[i], CATS)
        except Exception:
            results = [r or ai.local_suggest(names[i], CATS) for i, r in enumerate(results)]
        self._queue.put(("done", results))

    def _poll(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "done":
                    self._finish(payload)
                    return
        except queue.Empty:
            pass
        if self.top.winfo_exists():
            self._poll_id = self.top.after(120, self._poll)

    def _finish(self, results):
        self.busy = False
        self.results = results
        for btn in (self.btn_analyze, self.btn_files, self.btn_folder, self.btn_clear):
            btn.config(state="normal")
        self._render(results)
        api_count = sum(1 for r in results if r.get("source") == "API")
        if api_count:
            detail = "API %d 份 / 本地规则 %d 份" % (api_count, len(results) - api_count)
        else:
            detail = "本地规则 %d 份" % len(results)
        self.status.config(text="已生成 %d 份建议 · %s" % (len(results), detail))
        self.btn_copy.config(state="normal" if results else "disabled")
        self.btn_apply.config(state="normal" if (results and self.on_apply) else "disabled")
        self.hint.config(text="只给建议")

    def _render(self, results):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(results):
            self.tree.insert("", "end", iid="r%d" % i,
                             tags=(("zebra" if i % 2 else ""),
                                   ("api" if r.get("source") == "API" else "")),
                             values=(r.get("file", ""), r.get("cat", ""),
                                     "%.0f%%" % (float(r.get("confidence", 0)) * 100),
                                     r.get("source", ""), r.get("reason", "")))
        if not results and self.items:
            names = [x.get("name", "") for x in self.items]
            for i, name in enumerate(names):
                self.tree.insert("", "end", iid="r%d" % i,
                                 tags=("zebra" if i % 2 else "",),
                                 values=(name, "待分析", "", "", ""))

    # ---------- 结果动作 ----------
    def _copy_one(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        try:
            idx = int(str(iid).lstrip("r"))
        except ValueError:
            return
        if 0 <= idx < len(self.results):
            self._clipboard(ai.format_lines([self.results[idx]]))
            self.status.config(text="已复制这一条建议")

    def copy_all(self):
        if not self.results:
            return
        text = ai.format_lines(self.results)
        text += "\n\n以上仅为建议；入账前请人工确认类别。"
        self._clipboard(text)
        self.status.config(text="已复制 %d 条建议" % len(self.results))

    def _clipboard(self, text):
        try:
            self.top.clipboard_clear()
            self.top.clipboard_append(text)
        except tk.TclError:
            pass

    def apply(self):
        if not self.results or not self.on_apply:
            return
        try:
            self.on_apply(self.results)
        except Exception:
            self.status.config(text="回填类别失败；建议已保留，可先复制清单。")
            return
        self.close()

    def close(self):
        if self._poll_id is not None:
            try:
                self.top.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        try:
            self.top.destroy()
        except tk.TclError:
            pass


def open_advisor(window, items=None, on_apply=None):
    old = getattr(window, "ai_dialog", None)
    if old is not None:
        try:
            if old.top.winfo_exists():
                old.close()
        except Exception:
            pass
    window.ai_dialog = AdvisorDialog(window, items=items, on_apply=on_apply)
    return window.ai_dialog

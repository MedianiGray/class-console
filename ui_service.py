# -*- coding: utf-8 -*-
"""服务留痕：催交、回执、免交 / 延期与交接包的统一流水。"""

import csv
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from theme import FONT, C
from ui_empty import EmptyState
import tts


class ServiceView(ttk.Frame):
    COLS = ("time", "kind", "who", "sid", "cat", "detail", "channel")
    HEADS = {"time": "时间", "kind": "类型", "who": "学生", "sid": "学号",
             "cat": "类别", "detail": "内容", "channel": "渠道"}
    WIDTHS = {"time": 126, "kind": 74, "who": 82, "sid": 84, "cat": 86,
              "detail": 310, "channel": 90}
    KINDS = ("全部", "催交", "回执", "免交", "延期", "已到期",
             "恢复应交", "交接包")

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self.var_q = tk.StringVar()
        self.var_kind = tk.StringVar(value="全部")
        self._rows = {}
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(4, 8))
        tk.Label(top, text="筛选", bg=C["bg"], fg=C["muted"],
                 font=(FONT, 9)).pack(side="left", padx=(0, 6))
        ent = ttk.Entry(top, textvariable=self.var_q, width=24)
        ent.pack(side="left")
        ent.bind("<KeyRelease>", lambda e: self.refresh())
        cb = ttk.Combobox(top, textvariable=self.var_kind, values=self.KINDS,
                          state="readonly", width=10)
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Button(top, text="清空", style="Ghost.TButton",
                   command=self._clear).pack(side="left", padx=8)
        self.summary = ttk.Label(top, text="", style="Muted.TLabel")
        self.summary.pack(side="right")

        cards = tk.Frame(self, bg=C["bg"])
        cards.pack(fill="x", padx=18, pady=(0, 8))
        self.stat_labels = {}
        for key, label, color in (("chases", "近 7 天催交", C["orange"]),
                                  ("receipts", "近 7 天回执", C["green"]),
                                  ("exempt", "有效免交", C["sub"]),
                                  ("deferred", "有效延期", C["primary"])):
            card = tk.Frame(cards, bg=C["card"], highlightthickness=1,
                            highlightbackground=C["line"])
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Frame(card, bg=color, height=3).pack(fill="x")
            tk.Label(card, text=label, bg=C["card"], fg=C["muted"],
                     font=(FONT, 9), anchor="w").pack(fill="x", padx=12, pady=(8, 0))
            val = tk.Label(card, text="0", bg=C["card"], fg=C["text"],
                           font=(FONT, 17, "bold"), anchor="w")
            val.pack(fill="x", padx=12, pady=(0, 8))
            self.stat_labels[key] = val

        # 先占底栏与详情条：两者用 side="bottom" 提前分配高度，
        # 否则下方大表格先按请求高度吃掉空间，底栏的「朗读内容」会被挤出窗口。
        bar = ttk.Frame(self)
        bar.pack(side="bottom", fill="x", padx=18, pady=10)
        self.btn_copy = ttk.Button(bar, text="复制内容", style="Ghost.TButton",
                                   command=self._copy)
        self.btn_speak = ttk.Button(bar, text="朗读内容", style="Ghost.TButton",
                                    command=self._speak)
        self.btn_export = ttk.Button(bar, text="导出服务记录", style="Accent.TButton",
                                     command=self.export_csv)
        self.btn_copy.pack(side="left")
        self.btn_speak.pack(side="left", padx=8)
        self.btn_export.pack(side="right")

        detail = tk.Frame(self, bg=C["card"], highlightthickness=1,
                          highlightbackground=C["line"])
        detail.pack(side="bottom", fill="x", padx=18, pady=(8, 0))
        tk.Label(detail, text="这一条的内容", bg=C["card"], fg=C["sub"],
                 font=(FONT, 9), anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        self.detail = tk.Text(detail, height=3, wrap="word", relief="flat", bd=0,
                              bg=C["card"], fg=C["text"], font=(FONT, 9),
                              padx=0, pady=0, highlightthickness=0)
        self.detail.pack(fill="x", padx=12, pady=(0, 8))

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=18)
        tree_box = tk.Frame(wrap, bg=C["card"], highlightthickness=1,
                            highlightbackground=C["line"])
        tree_box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_box, columns=self.COLS, show="headings",
                                 selectmode="browse")
        for c in self.COLS:
            self.tree.heading(c, text=self.HEADS[c], anchor="w")
            self.tree.column(c, width=self.WIDTHS[c], anchor="w",
                             stretch=(c == "detail"))
        self.tree.tag_configure("zebra", background=C["zebra"])
        self.tree.tag_configure("orange", foreground=C["orange"])
        self.tree.tag_configure("green", foreground=C["green"])
        self.tree.tag_configure("red", foreground=C["red"])
        ysb = ttk.Scrollbar(tree_box, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(tree_box, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.empty = EmptyState(tree_box, wraplength=420)

    def _clear(self):
        self.var_q.set("")
        self.var_kind.set("全部")
        self.refresh()

    def refresh(self):
        stats = self.repo.service_stats()
        for key, val in stats.items():
            if key in self.stat_labels:
                self.stat_labels[key].config(text=str(val))
        all_rows = self.repo.service_feed(limit=2000)
        q = (self.var_q.get() or "").strip().lower()
        kind = self.var_kind.get()
        rows = []
        for r in all_rows:
            if kind != "全部" and r.get("kind") != kind:
                continue
            hay = " ".join(str(r.get(k) or "") for k in
                           ("who", "sid", "cat", "detail", "channel", "actor")).lower()
            if q and q not in hay:
                continue
            rows.append(r)
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        for i, r in enumerate(rows):
            tag = "zebra" if i % 2 else ""
            if r.get("kind") in ("催交", "已到期"):
                tag = "orange"
            elif r.get("kind") in ("回执", "免交"):
                tag = "green"
            iid = self.tree.insert("", "end", tags=(tag,), values=(
                r.get("time", ""), r.get("kind", ""), r.get("who", ""),
                r.get("sid", ""), r.get("cat", ""), r.get("detail", ""),
                r.get("channel", "")))
            self._rows[iid] = r
        shown = len(rows)
        total = len(all_rows)
        self.summary.config(text=("共 %d 条服务记录" % total if shown == total else
                                  "匹配 %d / 共 %d 条" % (shown, total)))
        if rows:
            self.empty.hide()
        elif total:
            self.empty.set("没有匹配的服务记录",
                           "现有流水被关键词或类型筛选挡住了，清空筛选即可看到全部。",
                           "清空筛选", self._clear)
            self.empty.show_place()
            self._set_detail(None)
        else:
            self.empty.set("还没有服务记录",
                           "免交、延期、回执、催交都会留在这里；到完成矩阵选中一行即可登记。",
                           "去名单矩阵", lambda: self.window.switch("roster"))
            self.empty.show_place()
            self._set_detail(None)
        self.btn_copy.config(state="normal" if rows else "disabled")
        self.btn_speak.config(state="normal" if rows else "disabled")

    def _speak(self):
        """朗读当前选中的服务记录；再点一次停止。"""
        if tts.is_speaking():
            tts.stop()
            self.btn_speak.config(text="朗读内容")
            self.window.toast("已停止朗读")
            return
        iid = self.tree.focus()
        row = self._rows.get(iid)
        if not row:
            self.window.toast("先选中一条服务记录")
            return
        text = "%s，%s，%s。%s" % (
            row.get("kind", ""), row.get("who", ""), row.get("cat", ""),
            row.get("detail", ""))
        ok, why = tts.speak(text)
        if not ok:
            self.window.toast(why or "系统语音不可用")
            return
        self.btn_speak.config(text="停止朗读")
        self.window.toast("正在朗读，再点一次可停止")
        self.after(400, self._watch_speak)

    def _watch_speak(self):
        if tts.is_speaking():
            self.after(400, self._watch_speak)
            return
        self.btn_speak.config(text="朗读内容")

    def _set_detail(self, row):
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        if row:
            text = "%s · %s\n%s\n经办：%s　来源：%s" % (
                row.get("time", ""), row.get("kind", ""),
                row.get("detail", ""), row.get("actor", ""),
                row.get("channel", ""))
            self.detail.insert("1.0", text)
        else:
            self.detail.insert("1.0", "选中一条记录后，这里显示完整话术或备注。")
        self.detail.config(state="disabled")

    def _on_select(self, _event=None):
        iid = self.tree.focus()
        self._set_detail(self._rows.get(iid))

    def _copy(self):
        iid = self.tree.focus()
        row = self._rows.get(iid)
        if not row:
            return
        text = row.get("detail", "")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.window.toast("服务内容已复制")

    def export_csv(self):
        path = filedialog.asksaveasfilename(
            title="导出服务记录", defaultextension=".csv",
            initialfile="服务留痕.csv",
            filetypes=[("CSV 表格", "*.csv")])
        if not path:
            return
        rows = [self._rows[i] for i in self.tree.get_children()]
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["时间", "类型", "学生", "学号", "类别", "内容",
                            "渠道", "经办"])
                for r in rows:
                    w.writerow([r.get("time", ""), r.get("kind", ""),
                                r.get("who", ""), r.get("sid", ""),
                                r.get("cat", ""), r.get("detail", ""),
                                r.get("channel", ""), r.get("actor", "")])
        except OSError as e:
            messagebox.showerror("导出失败", str(e))
            return
        self.window.toast("已导出 %d 条服务记录" % len(rows))

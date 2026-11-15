# -*- coding: utf-8 -*-
"""工作台概览看板：统计卡片、类别分布、待审核置顶、近期动态。

全部数据由现有仓库方法聚合得到，不新增写入流程；跳转台账由主窗口 switch 完成。
"""

import tkinter as tk
from tkinter import ttk

from theme import FONT, C


class DashboardView(ttk.Frame):
    CATS = ["团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self._build()

    def _build(self):
        header = ttk.Frame(self)
        header.pack(fill="x", padx=18, pady=(16, 12))
        ttk.Label(header, text="工作台概览", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="材料收集、审核与留痕一览", style="Sub.TLabel").pack(side="left", padx=10)

        # 统计卡片
        cards = ttk.Frame(self)
        cards.pack(fill="x", padx=18)
        self.card_values = {}
        card_defs = [
            ("total", "材料总数", C["text"]),
            ("pending", "待审核", C["orange"]),
            ("archived", "已归档", C["green"]),
            ("rejected", "已驳回", C["red"]),
        ]
        for i, (key, label, color) in enumerate(card_defs):
            card = tk.Frame(cards, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            cards.columnconfigure(i, weight=1)
            num = tk.Label(card, text="0", font=(FONT, 24, "bold"), fg=color, bg=C["card"])
            num.pack(anchor="w", padx=16, pady=(14, 2))
            tk.Label(card, text=label, font=(FONT, 10), fg=C["muted"],
                     bg=C["card"]).pack(anchor="w", padx=16, pady=(0, 14))
            self.card_values[key] = num

        # 名单 / 任务摘要入口
        notice = ttk.Frame(self)
        notice.pack(fill="x", padx=18, pady=(10, 0))
        self.roster_hint = tk.Label(notice, text="", fg=C["primary"], cursor="hand2",
                                    bg=C["bg"])
        self.roster_hint.pack(side="left")
        self.task_hint = tk.Label(notice, text="", fg=C["primary"], cursor="hand2",
                                  bg=C["bg"])
        self.task_hint.pack(side="left", padx=16)
        self.roster_hint.bind("<Button-1>", lambda e: self.window.switch("roster"))
        self.task_hint.bind("<Button-1>", lambda e: self.window.switch("tasks"))

        # 中部两栏：类别分布 / 近期动态
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=18, pady=(14, 0))
        mid.columnconfigure(0, weight=1, uniform="m")
        mid.columnconfigure(1, weight=1, uniform="m")

        left = ttk.LabelFrame(mid, text="类别分布")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.cat_box = tk.Frame(left, bg=C["card"])
        self.cat_box.pack(fill="both", expand=True, padx=12, pady=10)

        right = ttk.LabelFrame(mid, text="近期动态")
        right.grid(row=0, column=1, sticky="nsew")
        log_cols = ("time", "who", "act", "obj")
        self.log_tree = ttk.Treeview(right, columns=log_cols, show="headings", selectmode="browse")
        log_heads = {"time": "时间", "who": "操作人", "act": "动作", "obj": "对象"}
        log_widths = {"time": 110, "who": 90, "act": 70, "obj": 220}
        for c in log_cols:
            self.log_tree.heading(c, text=log_heads[c])
            self.log_tree.column(c, width=log_widths[c], anchor="w", stretch=True)
        self.log_tree.pack(fill="both", expand=True, padx=12, pady=10)

        # 底部：待审核置顶
        bottom = ttk.LabelFrame(self, text="待审核 · 需处理")
        bottom.pack(fill="both", expand=True, padx=18, pady=(14, 16))
        doc_cols = ("name", "who", "sid", "time")
        self.doc_tree = ttk.Treeview(bottom, columns=doc_cols, show="headings", selectmode="browse")
        doc_heads = {"name": "材料名称", "who": "提交人", "sid": "学号", "time": "提交时间"}
        doc_widths = {"name": 300, "who": 100, "sid": 100, "time": 130}
        for c in doc_cols:
            self.doc_tree.heading(c, text=doc_heads[c])
            self.doc_tree.column(c, width=doc_widths[c], anchor="w", stretch=True)
        self.doc_tree.pack(fill="both", expand=True, padx=12, pady=10)
        self.doc_tree.bind("<Double-1>", lambda e: self.window.switch("docs"))

        self.doc_empty = ttk.Label(bottom, text="暂无待审核材料", style="Muted.TLabel")

    def refresh(self):
        try:
            docs = self.repo.list_docs()
            logs = self.repo.list_logs()
        except Exception as e:
            self.window.show_status("看板加载失败：%s" % e)
            return

        pending = [d for d in docs if d.get("status") == "待审核"]
        archived = [d for d in docs if d.get("status") == "已归档"]
        rejected = [d for d in docs if d.get("status") == "已驳回"]
        counts = {"total": len(docs), "pending": len(pending),
                  "archived": len(archived), "rejected": len(rejected)}
        for k, lbl in self.card_values.items():
            lbl.config(text=str(counts[k]))

        # 类别分布
        for w in self.cat_box.winfo_children():
            w.destroy()
        total = len(docs) or 1
        for cat in self.CATS:
            n = sum(1 for d in docs if d.get("cat") == cat)
            row = tk.Frame(self.cat_box, bg=C["card"])
            row.pack(fill="x", pady=4)
            tk.Label(row, text=cat, width=10, anchor="w", bg=C["card"],
                     fg=C["text"]).pack(side="left")
            bar_bg = tk.Frame(row, bg=C["line"], height=10)
            bar_bg.pack(side="left", fill="x", expand=True, padx=8)
            if n > 0:
                bar = tk.Frame(bar_bg, bg=C["primary"], height=10)
                bar.pack(side="left", fill="y", ipadx=int(160 * n / total))
            tk.Label(row, text=str(n), width=4, anchor="e", bg=C["card"],
                     fg=C["muted"]).pack(side="right")

        # 近期动态（最近 6 条）
        self.log_tree.delete(*self.log_tree.get_children())
        for l in logs[:6]:
            self.log_tree.insert("", "end", values=(
                l.get("time", ""), l.get("who", ""), l.get("act", ""), l.get("obj", "")))

        # 待审核置顶（最多 5 条）
        self.doc_tree.delete(*self.doc_tree.get_children())
        for d in pending[:5]:
            self.doc_tree.insert("", "end", tags=(d.get("id"),), values=(
                d.get("name", ""), d.get("who", ""), d.get("sid", ""), d.get("time", "")))
        if pending:
            self.doc_empty.place_forget()
        else:
            self.doc_empty.place(relx=0.5, rely=0.5, anchor="center")

        # 名单 / 任务摘要（容错：旧数据缺表不阻断看板）
        try:
            chk = self.repo.roster_check()
            self.roster_hint.config(text="未交 %d 人 · 查看名单核对" % len(chk["absent"]))
            st = self.repo.task_stats()
            self.task_hint.config(text="临期 %d · 逾期 %d · 查看任务跟踪" % (st["due"], st["overdue"]))
        except Exception:
            self.roster_hint.config(text="")
            self.task_hint.config(text="")

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
        # 统计卡片
        cards = ttk.Frame(self)
        cards.pack(fill="x", padx=18, pady=(4, 0))
        self.card_values = {}
        card_defs = [
            ("total", "材料总数", C["text"]),
            ("pending", "待审核", C["orange"]),
            ("archived", "已归档", C["green"]),
            ("rejected", "已驳回", C["red"]),
        ]
        for i, (key, label, color) in enumerate(card_defs):
            card = tk.Frame(cards, bg=C["card"], highlightthickness=0)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            cards.columnconfigure(i, weight=1)
            row = tk.Frame(card, bg=C["card"])
            row.pack(fill="x", padx=14, pady=12)
            num = tk.Label(row, text="0", font=(FONT, 20, "bold"), fg=color, bg=C["card"])
            num.pack(side="left", padx=(0, 10))
            tk.Label(row, text=label, font=(FONT, 10), fg=C["muted"],
                     bg=C["card"]).pack(side="left", anchor="s")
            self.card_values[key] = num

        # 名单 / 任务摘要入口（浅底 chip）
        notice = ttk.Frame(self)
        notice.pack(fill="x", padx=18, pady=(10, 0))
        self.roster_chip, self.roster_hint = self._make_chip(notice)
        self.roster_chip.pack(side="left")
        self.task_chip, self.task_hint = self._make_chip(notice)
        self.task_chip.pack(side="left", padx=10)
        self.roster_hint.bind("<Button-1>", lambda e: self.window.switch("roster"))
        self.task_hint.bind("<Button-1>", lambda e: self.window.switch("tasks"))

        # 待办置顶（标题与内容按岗位区分处理 / 跟进 / 本人关注）
        self.bottom_frame = ttk.LabelFrame(self, text="待审核 · 需处理")
        bottom = self.bottom_frame
        bottom.pack(fill="x", padx=18, pady=(14, 0))
        doc_cols = ("name", "who", "sid", "time")
        self.doc_tree = ttk.Treeview(bottom, columns=doc_cols, show="headings",
                                     selectmode="browse", height=5)
        doc_heads = {"name": "材料名称", "who": "提交人", "sid": "学号", "time": "提交时间"}
        doc_widths = {"name": 300, "who": 100, "sid": 100, "time": 130}
        for c in doc_cols:
            self.doc_tree.heading(c, text=doc_heads[c])
            self.doc_tree.column(c, width=doc_widths[c], anchor="w", stretch=True)
        self.doc_tree.pack(fill="x", padx=12, pady=10)
        self.doc_tree.bind("<Double-1>", lambda e: self.window.switch("docs"))

        self.doc_empty = ttk.Label(bottom, text="暂无待审核材料", style="Muted.TLabel")

        # 中部两栏：类别分布 / 近期动态（占据剩余空间）
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=18, pady=(14, 16))
        mid.columnconfigure(0, weight=1, uniform="m")
        mid.columnconfigure(1, weight=1, uniform="m")

        left = ttk.LabelFrame(mid, text="类别分布")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.cat_box = tk.Frame(left, bg=C["card"])
        self.cat_box.pack(fill="both", expand=True, padx=12, pady=10)

        self.right_frame = ttk.LabelFrame(mid, text="近期动态")
        right = self.right_frame
        right.grid(row=0, column=1, sticky="nsew")
        log_cols = ("time", "who", "act", "obj")
        self.log_tree = ttk.Treeview(right, columns=log_cols, show="headings", selectmode="browse")
        log_heads = {"time": "时间", "who": "操作人", "act": "动作", "obj": "对象"}
        log_widths = {"time": 92, "who": 76, "act": 58, "obj": 180}
        for c in log_cols:
            self.log_tree.heading(c, text=log_heads[c])
            self.log_tree.column(c, width=log_widths[c], anchor="w", stretch=True)
        self.log_tree.pack(fill="both", expand=True, padx=12, pady=10)

    def _make_chip(self, parent):
        chip = tk.Frame(parent, bg=C["primary_soft"])
        lbl = tk.Label(chip, text="", fg=C["primary"], bg=C["primary_soft"],
                       cursor="hand2", font=(FONT, 10))
        lbl.pack(padx=12, pady=6)
        return chip, lbl

    def refresh(self):
        try:
            docs = self.repo.list_docs()
            logs = self.repo.list_logs()
        except Exception as e:
            self.window.show_status("看板加载失败：%s" % e)
            return

        can_archive = self.window.can("docs:archive")
        can_roster = self.window.can("roster:manage")
        can_task = self.window.can("task:manage")
        can_logs = self.window.can("logs:view")
        is_applicant = self.window.role == "applicant"

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
                bar.place(relwidth=n / total, relheight=1, rely=0)
            tk.Label(row, text=str(n), width=4, anchor="e", bg=C["card"],
                     fg=C["muted"]).pack(side="right")

        # 近期动态：仅日志查看权限可见
        if can_logs:
            self.right_frame.grid()
            self.log_tree.delete(*self.log_tree.get_children())
            for l in logs[:6]:
                self.log_tree.insert("", "end", values=(
                    l.get("time", ""), l.get("who", ""), l.get("act", ""), l.get("obj", "")))
        else:
            self.right_frame.grid_remove()

        # 待办队列：审核岗处理待审，经办人跟进，申请人看本人需关注项
        if is_applicant:
            focus = pending + rejected
            self.bottom_frame.config(text="需我关注的材料（%d）" % len(focus))
        elif can_archive:
            focus = pending
            self.bottom_frame.config(text="待审核 · 需处理（%d）" % len(pending))
        else:
            focus = pending
            self.bottom_frame.config(text="待审核 · 跟进（%d）" % len(pending))
        self.doc_tree.delete(*self.doc_tree.get_children())
        for d in focus[:5]:
            self.doc_tree.insert("", "end", tags=(d.get("id"),), values=(
                d.get("name", ""), d.get("who", ""), d.get("sid", ""), d.get("time", "")))
        if focus:
            self.doc_empty.place_forget()
        else:
            self.doc_empty.place(relx=0.5, rely=0.5, anchor="center")

        # 名单 / 任务摘要 chip：按权限显隐（容错：旧数据缺表不阻断看板）
        if can_roster:
            self.roster_chip.pack(side="left")
            try:
                chk = self.repo.roster_check()
                self.roster_hint.config(text="未交 %d 人 · 查看名单核对" % len(chk["absent"]))
            except Exception:
                self.roster_hint.config(text="")
        else:
            self.roster_chip.pack_forget()

        if can_task:
            self.task_chip.pack(side="left", padx=10)
            try:
                st = self.repo.task_stats()
                self.task_hint.config(text="临期 %d · 逾期 %d · 查看任务跟踪" % (st["due"], st["overdue"]))
            except Exception:
                self.task_hint.config(text="")
        else:
            self.task_chip.pack_forget()

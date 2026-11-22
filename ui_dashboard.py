# -*- coding: utf-8 -*-
"""工作台概览：一条主视觉带（待办 + 指标）＋ 待办表 / 类别分布 ＋ 近期动态。

信息层级从高到低：主视觉带（tint 底、数字最大）→ 卡片标题行 → 表体。
所有数据来自现有仓库方法，不新增写入流程。
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

    # ---------- 构件 ----------
    def _card(self, parent, title, sub="", link=None, command=None):
        card = tk.Frame(parent, bg=C["card"], highlightthickness=1,
                        highlightbackground=C["line"], highlightcolor=C["line"])
        head = tk.Frame(card, bg=C["card"])
        head.pack(fill="x", padx=16, pady=(13, 0))
        tk.Label(head, text=title, bg=C["card"], fg=C["text"],
                 font=(FONT, 10, "bold"), anchor="w").pack(side="left")
        if sub:
            tk.Label(head, text=sub, bg=C["card"], fg=C["sub"],
                     font=(FONT, 9)).pack(side="left", padx=(8, 0))
        if link:
            lbl = tk.Label(head, text=link + " →", bg=C["card"], fg=C["primary"],
                           font=(FONT, 9), cursor="hand2")
            lbl.pack(side="right")
            if command:
                lbl.bind("<Button-1>", lambda e: command())
        body = tk.Frame(card, bg=C["card"])
        body.pack(fill="both", expand=True, padx=16, pady=(10, 14))
        return card, body

    def _stat(self, parent, label, color):
        cell = tk.Frame(parent, bg=C["hero"])
        cell.pack(side="left", fill="both", expand=True)
        row = tk.Frame(cell, bg=C["hero"])
        row.pack(anchor="w", padx=(18, 0), pady=(18, 0))
        tk.Frame(row, bg=color, width=5, height=5).pack(side="left", pady=(3, 0))
        tk.Label(row, text=label, bg=C["hero"], fg=C["sub"],
                 font=(FONT, 9)).pack(side="left", padx=(6, 0))
        num = tk.Label(cell, text="0", bg=C["hero"], fg=C["text"],
                       font=(FONT, 20, "bold"), anchor="w")
        num.pack(anchor="w", padx=18, pady=(2, 16))
        return num

    def _build(self):
        self.columnconfigure(0, weight=2, uniform="g")
        self.columnconfigure(1, weight=1, uniform="g")
        self.rowconfigure(1, weight=1)

        # ---- 主视觉带：待办 + 指标，同一表面，避免四个白盒并排 ----
        hero = tk.Frame(self, bg=C["hero"], highlightthickness=1,
                        highlightbackground=C["hero_line"])
        hero.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        hero.columnconfigure(1, weight=1)

        left = tk.Frame(hero, bg=C["hero"])
        left.grid(row=0, column=0, sticky="nsw", padx=(20, 18), pady=12)
        tk.Label(left, text="待我处理", bg=C["hero"], fg=C["accent_ink"],
                 font=(FONT, 9, "bold")).pack(anchor="w")
        num_row = tk.Frame(left, bg=C["hero"])
        num_row.pack(anchor="w", pady=(1, 0))
        self.hero_num = tk.Label(num_row, text="0", bg=C["hero"], fg=C["text"],
                                 font=(FONT, 27, "bold"))
        self.hero_num.pack(side="left")
        tk.Label(num_row, text="项", bg=C["hero"], fg=C["sub"],
                 font=(FONT, 9)).pack(side="left", padx=(5, 0), pady=(14, 0))
        self.hero_hint = tk.Label(left, text="", bg=C["hero"], fg=C["sub"],
                                  font=(FONT, 9), anchor="w", justify="left")
        self.hero_hint.pack(anchor="w", pady=(1, 8))
        actions = tk.Frame(left, bg=C["hero"])
        actions.pack(anchor="w")
        self.btn_go = tk.Button(actions, text="打开材料台账", relief="flat", bd=0,
                                bg=C["primary"], fg=C["on_primary"],
                                activebackground=C["primary_hover"],
                                activeforeground=C["on_primary"], font=(FONT, 9, "bold"),
                                padx=12, pady=4, cursor="hand2",
                                command=lambda: self.window.switch("docs"))
        self.btn_go.pack(side="left")

        # 指标：右半区，hairline 分隔，数字 20 号，弱于主数字但强于正文
        right = tk.Frame(hero, bg=C["hero"])
        right.grid(row=0, column=1, sticky="nse", pady=12)
        tk.Frame(right, bg=C["hero"], width=1).pack(side="left", fill="y")
        box = tk.Frame(right, bg=C["hero"])
        box.pack(side="left", fill="y")
        self.card_values = {}
        for i, (key, label, color) in enumerate([
                ("total", "材料总数", C["sub"]),
                ("archived", "已归档", C["green"]),
                ("rejected", "已驳回", C["red"])]):
            if i:
                tk.Frame(box, bg=C["hero_line"], width=1).pack(side="left", fill="y", pady=14)
            self.card_values[key] = self._stat(box, label, color)
        self.card_values["pending"] = self.hero_num

        # 副线提示（未交 / 临期）：贴在主视觉带右下，小字不抢戏
        notices = tk.Frame(hero, bg=C["hero"])
        notices.grid(row=0, column=1, sticky="se", padx=(0, 18), pady=(0, 10))
        self.roster_hint = tk.Label(notices, text="", bg=C["hero"], fg=C["sub"],
                                    font=(FONT, 9), cursor="hand2")
        self.roster_hint.pack(side="left")
        self.task_hint = tk.Label(notices, text="", bg=C["hero"], fg=C["sub"],
                                  font=(FONT, 9), cursor="hand2")
        self.task_hint.pack(side="left", padx=(14, 0))
        self.roster_hint.bind("<Button-1>", lambda e: self.window.switch("roster"))
        self.task_hint.bind("<Button-1>", lambda e: self.window.switch("tasks"))

        # ---- 待办表（主栏）----
        self.pending_card, body = self._card(self, "待办队列", "按提交先后", "全部",
                                             lambda: self.window.switch("docs"))
        self.pending_card.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        self.bottom_title = tk.Label(body, text="", bg=C["card"], fg=C["sub"],
                                     font=(FONT, 9), anchor="w")
        self.bottom_title.pack(fill="x", pady=(0, 6))
        doc_cols = ("name", "who", "time")
        self.doc_tree = ttk.Treeview(body, columns=doc_cols, show="headings",
                                     selectmode="browse", height=4)
        heads = {"name": "材料名称", "who": "提交人", "time": "提交时间"}
        widths = {"name": 260, "who": 96, "time": 118}
        for c in doc_cols:
            self.doc_tree.heading(c, text=heads[c], anchor="w")
            self.doc_tree.column(c, width=widths[c], anchor="w", stretch=(c == "name"))
        self.doc_tree.pack(fill="both", expand=True)
        self.doc_tree.bind("<Double-1>", lambda e: self.window.switch("docs"))
        self.doc_empty = tk.Label(body, text="待办已清空，可以开始新的归档", bg=C["card"],
                                  fg=C["muted"], font=(FONT, 9))

        # ---- 类别分布（侧栏）----
        self.cat_card, cat_body = self._card(self, "类别分布", "", "台账",
                                             lambda: self.window.switch("docs"))
        self.cat_card.grid(row=1, column=1, sticky="nsew")
        self.cat_box = tk.Frame(cat_body, bg=C["card"])
        self.cat_box.pack(fill="both", expand=True)
        self.cat_total = tk.Label(cat_body, text="", bg=C["card"], fg=C["sub"],
                                  font=(FONT, 9), anchor="w")
        self.cat_total.pack(fill="x", pady=(8, 0))

        # ---- 近期动态（跨两栏）：用列表而不是表格，比台账更轻 ----
        self.log_card, log_body = self._card(self, "近期动态", "最近 4 条", "日志",
                                            lambda: self.window.switch("logs"))
        self.log_card.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.log_box = tk.Frame(log_body, bg=C["card"])
        self.log_box.pack(fill="x")

    # ---------- 数据 ----------
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

        # 主视觉：数字 + 一句话说明 + 按钮文案
        if is_applicant:
            focus = pending + rejected
            mine = [d for d in focus]
            self.hero_num.config(text=str(len(mine)))
            self.hero_hint.config(text="项材料等待处理或需补充" if mine else "暂无待处理材料")
            self.btn_go.config(text="查看我的材料")
        elif can_archive:
            focus = pending
            self.hero_num.config(text=str(len(pending)))
            if pending:
                oldest = min(pending, key=lambda d: d.get("time", ""))
                self.hero_hint.config(text="最早：%s · %s" %
                                      (oldest.get("name", "")[:16], oldest.get("who", "")))
            else:
                self.hero_hint.config(text="队列已清空，归档流程无积压")
            self.btn_go.config(text="处理待审材料")
        else:
            focus = pending
            self.hero_num.config(text=str(len(pending)))
            self.hero_hint.config(text=("最近提交：%s" % pending[0].get("name", "")[:18])
                                  if pending else "暂无待审核材料")
            self.btn_go.config(text="查看材料台账")

        # 待办表
        if is_applicant:
            tname = "需我关注"
        elif can_archive:
            tname = "待处理"
        else:
            tname = "待跟进"
        self.bottom_title.config(text="%s %d 条 · 显示前 %d 条" % (tname, len(focus), min(len(focus), 4)))
        self.doc_tree.delete(*self.doc_tree.get_children())
        for d in focus[:5]:
            self.doc_tree.insert("", "end", tags=(d.get("id"),), values=(
                d.get("name", ""), d.get("who", ""), d.get("time", "")))
        if focus:
            self.doc_empty.pack_forget()
        else:
            self.doc_empty.pack(pady=(6, 0))

        # 类别分布：横条 + 百分比，数字右对齐
        for w in self.cat_box.winfo_children():
            w.destroy()
        total = len(docs) or 1
        for cat in self.CATS:
            n = sum(1 for d in docs if d.get("cat") == cat)
            row = tk.Frame(self.cat_box, bg=C["card"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=cat, width=9, anchor="w", bg=C["card"],
                     fg=C["text"], font=(FONT, 9)).pack(side="left")
            bar_bg = tk.Frame(row, bg=C["surface_alt"], height=6)
            bar_bg.pack(side="left", fill="x", expand=True, padx=(0, 8))
            if n > 0:
                bar = tk.Frame(bar_bg, bg=C["primary"], height=6)
                bar.place(relwidth=n / total, relheight=1, rely=0)
            tk.Label(row, text=str(n), width=3, anchor="e", bg=C["card"],
                     fg=C["text"], font=(FONT, 9)).pack(side="right")
        self.cat_total.config(text="共 %d 条 · 覆盖 %d 类" %
                              (len(docs), len([c for c in self.CATS
                                               if any(d.get("cat") == c for d in docs)])))

        # 近期动态
        if can_logs:
            self.log_card.grid()
            for w in self.log_box.winfo_children():
                w.destroy()
            for l in logs[:4]:
                row = tk.Frame(self.log_box, bg=C["card"])
                row.pack(fill="x", pady=2)
                row.columnconfigure(3, weight=1)
                tk.Label(row, text=l.get("time", ""), bg=C["card"], fg=C["sub"],
                         font=(FONT, 9), width=13, anchor="w").grid(row=0, column=0, sticky="w")
                tk.Label(row, text=l.get("who", ""), bg=C["card"], fg=C["text"],
                         font=(FONT, 9), width=7, anchor="w").grid(row=0, column=1, sticky="w")
                tk.Label(row, text=l.get("act", ""), bg=C["card"], fg=C["accent_ink"],
                         font=(FONT, 9), width=5, anchor="w").grid(row=0, column=2, sticky="w")
                tk.Label(row, text=l.get("obj", ""), bg=C["card"], fg=C["muted"],
                         font=(FONT, 9), anchor="w").grid(row=0, column=3, sticky="w")
        else:
            self.log_card.grid_remove()

        # 副线提示
        self.roster_hint.pack_forget()
        self.task_hint.pack_forget()
        if can_roster:
            self.roster_hint.pack(side="left")
            try:
                chk = self.repo.roster_check()
                self.roster_hint.config(text="未交 %d 人 · 名单核对" % len(chk["absent"]))
            except Exception:
                self.roster_hint.config(text="")
        if can_task:
            self.task_hint.pack(side="left", padx=(14, 0))
            try:
                st = self.repo.task_stats()
                self.task_hint.config(text="临期 %d · 逾期 %d" % (st["due"], st["overdue"]))
            except Exception:
                self.task_hint.config(text="")

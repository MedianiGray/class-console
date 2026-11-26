# -*- coding: utf-8 -*-
"""工作台概览：一条主视觉带（待办 + 指标）＋ 待办表 / 类别分布 ＋ 近期动态。

信息层级从高到低：主视觉带（tint 底、数字最大）→ 卡片标题行 → 表体。
所有数据来自现有仓库方法，不新增写入流程。
"""

import tkinter as tk
from tkinter import ttk

from theme import FONT, C
from ui_empty import EmptyState


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
        self.canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0, bd=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")

        content = ttk.Frame(self.canvas)
        self.inner = content
        self._inner_window = self.canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", self._on_inner_config)
        self.canvas.bind("<Configure>", self._on_canvas_config)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")

        content.columnconfigure(0, weight=2, uniform="g")
        content.columnconfigure(1, weight=1, uniform="g")
        content.rowconfigure(2, weight=1)

        # ---- 首次引导：先留占位；已完成/已收起的用户不再构建内部控件 ----
        self.first_card = tk.Frame(content, bg=C["card"], highlightthickness=1,
                                   highlightbackground=C["line"])
        self.first_card.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self._first_run_built = False
        self.fr_rows = []

        # ---- 主视觉带：待办 + 指标，同一表面，避免四个白盒并排 ----
        hero = tk.Frame(content, bg=C["hero"], highlightthickness=1,
                        highlightbackground=C["hero_line"])
        hero.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
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
        self.pending_card, body = self._card(content, "待办队列", "按提交先后", "全部",
                                             lambda: self.window.switch("docs"))
        self.pending_card.grid(row=2, column=0, sticky="nsew", padx=(0, 12))
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
        # 空态按需创建：有材料时它从头到尾都用不上，不必占首帧的构建时间
        self._doc_empty_parent = body
        self.doc_empty = None

        # ---- 类别分布（侧栏）----
        self.cat_card, cat_body = self._card(content, "类别分布", "", "台账",
                                             lambda: self.window.switch("docs"))
        self.cat_card.grid(row=2, column=1, sticky="nsew")
        self.cat_box = tk.Frame(cat_body, bg=C["card"])
        self.cat_box.pack(fill="both", expand=True)
        self.cat_total = tk.Label(cat_body, text="", bg=C["card"], fg=C["sub"],
                                  font=(FONT, 9), anchor="w")
        self.cat_total.pack(fill="x", pady=(8, 0))

        # ---- 近期动态（跨两栏）：用列表而不是表格，比台账更轻 ----
        self.log_card, log_body = self._card(content, "近期动态", "最近 4 条", "日志",
                                            lambda: self.window.switch("logs"))
        self.log_card.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.log_box = tk.Frame(log_body, bg=C["card"])
        self.log_box.pack(fill="x")
        self._log_empty_parent = log_body
        self.log_empty = None

    # ---------- 滚动 ----------
    def _on_inner_config(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_config(self, event):
        self.canvas.itemconfigure(self._inner_window, width=event.width)

    def _on_wheel(self, event):
        if not self.winfo_ismapped():
            return
        x, y = self.winfo_pointerxy()
        if not (self.winfo_rootx() <= x < self.winfo_rootx() + self.winfo_width()
                and self.winfo_rooty() <= y < self.winfo_rooty() + self.winfo_height()):
            return
        try:
            widget = self.winfo_containing(x, y)
            if widget is not None and widget.winfo_class() == "Treeview":
                return
        except Exception:
            pass
        delta = int(-event.delta / 120) if event.delta else 0
        if delta:
            self.canvas.yview_scroll(delta, "units")

    # ---------- 数据 ----------
    def _ensure_cat_rows(self):
        """类别分布最多六行，建一次就够；后续刷新只改文字和比例。"""
        if getattr(self, "_cat_rows", None):
            return
        self._cat_rows = []
        for cat in self.CATS:
            row = tk.Frame(self.cat_box, bg=C["card"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=cat, width=9, anchor="w", bg=C["card"],
                     fg=C["text"], font=(FONT, 9)).pack(side="left")
            bar_bg = tk.Frame(row, bg=C["surface_alt"], height=6)
            bar_bg.pack(side="left", fill="x", expand=True, padx=(0, 8))
            bar = tk.Frame(bar_bg, bg=C["primary"], height=6)
            num = tk.Label(row, text="0", width=3, anchor="e", bg=C["card"],
                           fg=C["text"], font=(FONT, 9))
            num.pack(side="right")
            self._cat_rows.append((cat, 0, bar, num))

    def _ensure_log_rows(self):
        """近期动态固定四行，行内四个单元格只建一次。"""
        if getattr(self, "_log_rows", None):
            return
        self._log_rows = []
        for _i in range(4):
            row = tk.Frame(self.log_box, bg=C["card"])
            row.columnconfigure(3, weight=1)
            cells = [
                tk.Label(row, text="", bg=C["card"], fg=C["sub"], font=(FONT, 9),
                         width=13, anchor="w"),
                tk.Label(row, text="", bg=C["card"], fg=C["text"], font=(FONT, 9),
                         width=7, anchor="w"),
                tk.Label(row, text="", bg=C["card"], fg=C["accent_ink"], font=(FONT, 9),
                         width=5, anchor="w"),
                tk.Label(row, text="", bg=C["card"], fg=C["muted"], font=(FONT, 9),
                         anchor="w"),
            ]
            for col, lbl in enumerate(cells):
                lbl.grid(row=0, column=col, sticky="w")
            self._log_rows.append(cells)

    def _empty_state(self, name, parent, wraplength):
        """空态只在真的要显示时才建，避免每次启动都为它付控件构建开销。"""
        state = getattr(self, name, None)
        if state is None:
            state = EmptyState(parent, wraplength=wraplength)
            setattr(self, name, state)
        return state

    def _build_first_run(self):
        """首次需要显示引导时再建控件，避免已完成用户每次启动都付这份 Tk 开销。"""
        if self._first_run_built:
            return
        fr_head = tk.Frame(self.first_card, bg=C["card"])
        fr_head.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(fr_head, text="三步上手", bg=C["card"], fg=C["text"],
                 font=(FONT, 10, "bold")).pack(side="left")
        self.fr_count = tk.Label(fr_head, text="0 / 3", bg=C["primary_soft"], fg=C["primary"],
                                 font=(FONT, 8, "bold"), padx=8, pady=2)
        self.fr_count.pack(side="left", padx=(8, 0))
        self.fr_dismiss = tk.Button(fr_head, text="收起", relief="flat", bd=0,
                                    bg=C["card"], fg=C["sub"], activebackground=C["bg_soft"],
                                    activeforeground=C["text"], font=(FONT, 9), cursor="hand2",
                                    command=self.window.dismiss_first_run)
        self.fr_dismiss.pack(side="right")
        help_lbl = tk.Label(fr_head, text="使用帮助 →", bg=C["card"], fg=C["primary"],
                            font=(FONT, 9), cursor="hand2")
        help_lbl.pack(side="right", padx=(0, 14))
        help_lbl.bind("<Button-1>", lambda e: self.window.open_help())
        tk.Label(self.first_card, text="不弹欢迎页。完成一次提交 → 审核 → 归档，这张卡会自动收起。",
                 bg=C["card"], fg=C["muted"], font=(FONT, 9), anchor="w").pack(
                     fill="x", padx=18, pady=(2, 10))

        self.fr_steps = tk.Frame(self.first_card, bg=C["card"])
        self.fr_steps.pack(fill="x", padx=18, pady=(0, 14))
        for i in range(3):
            self.fr_steps.columnconfigure(i, weight=1, uniform="fr")
            cell = tk.Frame(self.fr_steps, bg=C["bg_soft"], highlightthickness=1,
                            highlightbackground=C["line"])
            cell.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            no = tk.Label(cell, text=str(i + 1), bg=C["primary_soft"], fg=C["primary"],
                          font=(FONT, 9, "bold"), width=2, height=1)
            no.pack(anchor="w", padx=12, pady=(10, 0))
            title = tk.Label(cell, text="", bg=C["bg_soft"], fg=C["text"],
                             font=(FONT, 9, "bold"), anchor="w", justify="left")
            title.pack(fill="x", padx=12, pady=(6, 0))
            desc = tk.Label(cell, text="", bg=C["bg_soft"], fg=C["muted"],
                            font=(FONT, 8), anchor="w", justify="left", wraplength=220)
            desc.pack(fill="x", padx=12, pady=(2, 8))
            btn = tk.Button(cell, text="", relief="flat", bd=0, bg=C["bg_soft"],
                            fg=C["primary"], activebackground=C["bg_soft"],
                            activeforeground=C["primary"], font=(FONT, 8, "bold"),
                            cursor="hand2", anchor="w", padx=0, pady=0)
            btn.pack(fill="x", padx=12, pady=(0, 10))
            self.fr_rows.append((no, title, desc, btn))
        self._first_run_built = True

    def _sync_first_run(self):
        if not self.window.first_run_visible():
            self.first_card.grid_remove()
            return
        self._build_first_run()
        self.first_card.grid()
        steps = self.window.first_run_steps()
        done = [("1" in steps), ("2" in steps), ("3" in steps)]
        is_applicant = self.window.role == "applicant"
        sid = str(getattr(self.window, "applicant_sid", "") or "").strip()
        if is_applicant:
            rows = [
                ("填写申请人学号", "填好后只看你自己的材料", self.window.open_settings),
                ("提交第一份材料", "登记材料，进入待审核队列",
                 lambda: self.window.switch("submit")),
                ("查看审核进度", "归档或驳回后回到这里看结果",
                 lambda: self.window.first_run_go(3, "docs")),
            ]
            if sid:
                done[0] = True
        else:
            first_cmd = (lambda: self.window.switch("submit")) if self.window.can("docs:create") \
                else (lambda: self.window.switch("docs"))
            third_cmd = (lambda: self.window.first_run_go(3, "roster")) \
                if self.window.can("roster:manage") \
                else (lambda: self.window.first_run_go(3, "tasks")) \
                if self.window.can("task:manage") \
                else (lambda: self.window.switch("docs"))
            rows = [
                ("录入或收集第一份材料", "手动提交，或从文件夹收集登记", first_cmd),
                ("审核并归档", "通过后写入归档目录，留下第一条留痕",
                 lambda: self.window.switch("docs")),
                ("核对名单或登记任务", "知道谁没交、什么时候截止", third_cmd),
            ]
        for i, (title, desc, cmd) in enumerate(rows):
            no, t_lbl, d_lbl, btn = self.fr_rows[i]
            is_done = done[i]
            no.config(text="✓" if is_done else str(i + 1),
                      bg=C["tag_green"] if is_done else C["primary_soft"],
                      fg=C["green"] if is_done else C["primary"])
            t_lbl.config(text=title)
            d_lbl.config(text=desc)
            if is_done:
                btn.config(text="已完成", state="disabled", fg=C["green"],
                           disabledforeground=C["green"])
            else:
                btn.config(text=("填写学号" if (is_applicant and i == 0) else
                                 "去录入" if i == 0 else "去审核" if i == 1 else "去核对"),
                           state="normal", fg=C["primary"], command=cmd)
        self.fr_count.config(text="%d / 3" % sum(1 for x in done if x))

    def refresh(self):
        self._sync_first_run()
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
        sid = str(getattr(self.window, "applicant_sid", "") or "").strip()
        # 申请人只看本人材料；其余岗位看全量
        display_docs = ([d for d in docs if sid and d.get("sid") == sid]
                        if is_applicant else docs)

        pending = [d for d in display_docs if d.get("status") == "待审核"]
        archived = [d for d in display_docs if d.get("status") == "已归档"]
        rejected = [d for d in display_docs if d.get("status") == "已驳回"]
        counts = {"total": len(display_docs), "pending": len(pending),
                  "archived": len(archived), "rejected": len(rejected)}
        for k, lbl in self.card_values.items():
            lbl.config(text=str(counts[k]))

        # 主视觉：数字 + 一句话说明 + 按钮文案
        if is_applicant:
            focus = pending + rejected
            if not sid:
                self.hero_num.config(text="0")
                self.hero_hint.config(text="请先在设置里填写「申请人学号」")
                self.btn_go.config(text="填写我的学号", command=self.window.open_settings)
            elif focus:
                self.hero_num.config(text=str(len(focus)))
                self.hero_hint.config(text="项材料等待处理或需补充")
                self.btn_go.config(text="查看我的材料",
                                   command=lambda: self.window.switch("docs"))
            else:
                self.hero_num.config(text="0")
                self.hero_hint.config(text="还没有待处理材料，提交后可在这里查看进度")
                self.btn_go.config(text="提交材料",
                                   command=lambda: self.window.switch("submit"))
        elif can_archive:
            focus = pending
            self.hero_num.config(text=str(len(pending)))
            if pending:
                oldest = min(pending, key=lambda d: d.get("time", ""))
                self.hero_hint.config(text="最早：%s · %s" %
                                      (oldest.get("name", "")[:16], oldest.get("who", "")))
            else:
                self.hero_hint.config(text="队列已清空，归档流程无积压")
            self.btn_go.config(text="处理待审材料",
                               command=lambda: self.window.switch("docs"))
        else:
            focus = pending
            self.hero_num.config(text=str(len(pending)))
            self.hero_hint.config(text=("最近提交：%s" % pending[0].get("name", "")[:18])
                                  if pending else "还没有待审核材料")
            self.btn_go.config(text="查看材料台账",
                               command=lambda: self.window.switch("docs"))

        # 待办表
        if is_applicant:
            tname = "需我关注"
        elif can_archive:
            tname = "待处理"
        else:
            tname = "待跟进"
        self.bottom_title.config(text="%s %d 条 · 显示前 %d 条" %
                                 (tname, len(focus), min(len(focus), 5)))
        self.doc_tree.delete(*self.doc_tree.get_children())
        for d in focus[:5]:
            self.doc_tree.insert("", "end", tags=(d.get("id"),), values=(
                d.get("name", ""), d.get("who", ""), d.get("time", "")))
        if focus:
            if self.doc_empty is not None:
                self.doc_empty.hide_pack()
        else:
            self.doc_empty = self._empty_state("doc_empty", self._doc_empty_parent, 420)
            if is_applicant and not sid:
                self.doc_empty.set("请先填写申请人学号",
                                   "未填写时不展示任何人的材料；填好后这里只显示你自己的进度。",
                                   "填写学号", self.window.open_settings)
            elif is_applicant:
                self.doc_empty.set("没有需要我关注的材料",
                                   "已提交的材料会在这里跟进审核与驳回；现在可以提交第一份材料。",
                                   "提交材料", lambda: self.window.switch("submit"))
            elif can_archive:
                self.doc_empty.set("待办已清空",
                                   "没有待审核的材料；新材料提交后会重新出现在这里。",
                                   "提交材料" if self.window.can("docs:create") else "查看台账",
                                   (lambda: self.window.switch("submit")) if self.window.can("docs:create")
                                   else (lambda: self.window.switch("docs")))
            else:
                self.doc_empty.set("没有待跟进的材料",
                                   "新材料进入待审核队列后会显示在这里，供你了解流转状态。",
                                   "查看台账", lambda: self.window.switch("docs"))
            self.doc_empty.show_pack(pady=(6, 0))

        # 类别分布：行只建一次，之后只改数字与横条宽度，避免每次刷新重建控件
        self._ensure_cat_rows()
        total = len(display_docs) or 1
        for cat, n, bar, num in self._cat_rows:
            num.config(text=str(n))
            if n > 0:
                bar.place(relwidth=n / total, relheight=1, rely=0)
                bar.lift()
            else:
                bar.place_forget()
        self.cat_total.config(text="共 %d 条 · 覆盖 %d 类" %
                              (len(display_docs), len([c for c in self.CATS
                                                       if any(d.get("cat") == c for d in display_docs)])))

        # 近期动态
        if can_logs:
            self.log_card.grid()
            if self.log_empty is not None:
                self.log_empty.pack_forget()
            self._ensure_log_rows()
            for i, row in enumerate(self._log_rows):
                item = logs[i] if i < len(logs) else None
                for col, lbl in enumerate(row):
                    lbl.config(text=item.get(("time", "who", "act", "obj")[col], "")
                               if item else "")
                parent = row[0].master
                if item:
                    if not parent.winfo_ismapped():
                        parent.pack(fill="x", pady=2)
                else:
                    parent.pack_forget()
            if not logs:
                self.log_empty = self._empty_state("log_empty", self._log_empty_parent, 520)
                self.log_empty.set("还没有操作动态",
                                   "提交、审核、归档后会在这里留下最近几条记录。",
                                   "查看全部日志", lambda: self.window.switch("logs"))
                self.log_empty.pack(fill="x", pady=(4, 0))
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

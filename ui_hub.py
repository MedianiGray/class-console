# -*- coding: utf-8 -*-
"""能力中心：主流程之外的低频入口，一页分组卡片。

只负责“找到并打开”，不在本页执行业务动作；提交、审核、归档仍回原页面。
与网页端能力中心同一 IA：智能辅助 / 文件与留痕两组，权限不足时卡片置灰。
"""

import tkinter as tk
from tkinter import ttk

from theme import FONT, C

# (key, 标题, 徽标, 说明, 所需权限, 图标)
SECTIONS = [
    ("智能辅助", "读上下文、出草稿，只给建议，不替你执行", [
        ("ai", "AI 建议", "进阶",
         "按文件名给类别、置信度与理由；默认本地规则，配置后可走模型。",
         "docs:collect", "✦"),
    ]),
    ("文件与留痕", "目录比对、操作记录与证据，低频但可追溯", [
        ("collect", "文件夹收集", "本地",
         "扫描本机文件夹，与台账比对后批量登记；不移动原文件。",
         "docs:collect", "▣"),
        ("logs", "操作日志", "留痕",
         "提交、审核、归档、备份与证据包的完整记录，可筛选可回溯。",
         "logs:view", "≡"),
        ("evidence", "证据包", "导出",
         "把台账、索引、日志与文件树打成一个 ZIP，评审方不装软件也能看。",
         "logs:view", "▤"),
    ]),
]


class HubView(ttk.Frame):
    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self._build()

    # ---------- 界面 ----------
    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill="x", padx=18, pady=(16, 4))
        ttk.Label(head, text="主流程之外，仍找得到；这里只负责打开，操作回原页面。",
                  style="Muted.TLabel").pack(anchor="w")
        qrow = ttk.Frame(head)
        qrow.pack(fill="x", pady=(8, 0))
        tk.Label(qrow, text="在本页找能力", bg=C["bg"], fg=C["muted"],
                 font=(FONT, 9)).pack(side="left", padx=(0, 8))
        self.var_q = tk.StringVar()
        entry = ttk.Entry(qrow, textvariable=self.var_q, width=36)
        entry.pack(side="left")
        self.var_q.trace_add("write", lambda *_: self._apply_filter())

        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True, padx=18, pady=(6, 0))

        foot = ttk.Frame(self)
        foot.pack(fill="x", padx=18, pady=(0, 14))
        ttk.Label(foot, text="能力中心不放主流程按钮；新增低频能力只加卡片，不改导航。",
                  style="Muted.TLabel").pack(side="left")

        self._render()

    def _render(self):
        for w in self.body.winfo_children():
            w.destroy()
        self._cards = []
        self._sec_boxes = []
        for col in range(3):
            self.body.columnconfigure(col, weight=1, uniform="hub")
        for idx, (title, sub, cards) in enumerate(SECTIONS):
            row = idx * 2
            box = ttk.Frame(self.body)
            box.grid(row=row, column=0, columnspan=3, sticky="w",
                     padx=(0, 0), pady=(12 if idx else 0, 2))
            tk.Label(box, text=title, bg=C["bg"], fg=C["text"],
                     font=(FONT, 11, "bold"), anchor="w").pack(side="left")
            tk.Label(box, text=sub, bg=C["bg"], fg=C["muted"], font=(FONT, 9),
                     anchor="w").pack(side="left", padx=(10, 0))
            self._sec_boxes.append(box)
            for i, item in enumerate(cards):
                self._card(item, row + 1, i)
        last = len(SECTIONS) * 2
        self.body.rowconfigure(last, weight=1)
        self.empty_label = tk.Label(
            self.body, text="没有匹配的能力。换个词，或清空搜索回到全部卡片。",
            bg=C["bg"], fg=C["muted"], font=(FONT, 9), pady=24)
        self.empty_label.grid(row=last + 1, column=0, columnspan=3, sticky="we")
        self.empty_label.grid_remove()
        self._apply_filter()

    def _card(self, item, row, col):
        key, title, badge, desc, perm, icon = item
        allowed = not perm or self.window.can(perm)
        card = tk.Frame(self.body, bg=C["card"] if allowed else C["bg_soft"],
                        highlightthickness=1,
                        highlightbackground=C["line"],
                        cursor="hand2")
        card.grid(row=row, column=col, sticky="nsew", padx=(0, 12), pady=(0, 12))

        top = tk.Frame(card, bg=card.cget("bg"))
        top.pack(fill="x", padx=14, pady=(14, 4))
        box = tk.Frame(top, bg=C["primary_soft"] if allowed else C["bg"],
                       width=28, height=28)
        box.pack(side="left")
        box.pack_propagate(False)
        tk.Label(box, text=icon, bg=box.cget("bg"),
                 fg=C["primary"] if allowed else C["sub"],
                 font=(FONT, 11, "bold")).pack(expand=True)
        tk.Label(top, text=title, bg=card.cget("bg"),
                 fg=C["text"] if allowed else C["sub"],
                 font=(FONT, 10, "bold"), anchor="w").pack(side="left", padx=(9, 0))
        tk.Label(top, text=badge if allowed else "当前岗位不可用",
                 bg=card.cget("bg"), fg=C["sub"] if not allowed else C["muted"],
                 font=(FONT, 8)).pack(side="right")

        tk.Label(card, text=desc, bg=card.cget("bg"),
                 fg=C["muted"] if allowed else C["sub"], font=(FONT, 9),
                 anchor="w", justify="left", wraplength=250).pack(
                     fill="x", padx=14, pady=(2, 6))
        if allowed:
            ttk.Button(card, text="打开", width=7,
                       command=lambda k=key: self.open_item(k)).pack(
                           side="bottom", anchor="w", padx=14, pady=(0, 12))
        else:
            tk.Label(card, text="换岗位或找管理员", bg=card.cget("bg"),
                     fg=C["sub"], font=(FONT, 8),
                     anchor="w").pack(side="bottom", fill="x", padx=14,
                                      pady=(0, 12))

        state = {"on": False}

        def enter(_e=None):
            if not allowed or state["on"]:
                return
            state["on"] = True
            card.configure(highlightbackground=C["primary"])

        def leave(_e=None):
            if not allowed:
                return
            # 鼠标落到子控件上也算在卡片内，避免边框闪
            try:
                x, y = card.winfo_pointerxy()
                if card.winfo_containing(x, y) in self._descendants(card):
                    return
            except (tk.TclError, KeyError):
                pass
            state["on"] = False
            card.configure(highlightbackground=C["line"])

        def click(_e=None):
            self.open_item(key)

        card.bind("<Enter>", enter)
        card.bind("<Leave>", leave)
        card.bind("<Button-1>", click)
        for w in self._descendants(card):
            if isinstance(w, ttk.Button):
                continue
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
            w.bind("<Button-1>", click)
        self._cards.append((card, "%s %s %s" % (title, desc, badge)))

    def _apply_filter(self):
        """页内过滤：只藏卡片与空组，不改导航与权限；无结果显示空态。"""
        if not hasattr(self, "_cards"):
            return
        q = self.var_q.get().strip().lower()
        any_visible = False
        for card, text in self._cards:
            hit = not q or q in text.lower()
            if hit:
                card.grid()
                any_visible = True
            else:
                card.grid_remove()
        for idx, (title, sub, cards) in enumerate(SECTIONS):
            box = self._sec_boxes[idx]
            vis = any(not q or q in (
                "%s %s %s" % (it[1], it[3], it[2])).lower()
                for it in cards)
            if vis:
                box.grid()
            else:
                box.grid_remove()
        if getattr(self, "empty_label", None) is not None:
            if any_visible:
                self.empty_label.grid_remove()
            else:
                self.empty_label.grid()

    @staticmethod
    def _descendants(widget):
        out = []
        stack = list(widget.winfo_children())
        while stack:
            w = stack.pop()
            out.append(w)
            stack.extend(w.winfo_children())
        return out

    # ---------- 动作 ----------
    def open_item(self, key):
        if key == "ai":
            import ui_ai
            ui_ai.open_advisor(self.window)
            return
        if key == "evidence":
            if not self.window.can("logs:view"):
                self.window.toast("当前岗位无权导出证据包")
                return
            import ui_audit
            self.evidence_dialog = ui_audit.open_evidence(
                self, self.repo, self.window,
                on_done=self._after_evidence)
            return
        self.window.switch(key)

    def _after_evidence(self):
        view = self.window.views.get("logs") if self.window.views else None
        if view is not None and hasattr(view, "refresh"):
            view.refresh()

    def refresh(self):
        self._render()

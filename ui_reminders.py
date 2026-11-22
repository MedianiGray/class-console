# -*- coding: utf-8 -*-
"""提醒中心：顶栏入口 + 分组清单；弱实现但常驻，不依赖后台推送。"""

import tkinter as tk
from tkinter import ttk

from database import days_until
from theme import FONT, C


def snapshot(repo, window):
    """按当前岗位与申请人学号汇总待办；只读，不写库。"""
    docs = repo.list_docs()
    if getattr(window, "role", "") == "applicant":
        sid = str(getattr(window, "applicant_sid", "") or "").strip()
        docs = [d for d in docs if sid and d.get("sid") == sid]
    pending = [d for d in docs if d.get("status") == "待审核"]
    rejected = [d for d in docs if d.get("status") == "已驳回"]

    task_alerts = []
    if window.can("task:manage"):
        for t in repo.list_tasks():
            if t.get("done"):
                continue
            left = days_until(t.get("deadline"))
            if left is not None and left <= 2:
                task_alerts.append((t, left))

    roster_absent = []
    if window.can("roster:manage"):
        try:
            roster_absent = repo.roster_check()["absent"]
        except Exception:
            roster_absent = []

    total = len(pending) + len(rejected) + len(task_alerts)
    if window.can("roster:manage"):
        total += len(roster_absent)
    return {"docs": docs, "pending": pending, "rejected": rejected,
            "task_alerts": task_alerts, "roster_absent": roster_absent,
            "total": total}


def _fmt_doc(d):
    return (d.get("name") or "未命名",
            "%s · %s" % (d.get("who") or "—", d.get("time") or "—"))


def _fmt_task(pair):
    t, left = pair
    if left < 0:
        tail = "逾期 %d 天" % abs(left)
    elif left == 0:
        tail = "今天截止"
    else:
        tail = "剩 %d 天" % left
    return (t.get("title") or "未命名任务",
            "%s · %s" % (t.get("deadline") or "—", tail))


class ReminderDialog:
    def __init__(self, window, anchor=None):
        self.window = window
        self.top = tk.Toplevel(window.winfo_toplevel())
        self.top.title("提醒中心")
        self.top.transient(window.winfo_toplevel())
        self.top.resizable(False, False)
        self.top.configure(bg=C["bg"])
        self.top.bind("<Escape>", lambda e: self.close())
        self._place(anchor)
        self._build()
        try:
            self.top.focus_set()
        except tk.TclError:
            pass

    def _place(self, anchor):
        top = self.window.winfo_toplevel()
        top.update_idletasks()
        w, h = 430, 560
        if anchor is not None:
            x = anchor.winfo_rootx() - w + anchor.winfo_width() + 10
            y = anchor.winfo_rooty() + anchor.winfo_height() + 8
        else:
            x = top.winfo_rootx() + top.winfo_width() - w - 40
            y = top.winfo_rooty() + 70
        sw = self.top.winfo_screenwidth()
        sh = self.top.winfo_screenheight()
        x = max(8, min(x, sw - w - 8))
        y = max(8, min(y, sh - h - 48))
        self.top.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def _section(self, parent, title, count, rows, empty, action, action_text):
        card = tk.Frame(parent, bg=C["card"], highlightthickness=1,
                        highlightbackground=C["line"])
        card.pack(fill="x", pady=(0, 10))
        head = tk.Frame(card, bg=C["card"])
        head.pack(fill="x", padx=14, pady=(11, 4))
        tk.Label(head, text=title, bg=C["card"], fg=C["text"],
                 font=(FONT, 10, "bold")).pack(side="left")
        tk.Label(head, text=str(count), bg=C["card"],
                 fg=C["primary"] if count else C["sub"],
                 font=(FONT, 9, "bold")).pack(side="left", padx=(6, 0))
        if action:
            link = tk.Label(head, text=action_text + " →", bg=C["card"], fg=C["primary"],
                            font=(FONT, 9), cursor="hand2")
            link.pack(side="right")
            link.bind("<Button-1>", lambda e: (self.close(), action()))
        if not rows:
            tk.Label(card, text=empty, bg=C["card"], fg=C["sub"], font=(FONT, 9),
                     anchor="w").pack(fill="x", padx=14, pady=(2, 10))
            return card
        for primary, secondary in rows[:3]:
            row = tk.Frame(card, bg=C["card"])
            row.pack(fill="x", padx=14, pady=(0, 5))
            tk.Label(row, text=primary, bg=C["card"], fg=C["text"], font=(FONT, 9),
                     anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(row, text=secondary, bg=C["card"], fg=C["sub"], font=(FONT, 8),
                     anchor="e").pack(side="right")
        more = count - min(count, 3)
        if more > 0:
            tk.Label(card, text="还有 %d 条" % more, bg=C["card"], fg=C["sub"],
                     font=(FONT, 8), anchor="w").pack(fill="x", padx=14, pady=(0, 4))
        tk.Frame(card, bg=C["bg"]).pack(fill="x", pady=(0, 6))
        return card

    def _build(self):
        snap = snapshot(self.window.repo, self.window)
        head = tk.Frame(self.top, bg=C["bg"])
        head.pack(fill="x", padx=18, pady=(16, 10))
        tk.Label(head, text="提醒中心", bg=C["bg"], fg=C["text"],
                 font=(FONT, 15, "bold")).pack(side="left")
        tk.Label(head, text="%d 项待处理" % snap["total"], bg=C["bg"], fg=C["sub"],
                 font=(FONT, 9)).pack(side="right", pady=(4, 0))

        body = tk.Frame(self.top, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=18)

        def go_docs(status):
            def _go():
                dv = self.window.views.get("docs")
                if dv is not None:
                    dv.status.set(status)
                    dv.refresh()
                self.window.switch("docs")
            return _go

        if self.window.can("docs:archive"):
            self._section(body, "待审材料", len(snap["pending"]),
                          [_fmt_doc(d) for d in snap["pending"]],
                          "没有待审材料", go_docs("待审核"), "去台账")
            self._section(body, "已驳回 · 待补交", len(snap["rejected"]),
                          [_fmt_doc(d) for d in snap["rejected"]],
                          "没有需补交的材料", go_docs("已驳回"), "去台账")
        else:
            self._section(body, "我的材料", len(snap["pending"]) + len(snap["rejected"]),
                          [_fmt_doc(d) for d in (snap["pending"] + snap["rejected"])],
                          "没有需要关注的材料", go_docs("全部"), "去台账")

        if self.window.can("task:manage"):
            self._section(body, "任务临期 / 逾期", len(snap["task_alerts"]),
                          [_fmt_task(x) for x in snap["task_alerts"]],
                          "没有临期或逾期任务",
                          lambda: self.window.switch("tasks"), "去任务")
        else:
            self._section(body, "任务提醒", 0, [], "当前视角不显示任务提醒", None, "")

        if self.window.can("roster:manage"):
            self._section(body, "名单未交", len(snap["roster_absent"]),
                          [("%s · %s" % (r.get("sid") or "—", r.get("who") or "—"), "")
                           for r in snap["roster_absent"]],
                          "名单没有未交人员",
                          lambda: self.window.switch("roster"), "去名单")
        else:
            self._section(body, "名单提醒", 0, [], "当前视角不显示名单提醒", None, "")

        footer = tk.Frame(self.top, bg=C["bg"])
        footer.pack(fill="x", padx=18, pady=(0, 14))
        tk.Label(footer, text="按当前岗位与申请人学号汇总；本机模式，不做推送。",
                 bg=C["bg"], fg=C["sub"], font=(FONT, 8)).pack(side="left")
        ttk.Button(footer, text="关闭", command=self.close).pack(side="right")

    def close(self):
        try:
            self.top.destroy()
        except tk.TclError:
            pass


def open_reminders(window, anchor=None):
    return ReminderDialog(window, anchor)

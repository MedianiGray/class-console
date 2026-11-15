# -*- coding: utf-8 -*-
"""主窗口：侧边栏导航 + 内容视图堆叠 + 角色切换 + 状态栏反馈。"""

import tkinter as tk
from tkinter import ttk, messagebox

from ui_dashboard import DashboardView
from ui_docs import DocsView
from ui_submit import SubmitView
from ui_logs import LogsView
from ui_roster import RosterView
from ui_tasks import TasksView
from theme import FONT, C


class MainWindow(ttk.Frame):
    NAV = [
        ("dashboard", "◫ 工作台概览"),
        ("docs", "▤ 材料台账"),
        ("roster", "☺ 名单核对"),
        ("tasks", "◷ 任务跟踪"),
        ("submit", "✎ 提交材料"),
        ("logs", "☰ 操作日志"),
    ]

    def __init__(self, master, repo):
        super().__init__(master)
        self.repo = repo
        self.role = "admin"
        self.current = "docs"
        self.operator_name = "学委"  # 本地默认操作人，后续可在设置中修改
        self._status_default = "本地模式 · 数据保存在本机"
        self._build()
        self.refresh_all()

    def role_label(self):
        return "管理员" if self.role == "admin" else "同学"

    # ---------- 界面搭建 ----------
    def _build(self):
        self.pack(fill="both", expand=True)

        sidebar = tk.Frame(self, bg=C["sidebar"], width=196)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        brand = tk.Frame(sidebar, bg=C["sidebar"])
        brand.pack(fill="x", padx=18, pady=(24, 20))
        tk.Label(brand, text="班级操作台", bg=C["sidebar"], fg=C["text"],
                 font=(FONT, 15, "bold")).pack(anchor="w")
        tk.Label(brand, text="本地桌面版", bg=C["sidebar"], fg=C["muted"],
                 font=(FONT, 10)).pack(anchor="w", pady=(3, 0))

        self.nav_items = {}
        nav_box = tk.Frame(sidebar, bg=C["sidebar"])
        nav_box.pack(fill="x", pady=6)
        for key, label in self.NAV:
            row = tk.Frame(nav_box, bg=C["sidebar"])
            row.pack(fill="x", pady=2)
            bar = tk.Frame(row, bg=C["sidebar"], width=3)
            bar.pack(side="left", fill="y")
            btn = tk.Button(row, text=label, bg=C["sidebar"], fg=C["muted"],
                            activebackground=C["sidebar_active"], activeforeground=C["primary"],
                            relief="flat", font=(FONT, 12), anchor="w",
                            padx=14, pady=11, cursor="hand2", bd=0,
                            command=lambda k=key: self.switch(k))
            btn.pack(side="left", fill="x", expand=True)
            self.nav_items[key] = (btn, bar, row)

        role_box = tk.Frame(sidebar, bg=C["sidebar"])
        role_box.pack(side="bottom", fill="x", pady=18)
        tk.Label(role_box, text="当前视角", bg=C["sidebar"], fg=C["muted"],
                 font=(FONT, 10)).pack(anchor="w", padx=18)
        self.role_var = tk.StringVar(value="管理员")
        role_row = tk.Frame(role_box, bg=C["sidebar"])
        role_row.pack(padx=12, pady=(10, 0))
        ttk.Radiobutton(role_row, text="管理员", variable=self.role_var, value="管理员",
                        command=self._toggle_role).pack(side="left", padx=4)
        ttk.Radiobutton(role_row, text="同学", variable=self.role_var, value="同学",
                        command=self._toggle_role).pack(side="left", padx=4)

        # 内容区
        content = tk.Frame(self, bg=C["content"])
        content.pack(side="left", fill="both", expand=True)

        header = tk.Frame(content, bg=C["content"])
        header.pack(fill="x", padx=24, pady=(20, 10))
        self.title_label = tk.Label(header, text="材料台账", bg=C["content"],
                                    fg=C["text"], font=(FONT, 16, "bold"))
        self.title_label.pack(side="left")
        self.stats_label = tk.Label(header, text="", bg=C["content"], fg=C["muted"],
                                    font=(FONT, 11))
        self.stats_label.pack(side="right")

        body = tk.Frame(content, bg=C["content"])
        body.pack(fill="both", expand=True, padx=24, pady=(4, 10))

        self.views = {
            "dashboard": DashboardView(body, self.repo, self),
            "docs": DocsView(body, self.repo, self),
            "roster": RosterView(body, self.repo, self),
            "tasks": TasksView(body, self.repo, self),
            "submit": SubmitView(body, self.repo, self),
            "logs": LogsView(body, self.repo, self),
        }
        for v in self.views.values():
            v.pack(fill="both", expand=True)

        # 状态栏
        status = tk.Frame(self, bg="#E4EAE9", height=28)
        status.pack(side="bottom", fill="x")
        self.status_left = tk.Label(status, text=self._status_default, bg="#E4EAE9",
                                    fg="#5B716E", font=(FONT, 10), anchor="w")
        self.status_left.pack(side="left", padx=14, pady=5)
        self.status_right = tk.Label(status, text="", bg="#E4EAE9", fg="#5B716E",
                                     font=(FONT, 10), anchor="e")
        self.status_right.pack(side="right", padx=14)

        self.switch("dashboard")

    # ---------- 反馈与确认 ----------
    def show_status(self, text, temp=False):
        self.status_left.config(text=text)
        if temp:
            self.after(3000, self._restore_status)

    def _restore_status(self):
        try:
            role_text = "管理员" if self.role == "admin" else "同学"
            self.status_left.config(text="%s · %s" % (self._status_default, role_text))
        except tk.TclError:
            pass

    def toast(self, message):
        self.show_status(message, temp=True)

    def confirm(self, title, message):
        return messagebox.askyesno(title, message, parent=self)

    # ---------- 行为 ----------
    def _toggle_role(self):
        self.role = "admin" if self.role_var.get() == "管理员" else "student"
        self.refresh_all()

    def switch(self, key):
        self.current = key
        for k, (btn, bar, row) in self.nav_items.items():
            active = k == key
            btn.config(bg=C["sidebar_active"] if active else C["sidebar"],
                       fg=C["primary"] if active else C["muted"])
            bar.config(bg=C["accent"] if active else C["sidebar"])
        self.title_label.config(text=dict(self.NAV)[key])
        self.views[key].tkraise()
        self.refresh_all()

    def refresh_all(self):
        try:
            s = self.repo.stats()
            self.stats_label.config(text="总数 %d · 待审核 %d · 已归档 %d · 已驳回 %d" %
                                    (s["total"], s["pending"], s["archived"],
                                     s.get("rejected", 0)))
            self.status_right.config(text="材料 %d 条 · 日志 %d 条" %
                                    (s["total"], len(self.repo.list_logs())))
            self._restore_status()
            for v in self.views.values():
                if hasattr(v, "refresh"):
                    v.refresh()
        except Exception as e:
            self.status_left.config(text="数据刷新失败：%s" % e)

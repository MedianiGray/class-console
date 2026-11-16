# -*- coding: utf-8 -*-
"""主窗口：侧边栏导航 + 内容视图堆叠 + 角色切换 + 状态栏反馈。"""

import tkinter as tk
from tkinter import ttk, messagebox

from ui_dashboard import DashboardView
from ui_docs import DocsView
from ui_collect import CollectView
from ui_submit import SubmitView
from ui_logs import LogsView
from ui_roster import RosterView
from ui_tasks import TasksView
from theme import FONT, C

# 岗位与权限点模型（与 web/index.html 对齐）。
# handler 经办人 / reviewer 审核者 / manager 汇总者 / applicant 申请人。
# 本地单机先做界面层裁剪；身份认证与强制权限留后端阶段。
ROLES = {
    "handler":   {"label": "经办人", "operator": "学委"},
    "reviewer":  {"label": "审核者", "operator": "辅导员"},
    "manager":   {"label": "汇总者", "operator": "负责人"},
    "applicant": {"label": "申请人", "operator": "同学"},
}
PERMISSIONS = {
    "handler":   ["docs:create", "docs:edit", "docs:import", "docs:reject", "docs:export",
                  "roster:manage", "task:manage", "logs:view"],
    "reviewer":  ["docs:create", "docs:edit", "docs:import", "docs:archive", "docs:reject", "docs:export",
                  "roster:manage", "task:manage", "backup:restore", "logs:view"],
    "manager":   ["docs:archive", "docs:reject", "docs:export",
                  "roster:manage", "task:manage", "template:config",
                  "backup:restore", "logs:view", "config:manage"],
    "applicant": ["docs:create", "docs:edit"],
}


class MainWindow(ttk.Frame):
    # (key, 标题, 所需权限点；None 表示所有岗位可见)
    NAV = [
        ("dashboard", "◫ 工作台概览", None),
        ("docs", "▤ 材料台账", None),
        ("collect", "▣ 文件夹收集", "docs:create"),
        ("roster", "☺ 名单核对", "roster:manage"),
        ("tasks", "◷ 任务跟踪", "task:manage"),
        ("submit", "✎ 提交材料", "docs:create"),
        ("logs", "☰ 操作日志", "logs:view"),
    ]

    def __init__(self, master, repo):
        super().__init__(master)
        self.repo = repo
        self.role = "handler"
        self.current = "docs"
        self.operator_name = ROLES[self.role]["operator"]
        self._status_default = "本地模式 · 数据保存在本机"
        self._build()
        self.refresh_all()

    def can(self, perm):
        return perm in PERMISSIONS.get(self.role, [])

    def role_label(self):
        return ROLES.get(self.role, ROLES["handler"])["label"]

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

        self.nav_box = tk.Frame(sidebar, bg=C["sidebar"])
        self.nav_box.pack(fill="x", pady=6)
        self._build_nav()

        role_box = tk.Frame(sidebar, bg=C["sidebar"])
        role_box.pack(side="bottom", fill="x", pady=18)
        tk.Label(role_box, text="当前视角", bg=C["sidebar"], fg=C["muted"],
                 font=(FONT, 10)).pack(anchor="w", padx=18)
        self.role_var = tk.StringVar(value=self.role)
        role_row = tk.Frame(role_box, bg=C["sidebar"])
        role_row.pack(padx=12, pady=(10, 0))
        for role_key, meta in ROLES.items():
            ttk.Radiobutton(role_row, text=meta["label"], variable=self.role_var,
                            value=role_key, command=self._toggle_role).pack(side="left", padx=4)

        # 内容区
        content = tk.Frame(self, bg=C["content"])
        content.pack(side="left", fill="both", expand=True)

        header = tk.Frame(content, bg=C["content"])
        header.pack(fill="x", padx=24, pady=(20, 10))
        self.title_label = tk.Label(header, text="材料台账", bg=C["content"],
                                    fg=C["text"], font=(FONT, 16, "bold"))
        self.title_label.pack(side="left")

        body = tk.Frame(content, bg=C["content"])
        body.pack(fill="both", expand=True, padx=24, pady=(4, 10))

        self.views = {
            "dashboard": DashboardView(body, self.repo, self),
            "docs": DocsView(body, self.repo, self),
            "collect": CollectView(body, self.repo, self),
            "roster": RosterView(body, self.repo, self),
            "tasks": TasksView(body, self.repo, self),
            "submit": SubmitView(body, self.repo, self),
            "logs": LogsView(body, self.repo, self),
        }

        # 状态栏
        status = tk.Frame(self, bg="#F0F3F7", height=28)
        status.pack(side="bottom", fill="x")
        self.status_left = tk.Label(status, text=self._status_default, bg="#F0F3F7",
                                    fg=C["sub"], font=(FONT, 10), anchor="w")
        self.status_left.pack(side="left", padx=14, pady=5)
        self.status_right = tk.Label(status, text="", bg="#F0F3F7", fg=C["sub"],
                                     font=(FONT, 10), anchor="e")
        self.status_right.pack(side="right", padx=14)

        self.switch("dashboard")

    def _nav_visible(self, key):
        for k, _label, perm in self.NAV:
            if k == key:
                return not perm or self.can(perm)
        return False

    def _build_nav(self):
        for (_btn, _bar, row) in getattr(self, "nav_items", {}).values():
            row.destroy()
        self.nav_items = {}
        for key, label, perm in self.NAV:
            if perm and not self.can(perm):
                continue
            row = tk.Frame(self.nav_box, bg=C["sidebar"])
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

    # ---------- 反馈与确认 ----------
    def show_status(self, text, temp=False):
        self.status_left.config(text=text)
        if temp:
            self.after(3000, self._restore_status)

    def _restore_status(self):
        try:
            self.status_left.config(text="%s · %s" % (self._status_default, self.role_label()))
        except tk.TclError:
            pass

    def toast(self, message):
        self.show_status(message, temp=True)

    def confirm(self, title, message):
        return messagebox.askyesno(title, message, parent=self)

    # ---------- 行为 ----------
    def _toggle_role(self):
        self.role = self.role_var.get()
        self.operator_name = ROLES[self.role]["operator"]
        self._build_nav()
        target = self.current if self._nav_visible(self.current) else "dashboard"
        self.switch(target)

    def _nav_title(self, key):
        return next((label for k, label, _p in self.NAV if k == key), key)

    def switch(self, key):
        if not self._nav_visible(key):
            if self.current != "dashboard":
                self.toast("当前视角无权访问该模块")
                self.switch("dashboard")
            return
        self.current = key
        for k, v in self.views.items():
            if k == key:
                v.pack(fill="both", expand=True)
                v.tkraise()
            else:
                v.pack_forget()
        for k, (btn, bar, row) in self.nav_items.items():
            active = k == key
            btn.config(bg=C["sidebar_active"] if active else C["sidebar"],
                       fg=C["primary"] if active else C["muted"])
            bar.config(bg=C["accent"] if active else C["sidebar"])
        self.title_label.config(text=self._nav_title(key))
        self.refresh_all()

    def refresh_all(self):
        try:
            s = self.repo.stats()
            self.status_right.config(text="材料 %d 条 · 日志 %d 条" %
                                    (s["total"], len(self.repo.list_logs())))
            self._restore_status()
            for v in self.views.values():
                if hasattr(v, "refresh"):
                    v.refresh()
        except Exception as e:
            self.status_left.config(text="数据刷新失败：%s" % e)

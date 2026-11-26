# -*- coding: utf-8 -*-
"""主窗口：顶栏应用外壳 + 分组侧栏 + 内容区 + 状态栏。

分层约定（改视觉时遵守）：
  顶栏 topbar  → 应用身份与全局搜索，略高于页面
  侧栏 sidebar → 导航分区，与页面同层但用发丝线切分
  页面 bg      → 最底
  卡片 card    → 抬升一层
  卡片内嵌     → surface_alt 再降/或提一档
"""

import tkinter as tk
from tkinter import ttk, messagebox

import theme
from theme import FONT, C
from seed import SEED_DOCS

# 岗位与权限点模型（与 web/index.html 对齐）。
ROLES = {
    "handler":   {"label": "经办人", "operator": "学委"},
    "reviewer":  {"label": "审核者", "operator": "辅导员"},
    "manager":   {"label": "汇总者", "operator": "负责人"},
    "applicant": {"label": "申请人", "operator": "同学"},
}
PERMISSIONS = {
    "handler":   ["docs:create", "docs:edit", "docs:import", "docs:collect", "docs:archive", "docs:reject",
                  "docs:export", "roster:manage", "task:manage", "template:config", "logs:view"],
    "reviewer":  ["docs:create", "docs:edit", "docs:import", "docs:collect", "docs:archive", "docs:reject", "docs:export",
                  "roster:manage", "task:manage", "template:config", "backup:restore", "logs:view"],
    "manager":   ["docs:collect", "docs:archive", "docs:reject", "docs:export",
                  "roster:manage", "task:manage", "template:config",
                  "backup:restore", "logs:view", "config:manage"],
    "applicant": ["docs:create", "docs:edit"],
}


def old_user_should_skip_first_run(doc_count, done, dismissed):
    """首次引导判定：只有“没写过标记且材料多于种子”的老库才静默跳过。"""
    return done is None and dismissed is None and doc_count > len(SEED_DOCS)


VIEWS = {
    "dashboard": ("ui_dashboard", "DashboardView"),
    "docs": ("ui_docs", "DocsView"),
    "files": ("ui_files", "FileRoomView"),
    "collect": ("ui_collect", "CollectView"),
    "roster": ("ui_roster", "RosterView"),
    "tasks": ("ui_tasks", "TasksView"),
    "service": ("ui_service", "ServiceView"),
    "submit": ("ui_submit", "SubmitView"),
    "logs": ("ui_logs", "LogsView"),
}


class LazyViews(dict):
    """按需构建视图：首屏只建当前页，切到哪页再建哪页。

    保留 dict 的读写语义，`views[key]` 与 `views.get` 都会在首次访问时构建，
    所以既有调用点（跳转、提醒、命令面板）不需要知道视图是否已经存在。
    """

    def __init__(self, master, window):
        super().__init__()
        self._master = master
        self._window = window

    def __missing__(self, key):
        spec = VIEWS.get(key)
        if spec is None:
            raise KeyError(key)
        from importlib import import_module
        cls = getattr(import_module(spec[0]), spec[1])
        view = cls(self._master, self._window.repo, self._window)
        dict.__setitem__(self, key, view)
        return view

    def get(self, key, default=None):
        if key not in self and key in VIEWS:
            return self[key]
        return dict.get(self, key, default)


class MainWindow(ttk.Frame):
    # (key, 标题, 所需权限点, 图标, 分组键)
    NAV = [
        ("dashboard", "工作台概览", None, "◈", None),
        ("docs", "材料台账", None, "▤", "flow"),
        ("files", "文件室", "docs:archive", "▧", "flow"),
        ("submit", "提交材料", "docs:create", "＋", "flow"),
        ("roster", "名单核对", "roster:manage", "◎", "crew"),
        ("tasks", "任务跟踪", "task:manage", "◷", "crew"),
        ("service", "服务留痕", "logs:view", "♡", "crew"),
        ("collect", "文件夹收集", "docs:collect", "▣", "aux"),
        ("logs", "操作日志", "logs:view", "≡", "aux"),
    ]
    NAV_SHORT = {"dashboard": "概览", "docs": "台账", "files": "文件",
                 "collect": "收集", "roster": "名单", "tasks": "任务",
                 "submit": "提交", "service": "服务", "logs": "日志"}
    GROUPS = [("flow", "办理材料"), ("crew", "跟进核对")]
    MORE_GROUP = "aux"

    def __init__(self, master, repo):
        super().__init__(master)
        self.repo = repo
        self.role = "handler"
        self.applicant_sid = str(theme.load_ui("applicant_sid", "") or "").strip()
        self.current = theme.load_ui("start_view", "dashboard")
        self.operator_name = ROLES[self.role]["operator"]
        self._status_default = "本地模式 · 数据保存在本机"
        self.collapsed = theme.load_ui("sidebar", "expanded") == "collapsed"
        self.theme_buttons = {}
        self.nav_badges = {}
        self.group_heads = {}
        self.more_btn = None
        self.more_bar = None
        self.more_count = None
        self.more_group_head = None
        self._closed_groups = set(
            g for g in theme.load_ui("nav_closed", "").split(",") if g)
        if not theme.is_applied():
            theme.init_from_settings()
        self._skip_first_run_for_old_users()
        top = self.winfo_toplevel()
        try:
            top.configure(bg=C["bg"])
        except tk.TclError:
            pass
        theme.apply_tk_defaults(top)
        theme.setup_ttk(top)
        self._build()
        self._enable_file_drop()

    def _skip_first_run_for_old_users(self):
        """老库已有真实材料、且从没写过首导标记时，静默视为已完成。"""
        if theme.load_ui("first_run_done", None) is not None:
            return
        if theme.load_ui("first_run_dismissed", None) is not None:
            return
        try:
            doc_count = len(self.repo.list_docs())
        except Exception:
            return
        if old_user_should_skip_first_run(
                doc_count,
                theme.load_ui("first_run_done", None),
                theme.load_ui("first_run_dismissed", None)):
            theme.save_ui("first_run_dismissed", "1")

    def _enable_file_drop(self):
        """等窗口真正映射后再挂 WM_DROPFILES，避免拿不到顶层 HWND。"""
        if getattr(self, "_drop_ready", None) is not None:
            return
        self._drop_ready = "pending"
        self.after(260, self._install_file_drop)

    def _install_file_drop(self):
        if not self.winfo_exists():
            return
        try:
            from drop_target import enable_drop
            self._drop_ready = enable_drop(self.winfo_toplevel(),
                                           self._on_files_dropped)
        except Exception:
            self._drop_ready = False
        if self._drop_ready is False and not getattr(self, "_drop_retried", False):
            self._drop_retried = True
            self.after(500, self._install_file_drop)

    def _on_files_dropped(self, paths):
        if not self.can("docs:archive"):
            self.toast("当前视角无权登记文件")
            return
        if self.current != "files":
            self.switch("files")
        self.views["files"].accept_drop(paths)

    def goto_doc(self, code):
        """按编号回到台账并筛出这一条。"""
        q = str(code or "").strip()
        if not q:
            return
        docs = self.views.get("docs")
        if docs is None:
            return
        docs.cat.set("全部")
        docs.status.set("全部")
        docs.type.set("全部")
        docs.q.set(q)
        self.switch("docs")
        docs.tree.focus_set()

    def goto_files(self, path=None):
        """从台账 / 缺失清单跳到文件室；有路径就展开并选中。"""
        if not self._nav_visible("files"):
            self.toast("当前视角无权访问文件室")
            return
        self.switch("files")
        if path:
            self.views["files"].reveal_path(path)

    def can(self, perm):
        return perm in PERMISSIONS.get(self.role, [])

    def role_label(self):
        return ROLES.get(self.role, ROLES["handler"])["label"]

    # ---------- 界面搭建 ----------
    def _build(self):
        self.pack(fill="both", expand=True)

        # 状态栏先占位（上沿发丝线），避免内容区请求高度把状态栏挤出窗口
        status = tk.Frame(self, bg=C["card"], height=26)
        status.pack_propagate(False)
        status.pack(side="bottom", fill="x")
        tk.Frame(self, bg=C["line"], height=1).pack(side="bottom", fill="x")
        self.status_left = tk.Label(status, text=self._status_default, bg=C["card"],
                                    fg=C["sub"], font=(FONT, 9), anchor="w")
        self.status_left.pack(side="left", padx=20, pady=4)
        self.status_right = tk.Label(status, text="", bg=C["card"], fg=C["sub"],
                                     font=(FONT, 9), anchor="e")
        self.status_right.pack(side="right", padx=20)

        self._build_topbar()

        # 侧栏（顶栏之下）
        sbw = 64 if self.collapsed else 212
        sidebar = tk.Frame(self, bg=C["sidebar"], width=sbw)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self.sidebar = sidebar
        tk.Frame(sidebar, bg=C["line"], width=1).pack(side="right", fill="y")

        self.nav_box = tk.Frame(sidebar, bg=C["sidebar"])
        self.nav_box.pack(fill="both", expand=True, padx=8, pady=(12, 8))
        self._build_nav()
        self._build_sidebar_footer()

        # 内容区
        content = tk.Frame(self, bg=C["bg"])
        content.pack(side="left", fill="both", expand=True)

        header = tk.Frame(content, bg=C["bg"])
        header.pack(fill="x", padx=28, pady=(18, 4))
        self.eyebrow_label = tk.Label(header, text="工作台 · 总览", bg=C["bg"], fg=C["sub"],
                                      font=(FONT, 9), anchor="w")
        self.eyebrow_label.pack(anchor="w")
        title_row = tk.Frame(header, bg=C["bg"])
        title_row.pack(fill="x", pady=(6, 0))
        self.title_label = tk.Label(title_row, text="工作台概览", bg=C["bg"],
                                    fg=C["text"], font=(FONT, 21, "bold"), anchor="w")
        self.title_label.pack(side="left")
        self.sub_label = tk.Label(title_row, text="", bg=C["bg"], fg=C["muted"],
                                  font=(FONT, 9), anchor="w")
        self.sub_label.pack(side="left", padx=(14, 0), pady=(9, 0))

        body = tk.Frame(content, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=24, pady=(12, 12))

        self.views = LazyViews(body, self)
        self.views["dashboard"]

        self._sync_role_hint()
        self.bind_all("<Control-f>", self._focus_search)
        self.bind_all("<Control-k>", self._open_cmdk)
        self.switch(self.current if self._nav_visible(self.current) else "dashboard")

    def _build_topbar(self):
        bar = tk.Frame(self, bg=C["topbar"], height=56)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        tk.Frame(self, bg=C["line"], height=1).pack(side="top", fill="x")
        self.topbar = bar

        # 品牌
        brand = tk.Frame(bar, bg=C["topbar"])
        brand.pack(side="left", padx=(18, 0))
        logo = tk.Frame(brand, bg=C["primary"], width=26, height=26)
        logo.pack(side="left")
        logo.pack_propagate(False)
        tk.Label(logo, text="文", bg=C["primary"], fg=C["on_primary"],
                 font=(FONT, 11, "bold")).pack(expand=True)
        tk.Label(brand, text="班级操作台", bg=C["topbar"], fg=C["text"],
                 font=(FONT, 13, "bold")).pack(side="left", padx=(10, 8))
        tk.Label(brand, text="本地版", bg=C["topbar"], fg=C["sub"],
                 font=(FONT, 9)).pack(side="left", pady=(4, 0))

        # 全局搜索：顶栏中央偏左，按键即用
        search_box = tk.Frame(bar, bg=C["surface_alt"], highlightthickness=1,
                              highlightbackground=C["line"])
        search_box.pack(side="left", padx=(28, 0), pady=12, ipady=1)
        tk.Label(search_box, text="⌕", bg=C["surface_alt"], fg=C["sub"],
                 font=(FONT, 11)).pack(side="left", padx=(10, 3))
        self.search_entry = tk.Entry(search_box, width=42, relief="flat", bd=0,
                                     bg=C["surface_alt"], fg=C["text"],
                                     insertbackground=C["text"],
                                     font=(FONT, 10), highlightthickness=0)
        self.search_entry.pack(side="left", padx=(0, 8), pady=4)
        self.search_entry.bind("<Return>", lambda e: self.search_go())
        self.search_entry.bind("<FocusIn>", self._search_hint_off)
        self.search_entry.bind("<FocusOut>", self._search_hint_on)
        tk.Label(search_box, text="Ctrl K", bg=C["surface_alt"], fg=C["sub"],
                 font=(FONT, 8)).pack(side="left", padx=(0, 10))
        self._search_hint_on()

        # 右侧：设置 + 身份
        gear = tk.Button(bar, text="⚙", relief="flat", bd=0, bg=C["topbar"],
                         fg=C["muted"], activebackground=C["bg_soft"],
                         activeforeground=C["text"], font=(FONT, 12), padx=8, pady=2,
                         cursor="hand2", command=self.open_settings)
        gear.pack(side="right", padx=(0, 14))

        # 提醒中心：常驻入口 + 未读角标；弱实现，不做推送
        rem = tk.Frame(bar, bg=C["topbar"])
        rem.pack(side="right", padx=(0, 6), pady=12)
        self.reminder_btn = tk.Button(rem, text="提醒", relief="flat", bd=0,
                                      bg=C["topbar"], fg=C["muted"],
                                      activebackground=C["bg_soft"],
                                      activeforeground=C["text"], font=(FONT, 9),
                                      padx=8, pady=3, cursor="hand2",
                                      command=self._open_reminders)
        self.reminder_btn.pack(side="left")
        self.reminder_badge = tk.Label(rem, text="", bg=C["primary"], fg=C["on_primary"],
                                       font=(FONT, 8, "bold"), padx=5, pady=0)
        self.reminder_badge.bind("<Button-1>", lambda e: self._open_reminders())

        # 身份卡：头像 + 岗位 · 角色，点击切换视角
        chip = tk.Frame(bar, bg=C["surface_alt"], highlightthickness=1,
                        highlightbackground=C["line"], cursor="hand2")
        chip.pack(side="right", padx=(0, 8), pady=12)
        av = tk.Frame(chip, bg=C["primary_soft"], width=22, height=22)
        av.pack(side="left", padx=(7, 8), pady=4)
        av.pack_propagate(False)
        self.role_avatar = tk.Label(av, text="学", bg=C["primary_soft"], fg=C["primary"],
                                    font=(FONT, 9, "bold"))
        self.role_avatar.pack(expand=True)
        self.role_name = tk.Label(chip, text="%s · %s" % (self.operator_name,
                                                          self.role_label()),
                                  bg=C["surface_alt"], fg=C["text"],
                                  font=(FONT, 9), anchor="w")
        self.role_name.pack(side="left", pady=4)
        self.role_hint = self.role_name
        tk.Label(chip, text="▾", bg=C["surface_alt"], fg=C["sub"],
                 font=(FONT, 9)).pack(side="left", padx=(7, 9))
        self.role_var = tk.StringVar(value=self.role)
        self.role_disp = tk.StringVar(value=self.role_label())
        for w in (chip, av, self.role_avatar, self.role_name):
            w.bind("<Button-1>", self._role_menu)

    def reminder_snapshot(self):
        from ui_reminders import snapshot
        return snapshot(self.repo, self)

    def refresh_reminders(self):
        if not hasattr(self, "reminder_badge"):
            return
        try:
            total = self.reminder_snapshot()["total"]
        except Exception:
            total = 0
        if total > 0:
            self.reminder_badge.config(text=str(total))
            if not self.reminder_badge.winfo_ismapped():
                self.reminder_badge.pack(side="left", padx=(4, 0))
        else:
            self.reminder_badge.pack_forget()

    def _open_reminders(self):
        from ui_reminders import open_reminders
        old = getattr(self, "reminder_dialog", None)
        if old is not None:
            try:
                if old.top.winfo_exists():
                    old.close()
            except Exception:
                pass
        self.reminder_dialog = open_reminders(self, self.reminder_btn)
        return self.reminder_dialog

    def _role_menu(self, event=None):
        m = tk.Menu(self, tearoff=0, bg=C["card"], fg=C["text"],
                    activebackground=C["primary_soft"], activeforeground=C["primary"],
                    bd=0, font=(FONT, 10))
        for key, meta in ROLES.items():
            m.add_command(label="%s · %s" % (meta["label"], meta["operator"]),
                          command=lambda k=key: self._set_role(k))
        try:
            if event is None:
                x = self.role_hint.winfo_rootx() + 4
                y = self.role_hint.winfo_rooty() + self.role_hint.winfo_height() + 6
            else:
                x = event.x_root + 4
                y = event.y_root + 10
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _set_role(self, key):
        if key == self.role:
            return
        self.role_var.set(key)
        self._toggle_role()

    def _build_sidebar_footer(self):
        foot = tk.Frame(self.sidebar, bg=C["sidebar"])
        foot.pack(side="bottom", fill="x", padx=8, pady=(4, 10))

        if self.collapsed:
            self.gear_side = tk.Button(foot, text="⚙", relief="flat", bd=0,
                                       bg=C["sidebar"], fg=C["muted"],
                                       activebackground=C["bg_soft"],
                                       activeforeground=C["text"], font=(FONT, 12),
                                       cursor="hand2", pady=5, command=self.open_settings)
            self.gear_side.pack(fill="x", pady=(0, 2))
            tk.Button(foot, text="»", relief="flat", bd=0, bg=C["sidebar"], fg=C["sub"],
                      activebackground=C["bg_soft"], activeforeground=C["text"],
                      font=(FONT, 10), cursor="hand2", pady=4,
                      command=self.toggle_sidebar).pack(fill="x")
            return

        tk.Frame(foot, bg=C["line"], height=1).pack(fill="x", pady=(0, 8))
        self.gear_side = tk.Button(foot, text="⚙   设置", relief="flat", bd=0,
                                   bg=C["sidebar"], fg=C["muted"],
                                   activebackground=C["bg_soft"],
                                   activeforeground=C["text"], font=(FONT, 9),
                                   anchor="w", padx=8, pady=5, cursor="hand2",
                                   command=self.open_settings)
        self.gear_side.pack(side="left", fill="x", expand=True)
        tk.Button(foot, text="«", relief="flat", bd=0, bg=C["sidebar"], fg=C["sub"],
                  activebackground=C["bg_soft"], activeforeground=C["text"],
                  font=(FONT, 10), padx=6, cursor="hand2",
                  command=self.toggle_sidebar).pack(side="right")

    def _focus_search(self, _e=None):
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")
        return "break"

    def _open_cmdk(self, _e=None):
        old = getattr(self, "cmdk", None)
        if old is not None:
            try:
                if old.top.winfo_exists():
                    old.close()
                    return "break"
            except Exception:
                pass
        import ui_cmdk
        self.cmdk = ui_cmdk.open_palette(self)
        return "break"

    def _open_more(self):
        old = getattr(self, "more_dialog", None)
        if old is not None:
            try:
                if old.top.winfo_exists():
                    old.close()
            except Exception:
                pass
        import ui_more
        self.more_dialog = ui_more.open_more(self)
        return self.more_dialog

    def _sync_role_hint(self):
        meta = ROLES.get(self.role, ROLES["handler"])
        try:
            self.role_name.config(text="%s · %s" % (meta["operator"], meta["label"]))
            self.role_avatar.config(text=meta["operator"][:1])
        except (tk.TclError, AttributeError):
            pass

    def _sync_theme_buttons(self):
        mode = theme.mode()
        for key, btn in self.theme_buttons.items():
            active = key == mode
            btn.config(bg=C["primary_soft"] if active else C["bg_soft"],
                       fg=C["primary"] if active else C["muted"],
                       activebackground=C["primary_soft"] if active else C["card"],
                       activeforeground=C["primary"] if active else C["text"])

    def _nav_visible(self, key):
        for k, _label, perm, _icon, _g in self.NAV:
            if k == key:
                return not perm or self.can(perm)
        return False

    def _group_toggle(self, gkey):
        if gkey in self._closed_groups:
            self._closed_groups.discard(gkey)
        else:
            self._closed_groups.add(gkey)
        theme.save_ui("nav_closed", ",".join(sorted(self._closed_groups)))
        self._build_nav()

    def more_items(self):
        items = [it for it in self.NAV
                 if it[4] == self.MORE_GROUP and self._nav_visible(it[0])]
        if self.can("docs:collect"):
            items.append(("ai", "AI 建议", "docs:collect", "✦", self.MORE_GROUP))
        return items

    def _build_nav(self):
        for w in self.nav_box.winfo_children():
            w.destroy()
        self.nav_items = {}
        self.nav_badges = {}
        self.group_heads = {}
        self.more_btn = None
        self.more_bar = None
        self.more_count = None
        self.more_group_head = None

        first = self.NAV[0]
        if self._nav_visible(first[0]):
            self._nav_row(first)

        for gkey, glabel in self.GROUPS:
            items = [it for it in self.NAV if it[4] == gkey and self._nav_visible(it[0])]
            if not items:
                continue
            closed = gkey in self._closed_groups
            if not self.collapsed:
                head = tk.Frame(self.nav_box, bg=C["sidebar"], cursor="hand2")
                head.pack(fill="x", pady=(14, 4))
                lbl = tk.Label(head, text=glabel, bg=C["sidebar"], fg=C["sub"],
                               font=(FONT, 9), anchor="w")
                lbl.pack(side="left", padx=(8, 0))
                chev = tk.Label(head, text="▸" if closed else "▾", bg=C["sidebar"],
                                fg=C["sub"], font=(FONT, 8))
                chev.pack(side="right", padx=(0, 6))
                for w in (head, lbl, chev):
                    w.bind("<Button-1>", lambda e, g=gkey: self._group_toggle(g))
                self.group_heads[gkey] = head
            if closed and not self.collapsed:
                continue
            for item in items:
                self._nav_row(item)
        self._build_more_row()
        self._paint_nav_active()

    def _build_more_row(self):
        """低频入口合成一行；折叠时只留三点，不显示数量。"""
        items = self.more_items()
        if not items:
            return
        if not self.collapsed:
            head = tk.Frame(self.nav_box, bg=C["sidebar"])
            head.pack(fill="x", pady=(14, 4))
            tk.Label(head, text="更多", bg=C["sidebar"], fg=C["sub"],
                     font=(FONT, 9), anchor="w").pack(side="left", padx=(8, 0))
            self.more_group_head = head
        else:
            tk.Frame(self.nav_box, bg=C["line"], height=1).pack(
                fill="x", padx=6, pady=(10, 5))
        row = tk.Frame(self.nav_box, bg=C["sidebar"])
        row.pack(fill="x", pady=1)
        bar = tk.Frame(row, bg=C["sidebar"], width=3)
        bar.pack(side="left", fill="y")
        text = "···" if self.collapsed else "···   更多功能"
        btn = tk.Button(row, text=text, bg=C["sidebar"], fg=C["muted"],
                        activebackground=C["sidebar_active"], activeforeground=C["primary"],
                        relief="flat", font=(FONT, 11 if self.collapsed else 10),
                        anchor="center" if self.collapsed else "w",
                        padx=0 if self.collapsed else 9,
                        pady=6, cursor="hand2", bd=0,
                        command=self._open_more)
        btn.pack(side="left", fill="x", expand=True)
        if not self.collapsed:
            self.more_count = tk.Label(row, text=str(len(items)), bg=C["sidebar"],
                                       fg=C["sub"], font=(FONT, 8), padx=6)
            self.more_count.pack(side="right", padx=(0, 8))
        self.more_btn = btn
        self.more_bar = bar

    def _paint_nav_active(self):
        for k, (btn, _row, bar) in self.nav_items.items():
            active = k == self.current
            btn.config(bg=C["sidebar_active"] if active else C["sidebar"],
                       fg=C["primary"] if active else C["muted"])
            bar.config(bg=C["primary"] if active else C["sidebar"])
        if self.more_btn is not None:
            more_active = self.current in [it[0] for it in self.more_items()]
            self.more_btn.config(bg=C["sidebar_active"] if more_active else C["sidebar"],
                                 fg=C["primary"] if more_active else C["muted"])
            self.more_bar.config(bg=C["primary"] if more_active else C["sidebar"])
            if self.more_count is not None:
                self.more_count.config(bg=C["sidebar_active"] if more_active else C["sidebar"],
                                       fg=C["primary"] if more_active else C["sub"])

    def _nav_row(self, item):
        key, label, _perm, icon, _g = item
        row = tk.Frame(self.nav_box, bg=C["sidebar"])
        row.pack(fill="x", pady=1)
        bar = tk.Frame(row, bg=C["sidebar"], width=3)
        bar.pack(side="left", fill="y")
        text = icon if self.collapsed else "%s   %s" % (icon, label)
        btn = tk.Button(row, text=text, bg=C["sidebar"], fg=C["muted"],
                        activebackground=C["sidebar_active"], activeforeground=C["primary"],
                        relief="flat", font=(FONT, 11 if self.collapsed else 10),
                        anchor="center" if self.collapsed else "w",
                        padx=0 if self.collapsed else 9,
                        pady=6, cursor="hand2", bd=0,
                        command=lambda k=key: self.switch(k))
        btn.pack(side="left", fill="x", expand=True)
        badge = None
        if not self.collapsed:
            badge = tk.Label(row, text="", bg=C["sidebar"], fg=C["primary"],
                             font=(FONT, 8), padx=5)
            badge.pack(side="right", padx=(0, 8))
        if key == "docs":
            self.nav_badges["docs"] = badge
        self.nav_items[key] = (btn, row, bar)

    # ---------- 主题 ----------
    def apply_theme(self, mode):
        if mode == theme.mode() and theme.is_applied():
            return
        theme.set_mode(mode)
        self._restyle()

    def apply_appearance(self, mode=None, accent=None):
        """设置面板调用：模式与强调色可分别改，改完整体重建一次。"""
        if mode is not None:
            theme.save_mode(mode)
            theme.apply(mode, accent or theme.accent())
        if accent is not None:
            theme.save_accent(accent)
            theme.apply(theme.mode(), accent)
        self._restyle()

    def apply_density(self, value):
        theme.set_density(value)
        theme.apply(theme.mode(), theme.accent())
        self._restyle()

    def toggle_sidebar(self):
        self.collapsed = not self.collapsed
        theme.save_ui("sidebar", "collapsed" if self.collapsed else "expanded")
        self._restyle()

    def open_settings(self):
        import ui_settings
        ui_settings.open_settings(self)

    # ---------- 首次引导 ----------
    def first_run_steps(self):
        raw = str(theme.load_ui("first_run_steps", "") or "")
        return set(x for x in raw.split(",") if x)

    def first_run_visible(self):
        return (str(theme.load_ui("first_run_done", "0")) != "1" and
                str(theme.load_ui("first_run_dismissed", "0")) != "1")

    def mark_first_run(self, step):
        steps = self.first_run_steps()
        step = str(step)
        if step not in steps:
            steps.add(step)
        if self.role == "applicant" and self.applicant_sid:
            steps.add("1")
        theme.save_ui("first_run_steps", ",".join(sorted(steps)))
        if {"1", "2"}.issubset(steps) and str(theme.load_ui("first_run_done", "0")) != "1":
            theme.save_ui("first_run_done", "1")
            self.toast("上手完成，使用帮助已收进设置")
        self.refresh_all()

    def first_run_go(self, step, view):
        self.mark_first_run(step)
        self.switch(view)

    def dismiss_first_run(self):
        theme.save_ui("first_run_dismissed", "1")
        self.refresh_all()

    def reset_first_run(self):
        theme.save_ui("first_run_done", "0")
        theme.save_ui("first_run_dismissed", "0")
        theme.save_ui("first_run_steps", "")
        self.switch("dashboard")
        self.toast("三步上手已重新显示在概览")

    def open_help(self):
        top = tk.Toplevel(self)
        top.title("使用帮助")
        top.configure(bg=C["bg"])
        theme.apply_tk_defaults(top)
        w, h = 560, 440
        self.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - h) // 3)
        top.geometry("%dx%d+%d+%d" % (w, h, x, y))
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        tk.Label(top, text="三步上手", bg=C["bg"], fg=C["text"],
                 font=(FONT, 15, "bold"), anchor="w").pack(fill="x", padx=22, pady=(18, 2))
        tk.Label(top, text="不弹欢迎页；完成一次提交 → 审核 → 归档后，卡片会自动收起。",
                 bg=C["bg"], fg=C["muted"], font=(FONT, 9), anchor="w").pack(
                     fill="x", padx=22, pady=(0, 10))
        card = tk.Frame(top, bg=C["card"], highlightthickness=1,
                       highlightbackground=C["line"])
        card.pack(fill="both", expand=True, padx=22, pady=(0, 12))
        steps = self.first_run_steps()
        is_applicant = self.role == "applicant"
        rows = ([
            ("填写申请人学号", "在设置里填好学号，只看自己的材料"),
            ("提交第一份材料", "登记后进入待审核队列"),
            ("查看审核进度", "归档或驳回后回到台账看结果"),
        ] if is_applicant else [
            ("录入或收集第一份材料", "手动提交，或从文件夹收集登记"),
            ("审核并归档", "通过后写入归档目录，留下第一条留痕"),
            ("核对名单或登记任务", "知道谁没交、什么时候截止"),
        ])
        for i, (title, desc) in enumerate(rows):
            row = tk.Frame(card, bg=C["card"])
            row.pack(fill="x", padx=14, pady=(10 if i == 0 else 0, 0))
            done = str(i + 1) in steps
            tk.Label(row, text="✓" if done else str(i + 1), width=2,
                     bg=C["tag_green"] if done else C["primary_soft"],
                     fg=C["green"] if done else C["primary"],
                     font=(FONT, 9, "bold")).pack(side="left", anchor="n")
            box = tk.Frame(row, bg=C["card"])
            box.pack(side="left", fill="x", expand=True, padx=(10, 0))
            tk.Label(box, text=title, bg=C["card"], fg=C["text"],
                     font=(FONT, 10, "bold"), anchor="w").pack(fill="x")
            tk.Label(box, text=desc, bg=C["card"], fg=C["muted"],
                     font=(FONT, 9), anchor="w", justify="left").pack(fill="x", pady=(1, 6))
            if i < 2:
                tk.Frame(card, bg=C["line"], height=1).pack(fill="x", padx=14, pady=(0, 0))
        footer = tk.Frame(top, bg=C["bg"])
        footer.pack(side="bottom", fill="x", padx=22, pady=(0, 16))
        ttk.Button(footer, text="关闭", command=top.destroy).pack(side="right")
        ttk.Button(footer, text="重新显示在概览", command=lambda: (top.destroy(),
                                                                  self.reset_first_run())).pack(
            side="right", padx=(0, 8))
        top.bind("<Escape>", lambda e: top.destroy())
        try:
            top.grab_set()
        except tk.TclError:
            pass

    # ---------- 全局搜索 ----------
    _SEARCH_PH = "搜索材料、学号、编号…"

    def _search_hint_on(self, _e=None):
        if not self.search_entry.get().strip():
            self._ph_active = True
            self.search_entry.delete(0, "end")
            self.search_entry.insert(0, self._SEARCH_PH)
            self.search_entry.config(fg=C["sub"])

    def _search_hint_off(self, _e=None):
        if getattr(self, "_ph_active", False):
            self._ph_active = False
            self.search_entry.delete(0, "end")
            self.search_entry.config(fg=C["text"])

    def search_text(self):
        if getattr(self, "_ph_active", False):
            return ""
        return self.search_entry.get().strip()

    def search_go(self, *_):
        q = self.search_text()
        if not q:
            return
        docs = self.views.get("docs")
        if docs is not None:
            docs.cat.set("全部")
            docs.status.set("全部")
            docs.type.set("全部")
            docs.q.set(q)
        self.switch("docs")
        if docs is not None:
            docs.tree.focus_set()

    def _restyle(self):
        """改 token 后整体重建界面；数据与当前视图、岗位保持不变。"""
        top = self.winfo_toplevel()
        try:
            top.configure(bg=C["bg"])
        except tk.TclError:
            pass
        theme.apply_tk_defaults(top)
        theme.setup_ttk(top)
        for child in self.winfo_children():
            child.destroy()
        self.nav_items = {}
        self._build()

    # ---------- 反馈与确认 ----------
    def show_status(self, text, temp=False):
        self.status_left.config(text=text)
        if temp:
            self.after(3000, self._restore_status)

    def _restore_status(self):
        try:
            self.status_left.config(text=self._status_default)
        except tk.TclError:
            pass

    def toast(self, message):
        self.show_status(message, temp=True)

    def confirm(self, title, message):
        return messagebox.askyesno(title, message, parent=self)

    # ---------- 行为 ----------
    def _on_role_selected(self, _event=None):
        label = self.role_disp.get()
        key = next((k for k, m in ROLES.items() if m["label"] == label), None)
        if key is None or key == self.role:
            return
        self.role_var.set(key)
        self._toggle_role()

    def _toggle_role(self):
        self.role = self.role_var.get()
        self.operator_name = ROLES[self.role]["operator"]
        self.role_disp.set(self.role_label())
        self._build_nav()
        self._sync_role_hint()
        target = self.current if self._nav_visible(self.current) else "dashboard"
        self.switch(target)

    def _nav_title(self, key):
        return next((label for k, label, _p, _i, _g in self.NAV if k == key), key)

    def _nav_eyebrow(self, key):
        group = next((g for k, _l, _p, _i, g in self.NAV if k == key), None)
        glabel = dict(self.GROUPS).get(
            group, "更多" if group == self.MORE_GROUP else "总览")
        return "工作台 · %s" % glabel

    def switch(self, key):
        if not self._nav_visible(key):
            if self.current != "dashboard":
                self.toast("当前视角无权访问该模块")
                self.switch("dashboard")
            return
        self.current = key
        # 先按需构建目标视图，再统一显隐；否则遍历时目标页还不存在，切过去会是空白。
        self.views[key]
        for k, v in self.views.items():
            if k == key:
                v.pack(fill="both", expand=True)
                v.tkraise()
            else:
                v.pack_forget()
        self._paint_nav_active()
        self.title_label.config(text=self._nav_title(key))
        self.eyebrow_label.config(text=self._nav_eyebrow(key))
        self.refresh_all()
        if key in ("roster", "tasks") and self.first_run_visible():
            steps = self.first_run_steps()
            if "3" not in steps:
                self.mark_first_run(3)

    def refresh_all(self):
        try:
            s = self.repo.stats()
            self.status_right.config(text="材料 %d 条 · 日志 %d 条" %
                                     (s["total"], self.repo.count_logs()))
            self.sub_label.config(text="%s · %s" % (self.role_label(), self.operator_name))
            self._restore_status()
            pending = s.get("pending")
            if pending is None:
                docs = self.repo.list_docs()
                pending = sum(1 for d in docs if d.get("status") == "待审核")
            badge = self.nav_badges.get("docs")
            if badge is not None:
                badge.config(text=str(pending) if pending else "",
                             bg=C["primary_soft"] if pending else C["sidebar"])
            # 只刷新当前视图；其余视图在首次切换时构建，构建后自行读取最新数据。
            view = self.views.get(self.current)
            if view is not None and hasattr(view, "refresh"):
                view.refresh()
            self.refresh_reminders()
        except Exception as e:
            self.status_left.config(text="数据刷新失败：%s" % e)

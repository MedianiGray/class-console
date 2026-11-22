# -*- coding: utf-8 -*-
"""桌面端命令面板：Ctrl+K 搜材料、跳视图、执行动作。

输入以 > 开头时只列动作，例如 >归档、>导出、>提醒。
和网页端保持同一套动作口径；危险动作仍走原来的确认弹窗。
"""

import tkinter as tk
from tkinter import ttk

import theme
from theme import FONT, C


class CommandPalette:
    WIDTH = 620
    HEIGHT = 440

    def __init__(self, window):
        self.window = window
        self.items = []
        self.sel = 0
        self.top = tk.Toplevel(window)
        self.top.title("命令面板")
        self.top.transient(window)
        self.top.overrideredirect(True)
        self.top.configure(bg=C["line"])
        try:
            self.top.attributes("-topmost", True)
        except tk.TclError:
            pass
        self._center()
        self._build()
        self._load("")
        try:
            self.top.grab_set()
        except tk.TclError:
            pass
        self.top.bind("<Escape>", lambda e: self.close())
        self.top.protocol("WM_DELETE_WINDOW", self.close)

    def _center(self):
        root = self.window.winfo_toplevel()
        try:
            rx, ry = root.winfo_rootx(), root.winfo_rooty()
            rw, rh = root.winfo_width(), root.winfo_height()
        except tk.TclError:
            rx = ry = 0
            rw, rh = 1100, 760
        x = max(0, rx + (rw - self.WIDTH) // 2)
        y = max(0, ry + max(48, (rh - self.HEIGHT) // 3))
        self.top.geometry("%dx%d+%d+%d" % (self.WIDTH, self.HEIGHT, x, y))

    def _build(self):
        shell = tk.Frame(self.top, bg=C["card"])
        shell.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(shell, bg=C["card"])
        head.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(head, text="⌘", bg=C["primary_soft"], fg=C["primary"],
                 font=(FONT, 11, "bold"), padx=7, pady=2).pack(side="left")
        self.entry = tk.Entry(head, relief="flat", bd=0, bg=C["card"], fg=C["text"],
                              insertbackground=C["text"], font=(FONT, 13),
                              highlightthickness=0)
        self.entry.pack(side="left", fill="x", expand=True, padx=(10, 8), pady=2)
        tk.Label(head, text="Esc", bg=C["card"], fg=C["sub"],
                 font=(FONT, 8)).pack(side="right")
        self.entry.bind("<KeyRelease>", self._on_key)
        self.entry.bind("<Down>", self._down)
        self.entry.bind("<Up>", self._up)
        self.entry.bind("<Return>", self._enter)
        self.entry.bind("<Escape>", lambda e: self.close())

        tk.Frame(shell, bg=C["line"], height=1).pack(fill="x")
        body = tk.Frame(shell, bg=C["card"])
        body.pack(fill="both", expand=True, padx=8, pady=7)
        self.listbox = tk.Listbox(
            body, relief="flat", bd=0, bg=C["card"], fg=C["text"],
            selectbackground=C["primary_soft"], selectforeground=C["primary"],
            activestyle="none", font=(FONT, 10), highlightthickness=0,
            exportselection=False)
        ysb = ttk.Scrollbar(body, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=ysb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.listbox.bind("<ButtonRelease-1>", self._click)
        self.listbox.bind("<Double-1>", self._enter)

        foot = tk.Frame(shell, bg=C["card"])
        foot.pack(fill="x", padx=14, pady=(0, 9))
        tk.Label(foot, text="↑↓ 选择 · Enter 执行 · > 开头只看动作，如 >归档", bg=C["card"],
                 fg=C["sub"], font=(FONT, 8), anchor="w").pack(fill="x")
        tk.Frame(shell, bg=C["line"], height=1).pack(fill="x")

    def _actions(self):
        w = self.window
        acts = [
            {"kind": "动作", "group": "常用动作", "title": "打开提醒中心",
             "sub": "待审、已驳回、任务临期、名单未交", "keywords": "提醒 待办 通知",
             "run": w._open_reminders},
        ]
        if w.can("docs:create"):
            acts.append({"kind": "动作", "group": "常用动作", "title": "提交新材料",
                         "sub": "跳到提交表单，按模板填字段", "keywords": "提交 新建 材料",
                         "run": lambda: w.switch("submit")})
        if w.can("docs:archive"):
            acts.append({"kind": "动作", "group": "台账动作", "title": "归档已选材料",
                         "sub": "对台账当前选中的材料执行归档", "keywords": "归档 通过 入库",
                         "run": self._archive_selected})
        if w.can("docs:export"):
            acts.append({"kind": "动作", "group": "台账动作", "title": "导出当前台账 CSV",
                         "sub": "按当前筛选与排序导出", "keywords": "导出 csv 表格",
                         "run": self._export_csv})
        acts.extend([
            {"kind": "动作", "group": "台账动作", "title": "重置台账列宽",
             "sub": "恢复八列默认宽度，排序不变", "keywords": "列宽 重置 表格",
             "run": self._reset_widths},
            {"kind": "动作", "group": "台账动作", "title": "清空台账筛选",
             "sub": "关键词、类别、类型、状态全部复位", "keywords": "筛选 清空 重置",
             "run": self._clear_filters},
            {"kind": "动作", "group": "常用动作", "title": "切换深浅色",
             "sub": "在深色与浅色之间切换并记住", "keywords": "主题 深色 浅色 外观",
             "run": self._toggle_theme},
            {"kind": "动作", "group": "常用动作", "title": "打开设置",
             "sub": "外观、归档、模板字段与数据备份", "keywords": "设置 配置 偏好",
             "run": w.open_settings},
            {"kind": "动作", "group": "常用动作", "title": "刷新数据",
             "sub": "重新读取材料、名单、任务与日志", "keywords": "刷新 同步 重载",
             "run": w.refresh_all},
        ])
        return acts

    def _docs(self, q):
        rows = self.window.repo.list_docs()
        if self.window.role == "applicant":
            sid = str(getattr(self.window, "applicant_sid", "") or "").strip()
            rows = [d for d in rows if sid and d.get("sid") == sid]
        if q:
            rows = [d for d in rows if q in " ".join(
                str(d.get(k) or "") for k in
                ("name", "code", "cat", "who", "sid", "status", "file")).lower()]
        rows = sorted(rows, key=lambda d: str(d.get("time") or ""), reverse=True)
        return rows[:12]

    def _load(self, raw):
        text = raw.strip()
        actions_only = text.startswith(">")
        q = text[1:].strip().lower() if actions_only else text.lower()

        def hit(it):
            if not q:
                return True
            return q in ("%s %s %s" % (it.get("title", ""), it.get("sub", ""),
                                       it.get("keywords", ""))).lower()

        items = []
        acts = [a for a in self._actions() if hit(a)]
        if actions_only:
            items = acts
        else:
            views = []
            for key, label, perm, _icon, _group in self.window.NAV:
                if not self.window._nav_visible(key):
                    continue
                views.append({"kind": "视图", "group": "跳转视图", "title": label,
                              "sub": "前往 · " + self.window._nav_eyebrow(key),
                              "keywords": key,
                              "run": lambda k=key: self.window.switch(k)})
            views = [v for v in views if hit(v)]
            docs = self._docs(q)
            doc_items = [{"kind": "材料", "group": "材料",
                          "title": d.get("name") or "未命名",
                          "sub": " · ".join(str(d.get(k) or "") for k in
                                            ("code", "cat", "who", "status") if d.get(k)),
                          "keywords": "",
                          "run": lambda i=d.get("id"): self._open_doc(i)}
                         for d in docs]
            items = acts + views + doc_items

        self.items = items[:20]
        self.sel = 0
        self.listbox.delete(0, "end")
        if not self.items:
            self.listbox.insert("end", "　没有匹配的命令或材料")
            self.listbox.itemconfigure(0, foreground=C["sub"])
            return
        last = None
        for it in self.items:
            if it["group"] != last:
                self.listbox.insert("end", "  " + it["group"])
                self.listbox.itemconfigure("end", foreground=C["sub"], selectbackground=C["card"])
                last = it["group"]
            line = "   %-4s  %s" % (it["kind"], it["title"])
            if it.get("sub"):
                line += "    " + it["sub"]
            self.listbox.insert("end", line)
        self._paint()

    def _paint(self):
        if not self.items:
            return
        pos = 0
        last = None
        target = 0
        for i, it in enumerate(self.items):
            if it["group"] != last:
                pos += 1
                last = it["group"]
            if i == self.sel:
                target = pos
                break
            pos += 1
        self.listbox.selection_clear(0, "end")
        if target < self.listbox.size():
            self.listbox.selection_set(target)
            self.listbox.activate(target)
            try:
                self.listbox.see(target)
            except tk.TclError:
                pass

    def _on_key(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        self._load(self.entry.get())

    def _move(self, delta):
        if not self.items:
            return "break"
        self.sel = max(0, min(len(self.items) - 1, self.sel + delta))
        self._paint()
        return "break"

    def _down(self, _e=None):
        return self._move(1)

    def _up(self, _e=None):
        return self._move(-1)

    def _click(self, _e=None):
        pos = self.listbox.curselection()
        if not pos:
            return
        # 把 listbox 行号换算回 items 下标，跳过分组标题
        real = -1
        seen = -1
        last = None
        for i, it in enumerate(self.items):
            if it["group"] != last:
                seen += 1  # 分组标题
                last = it["group"]
            seen += 1
            if seen == pos[0]:
                real = i
                break
        if real >= 0:
            self.sel = real
            self._run()

    def _enter(self, _e=None):
        self._run()
        return "break"

    def _run(self):
        if not self.items:
            return
        item = self.items[self.sel]
        self.close()
        try:
            item["run"]()
        except Exception as e:
            self.window.toast("命令执行失败：%s" % e)

    def _open_doc(self, doc_id):
        docs = self.window.views.get("docs")
        if docs is None:
            return
        self.window.switch("docs")
        docs.q.set("")
        docs.cat.set("全部")
        docs.type.set("全部")
        docs.status.set("全部")
        docs.refresh()
        iid = docs._row_iids.get(doc_id)
        if not iid:
            self.window.toast("材料不在当前台账中")
            return
        docs.tree.selection_set(iid)
        docs.tree.focus(iid)
        docs.tree.see(iid)
        docs.view()

    def _archive_selected(self):
        docs = self.window.views.get("docs")
        if docs is None:
            return
        if self.window.current != "docs" or not docs._selected_ids():
            self.window.switch("docs")
            self.window.toast("请先在台账中选中要归档的材料")
            return
        docs.archive()

    def _export_csv(self):
        docs = self.window.views.get("docs")
        if docs is not None:
            self.window.switch("docs")
            docs.export_csv()

    def _reset_widths(self):
        docs = self.window.views.get("docs")
        if docs is not None:
            self.window.switch("docs")
            docs.reset_widths()

    def _clear_filters(self):
        docs = self.window.views.get("docs")
        if docs is not None:
            self.window.switch("docs")
            docs.q.set("")
            docs.cat.set("全部")
            docs.type.set("全部")
            docs.status.set("全部")
            docs.refresh()
            self.window.toast("台账筛选已清空")

    def _toggle_theme(self):
        mode = "light" if theme.mode() == "dark" else "dark"
        self.window.apply_theme(mode)
        self.window.toast("已切换到%s" % ("深色" if mode == "dark" else "浅色"))

    def close(self):
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        try:
            self.top.destroy()
        except tk.TclError:
            pass


def open_palette(window):
    old = getattr(window, "cmdk", None)
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    window.cmdk = CommandPalette(window)
    return window.cmdk

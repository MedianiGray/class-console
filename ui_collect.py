# -*- coding: utf-8 -*-
"""文件夹收集视图：扫描本机文件夹，比对台账后将未登记材料批量入账并自动编号。

入账时只登记文件名与本机路径，不移动、不复制原文件；
文件在「归档」时按「类别 / 学号-姓名 / 编号_材料名」复制到归档根目录。
不做后台持续监听，每次手动扫描比对一次台账。
"""

import os
import time
import tkinter as tk
from tkinter import ttk, filedialog

import archive
from theme import FONT, C
from ui_empty import EmptyState
from ui_error import show_error


class CollectView(ttk.Frame):
    CATS = ["团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]
    SKIP_PREFIX = (".", "~$")  # 隐藏文件、Office 临时锁文件

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self.folder = ""
        self.items = []
        self._build()

    # ---------- 界面 ----------
    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(16, 10))

        ttk.Button(top, text="选择文件夹", style="Ghost.TButton",
                   command=self.pick_folder).pack(side="left")
        ttk.Label(top, text="默认类别").pack(side="left", padx=(16, 0))
        self.var_cat = tk.StringVar(value=self.CATS[0])
        ttk.Combobox(top, textvariable=self.var_cat, values=self.CATS,
                     width=12, state="readonly").pack(side="left", padx=8)
        ttk.Button(top, text="扫描新文件", style="Accent.TButton",
                   command=self.scan).pack(side="left", padx=8)
        self.path_label = ttk.Label(top, text="尚未选择文件夹", style="Muted.TLabel")
        self.path_label.pack(side="left", padx=12)

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=18)
        cols = ("check", "file", "size", "mtime", "cat", "status")
        heads = {"check": "选", "file": "文件", "size": "大小",
                 "mtime": "修改时间", "cat": "入账类别", "status": "比对结果"}
        widths = {"check": 44, "file": 320, "size": 80, "mtime": 130,
                  "cat": 110, "status": 100}
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 selectmode="browse")
        for c in cols:
            self.tree.heading(c, text=heads[c], anchor="w")
            self.tree.column(c, width=widths[c], anchor="w", stretch=True)
        self.tree.tag_configure("zebra", background=C["zebra"])

        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_click)

        self.empty = EmptyState(wrap, wraplength=400)
        self.empty.set("还没有扫描结果",
                       "选择一个材料文件夹，扫描后会列出文件、大小与是否已登记；不移动原文件。",
                       "选择文件夹", self.pick_folder)
        self.empty.show_place()

        bar = ttk.Frame(self)
        bar.pack(side="bottom", fill="x", padx=18, pady=(6, 12), before=wrap)
        self.btn_ai = ttk.Button(bar, text="AI 分类建议", style="Ghost.TButton",
                                  command=self.suggest_categories)
        self.btn_ai.pack(side="left")
        self.btn_import = ttk.Button(bar, text="将所选入账（自动编号）",
                                      style="Accent.TButton", command=self.import_selected)
        self.btn_import.pack(side="left", padx=(8, 0))
        ttk.Label(bar, text="仅登记文件名与本机路径，不移动或复制原文件",
                  style="Muted.TLabel").pack(side="left", padx=12)
        self.hint = ttk.Label(bar, text="", style="Muted.TLabel")
        self.hint.pack(side="right")

    # ---------- 勾选 ----------
    def _on_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        for it in self.items:
            if it["iid"] == iid:
                it["checked"] = not it["checked"]
                self.tree.set(iid, "check", "[x]" if it["checked"] else "[ ]")
                return

    # ---------- 扫描 ----------
    def pick_folder(self):
        path = filedialog.askdirectory(title="选择要收集的材料文件夹")
        if path:
            self.folder = path
            self.path_label.config(text=path)
            self.scan()

    @staticmethod
    def _human_size(n):
        n = float(n or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return ("%.0f" % n) if unit == "B" else ("%.1f" % n)
            n /= 1024
        return ""

    def scan(self):
        if not self.folder:
            self.window.toast("请先选择要收集的文件夹")
            return
        existing = {d.get("file") for d in self.repo.list_docs()}
        self.tree.delete(*self.tree.get_children())
        self.items = []
        try:
            names = os.listdir(self.folder)
        except OSError as e:
            self.tree.delete(*self.tree.get_children())
            self.hint.config(text="文件夹暂时读不了", foreground=C["red"])
            self.empty.set(
                "这个文件夹暂时读不了",
                "系统拒绝读取（权限、占用或被移走）。台账没有变化；可以重新扫描，或换一个文件夹。",
                "重新扫描", self.scan)
            self.empty.show_place()
            return

        i = 0
        skipped = 0
        for name in sorted(names):
            full = os.path.join(self.folder, name)
            try:
                is_file = os.path.isfile(full)
            except OSError:
                skipped += 1
                continue
            if not is_file or name.startswith(self.SKIP_PREFIX):
                continue
            registered = name in existing
            try:
                st = os.stat(full)
                mtime = time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime))
                size = self._human_size(st.st_size)
            except OSError:
                skipped += 1
                mtime, size = "", ""
            iid = "r%d" % i
            status = "已登记" if registered else "未登记"
            check = "[ ]" if registered else "[x]"
            self.tree.insert("", "end", iid=iid,
                              tags=("zebra" if i % 2 else "",),
                              values=(check, name, size, mtime, "跟随默认", status))
            self.items.append({"iid": iid, "name": name, "path": full,
                               "registered": registered, "checked": not registered,
                               "cat": ""})
            i += 1
        new_count = sum(1 for x in self.items if not x["registered"])
        hint = "共 %d 个文件，未登记 %d 个" % (len(self.items), new_count)
        if skipped:
            hint += "；另有 %d 个文件读不到，已跳过" % skipped
        self.hint.config(text=hint, foreground=C["sub"])
        if self.items:
            self.empty.hide()
        else:
            self.empty.set("这个文件夹里没有可登记的文件",
                           "扫描只统计文件，跳过隐藏与临时文件；换一个文件夹或重新扫描后再看。",
                           "重新扫描", self.scan)
            self.empty.show_place()

    # ---------- AI 分类建议 ----------
    def suggest_categories(self):
        if not self.window.can("docs:create"):
            self.window.toast("当前视角无权执行该操作")
            return
        chosen = [x for x in self.items if x["checked"] and not x["registered"]]
        if not chosen:
            self.window.toast("先勾选要分析的新文件")
            return
        if len(chosen) > 40:
            self.window.toast("一次最多分析 40 份，先取消一部分勾选")
            return
        import ui_ai
        ui_ai.open_advisor(self.window, items=chosen, on_apply=self._apply_suggestions)

    def _apply_suggestions(self, results):
        by_name = {r.get("file"): r for r in (results or [])}
        applied = 0
        for it in self.items:
            r = by_name.get(it.get("name"))
            if not r:
                continue
            it["cat"] = r.get("cat", "")
            try:
                self.tree.set(it["iid"], "cat", it["cat"] or "跟随默认")
            except tk.TclError:
                pass
            applied += 1
        if applied:
            self.window.toast("已把 %d 份文件的类别建议填到表格，入账前仍可改" % applied)
        else:
            self.window.toast("没有可回填的建议")

    # ---------- 入账 ----------
    def import_selected(self):
        if not self.window.can("docs:create"):
            self.window.toast("当前视角无权执行该操作")
            return
        chosen = [x for x in self.items if x["checked"] and not x["registered"]]
        if not chosen:
            self.window.toast("没有可入账的新文件")
            return
        default_cat = self.var_cat.get()
        cats = [x.get("cat") or default_cat for x in chosen]
        distinct = sorted(set(cats))
        if len(distinct) == 1:
            cat_text = "「%s」" % distinct[0]
        else:
            cat_text = "各自类别（%d 种）" % len(distinct)
        if not self.window.confirm(
                "批量入账确认",
                "将把 %d 份未登记材料按%s入账，并自动生成编号；提交人先记为「待补」，可稍后在台账补全。"
                % (len(chosen), cat_text)):
            return

        ok = 0
        failed = []
        for x in chosen:
            base = os.path.splitext(x["name"])[0]
            cat = x.get("cat") or default_cat
            try:
                self.repo.add_doc({
                    "name": base, "cat": cat, "who": "待补", "sid": "",
                    "note": "文件夹收集：%s" % os.path.basename(self.folder),
                    "file": x["name"], "path": x["path"], "scope": "全员",
                    "actor": self.window.operator_name,
                    "actor_role": self.window.role_label(),
                })
                ok += 1
            except Exception as e:
                failed.append("%s（%s）" % (x["name"], type(e).__name__))
        log_failed = False
        index_failed = False
        if ok:
            try:
                self.repo.add_log("收集入账", "%d 份文件" % ok,
                                  self.window.operator_name,
                                  self.window.role_label())
            except Exception:
                log_failed = True
            try:
                index_path = archive.write_index(self.repo.list_docs())
                index_failed = not bool(index_path)
            except Exception:
                index_failed = True
        self.window.refresh_all()
        msg = "已入账 %d 份材料并自动编号" % ok
        if failed:
            msg += "，%d 份没有写入台账" % len(failed)
        if log_failed:
            msg += "，操作日志写入失败"
        if index_failed:
            msg += "，归档索引表写入失败"
        self.window.toast(msg[:120])
        if ok:
            self.window.mark_first_run(1)
        if failed:
            show_error(
                self, "部分文件没有入账",
                "有 %d 个文件未能写入台账：%s。" % (len(failed),
                                                     "；".join(failed[:2])),
                "已成功的 %d 份照常保留；失败文件没有登记，仍在原文件夹。" % ok,
                "先确认原文件没有被移走，再重新扫描并单独入账失败项。",
                "原文件不会被移动或删除；需要时可导出备份留底。",
                actions=[("重新扫描", self.scan), ("知道了", lambda: None)])
        self.scan()

    def refresh(self):
        if self.items:
            self.scan()

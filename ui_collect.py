# -*- coding: utf-8 -*-
"""文件夹收集视图：扫描本机文件夹，比对台账后将未登记材料批量入账并自动编号。

入账时按「类别 / 学号-姓名 / 编号_材料名」复制一份到归档根目录；
原文件保持不动。不做后台持续监听，每次手动扫描比对一次台账。
"""

import os
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import archive
from theme import FONT, C


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
        cols = ("check", "file", "size", "mtime", "status")
        heads = {"check": "选", "file": "文件", "size": "大小",
                 "mtime": "修改时间", "status": "比对结果"}
        widths = {"check": 44, "file": 340, "size": 90, "mtime": 140, "status": 110}
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

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=12)
        self.btn_import = ttk.Button(bar, text="将所选入账（自动编号）",
                                      style="Accent.TButton", command=self.import_selected)
        self.btn_import.pack(side="left")
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
                self.tree.set(iid, "check", "☑" if it["checked"] else "☐")
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
            self.window.toast("读取文件夹失败：%s" % e)
            return

        i = 0
        for name in sorted(names):
            full = os.path.join(self.folder, name)
            if not os.path.isfile(full) or name.startswith(self.SKIP_PREFIX):
                continue
            registered = name in existing
            try:
                st = os.stat(full)
                mtime = time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime))
                size = self._human_size(st.st_size)
            except OSError:
                mtime, size = "", ""
            iid = "r%d" % i
            status = "已登记" if registered else "未登记"
            self.tree.insert("", "end", iid=iid,
                              tags=("zebra" if i % 2 else "",),
                              values=("☐", name, size, mtime, status))
            self.items.append({"iid": iid, "name": name, "path": full,
                               "registered": registered, "checked": not registered})
            i += 1
        new_count = sum(1 for x in self.items if not x["registered"])
        self.hint.config(text="共 %d 个文件，未登记 %d 个" % (len(self.items), new_count))

    # ---------- 入账 ----------
    def import_selected(self):
        if not self.window.can("docs:create"):
            self.window.toast("当前视角无权执行该操作")
            return
        chosen = [x for x in self.items if x["checked"] and not x["registered"]]
        if not chosen:
            self.window.toast("没有可入账的新文件")
            return
        cat = self.var_cat.get()
        if not self.window.confirm(
                "批量入账确认",
                "将把 %d 份未登记材料按「%s」入账，并自动生成编号；提交人先记为「待补」，可稍后在台账补全。"
                % (len(chosen), cat)):
            return

        ok = 0
        for x in chosen:
            base = os.path.splitext(x["name"])[0]
            try:
                self.repo.add_doc({
                    "name": base, "cat": cat, "who": "待补", "sid": "",
                    "note": "文件夹收集：%s" % os.path.basename(self.folder),
                    "file": x["name"], "path": x["path"], "scope": "全员",
                })
                ok += 1
            except Exception as e:
                messagebox.showerror("入账失败", "%s：%s" % (x["name"], e), parent=self)
        if ok:
            try:
                self.repo.add_log("收集入账", "%d 份文件" % ok,
                                  self.window.operator_name, self.window.role_label())
            except Exception:
                pass
            try:
                archive.write_index(self.repo.list_docs())
            except Exception:
                pass
        self.window.refresh_all()
        self.window.toast("已入账 %d 份材料并自动编号" % ok)
        self.scan()

    def refresh(self):
        if self.items:
            self.scan()

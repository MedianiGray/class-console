# -*- coding: utf-8 -*-
"""材料台账视图：搜索、筛选、查看、归档、驳回。"""

import tkinter as tk
from tkinter import ttk, messagebox

from theme import FONT, C


class DocsView(ttk.Frame):
    COLS = ("name", "cat", "who", "sid", "time", "status", "file")
    HEADS = {"name": "材料名称", "cat": "类别", "who": "提交人", "sid": "学号",
             "time": "提交时间", "status": "状态", "file": "附件"}
    WIDTHS = {"name": 260, "cat": 100, "who": 90, "sid": 90, "time": 130,
              "status": 90, "file": 150}
    CATS = ["全部", "团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]
    STATUS_TAG = {"已归档": "green", "已驳回": "red",
                  "待审核": "orange", "待补材料": "orange"}

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(16, 10))

        ttk.Label(top, text="搜索").pack(side="left")
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *a: self.refresh())
        search = ttk.Entry(top, textvariable=self.q, width=22)
        search.pack(side="left", padx=8)
        search.bind("<Return>", lambda e: self.refresh())

        ttk.Label(top, text="类别").pack(side="left", padx=(16, 0))
        self.cat = tk.StringVar(value="全部")
        cb = ttk.Combobox(top, textvariable=self.cat, values=self.CATS,
                          width=12, state="readonly")
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        ttk.Label(top, text="状态").pack(side="left", padx=(16, 0))
        self.status = tk.StringVar(value="全部")
        sb = ttk.Combobox(top, textvariable=self.status,
                          values=["全部", "待审核", "已归档", "已驳回", "待补材料"],
                          width=12, state="readonly")
        sb.pack(side="left", padx=8)
        sb.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=18)
        self.tree = ttk.Treeview(wrap, columns=self.COLS, show="headings",
                                 selectmode="browse")
        for c in self.COLS:
            self.tree.heading(c, text=self.HEADS[c])
            self.tree.column(c, width=self.WIDTHS[c], anchor="w", stretch=True)
        self.tree.tag_configure("zebra", background=C["zebra"])
        self.tree.tag_configure("green", foreground=C["green"])
        self.tree.tag_configure("orange", foreground=C["orange"])
        self.tree.tag_configure("red", foreground=C["red"])

        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")

        self.empty = ttk.Label(wrap, text="暂无符合条件的材料，可到「提交材料」录入",
                                style="Muted.TLabel")

        # 选中联动与快捷键
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_actions())
        self.tree.bind("<Double-1>", lambda e: self.view())
        self.tree.bind("<Return>", lambda e: self.view())

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=12)
        self.btn_view = ttk.Button(bar, text="查看", command=self.view)
        self.btn_archive = ttk.Button(bar, text="归档", style="Accent.TButton",
                                      command=self.archive)
        self.btn_reject = ttk.Button(bar, text="驳回", style="Danger.TButton",
                                     command=self.reject)
        self.hint = ttk.Label(bar, text="", style="Muted.TLabel")
        self.hint.pack(side="right")

    # ---------- 数据与状态 ----------
    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(self.tree.item(sel[0])["tags"][0])
        except (ValueError, IndexError, KeyError):
            return None

    def _find_doc(self, doc_id):
        return next((x for x in self.repo.list_docs() if x.get("id") == doc_id), None)

    def _update_actions(self):
        has = self._selected() is not None
        state = "normal" if has else "disabled"
        self.btn_view.config(state=state)
        if self.window.role == "admin":
            self.btn_archive.config(state=state)
            self.btn_reject.config(state=state)

    def refresh(self):
        rows = self.repo.list_docs(self.q.get().strip(), self.cat.get())
        st = self.status.get()
        if st and st != "全部":
            rows = [x for x in rows if x.get("status") == st]
        self.tree.delete(*self.tree.get_children())
        for i, d in enumerate(rows):
            row_tag = "zebra" if i % 2 else ""
            status = d.get("status", "") or ""
            status_tag = self.STATUS_TAG.get(status, "orange")
            self.tree.insert("", "end", tags=(d.get("id"), row_tag, status_tag), values=(
                d.get("name", ""), d.get("cat", ""), d.get("who", ""), d.get("sid", ""),
                d.get("time", ""), status, d.get("file") or "无附件"))
        self.hint.config(text="共 %d 条" % len(rows))

        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.4, anchor="center")

        # 同学视角隐藏审核按钮
        is_admin = self.window.role == "admin"
        for b in (self.btn_archive, self.btn_reject):
            b.pack_forget()
        if is_admin:
            self.btn_archive.pack(side="left", padx=8)
            self.btn_reject.pack(side="left")
        self.btn_view.pack(side="left")
        self._update_actions()

    # ---------- 操作 ----------
    def view(self):
        doc_id = self._selected()
        if doc_id is None:
            self.window.toast("请先在列表中选择一条材料")
            return
        doc = self._find_doc(doc_id)
        if not doc:
            return
        name = doc.get("name", "")
        try:
            self.repo.add_log("查看", name, self.window.operator_name,
                              self.window.role_label())
        except Exception:
            self.window.toast("操作已记录，但日志写入失败")
        try:
            self.window.refresh_all()
        except Exception:
            pass

        detail = ("名称：%s\n类别：%s\n提交人：%s（%s）\n提交时间：%s\n状态：%s\n附件：%s\n说明：%s"
                  % (name, doc.get("cat", ""), doc.get("who", ""), doc.get("sid", ""),
                     doc.get("time", ""), doc.get("status", ""),
                     doc.get("file") or "无", doc.get("note") or "无"))

        trace = [l for l in self.repo.list_logs() if l.get("obj") == name]
        if trace:
            lines = ["", "最近操作记录："]
            for l in trace[:5]:
                lines.append("  %s  %s（%s）· %s" % (
                    l.get("time", ""), l.get("who", ""), l.get("role", ""), l.get("act", "")))
            detail += "\n".join(lines)

        messagebox.showinfo("材料详情", detail)

    def archive(self):
        doc_id = self._selected()
        if doc_id is None:
            self.window.toast("请先选择一条材料")
            return
        doc = self._find_doc(doc_id)
        if not doc:
            return
        if doc["status"] == "已归档":
            self.window.toast("该材料已是已归档状态")
            return
        if not self.window.confirm("归档确认", "确定将「%s」归档吗？" % doc["name"]):
            return
        try:
            saved = self.repo.archive_doc(doc_id)
        except Exception as e:
            messagebox.showerror("归档失败", str(e))
            return
        if saved:
            try:
                self.repo.add_log("归档", saved.get("name", ""), self.window.operator_name,
                                  self.window.role_label())
            except Exception:
                pass
            self.window.refresh_all()
            self.window.toast("已归档，并写入操作日志")

    def reject(self):
        doc_id = self._selected()
        if doc_id is None:
            self.window.toast("请先选择一条材料")
            return
        doc = self._find_doc(doc_id)
        if not doc:
            return
        if doc["status"] == "已驳回":
            self.window.toast("该材料已是已驳回状态")
            return
        if not self.window.confirm("驳回确认", "确定驳回「%s」吗？驳回后该材料将标记为已驳回。" % doc["name"]):
            return
        try:
            saved = self.repo.reject_doc(doc_id)
        except Exception as e:
            messagebox.showerror("驳回失败", str(e))
            return
        if saved:
            try:
                self.repo.add_log("驳回", saved.get("name", ""), self.window.operator_name,
                                  self.window.role_label())
            except Exception:
                pass
            self.window.refresh_all()
            self.window.toast("已驳回，并写入操作日志")

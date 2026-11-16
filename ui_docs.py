# -*- coding: utf-8 -*-
"""材料台账视图：搜索、筛选、查看、归档、驳回。"""

import csv
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from theme import FONT, C
from database import form_template


class DocsView(ttk.Frame):
    COLS = ("code", "name", "cat", "who", "sid", "time", "status", "file")
    HEADS = {"code": "编号", "name": "材料名称", "cat": "类别", "who": "提交人",
             "sid": "学号", "time": "提交时间", "status": "状态", "file": "附件"}
    WIDTHS = {"code": 90, "name": 240, "cat": 100, "who": 90, "sid": 90,
              "time": 130, "status": 90, "file": 150}
    CATS = ["全部", "团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]
    TYPE_OPTIONS = [("全部", "全部"), ("general", "个人材料"), ("meeting", "主题班会记录"),
                    ("dorm", "宿舍走访记录"), ("pledg", "班级承诺书"),
                    ("talk", "违纪约谈记录"), ("custom", "自定义材料")]
    TYPE_LABEL = dict(TYPE_OPTIONS)
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

        ttk.Label(top, text="类型").pack(side="left", padx=(16, 0))
        self.type = tk.StringVar(value="全部")
        tb = ttk.Combobox(top, textvariable=self.type,
                          values=[label for _, label in self.TYPE_OPTIONS],
                          width=14, state="readonly")
        tb.pack(side="left", padx=8)
        tb.bind("<<ComboboxSelected>>", lambda e: self.refresh())

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
        self.btn_csv = ttk.Button(bar, text="导出 CSV", command=self.export_csv)
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
        if self.window.can("docs:archive"):
            self.btn_archive.config(state=state)
        if self.window.can("docs:reject"):
            self.btn_reject.config(state=state)

    def _filtered_rows(self):
        rows = self.repo.list_docs(self.q.get().strip(), self.cat.get())
        st = self.status.get()
        if st and st != "全部":
            rows = [x for x in rows if x.get("status") == st]
        tlabel = self.type.get()
        if tlabel and tlabel != "全部":
            tkey = next((k for k, v in self.TYPE_OPTIONS if v == tlabel), "")
            rows = [x for x in rows if (x.get("form_type") or "general") == tkey]
        return rows

    def refresh(self):
        rows = self._filtered_rows()
        self.tree.delete(*self.tree.get_children())
        for i, d in enumerate(rows):
            row_tag = "zebra" if i % 2 else ""
            status = d.get("status", "") or ""
            status_tag = self.STATUS_TAG.get(status, "orange")
            atts = d.get("attachments") or []
            file_disp = ("%d 个附件" % len(atts)) if atts else (d.get("file") or "无附件")
            self.tree.insert("", "end", tags=(d.get("id"), row_tag, status_tag), values=(
                d.get("code", ""), d.get("name", ""), d.get("cat", ""), d.get("who", ""),
                d.get("sid", ""), d.get("time", ""), status, file_disp))
        self.hint.config(text="共 %d 条" % len(rows))

        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.4, anchor="center")

        # 按权限点控制审核按钮显隐
        self.btn_archive.pack_forget()
        self.btn_reject.pack_forget()
        if self.window.can("docs:archive"):
            self.btn_archive.pack(side="left", padx=8)
        if self.window.can("docs:reject"):
            self.btn_reject.pack(side="left")
        self.btn_view.pack(side="left")
        self._update_actions()

    # ---------- 操作 ----------
    def _reason_dialog(self, title, prompt):
        """弹出备注录入框；返回 (确定?, 备注)。取消返回 None。"""
        result = {"ok": False, "reason": ""}
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.transient(self)
        dlg.resizable(False, False)
        ttk.Label(dlg, text=prompt).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))
        box = tk.Text(dlg, height=4, width=42, font=(FONT, 11))
        box.grid(row=1, column=0, padx=16, pady=(0, 12))

        def confirm():
            result["ok"] = True
            result["reason"] = box.get("1.0", "end").strip()
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.grid(row=2, column=0, pady=(0, 14))
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="确定", style="Accent.TButton", command=confirm).pack(side="right")
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.wait_window()
        return result if result["ok"] else None

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

        ftype = doc.get("form_type") or "general"
        tpl = form_template(ftype)
        extra = doc.get("extra") or {}
        detail = ("编号：%s\n类型：%s\n名称：%s\n类别：%s\n提交人：%s（%s）\n提交时间：%s\n状态：%s\n说明：%s"
                  % (doc.get("code") or "—", tpl["label"], name, doc.get("cat", ""),
                     doc.get("who", ""), doc.get("sid", ""),
                     doc.get("time", ""), doc.get("status", ""),
                     doc.get("note") or "无"))

        for f in tpl["fields"]:
            val = ""
            if isinstance(extra, dict):
                val = (extra.get(f["key"]) or "").strip()
            if val:
                detail += "\n%s：%s" % (f["label"], val)

        atts = doc.get("attachments") or []
        if atts:
            detail += "\n附件（%d）：" % len(atts)
            for a in atts:
                line = "\n  · %s" % (a.get("name") or "未命名")
                if a.get("path"):
                    line += "（%s）" % a["path"]
                detail += line
        elif doc.get("file"):
            detail += "\n附件：%s" % doc.get("file")
        else:
            detail += "\n附件：无"

        doc_path = doc.get("path") or ""
        if doc_path:
            detail += "\n本机路径：%s" % doc_path
        reason = doc.get("reason") or ""
        if reason:
            detail += "\n审核备注：%s" % reason

        trace = [l for l in self.repo.list_logs() if l.get("obj") == name]
        if trace:
            lines = ["", "最近操作记录："]
            for l in trace[:5]:
                lines.append("  %s  %s（%s）· %s" % (
                    l.get("time", ""), l.get("who", ""), l.get("role", ""), l.get("act", "")))
            detail += "\n".join(lines)

        messagebox.showinfo("材料详情", detail)

    def archive(self):
        if not self.window.can("docs:archive"):
            self.window.toast("当前视角无权归档")
            return
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
        dlg = self._reason_dialog("归档确认", "归档「%s」，可补充归档备注（可选）：" % doc["name"])
        if dlg is None:
            return
        try:
            saved = self.repo.archive_doc(doc_id, dlg["reason"])
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
        if not self.window.can("docs:reject"):
            self.window.toast("当前视角无权驳回")
            return
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
        dlg = self._reason_dialog("驳回确认", "驳回「%s」，请填写驳回原因（可选）：" % doc["name"])
        if dlg is None:
            return
        try:
            saved = self.repo.reject_doc(doc_id, dlg["reason"])
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

    def export_csv(self):
        rows = self._filtered_rows()
        if not rows:
            self.window.toast("当前没有可导出的材料")
            return
        path = filedialog.asksaveasfilename(
            title="导出 CSV", defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        headers = ["材料编号", "材料类型", "材料名称", "类别", "提交人", "学号",
                   "提交时间", "状态", "附件", "备注", "审核备注"]
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(headers)
                for d in rows:
                    atts = d.get("attachments") or []
                    att_names = "; ".join(a.get("name", "") for a in atts) or d.get("file") or ""
                    tpl = form_template(d.get("form_type") or "general")
                    w.writerow([d.get("code", ""), tpl["label"], d.get("name", ""),
                                d.get("cat", ""), d.get("who", ""), d.get("sid", ""),
                                d.get("time", ""), d.get("status", ""), att_names,
                                d.get("note", ""), d.get("reason") or ""])
            self.window.toast("已导出 %d 条记录" % len(rows))
        except OSError as e:
            messagebox.showerror("导出失败", str(e))

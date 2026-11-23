# -*- coding: utf-8 -*-
"""名单核对视图：学号—姓名名单、应交/已交/未交核对、服务登记与完成矩阵。"""

import datetime
import tkinter as tk
from tkinter import ttk, messagebox

import service
from theme import FONT, C


class RosterView(ttk.Frame):
    COLS = ("sid", "who", "status")
    HEADS = {"sid": "学号", "who": "姓名", "status": "材料状态"}
    WIDTHS = {"sid": 140, "who": 160, "status": 90}
    MATRIX_CATS = ["团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(4, 10))
        self.summary = ttk.Label(top, text="", style="Muted.TLabel")
        self.summary.pack(side="right")

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=18)
        wrap.columnconfigure(0, weight=3)
        wrap.columnconfigure(1, weight=1)
        wrap.rowconfigure(0, weight=1)

        style = ttk.Style(self.window)
        style.configure("Roster.TNotebook", background=C["bg"], borderwidth=0)
        style.configure("Roster.TNotebook.Tab", background=C["bg_soft"],
                        foreground=C["sub"], padding=(14, 6))
        style.map("Roster.TNotebook.Tab",
                  background=[("selected", C["card"])],
                  foreground=[("selected", C["text"])])
        self.nb = ttk.Notebook(wrap, style="Roster.TNotebook")
        self.nb.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        list_tab = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(list_tab, text="名单核对")
        matrix_tab = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(matrix_tab, text="完成矩阵")

        table_box = tk.Frame(list_tab, bg=C["card"], highlightthickness=1,
                             highlightbackground=C["line"])
        table_box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table_box, columns=self.COLS, show="headings",
                                 selectmode="browse")
        for c in self.COLS:
            self.tree.heading(c, text=self.HEADS[c], anchor="w")
            self.tree.column(c, width=self.WIDTHS[c], anchor="w", stretch=True)
        self.tree.tag_configure("zebra", background=C["zebra"])
        ysb = ttk.Scrollbar(table_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
        ysb.pack(side="right", fill="y", padx=(0, 1), pady=1)

        self.empty = ttk.Label(table_box, text="名单为空，可在下方添加成员", style="Muted.TLabel")

        # 完成矩阵：名单成员 × 材料类别，补「谁哪类还没交」的信息
        matrix_tab.rowconfigure(1, weight=1)
        matrix_tab.columnconfigure(0, weight=1)
        self.matrix_summary = ttk.Label(matrix_tab, text="", style="Muted.TLabel",
                                        anchor="w", wraplength=760, justify="left")
        self.matrix_summary.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        mx_box = tk.Frame(matrix_tab, bg=C["card"], highlightthickness=1,
                          highlightbackground=C["line"])
        mx_box.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 4))
        self.matrix = ttk.Treeview(
            mx_box, columns=("sid", "who") + tuple(self.MATRIX_CATS),
            show="headings", selectmode="browse")
        self.matrix.heading("sid", text="学号", anchor="w")
        self.matrix.heading("who", text="姓名", anchor="w")
        self.matrix.column("sid", width=104, minwidth=88, anchor="w", stretch=False)
        self.matrix.column("who", width=84, minwidth=70, anchor="w", stretch=False)
        for cat in self.MATRIX_CATS:
            self.matrix.heading(cat, text=cat, anchor="center")
            self.matrix.column(cat, width=92, minwidth=76, anchor="center", stretch=False)
        self.matrix.tag_configure("zebra", background=C["zebra"])
        mysb = ttk.Scrollbar(mx_box, orient="vertical", command=self.matrix.yview)
        mxsb = ttk.Scrollbar(mx_box, orient="horizontal", command=self.matrix.xview)
        self.matrix.configure(yscrollcommand=mysb.set, xscrollcommand=mxsb.set)
        self.matrix.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=(1, 0))
        mysb.grid(row=0, column=1, sticky="ns", padx=(0, 1), pady=1)
        mxsb.grid(row=1, column=0, sticky="ew", padx=(1, 0), pady=(0, 1))
        mx_box.rowconfigure(0, weight=1)
        mx_box.columnconfigure(0, weight=1)
        self.matrix.bind("<Double-1>", self._open_student)
        self.matrix.bind("<Button-1>", self._on_matrix_click, add="+")
        self.matrix.bind("<<TreeviewSelect>>", self._on_matrix_select, add="+")

        # 服务操作条：选中一行 + 类别，就地登记，不再开第二套页面
        actbar = tk.Frame(matrix_tab, bg=C["bg"])
        actbar.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 6))
        self.matrix_target = tk.Label(
            actbar, text="选中一行后再登记", bg=C["bg"], fg=C["muted"],
            font=(FONT, 9), anchor="w")
        self.matrix_target.pack(side="left")
        self.svc_cat = tk.StringVar(value=self.MATRIX_CATS[0])
        self.svc_cat_box = ttk.Combobox(
            actbar, textvariable=self.svc_cat, values=self.MATRIX_CATS,
            state="readonly", width=10)
        self.svc_cat_box.pack(side="left", padx=(10, 6))
        self.svc_cat_box.bind("<<ComboboxSelected>>",
                              lambda e: self._update_matrix_actions())
        self.btn_receipt = ttk.Button(actbar, text="登记回执",
                                      style="Ghost.TButton",
                                      command=self._receipt_dialog)
        self.btn_chase = ttk.Button(actbar, text="生成催交",
                                    style="Ghost.TButton",
                                    command=self._chase_selected)
        self.btn_exempt = ttk.Button(actbar, text="免交 / 延期",
                                     command=self._exempt_dialog)
        self.btn_exempt.pack(side="right")
        self.btn_chase.pack(side="right", padx=6)
        self.btn_receipt.pack(side="right")

        # 右侧核对面板：三个数字 + 未交名单，补足「谁没交」的信息
        panel = tk.Frame(wrap, bg=C["card"], highlightthickness=1,
                         highlightbackground=C["line"])
        panel.grid(row=0, column=1, sticky="nsew")
        tk.Label(panel, text="核对概况", bg=C["card"], fg=C["text"],
                 font=(FONT, 10, "bold"), anchor="w").pack(fill="x", padx=16, pady=(14, 8))
        self.stat_labels = {}
        for key, label, color in (("total", "应交", C["muted"]),
                                  ("done", "已交", C["green"]),
                                  ("absent", "未交", C["orange"])):
            row = tk.Frame(panel, bg=C["card"])
            row.pack(fill="x", padx=16, pady=2)
            tk.Frame(row, bg=color, width=4, height=4).pack(side="left", pady=(6, 0))
            tk.Label(row, text=label, bg=C["card"], fg=C["sub"],
                     font=(FONT, 9)).pack(side="left", padx=(8, 0))
            num = tk.Label(row, text="0", bg=C["card"], fg=C["text"],
                           font=(FONT, 15, "bold"))
            num.pack(side="right")
            self.stat_labels[key] = num
        tk.Frame(panel, bg=C["line"], height=1).pack(fill="x", padx=16, pady=(10, 8))
        tk.Label(panel, text="未交名单", bg=C["card"], fg=C["sub"],
                 font=(FONT, 9), anchor="w").pack(fill="x", padx=16)
        self.absent_box = tk.Frame(panel, bg=C["card"])
        self.absent_box.pack(fill="both", expand=True, padx=16, pady=(6, 14))

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=12)
        self.btn_add = ttk.Button(bar, text="添加成员", style="Accent.TButton",
                                  command=self.add_dialog)
        self.btn_remove = ttk.Button(bar, text="移除选中", style="Ghost.TButton",
                                     command=self.remove_selected)
        self.btn_clear = ttk.Button(bar, text="清空名单", style="Ghost.TButton",
                                    command=self.clear_all)

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(self.tree.item(sel[0])["tags"][0])
        except (ValueError, IndexError, KeyError):
            return None

    def refresh(self):
        rows = self.repo.list_roster()
        docs = self.repo.list_docs()
        submitted = {d.get("sid") for d in docs
                     if d.get("sid") and d.get("status") in ("待审核", "已归档")}
        rejected = {d.get("sid") for d in docs
                    if d.get("sid") and d.get("status") == "已驳回"}
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(rows):
            tag = "zebra" if i % 2 else ""
            sid = r.get("sid")
            if sid in submitted:
                status = "已交"
            elif sid in rejected:
                status = "需补交"
            else:
                status = "未交"
            self.tree.insert("", "end", tags=(r["id"], tag),
                             values=(r.get("sid", ""), r.get("who", ""), status))
        ex_map = self.repo.exemption_map()
        receipts = self.repo.latest_receipts()
        self._refresh_matrix(rows, docs, ex_map, receipts)
        chk = self.repo.roster_check()
        self.summary.config(text="名单共 %d 人" % chk["total"])
        for key, val in (("total", chk["total"]), ("done", chk["done"]),
                         ("absent", len(chk["absent"]))):
            if key in self.stat_labels:
                self.stat_labels[key].config(text=str(val))
        for w in self.absent_box.winfo_children():
            w.destroy()
        absent = chk["absent"]
        if not absent:
            tk.Label(self.absent_box, text="全部已交，核对完成", bg=C["card"],
                     fg=C["green"], font=(FONT, 9), anchor="w").pack(fill="x")
        else:
            for r in absent[:12]:
                row = tk.Frame(self.absent_box, bg=C["card"])
                row.pack(fill="x", pady=2)
                tk.Label(row, text=r.get("who", ""), bg=C["card"], fg=C["text"],
                         font=(FONT, 9), anchor="w").pack(side="left")
                tk.Label(row, text=r.get("sid", ""), bg=C["card"], fg=C["sub"],
                         font=(FONT, 9), anchor="e").pack(side="right")
            if len(absent) > 12:
                tk.Label(self.absent_box, text="另有 %d 人…" % (len(absent) - 12),
                         bg=C["card"], fg=C["sub"], font=(FONT, 9),
                         anchor="w").pack(fill="x")
        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.4, anchor="center")

        # 名单维护按 roster:manage 权限点显隐
        can_manage = self.window.can("roster:manage")
        for b in (self.btn_add, self.btn_remove, self.btn_clear):
            b.pack_forget()
        if can_manage:
            self.btn_add.pack(side="left")
            self.btn_remove.pack(side="left", padx=8)
            self.btn_clear.pack(side="left")
        self._update_matrix_actions()

    def _on_matrix_click(self, event):
        col = self.matrix.identify_column(event.x)
        try:
            idx = int(col.replace("#", "")) - 3
        except ValueError:
            idx = -1
        if 0 <= idx < len(self.MATRIX_CATS):
            self.svc_cat.set(self.MATRIX_CATS[idx])
        self._update_matrix_actions()
        return None

    def _on_matrix_select(self, _event=None):
        self._update_matrix_actions()

    def _matrix_selected(self):
        iid = self.matrix.focus() or (self.matrix.selection()[0]
                                      if self.matrix.selection() else "")
        if not iid:
            return None
        vals = self.matrix.item(iid, "values")
        if not vals:
            return None
        return str(vals[0]), str(vals[1])

    def _selected_cell_status(self):
        pair = self._matrix_selected()
        if not pair:
            return "无记录"
        sid, _who = pair
        return service.cell_status(self.repo.list_docs(), sid,
                                   self.svc_cat.get(),
                                   self.repo.exemption_map(),
                                   self.repo.latest_receipts())

    def _update_matrix_actions(self):
        pair = self._matrix_selected()
        can = bool(pair) and self.window.can("roster:manage")
        if pair:
            self.matrix_target.config(
                text="%s · %s · %s：%s" % (pair[1], pair[0], self.svc_cat.get(),
                                          self._selected_cell_status()),
                fg=C["text"])
        else:
            self.matrix_target.config(text="选中一行后再登记", fg=C["muted"])
        for b in (self.btn_exempt, self.btn_chase, self.btn_receipt):
            b.config(state="normal" if can else "disabled")

    def _cell_status(self, docs, sid, cat, ex_map=None, receipts=None):
        return service.cell_status(docs, sid, cat, ex_map, receipts)

    def _refresh_matrix(self, rows, docs, ex_map=None, receipts=None):
        self.matrix.delete(*self.matrix.get_children())
        keys = ("已交", "待审", "补交", "免交", "延期",
                "回执·已交", "回执·校外", "回执·稍后", "无记录")
        counts = {k: 0 for k in keys}
        for i, r in enumerate(rows):
            sid = r.get("sid") or ""
            cells = [self._cell_status(docs, sid, c, ex_map, receipts)
                     for c in self.MATRIX_CATS]
            for c in cells:
                counts[c] = counts.get(c, 0) + 1
            self.matrix.insert("", "end", tags=(r["id"], "zebra" if i % 2 else ""),
                               values=(sid, r.get("who", "")) + tuple(cells))
        total = sum(counts.values())
        if total:
            receipt = (counts["回执·已交"] + counts["回执·校外"] +
                       counts["回执·稍后"])
            text = ("已交 %d · 待审 %d · 补交 %d · 免交 %d · 延期 %d · 回执 %d · 无记录 %d　"
                    "双击一行查看该生全部材料" % (
                        counts["已交"], counts["待审"], counts["补交"],
                        counts["免交"], counts["延期"], receipt,
                        counts["无记录"]))
        else:
            text = "名单为空，先添加成员再查看完成矩阵"
        self.matrix_summary.config(text=text)

    def _open_student(self, _event=None):
        iid = self.matrix.focus()
        if not iid:
            return "break"
        vals = self.matrix.item(iid, "values")
        if not vals:
            return "break"
        sid = str(vals[0])
        docs = self.window.views.get("docs")
        if docs is None or not sid:
            return "break"
        docs.q.set(sid)
        docs.cat.set("全部")
        docs.type.set("全部")
        docs.status.set("全部")
        docs.refresh()
        self.window.switch("docs")
        self.window.toast("已按学号 %s 筛出台账" % sid)
        return "break"

    # ---------- 服务登记 ----------
    def _need_service_target(self, action):
        pair = self._matrix_selected()
        if not pair:
            self.window.toast("请先在完成矩阵里选中一名成员")
            return None
        if not self.window.can("roster:manage"):
            self.window.toast("当前视角无权登记服务动作")
            return None
        return pair

    def _service_dialog(self, title, width, height):
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.transient(self.window)
        dlg.resizable(False, False)
        dlg.configure(bg=C["bg"])
        top = self.window.winfo_toplevel()
        top.update_idletasks()
        x = top.winfo_rootx() + max(0, (top.winfo_width() - width) // 2)
        y = top.winfo_rooty() + max(0, (top.winfo_height() - height) // 2)
        dlg.geometry("%dx%d+%d+%d" % (width, height, x, y))
        dlg.grab_set()
        return dlg

    def _exempt_dialog(self):
        pair = self._need_service_target("登记免交 / 延期")
        if not pair:
            return
        sid, who = pair
        cat = self.svc_cat.get()
        old = next((x for x in self.repo.list_exemptions()
                    if x.get("sid") == sid and x.get("cat") == cat), None)
        dlg = self._service_dialog("免交 / 延期", 430, 350)
        tk.Label(dlg, text="%s · %s" % (who, cat), bg=C["bg"], fg=C["text"],
                 font=(FONT, 10, "bold"), anchor="w").pack(fill="x", padx=18, pady=(16, 4))
        if old:
            tk.Label(dlg, text="当前登记：%s　%s" % (
                old.get("state") or old.get("kind"),
                old.get("until") and ("至 " + old["until"]) or ""),
                bg=C["bg"], fg=C["muted"], font=(FONT, 9), anchor="w").pack(
                    fill="x", padx=18)
        else:
            tk.Label(dlg, text="没有登记时按「无记录」催交；登记后不再重复追赶。",
                     bg=C["bg"], fg=C["muted"], font=(FONT, 9), anchor="w",
                     wraplength=390, justify="left").pack(fill="x", padx=18)

        kind = tk.StringVar(value=(old.get("kind") if old else "免交"))
        reason = tk.StringVar(value=(old.get("reason") if old else ""))
        until = tk.StringVar(value=(old.get("until") if old else
                                   (datetime.date.today() +
                                    datetime.timedelta(days=7)).strftime("%Y-%m-%d")))
        form = tk.Frame(dlg, bg=C["bg"])
        form.pack(fill="x", padx=18, pady=(10, 0))
        tk.Label(form, text="类型", bg=C["bg"], fg=C["sub"], font=(FONT, 9)).grid(
            row=0, column=0, sticky="w", pady=4)
        kbox = tk.Frame(form, bg=C["bg"])
        kbox.grid(row=0, column=1, sticky="w", padx=(10, 0))
        for val in ("免交", "延期"):
            tk.Radiobutton(kbox, text=val, variable=kind, value=val, bg=C["bg"],
                           fg=C["text"], selectcolor=C["card"],
                           activebackground=C["bg"], activeforeground=C["text"],
                           font=(FONT, 9)).pack(side="left", padx=(0, 12))
        tk.Label(form, text="原因 *", bg=C["bg"], fg=C["sub"], font=(FONT, 9)).grid(
            row=1, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=reason, width=32).grid(
            row=1, column=1, sticky="w", padx=(10, 0), pady=4)
        tk.Label(form, text="延期到", bg=C["bg"], fg=C["sub"], font=(FONT, 9)).grid(
            row=2, column=0, sticky="w", pady=4)
        until_entry = ttk.Entry(form, textvariable=until, width=16)
        until_entry.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=4)
        tk.Label(form, text="转学、免修、校外已交写清原因；延期到期后自动回到无记录。",
                 bg=C["bg"], fg=C["muted"], font=(FONT, 8), anchor="w",
                 wraplength=390, justify="left").grid(
                     row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        err = tk.Label(dlg, text="", bg=C["bg"], fg=C["red"], font=(FONT, 9),
                       anchor="w", wraplength=390, justify="left")
        err.pack(fill="x", padx=18, pady=(6, 0))

        def sync_until(*_a):
            until_entry.config(state=("normal" if kind.get() == "延期" else "disabled"))

        kind.trace_add("write", sync_until)
        sync_until()

        def save():
            try:
                self.repo.set_exemption(
                    sid, who, cat, kind.get(), reason.get(), until.get(),
                    self.window.operator_name, self.window.role_label())
            except Exception as e:
                err.config(text=str(e))
                return
            dlg.destroy()
            self.window.refresh_all()
            self.window.toast("已登记%s：%s · %s" % (kind.get(), who, cat))

        def remove():
            if not old:
                return
            if not self.window.confirm("取消登记", "确定取消 %s · %s 的%s吗？" % (
                    who, cat, old.get("kind"))):
                return
            self.repo.remove_exemption(sid, cat, self.window.operator_name,
                                       self.window.role_label())
            dlg.destroy()
            self.window.refresh_all()
            self.window.toast("已恢复应交：%s · %s" % (who, cat))

        btns = tk.Frame(dlg, bg=C["bg"])
        btns.pack(fill="x", padx=18, pady=(10, 14))
        ttk.Button(btns, text="关闭", style="Ghost.TButton",
                   command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="保存登记", style="Accent.TButton",
                   command=save).pack(side="right", padx=8)
        if old:
            ttk.Button(btns, text="取消现有登记", style="Ghost.TButton",
                       command=remove).pack(side="left")

    def _receipt_dialog(self):
        pair = self._need_service_target("登记回执")
        if not pair:
            return
        sid, who = pair
        cat = self.svc_cat.get()
        dlg = self._service_dialog("登记回执", 430, 310)
        tk.Label(dlg, text="%s · %s" % (who, cat), bg=C["bg"], fg=C["text"],
                 font=(FONT, 10, "bold"), anchor="w").pack(fill="x", padx=18, pady=(16, 4))
        tk.Label(dlg, text="回执只停止重复追赶，不等于材料已归档。",
                 bg=C["bg"], fg=C["muted"], font=(FONT, 9), anchor="w").pack(
                     fill="x", padx=18)
        form = tk.Frame(dlg, bg=C["bg"])
        form.pack(fill="x", padx=18, pady=(10, 0))
        tk.Label(form, text="回执", bg=C["bg"], fg=C["sub"], font=(FONT, 9)).grid(
            row=0, column=0, sticky="w", pady=4)
        response = tk.StringVar(value="已提交")
        ttk.Combobox(form, textvariable=response, values=("已提交", "校外交", "稍后补"),
                     state="readonly", width=12).grid(
                         row=0, column=1, sticky="w", padx=(10, 0), pady=4)
        tk.Label(form, text="备注", bg=C["bg"], fg=C["sub"], font=(FONT, 9)).grid(
            row=1, column=0, sticky="w", pady=4)
        note = tk.StringVar()
        ttk.Entry(form, textvariable=note, width=30).grid(
            row=1, column=1, sticky="w", padx=(10, 0), pady=4)
        hint = tk.Label(dlg, text=service.receipt_suggestion("已提交"), bg=C["bg"],
                        fg=C["muted"], font=(FONT, 8), anchor="w", wraplength=390,
                        justify="left")
        hint.pack(fill="x", padx=18, pady=(6, 0))
        response.trace_add("write", lambda *a: hint.config(
            text=service.receipt_suggestion(response.get())))
        err = tk.Label(dlg, text="", bg=C["bg"], fg=C["red"], font=(FONT, 9),
                       anchor="w", wraplength=390, justify="left")
        err.pack(fill="x", padx=18, pady=(6, 0))

        def save():
            try:
                self.repo.add_receipt(sid, who, cat, response.get(), note.get(),
                                      self.window.operator_name,
                                      self.window.role_label())
            except Exception as e:
                err.config(text=str(e))
                return
            dlg.destroy()
            self.window.refresh_all()
            self.window.toast("已登记回执：%s · %s · %s" % (who, cat, response.get()))

        btns = tk.Frame(dlg, bg=C["bg"])
        btns.pack(fill="x", padx=18, pady=(12, 14))
        ttk.Button(btns, text="关闭", style="Ghost.TButton",
                   command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="保存回执", style="Accent.TButton",
                   command=save).pack(side="right", padx=8)

    def _chase_selected(self):
        pair = self._need_service_target("生成催交")
        if not pair:
            return
        sid, who = pair
        docs = self.repo.list_docs()
        missing = service.missing_categories(
            docs, sid, self.repo.exemption_map(), self.repo.latest_receipts())
        if not missing:
            messagebox.showinfo("无需催交",
                                "该生没有待催类别：待审的等审核，免交 / 延期的已登记。",
                                parent=self.window)
            return
        state = self.repo.chase_state(sid)
        if not state["allowed"]:
            messagebox.showinfo(
                "24 小时内不重复提醒",
                "上次联系在 %s，还需等待约 %s。\n\n同一学生每天只提醒一次；"
                "如已收到回执，可在矩阵里登记回执。" % (
                    state.get("last") or "不久前",
                    service.wait_text(state.get("remain_min"))),
                parent=self.window)
            return
        deadline = self.repo.nearest_deadline(missing)
        msg = service.chase_message(who, missing, deadline)
        dlg = self._service_dialog("生成催交话术", 500, 400)
        tk.Label(dlg, text="%s · %s" % (who, sid), bg=C["bg"], fg=C["text"],
                 font=(FONT, 10, "bold"), anchor="w").pack(fill="x", padx=18, pady=(14, 4))
        tk.Label(dlg, text="将发：%s%s" % ("、".join(missing),
                 ("　截止 " + deadline) if deadline else ""),
                 bg=C["bg"], fg=C["muted"], font=(FONT, 9), anchor="w",
                 wraplength=460, justify="left").pack(fill="x", padx=18)
        box = tk.Text(dlg, wrap="word", height=8, relief="flat", bd=0,
                      bg=C["card"], fg=C["text"], font=(FONT, 10),
                      padx=10, pady=8, highlightthickness=1,
                      highlightbackground=C["line"])
        box.pack(fill="both", expand=True, padx=18, pady=(8, 6))
        box.insert("1.0", msg)
        box.config(state="disabled")
        crow = tk.Frame(dlg, bg=C["bg"])
        crow.pack(fill="x", padx=18)
        tk.Label(crow, text="渠道", bg=C["bg"], fg=C["sub"], font=(FONT, 9)).pack(side="left")
        channel = tk.StringVar(value="微信 / 群公告")
        ttk.Combobox(crow, textvariable=channel, state="readonly", width=14,
                     values=("微信 / 群公告", "私聊", "当面提醒")).pack(
                         side="left", padx=(8, 0))
        tk.Label(crow, text="复制后只登记一次，24 小时内不再催同一人。",
                 bg=C["bg"], fg=C["muted"], font=(FONT, 8)).pack(side="left", padx=(10, 0))
        err = tk.Label(dlg, text="", bg=C["bg"], fg=C["red"], font=(FONT, 9),
                       anchor="w", wraplength=460, justify="left")
        err.pack(fill="x", padx=18)

        def copy_only():
            self.clipboard_clear()
            self.clipboard_append(msg)
            self.window.toast("话术已复制，未登记催交")

        def copy_and_log():
            try:
                self.repo.add_followup(sid, who, "、".join(missing), msg,
                                       channel.get(), self.window.operator_name,
                                       self.window.role_label())
            except Exception as e:
                err.config(text=str(e))
                return
            self.clipboard_clear()
            self.clipboard_append(msg)
            dlg.destroy()
            self.window.refresh_all()
            self.window.toast("话术已复制，并记入服务留痕")

        btns = tk.Frame(dlg, bg=C["bg"])
        btns.pack(fill="x", padx=18, pady=(10, 14))
        ttk.Button(btns, text="关闭", style="Ghost.TButton",
                   command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="复制并登记", style="Accent.TButton",
                   command=copy_and_log).pack(side="right", padx=8)
        ttk.Button(btns, text="只复制", style="Ghost.TButton",
                   command=copy_only).pack(side="right")

    def add_dialog(self):
        if not self.window.can("roster:manage"):
            self.window.toast("当前视角无权执行该操作")
            return
        dlg = tk.Toplevel(self)
        dlg.title("添加成员")
        dlg.transient(self)
        dlg.resizable(False, False)
        sid_var, who_var = tk.StringVar(), tk.StringVar()
        err = ttk.Label(dlg, text="", foreground=C["red"], font=(FONT, 10))

        ttk.Label(dlg, text="学号 *").grid(row=0, column=0, sticky="w", padx=16, pady=10)
        ttk.Entry(dlg, textvariable=sid_var, width=20).grid(row=0, column=1, padx=16, pady=10)
        ttk.Label(dlg, text="姓名 *").grid(row=1, column=0, sticky="w", padx=16, pady=10)
        ttk.Entry(dlg, textvariable=who_var, width=20).grid(row=1, column=1, padx=16, pady=10)
        err.grid(row=2, column=0, columnspan=2, sticky="w", padx=16)

        def submit():
            try:
                self.repo.add_roster(sid_var.get(), who_var.get())
            except Exception as e:
                err.config(text=str(e))
                return
            dlg.destroy()
            self.window.refresh_all()
            self.window.toast("已添加成员")

        btns = ttk.Frame(dlg)
        btns.grid(row=3, column=0, columnspan=2, pady=(6, 14))
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="保存", style="Accent.TButton", command=submit).pack(side="right")
        dlg.bind("<Return>", lambda e: submit())

    def remove_selected(self):
        if not self.window.can("roster:manage"):
            self.window.toast("当前视角无权执行该操作")
            return
        rid = self._selected()
        if rid is None:
            self.window.toast("请先在列表中选择一名成员")
            return
        if not self.window.confirm("移除确认", "确定移除该成员吗？"):
            return
        self.repo.remove_roster(rid)
        self.window.refresh_all()
        self.window.toast("成员已移除")

    def clear_all(self):
        if not self.window.can("roster:manage"):
            self.window.toast("当前视角无权执行该操作")
            return
        rows = self.repo.list_roster()
        if not rows:
            self.window.toast("名单已是空的")
            return
        if not self.window.confirm("清空名单", "确定清空全部 %d 名成员吗？此操作不可撤销。" % len(rows)):
            return
        for r in rows:
            self.repo.remove_roster(r["id"])
        self.window.refresh_all()
        self.window.toast("名单已清空")

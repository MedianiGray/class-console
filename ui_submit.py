# -*- coding: utf-8 -*-
"""提交材料视图：模板表单录入、内联校验、多附件登记。"""

import os
import tkinter as tk
from tkinter import ttk, filedialog

from theme import FONT, C


class SubmitView(ttk.Frame):
    CATS = ["团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]
    TYPE_OPTIONS = [
        ("general", "个人材料"),
        ("meeting", "主题班会记录"),
        ("dorm", "宿舍走访记录"),
        ("pledg", "班级承诺书"),
        ("talk", "违纪约谈记录"),
        ("custom", "自定义材料"),
    ]

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self.attachments = []
        self.extra_vars = {}
        self._last_suggest = ""
        self._submitting = False
        self._build()

    def _build(self):
        # 操作区固定在窗口底部，滚动只作用于表单字段
        footer = tk.Frame(self, bg=C["bg"])
        footer.pack(side="bottom", fill="x")
        tk.Frame(footer, bg=C["line"], height=1).pack(fill="x")
        bar = tk.Frame(footer, bg=C["bg"])
        bar.pack(fill="x", padx=24, pady=10)
        self.err_label = ttk.Label(bar, text="", foreground=C["red"], font=(FONT, 9))
        self.err_label.pack(side="left")
        self.btn_submit = ttk.Button(bar, text="提交材料", style="Accent.TButton",
                                     command=self.submit)
        self.btn_submit.pack(side="right")
        ttk.Button(bar, text="清空", command=self.clear).pack(side="right", padx=8)

        # 表单外套滚动容器；卡片限宽居中，字段不被拉成整行宽
        holder = tk.Frame(self, bg=C["bg"])
        holder.pack(fill="both", expand=True)
        canvas = tk.Canvas(holder, bg=C["bg"], highlightthickness=0, bd=0,
                           yscrollincrement=40)
        vsb = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=C["bg"])
        win = canvas.create_window((0, 0), window=inner, anchor="n")

        def _fit(event):
            width = min(840, max(540, event.width - 64))
            canvas.itemconfigure(win, width=width)
            canvas.coords(win, max(24, (event.width - width) // 2), 12)
        canvas.bind("<Configure>", _fit)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _wheel(e):
            canvas.yview_scroll(int(-e.delta / 120) * 3, "units")

        def _bind_wheel(_e=None):
            canvas.bind_all("<MouseWheel>", _wheel)

        def _unbind_wheel(_e=None):
            canvas.unbind_all("<MouseWheel>")

        for w in (canvas, inner):
            w.bind("<Enter>", _bind_wheel)
            w.bind("<Leave>", _unbind_wheel)

        card = tk.Frame(inner, bg=C["card"], highlightthickness=1,
                        highlightbackground=C["line"])
        card.pack(fill="x", pady=(4, 20))

        head = tk.Frame(card, bg=C["card"])
        head.pack(fill="x", padx=26, pady=(12, 0))
        tk.Label(head, text="填写材料信息", bg=C["card"], fg=C["text"],
                 font=(FONT, 11, "bold")).pack(side="left")
        tk.Label(head, text="带 * 为必填，提交后进入待审核队列", bg=C["card"],
                 fg=C["sub"], font=(FONT, 9)).pack(side="right", pady=(3, 0))
        tk.Frame(card, bg=C["line"], height=1).pack(fill="x", padx=26, pady=(12, 0))

        body = tk.Frame(card, bg=C["card"])
        body.pack(fill="x", padx=26, pady=(12, 16))
        body.columnconfigure(0, weight=1, uniform="f")
        body.columnconfigure(1, weight=1, uniform="f")

        self.var_type = tk.StringVar(value=self.TYPE_OPTIONS[0][1])
        self.var_title = tk.StringVar()
        self.var_name = tk.StringVar()
        self.var_sid = tk.StringVar()
        self.var_cat = tk.StringVar()
        self.var_code = tk.StringVar()
        self.var_note = None

        cell = self._cell(body, 0, 0, "材料类型 *")
        type_cb = ttk.Combobox(cell, textvariable=self.var_type,
                               values=[label for _, label in self.TYPE_OPTIONS],
                               state="readonly")
        type_cb.pack(fill="x")
        type_cb.bind("<<ComboboxSelected>>", lambda e: self._on_type())
        self._type_label = {label: key for key, label in self.TYPE_OPTIONS}

        cell = self._cell(body, 0, 1, "材料类别 *")
        cat_cb = ttk.Combobox(cell, textvariable=self.var_cat, values=self.CATS,
                              state="readonly")
        cat_cb.pack(fill="x")
        cat_cb.bind("<<ComboboxSelected>>", lambda e: self._suggest_code())
        cat_cb.bind("<Return>", lambda e: self.submit())
        cat_cb.bind("<Escape>", lambda e: self.clear())

        cell = self._cell(body, 1, 0, "材料名称 *", span=2)
        self._entry(cell, self.var_title)

        cell = self._cell(body, 2, 0, "提交人 / 记录人")
        self._entry(cell, self.var_name)
        cell = self._cell(body, 2, 1, "学号")
        self._entry(cell, self.var_sid)

        cell = self._cell(body, 3, 0, "材料编号（留空自动）")
        self._entry(cell, self.var_code)

        # 模板专属字段（随类型重建）
        self.extra_box = tk.Frame(body, bg=C["card"])
        self.extra_box.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.extra_box.columnconfigure(0, weight=1)
        self._extra_row = 4

        cell = self._cell(body, 5, 0, "材料说明", span=2)
        self.var_note = tk.Text(cell, height=2, font=(FONT, 10), relief="flat",
                                bd=0, bg=C["surface_alt"], fg=C["text"],
                                insertbackground=C["text"], highlightthickness=1,
                                highlightbackground=C["line"],
                                highlightcolor=C["primary"], padx=8, pady=6)
        self.var_note.pack(fill="x")

        cell = self._cell(body, 6, 0, "附件", span=2, pady=(0, 0))
        att = tk.Frame(cell, bg=C["card"])
        att.pack(fill="x")
        self.att_list = tk.Listbox(att, height=2, font=(FONT, 9), selectmode="extended",
                                   relief="flat", bd=0, bg=C["surface_alt"],
                                   fg=C["text"], highlightthickness=1,
                                   highlightbackground=C["line"],
                                   selectbackground=C["select"])
        self.att_list.pack(fill="x")
        att_btns = tk.Frame(att, bg=C["card"])
        att_btns.pack(fill="x", pady=(6, 0))
        ttk.Button(att_btns, text="添加附件", command=self.pick_files).pack(side="left")
        ttk.Button(att_btns, text="移除所选", command=self.remove_selected).pack(side="left", padx=6)
        ttk.Button(att_btns, text="清空", command=self.clear_files).pack(side="left")

        self._render_extra("general")

    def _cell(self, parent, row, col, label, span=1, pady=(0, 10)):
        cell = tk.Frame(parent, bg=C["card"])
        padx = (0, 10) if (col == 0 and span == 1) else (0, 0)
        cell.grid(row=row, column=col, columnspan=span, sticky="ew",
                  padx=padx, pady=pady)
        tk.Label(cell, text=label, bg=C["card"], fg=C["sub"], font=(FONT, 9),
                 anchor="w").pack(fill="x", pady=(0, 3))
        return cell

    def _entry(self, parent, var):
        entry = ttk.Entry(parent, textvariable=var)
        entry.pack(fill="x")
        entry.bind("<Return>", lambda e: self.submit())
        entry.bind("<Escape>", lambda e: self.clear())
        return entry

    def _row_entry(self, parent, r, label, var):
        cell = self._cell(parent, r, 0, label, span=2)
        return self._entry(cell, var)

    # ---------- 模板专属字段 ----------
    def _current_type(self):
        return self._type_label.get(self.var_type.get(), "general")

    def _render_extra(self, ftype):
        for w in self.extra_box.winfo_children():
            w.destroy()
        self.extra_vars = {}
        tpl = self.repo.form_template(ftype)
        for i, f in enumerate(tpl["fields"]):
            key, label, kind = f["key"], f["label"], f["type"]
            req = " *" if f.get("required") else ""
            cell = tk.Frame(self.extra_box, bg=C["card"])
            cell.grid(row=i, column=0, sticky="ew", pady=(0, 10))
            tk.Label(cell, text=label + req, bg=C["card"], fg=C["sub"],
                     font=(FONT, 9), anchor="w").pack(fill="x", pady=(0, 4))
            if kind == "textarea":
                w = tk.Text(cell, height=3, font=(FONT, 10), relief="flat", bd=0,
                            bg=C["surface_alt"], fg=C["text"],
                            insertbackground=C["text"], highlightthickness=1,
                            highlightbackground=C["line"],
                            highlightcolor=C["primary"], padx=8, pady=6)
                w.pack(fill="x")
                self.extra_vars[key] = {"kind": "textarea", "widget": w}
            elif kind == "select":
                var = tk.StringVar(value=(f["options"][0] if f.get("options") else ""))
                cb = ttk.Combobox(cell, textvariable=var,
                                  values=f.get("options", []), state="readonly")
                cb.pack(fill="x")
                self.extra_vars[key] = {"kind": "select", "var": var}
            else:
                var = tk.StringVar()
                entry = ttk.Entry(cell, textvariable=var)
                entry.pack(fill="x")
                self.extra_vars[key] = {"kind": "entry", "var": var}

    def _extra_value(self, key):
        v = self.extra_vars.get(key)
        if not v:
            return ""
        if v["kind"] == "textarea":
            return v["widget"].get("1.0", "end").strip()
        return v["var"].get().strip()

    def _collect_extra(self):
        return {key: self._extra_value(key) for key in self.extra_vars}

    def _on_type(self):
        self._render_extra(self._current_type())
        self._suggest_code()

    # ---------- 编号建议 ----------
    def _suggest_code(self, *_):
        cat = self.var_cat.get()
        if not cat:
            return
        suggest = self.repo.next_code(cat, self._current_type())
        cur = self.var_code.get().strip()
        if not cur or cur == self._last_suggest:
            self.var_code.set(suggest)
            self._last_suggest = suggest

    # ---------- 附件 ----------
    def _refresh_att_list(self):
        self.att_list.delete(0, "end")
        for a in self.attachments:
            self.att_list.insert("end", a["name"])

    def pick_files(self):
        paths = filedialog.askopenfilenames(title="选择附件")
        for p in paths:
            self.attachments.append({"name": os.path.basename(p), "path": p, "kind": ""})
        self._refresh_att_list()

    def remove_selected(self):
        sel = list(self.att_list.curselection())
        for idx in reversed(sel):
            del self.attachments[idx]
        self._refresh_att_list()

    def clear_files(self):
        self.attachments = []
        self._refresh_att_list()

    # ---------- 校验 ----------
    def _validate(self):
        ftype = self._current_type()
        title = self.var_title.get().strip()
        name = self.var_name.get().strip()
        sid = self.var_sid.get().strip()
        cat = self.var_cat.get()
        errors = []
        if not title:
            errors.append("材料名称")
        if not cat:
            errors.append("材料类别")
        if ftype == "general":
            if not name:
                errors.append("提交人")
            if not sid:
                errors.append("学号")
            elif not sid.isdigit():
                errors.append("学号需为纯数字")
            elif not (4 <= len(sid) <= 12):
                errors.append("学号长度应为 4-12 位")
        elif sid and (not sid.isdigit() or not (4 <= len(sid) <= 12)):
            errors.append("学号格式不正确")
        for f in self.repo.form_template(ftype)["fields"]:
            if f.get("required") and not self._extra_value(f["key"]):
                errors.append(f["label"])
        return title, name, sid, cat, errors

    def clear(self):
        filled = any((self.var_title.get(), self.var_name.get(), self.var_sid.get(),
                      self.var_cat.get(), self.var_note.get("1.0", "end").strip(),
                      self.attachments))
        if filled and not self.window.confirm("清空确认", "当前已填写的内容将被清空，确定继续吗？"):
            return
        self.var_type.set(self.TYPE_OPTIONS[0][1])
        self.var_title.set("")
        self.var_name.set("")
        self.var_sid.set("")
        self.var_cat.set("")
        self.var_code.set("")
        self._last_suggest = ""
        self.var_note.delete("1.0", "end")
        self.clear_files()
        self._render_extra("general")
        self.err_label.config(text="")

    def submit(self):
        if self._submitting:
            return
        title, name, sid, cat, errors = self._validate()
        if errors:
            self.err_label.config(text="请检查：" + "、".join(errors))
            return
        note = self.var_note.get("1.0", "end").strip()
        ftype = self._current_type()
        extra = self._collect_extra()

        dup = [d for d in self.repo.list_docs()
               if d.get("sid") == sid and d.get("name") == title and d.get("cat") == cat]
        if dup and not self.window.confirm(
                "重复提交确认",
                "学号 %s 已提交过「%s」，是否仍要再次提交？" % (sid, title)):
            return

        first = self.attachments[0] if self.attachments else {}
        self._submitting = True
        self.btn_submit.config(state="disabled")
        try:
            self.repo.add_doc({
                "name": title, "cat": cat, "who": name, "sid": sid,
                "note": note, "file": first.get("name", ""), "path": first.get("path", ""),
                "code": self.var_code.get().strip(), "scope": "全员",
                "form_type": ftype, "extra": extra, "attachments": self.attachments,
            })
            # 提交只登记，不提前复制；文件统一由「归档」落盘，
            # 避免待审/驳回材料进入归档目录，也避免同一份材料被复制两次。
        except Exception as e:
            self._submitting = False
            self.btn_submit.config(state="normal")
            self.err_label.config(text="提交失败：%s" % e)
            return
        try:
            self.repo.add_log("提交", title, self.window.operator_name,
                              self.window.role_label())
        except Exception:
            pass
        self._submitting = False
        self.btn_submit.config(state="normal")

        self.var_type.set(self.TYPE_OPTIONS[0][1])
        self.var_title.set("")
        self.var_name.set("")
        self.var_sid.set("")
        self.var_cat.set("")
        self.var_code.set("")
        self._last_suggest = ""
        self.var_note.delete("1.0", "end")
        self.clear_files()
        self._render_extra("general")
        self.err_label.config(text="")

        self.window.refresh_all()
        self.window.toast("材料已提交，进入待审核列表")
        self.window.switch("docs")

    def refresh(self):
        self.err_label.config(text="")

    def reload_template(self):
        """模板字段在设置里改动后，重建当前类型的附加字段。"""
        self._render_extra(self._current_type())

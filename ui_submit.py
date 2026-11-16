# -*- coding: utf-8 -*-
"""提交材料视图：模板表单录入、内联校验、多附件登记。"""

import os
import tkinter as tk
from tkinter import ttk, filedialog

from theme import FONT, C
from database import form_template


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
        card = tk.Frame(self, bg=C["card"])
        card.pack(padx=32, pady=24, fill="both", expand=True)
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="带 * 为必填项，提交后进入待审核列表并生成操作记录",
                  style="Sub.TLabel").grid(row=0, column=0, columnspan=2, sticky="w",
                                           padx=24, pady=(12, 16))

        self.var_type = tk.StringVar(value="general")
        self.var_title = tk.StringVar()
        self.var_name = tk.StringVar()
        self.var_sid = tk.StringVar()
        self.var_cat = tk.StringVar()
        self.var_code = tk.StringVar()
        self.var_note = tk.Text(card, height=4, font=(FONT, 11))

        ttk.Label(card, text="材料类型").grid(row=1, column=0, sticky="w",
                                              padx=(24, 12), pady=10)
        type_cb = ttk.Combobox(card, textvariable=self.var_type,
                               values=[label for _, label in self.TYPE_OPTIONS],
                               state="readonly")
        type_cb.grid(row=1, column=1, sticky="ew", pady=10)
        type_cb.bind("<<ComboboxSelected>>", lambda e: self._on_type())
        self._type_label = {label: key for key, label in self.TYPE_OPTIONS}

        self._row_entry(card, 2, "材料名称 *", self.var_title)
        self._row_entry(card, 3, "提交人 / 记录人", self.var_name)
        self._row_entry(card, 4, "学号", self.var_sid)

        ttk.Label(card, text="材料类别 *").grid(row=5, column=0, sticky="w",
                                                padx=(24, 12), pady=10)
        cat_cb = ttk.Combobox(card, textvariable=self.var_cat, values=self.CATS,
                              state="readonly")
        cat_cb.grid(row=5, column=1, sticky="ew", pady=10)
        cat_cb.bind("<<ComboboxSelected>>", lambda e: self._suggest_code())
        cat_cb.bind("<Return>", lambda e: self.submit())
        cat_cb.bind("<Escape>", lambda e: self.clear())

        self._row_entry(card, 6, "材料编号（留空自动）", self.var_code)

        # 模板专属字段（随类型重建）
        self.extra_box = ttk.Frame(card)
        self.extra_box.grid(row=7, column=0, columnspan=2, sticky="ew")
        self.extra_box.columnconfigure(1, weight=1)

        ttk.Label(card, text="材料说明").grid(row=8, column=0, sticky="nw",
                                              padx=(24, 12), pady=10)
        self.var_note.grid(row=8, column=1, sticky="ew", pady=10)

        ttk.Label(card, text="附件").grid(row=9, column=0, sticky="nw",
                                          padx=(24, 12), pady=10)
        att = ttk.Frame(card)
        att.grid(row=9, column=1, sticky="ew", pady=10)
        self.att_list = tk.Listbox(att, height=3, font=(FONT, 10),
                                   selectmode="extended")
        self.att_list.pack(side="left", fill="both", expand=True)
        att_btns = ttk.Frame(att)
        att_btns.pack(side="left", padx=(8, 0))
        ttk.Button(att_btns, text="添加附件", command=self.pick_files).pack(anchor="w")
        ttk.Button(att_btns, text="移除所选", command=self.remove_selected).pack(anchor="w", pady=6)
        ttk.Button(att_btns, text="清空", command=self.clear_files).pack(anchor="w")

        self.err_label = ttk.Label(card, text="", foreground=C["red"], font=(FONT, 10))
        self.err_label.grid(row=10, column=0, columnspan=2, sticky="w", padx=24, pady=(6, 0))

        actions = ttk.Frame(card)
        actions.grid(row=11, column=0, columnspan=2, sticky="e", padx=24, pady=(18, 22))
        ttk.Button(actions, text="清空", command=self.clear).pack(side="right", padx=8)
        self.btn_submit = ttk.Button(actions, text="提交材料", style="Accent.TButton",
                                     command=self.submit)
        self.btn_submit.pack(side="right")

        self._render_extra("general")

    def _row_entry(self, parent, r, label, var):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w",
                                           padx=(24, 12), pady=10)
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=r, column=1, sticky="ew", pady=10)
        entry.bind("<Return>", lambda e: self.submit())
        entry.bind("<Escape>", lambda e: self.clear())

    # ---------- 模板专属字段 ----------
    def _current_type(self):
        return self._type_label.get(self.var_type.get(), "general")

    def _render_extra(self, ftype):
        for w in self.extra_box.winfo_children():
            w.destroy()
        self.extra_vars = {}
        tpl = form_template(ftype)
        for i, f in enumerate(tpl["fields"]):
            key, label, kind = f["key"], f["label"], f["type"]
            req = " *" if f.get("required") else ""
            ttk.Label(self.extra_box, text=label + req).grid(
                row=i, column=0, sticky="w", padx=(24, 12), pady=8)
            if kind == "textarea":
                w = tk.Text(self.extra_box, height=3, font=(FONT, 11))
                w.grid(row=i, column=1, sticky="ew", pady=8)
                self.extra_vars[key] = {"kind": "textarea", "widget": w}
            elif kind == "select":
                var = tk.StringVar(value=(f["options"][0] if f.get("options") else ""))
                cb = ttk.Combobox(self.extra_box, textvariable=var,
                                  values=f.get("options", []), state="readonly")
                cb.grid(row=i, column=1, sticky="ew", pady=8)
                self.extra_vars[key] = {"kind": "select", "var": var}
            else:
                var = tk.StringVar()
                entry = ttk.Entry(self.extra_box, textvariable=var)
                entry.grid(row=i, column=1, sticky="ew", pady=8)
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
        for f in form_template(ftype)["fields"]:
            if f.get("required") and not self._extra_value(f["key"]):
                errors.append(f["label"])
        return title, name, sid, cat, errors

    def clear(self):
        filled = any((self.var_title.get(), self.var_name.get(), self.var_sid.get(),
                      self.var_cat.get(), self.var_note.get("1.0", "end").strip(),
                      self.attachments))
        if filled and not self.window.confirm("清空确认", "当前已填写的内容将被清空，确定继续吗？"):
            return
        self.var_type.set("general")
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

        self.var_type.set("general")
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

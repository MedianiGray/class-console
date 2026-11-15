# -*- coding: utf-8 -*-
"""提交材料视图：表单录入、内联校验、附件文件名记录。"""

import os
import tkinter as tk
from tkinter import ttk, filedialog

from theme import FONT, C


class SubmitView(ttk.Frame):
    CATS = ["团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self.file_name = ""
        self._submitting = False
        self._build()

    def _build(self):
        card = tk.Frame(self, bg=C["card"])
        card.pack(padx=32, pady=24, fill="both", expand=True)
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="提交班级材料", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=24, pady=(22, 2))
        ttk.Label(card, text="带 * 为必填项，提交后进入待审核列表并生成操作记录",
                  style="Sub.TLabel").grid(row=1, column=0, columnspan=2, sticky="w",
                                           padx=24, pady=(0, 16))

        self.var_name = tk.StringVar()
        self.var_sid = tk.StringVar()
        self.var_cat = tk.StringVar()
        self.var_title = tk.StringVar()
        self.var_note = tk.Text(card, height=4, font=(FONT, 11))

        self._row_entry(card, 2, "材料名称 *", self.var_title)
        self._row_entry(card, 3, "姓名 *", self.var_name)
        self._row_entry(card, 4, "学号 *", self.var_sid)

        ttk.Label(card, text="材料类别 *").grid(row=5, column=0, sticky="w", padx=(24, 12), pady=10)
        cat_cb = ttk.Combobox(card, textvariable=self.var_cat, values=self.CATS,
                              state="readonly")
        cat_cb.grid(row=5, column=1, sticky="ew", pady=10)
        cat_cb.bind("<Return>", lambda e: self.submit())
        cat_cb.bind("<Escape>", lambda e: self.clear())

        ttk.Label(card, text="材料说明").grid(row=6, column=0, sticky="nw", padx=(24, 12), pady=10)
        self.var_note.grid(row=6, column=1, sticky="ew", pady=10)

        ttk.Label(card, text="附件").grid(row=7, column=0, sticky="nw", padx=(24, 12), pady=10)
        attach = ttk.Frame(card)
        attach.grid(row=7, column=1, sticky="w", pady=10)
        self.var_file = tk.StringVar(value="未选择文件")
        self.file_label = ttk.Label(attach, textvariable=self.var_file, style="Muted.TLabel")
        self.file_label.pack(side="left", padx=(0, 12))
        ttk.Button(attach, text="选择文件", command=self.pick_file).pack(side="left")
        self.btn_remove_file = ttk.Button(attach, text="移除", command=self.remove_file)
        self.btn_remove_file.pack(side="left", padx=8)

        # 内联错误提示
        self.err_label = ttk.Label(card, text="", foreground=C["red"], font=(FONT, 10))
        self.err_label.grid(row=8, column=0, columnspan=2, sticky="w", padx=24, pady=(6, 0))

        actions = ttk.Frame(card)
        actions.grid(row=9, column=0, columnspan=2, sticky="e", padx=24, pady=(18, 22))
        ttk.Button(actions, text="清空", command=self.clear).pack(side="right", padx=8)
        self.btn_submit = ttk.Button(actions, text="提交材料", style="Accent.TButton",
                                     command=self.submit)
        self.btn_submit.pack(side="right")



    def _row_entry(self, parent, r, label, var):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w",
                                           padx=(24, 12), pady=10)
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=r, column=1, sticky="ew", pady=10)
        entry.bind("<Return>", lambda e: self.submit())
        entry.bind("<Escape>", lambda e: self.clear())

    # ---------- 附件 ----------
    def pick_file(self):
        path = filedialog.askopenfilename(title="选择附件")
        if path:
            self.file_name = os.path.basename(path)
            self.var_file.set(self.file_name)

    def remove_file(self):
        self.file_name = ""
        self.var_file.set("未选择文件")

    # ---------- 校验 ----------
    def _validate(self):
        title = self.var_title.get().strip()
        name = self.var_name.get().strip()
        sid = self.var_sid.get().strip()
        cat = self.var_cat.get()
        errors = []
        if not title:
            errors.append("材料名称")
        if not name:
            errors.append("姓名")
        if not sid:
            errors.append("学号")
        elif not sid.isdigit():
            errors.append("学号需为纯数字")
        elif not (4 <= len(sid) <= 12):
            errors.append("学号长度应为 4-12 位")
        if not cat:
            errors.append("材料类别")
        return title, name, sid, cat, errors

    def clear(self):
        filled = any((self.var_title.get(), self.var_name.get(), self.var_sid.get(),
                      self.var_cat.get(), self.var_note.get("1.0", "end").strip(),
                      self.file_name))
        if filled and not self.window.confirm("清空确认", "当前已填写的内容将被清空，确定继续吗？"):
            return
        self.var_title.set("")
        self.var_name.set("")
        self.var_sid.set("")
        self.var_cat.set("")
        self.var_note.delete("1.0", "end")
        self.remove_file()
        self.err_label.config(text="")

    def submit(self):
        if self._submitting:
            return
        title, name, sid, cat, errors = self._validate()
        if errors:
            self.err_label.config(text="请检查：" + "、".join(errors))
            return
        note = self.var_note.get("1.0", "end").strip()

        dup = [d for d in self.repo.list_docs()
               if d.get("sid") == sid and d.get("name") == title and d.get("cat") == cat]
        if dup and not self.window.confirm(
                "重复提交确认",
                "学号 %s 已提交过「%s」，是否仍要再次提交？" % (sid, title)):
            return

        self._submitting = True
        self.btn_submit.config(state="disabled")
        try:
            self.repo.add_doc({
                "name": title, "cat": cat, "who": name, "sid": sid,
                "note": note, "file": self.file_name, "scope": "全员"
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

        self.var_title.set("")
        self.var_name.set("")
        self.var_sid.set("")
        self.var_cat.set("")
        self.var_note.delete("1.0", "end")
        self.remove_file()
        self.err_label.config(text="")

        self.window.refresh_all()
        self.window.toast("材料已提交，进入待审核列表")
        self.window.switch("docs")

    def refresh(self):
        self.err_label.config(text="")

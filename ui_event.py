# -*- coding: utf-8 -*-
"""v0.36 活动工作台：策划、名单签到、预算结算与结项包。

本版不接在线报名后端；名单来自本地录入或 CSV 导入，签到与结算都在本机
完成。界面只负责把一次活动对齐成可交付的结项材料。
"""

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import datalab as dl
import events as ev
from database import (EVENT_PLAN_SECTIONS, EVENT_ROLES, EVENT_STATUS,
                      EVENT_SUMMARY_SECTIONS)
from theme import C, FONT


class EventView(ttk.Frame):
    PERM = "event:run"
    PLAN_COLS = ("section", "content", "state")
    PLAN_HEADS = {"section": "策划小节", "content": "内容", "state": "状态"}
    PLAN_WIDTHS = {"section": 130, "content": 700, "state": 66}
    PERSON_COLS = ("name", "sid", "role", "status", "contact", "note")
    PERSON_HEADS = {"name": "姓名", "sid": "学号", "role": "角色",
                    "status": "状态", "contact": "联系方式", "note": "备注"}
    PERSON_WIDTHS = {"name": 120, "sid": 130, "role": 76, "status": 84,
                     "contact": 150, "note": 300}
    EXP_COLS = ("item", "budget", "actual", "diff", "note")
    EXP_HEADS = {"item": "项目", "budget": "预算", "actual": "实付",
                 "diff": "差额", "note": "说明"}
    EXP_WIDTHS = {"item": 220, "budget": 96, "actual": 96, "diff": 96, "note": 430}
    NOTE_COLS = ("section", "content", "state")
    NOTE_HEADS = {"section": "总结小节", "content": "内容", "state": "状态"}
    NOTE_WIDTHS = {"section": 130, "content": 620, "state": 66}
    CHK_COLS = ("name", "ok", "note")
    CHK_HEADS = {"name": "检查项", "ok": "结论", "note": "说明"}
    CHK_WIDTHS = {"name": 120, "ok": 60, "note": 360}

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self.current_pid = None
        self.project_map = {}
        self.plan = []
        self.people = []
        self.expenses = []
        self.notes = []
        self.last_package = None
        self.buttons = []
        self._loaded_pid = None
        self._build()

    def _build(self):
        style = ttk.Style(self)
        style.configure("Section.TLabel", font=(FONT, 10, "bold"),
                        background=C["bg"], foreground=C["text"])
        head = ttk.Frame(self)
        head.pack(fill="x", padx=18, pady=(4, 6))
        ttk.Label(head, text="活动工作台", style="H2.TLabel").pack(side="left")
        self.summary = ttk.Label(head, text="", style="Muted.TLabel")
        self.summary.pack(side="right")

        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(0, 8))
        ttk.Label(top, text="活动项目", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.project_var = tk.StringVar(value="")
        self.project_cb = ttk.Combobox(top, textvariable=self.project_var,
                                       state="readonly", width=44)
        self.project_cb.grid(row=0, column=1, sticky="w", padx=(8, 8))
        self.project_cb.bind("<<ComboboxSelected>>", lambda e: self._on_project())
        self.btn_new = ttk.Button(top, text="新建活动项目", style="Accent.TButton",
                                  command=lambda: self.project_dialog(None))
        self.btn_new.grid(row=0, column=2, padx=2)
        self.btn_edit = ttk.Button(top, text="编辑项目", style="Ghost.TButton",
                                   command=lambda: self.project_dialog("edit"))
        self.btn_edit.grid(row=0, column=3, padx=2)
        ttk.Button(top, text="刷新", style="Ghost.TButton",
                   command=self.refresh).grid(row=0, column=4, padx=(2, 12))
        self.project_hint = ttk.Label(top, text="", style="Muted.TLabel")
        self.project_hint.grid(row=1, column=1, columnspan=4, sticky="w",
                               padx=(8, 0), pady=(4, 0))
        top.columnconfigure(1, weight=1)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=18, pady=(0, 4))
        self.tab_plan = ttk.Frame(self.nb)
        self.tab_sign = ttk.Frame(self.nb)
        self.tab_money = ttk.Frame(self.nb)
        self.tab_wrap = ttk.Frame(self.nb)
        self.nb.add(self.tab_plan, text="策划 / 名单")
        self.nb.add(self.tab_sign, text="签到")
        self.nb.add(self.tab_money, text="预算 / 结算")
        self.nb.add(self.tab_wrap, text="总结 / 结项包")
        self._build_plan()
        self._build_sign()
        self._build_money()
        self._build_wrap()
        self.after(50, self.refresh)

    def _mk_tree(self, parent, cols, heads, widths, height=8, expand=True):
        wrap = ttk.Frame(parent)
        wrap.pack(fill="both" if expand else "x", expand=expand,
                  padx=14, pady=(6, 0))
        tree = ttk.Treeview(wrap, columns=cols, show="headings",
                            selectmode="browse", height=height)
        for c in cols:
            tree.heading(c, text=heads[c], anchor="w")
            tree.column(c, width=widths[c], anchor="w",
                        stretch=(c in ("content", "note") or c == cols[-1]))
        tree.tag_configure("zebra", background=C["zebra"])
        tree.tag_configure("green", foreground=C["green"])
        tree.tag_configure("orange", foreground=C["orange"])
        tree.tag_configure("red", foreground=C["red"])
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ysb.set)
        tree.pack(side="left", fill="both", expand=expand)
        ysb.pack(side="right", fill="y")
        return tree

    def _button(self, parent, text, cmd, style="Ghost.TButton", track=True):
        btn = ttk.Button(parent, text=text, style=style, command=cmd)
        btn.pack(side="left", padx=(0, 6))
        if track:
            self.buttons.append(btn)
        return btn

    # ---------- 策划 / 名单 ----------
    def _build_plan(self):
        head = ttk.Frame(self.tab_plan)
        head.pack(fill="x", padx=14, pady=(8, 0))
        ttk.Label(head, text="活动策划", style="Section.TLabel").pack(side="left")
        self.plan_summary = ttk.Label(head, text="", style="Muted.TLabel")
        self.plan_summary.pack(side="right")
        self.plan_tree = self._mk_tree(self.tab_plan, self.PLAN_COLS,
                                       self.PLAN_HEADS, self.PLAN_WIDTHS,
                                       height=6, expand=False)
        self.plan_tree.bind("<Double-1>", lambda e: self.plan_dialog())
        pbar = ttk.Frame(self.tab_plan)
        pbar.pack(fill="x", padx=14, pady=(4, 6))
        self._button(pbar, "写 / 改小节", self.plan_dialog, "Accent.TButton")

        head2 = ttk.Frame(self.tab_plan)
        head2.pack(fill="x", padx=14, pady=(0, 0))
        ttk.Label(head2, text="名单", style="Section.TLabel").pack(side="left")
        self.people_summary = ttk.Label(head2, text="", style="Muted.TLabel")
        self.people_summary.pack(side="right")
        self.people_tree = self._mk_tree(self.tab_plan, self.PERSON_COLS,
                                         self.PERSON_HEADS, self.PERSON_WIDTHS,
                                         height=6)
        self.people_tree.bind("<Double-1>", lambda e: self.person_dialog("edit"))
        bar = ttk.Frame(self.tab_plan)
        bar.pack(side="bottom", fill="x", padx=14, pady=(4, 10),
                 before=self.people_tree.master)
        self._button(bar, "添加人员", lambda: self.person_dialog(None), "Accent.TButton")
        self._button(bar, "编辑人员", lambda: self.person_dialog("edit"))
        self._button(bar, "导入名单 CSV…", self.import_people)
        self._button(bar, "删除人员", self.remove_person, "Danger.TButton")

    # ---------- 签到 ----------
    def _build_sign(self):
        head = ttk.Frame(self.tab_sign)
        head.pack(fill="x", padx=14, pady=(8, 0))
        ttk.Label(head, text="签到核对", style="Section.TLabel").pack(side="left")
        self.sign_summary = ttk.Label(head, text="", style="Muted.TLabel")
        self.sign_summary.pack(side="right")
        self.status_line = ttk.Label(self.tab_sign, text="", style="Muted.TLabel")
        self.status_line.pack(anchor="w", padx=14, pady=(4, 0))
        self.sign_tree = self._mk_tree(self.tab_sign, ("name", "sid", "role", "status", "note"),
                                       {"name": "姓名", "sid": "学号", "role": "角色",
                                        "status": "状态", "note": "备注"},
                                       {"name": 140, "sid": 150, "role": 90,
                                        "status": 100, "note": 620})
        self.sign_tree.bind("<Double-1>", lambda e: self.person_dialog("edit"))
        bar = ttk.Frame(self.tab_sign)
        bar.pack(side="bottom", fill="x", padx=14, pady=(6, 10))
        self._button(bar, "标为已签到", lambda: self.set_status("已签到"), "Accent.TButton")
        self._button(bar, "标为临时到场", lambda: self.set_status("临时到场"))
        self._button(bar, "标为缺席", lambda: self.set_status("缺席"))
        self._button(bar, "退回已报名", lambda: self.set_status("已报名"))

    # ---------- 结算 ----------
    def _build_money(self):
        head = ttk.Frame(self.tab_money)
        head.pack(fill="x", padx=14, pady=(8, 0))
        ttk.Label(head, text="预算与实付", style="Section.TLabel").pack(side="left")
        self.money_summary = ttk.Label(head, text="", style="Muted.TLabel")
        self.money_summary.pack(side="right")
        self.money_line = ttk.Label(self.tab_money, text="", style="Muted.TLabel")
        self.money_line.pack(anchor="w", padx=14, pady=(4, 0))
        self.exp_tree = self._mk_tree(self.tab_money, self.EXP_COLS,
                                      self.EXP_HEADS, self.EXP_WIDTHS)
        self.exp_tree.bind("<Double-1>", lambda e: self.expense_dialog("edit"))
        bar = ttk.Frame(self.tab_money)
        bar.pack(side="bottom", fill="x", padx=14, pady=(6, 10),
                 before=self.exp_tree.master)
        self._button(bar, "添加明细", lambda: self.expense_dialog(None), "Accent.TButton")
        self._button(bar, "编辑明细", lambda: self.expense_dialog("edit"))
        self._button(bar, "删除明细", self.remove_expense, "Danger.TButton")

    # ---------- 总结 / 结项包 ----------
    def _build_wrap(self):
        head = ttk.Frame(self.tab_wrap)
        head.pack(fill="x", padx=14, pady=(8, 0))
        ttk.Label(head, text="总结", style="Section.TLabel").pack(side="left")
        self.note_summary = ttk.Label(head, text="", style="Muted.TLabel")
        self.note_summary.pack(side="right")
        self.note_tree = self._mk_tree(self.tab_wrap, self.NOTE_COLS,
                                       self.NOTE_HEADS, self.NOTE_WIDTHS,
                                       height=3, expand=False)
        self.note_tree.bind("<Double-1>", lambda e: self.note_dialog())
        nbar = ttk.Frame(self.tab_wrap)
        nbar.pack(fill="x", padx=14, pady=(4, 6))
        self._button(nbar, "写 / 改总结", self.note_dialog, "Accent.TButton")

        head2 = ttk.Frame(self.tab_wrap)
        head2.pack(fill="x", padx=14, pady=(0, 0))
        ttk.Label(head2, text="结项检查", style="Section.TLabel").pack(side="left")
        self.chk_summary = ttk.Label(head2, text="", style="Muted.TLabel")
        self.chk_summary.pack(side="right")
        self.chk_tree = self._mk_tree(self.tab_wrap, self.CHK_COLS,
                                      self.CHK_HEADS, self.CHK_WIDTHS,
                                      height=6, expand=False)
        bottom = ttk.Frame(self.tab_wrap)
        bottom.pack(side="bottom", fill="x", padx=14, pady=(6, 10),
                    before=self.note_tree.master)
        ttk.Label(bottom, text="输出目录", style="Muted.TLabel").pack(side="left")
        self.out_var = tk.StringVar(value=str(Path.home() / "Documents" / "班级操作台交付"))
        ttk.Entry(bottom, textvariable=self.out_var, width=34).pack(side="left", padx=(6, 6))
        ttk.Button(bottom, text="选…", style="Ghost.TButton",
                   command=self.pick_out).pack(side="left", padx=(0, 8))
        self.btn_make = ttk.Button(bottom, text="生成活动结项包", style="Accent.TButton",
                                   command=self.make_package)
        self.btn_make.pack(side="left", padx=(0, 6))
        self.btn_open = ttk.Button(bottom, text="打开总结", style="Ghost.TButton",
                                   command=self.open_report, state="disabled")
        self.btn_open.pack(side="left", padx=(0, 6))
        ttk.Button(bottom, text="打开目录", style="Ghost.TButton",
                   command=self.open_folder).pack(side="left")

    # ---------- 项目 ----------
    def refresh(self, select_pid=None):
        try:
            projects = self.repo.list_projects("event")
        except Exception:
            projects = []
        self.project_map = {}
        labels = []
        for p in projects:
            base = "%s（%s）" % (p.get("name") or "未命名", p.get("status") or "")
            label = base
            if label in self.project_map:
                label = "%s #%d" % (base, p["id"])
            self.project_map[label] = p["id"]
            labels.append(label)
        self.project_cb["values"] = labels
        ids = [p["id"] for p in projects]
        wanted = select_pid if select_pid in ids else self.current_pid
        if wanted not in ids:
            wanted = ids[0] if ids else None
        if wanted is None:
            self.project_var.set("")
            self.current_pid = None
            self._load_project(None)
            self.summary.configure(text="还没有活动项目")
            self.project_hint.configure(text="先建活动项目，再写策划、录名单、核对签到与结算。")
            return
        label = [k for k, v in self.project_map.items() if v == wanted][0]
        self.project_var.set(label)
        self.current_pid = wanted
        self._load_project(wanted)

    def _on_project(self):
        self.current_pid = self.project_map.get(self.project_var.get())
        self._load_project(self.current_pid)

    def _load_project(self, pid):
        if pid != self._loaded_pid:
            self.last_package = None
            self.btn_open.configure(state="disabled")
        self._loaded_pid = pid
        state = "normal" if pid else "disabled"
        for btn in self.buttons + [self.btn_make]:
            try:
                btn.configure(state=state)
            except tk.TclError:
                pass
        for tree in (self.plan_tree, self.people_tree, self.sign_tree,
                     self.exp_tree, self.note_tree, self.chk_tree):
            tree.delete(*tree.get_children())
        if pid is None:
            self.plan, self.people, self.expenses, self.notes = [], [], [], []
            for label in (self.plan_summary, self.people_summary, self.sign_summary,
                          self.status_line, self.money_summary, self.money_line,
                          self.note_summary, self.chk_summary):
                label.configure(text="")
            return
        project = self.repo.find_project(pid)
        if project is None:
            return
        self.plan = self.repo.list_event_plan(pid)
        self.people = self.repo.list_event_people(pid)
        self.expenses = self.repo.list_event_expenses(pid)
        self.notes = self.repo.list_event_notes(pid)
        self._fill_plan()
        self._fill_people()
        self._fill_expenses()
        self._fill_notes()
        self._refresh_readiness()
        self.summary.configure(text="%d 人 · 到场 %.1f%% · 预算 %s / 实付 %s" % (
            len(self.people), ev.people_stats(self.repo, pid)["rate"],
            ev._fmt_money(sum(float(e.get("budget") or 0) for e in self.expenses)),
            ev._fmt_money(sum(float(e.get("actual") or 0) for e in self.expenses)))
            if self.people or self.expenses else "策划与名单待填")
        self.project_hint.configure(
            text="%s · %s · 活动日期 %s" % (
                project.get("stage"), project.get("status"),
                project.get("start_date") or "未填"))

    def _fill_plan(self):
        self.plan_tree.delete(*self.plan_tree.get_children())
        by_section = {r.get("section"): r for r in self.plan}
        filled = 0
        for i, section in enumerate(EVENT_PLAN_SECTIONS):
            row = by_section.get(section) or {}
            content = (row.get("content") or "").replace("\n", " ")
            preview = content[:90] + ("…" if len(content) > 90 else "")
            state = "已填" if content.strip() else "待补"
            filled += 1 if content.strip() else 0
            self.plan_tree.insert("", "end",
                                  tags=(str(row.get("id") or 0), "zebra" if i % 2 else "",
                                        "green" if content.strip() else "orange"),
                                  values=(section, preview or "（空，双击填写）", state))
        self.plan_summary.configure(text="%d / 8 小节 · %d%%" % (
            filled, int(filled / 8 * 100)))

    def _fill_people(self):
        self.people_tree.delete(*self.people_tree.get_children())
        self.sign_tree.delete(*self.sign_tree.get_children())
        for i, r in enumerate(self.people):
            status = r.get("status") or "已报名"
            tag = "green" if status in ("已签到", "临时到场") else (
                "red" if status == "缺席" else "")
            self.people_tree.insert("", "end",
                                    tags=(str(r["id"]), "zebra" if i % 2 else "", tag),
                                    values=(r.get("name"), r.get("sid"), r.get("role"),
                                            status, r.get("contact"), r.get("note")))
            self.sign_tree.insert("", "end",
                                  tags=(str(r["id"]), "zebra" if i % 2 else "", tag),
                                  values=(r.get("name"), r.get("sid"), r.get("role"),
                                          status, r.get("note")))
        st = ev.people_stats(self.repo, self.current_pid)
        self.people_summary.configure(text="%d 人 · 已到 %d · 缺席 %d" % (
            st["total"], st["attended"], st["absent"]))
        self.sign_summary.configure(text="到场率 %.1f%%" % st["rate"])
        self.status_line.configure(
            text="已签到 %d ｜ 临时到场 %d ｜ 缺席 %d ｜ 已报名 %d ｜ 合计 %d（到场率 =（已签到 + 临时到场）/ 总名单）" % (
                st["counts"]["已签到"], st["walkin"], st["absent"],
                st["registered"], st["total"]))

    def _fill_expenses(self):
        self.exp_tree.delete(*self.exp_tree.get_children())
        for i, r in enumerate(self.expenses):
            diff = float(r.get("budget") or 0) - float(r.get("actual") or 0)
            tag = "red" if diff < 0 else ""
            self.exp_tree.insert("", "end",
                                 tags=(str(r["id"]), "zebra" if i % 2 else "", tag),
                                 values=(r.get("item"), ev._fmt_money(r.get("budget")),
                                         ev._fmt_money(r.get("actual")),
                                         ev._fmt_money(diff), r.get("note")))
        st = ev.expense_stats(self.repo, self.current_pid)
        self.money_summary.configure(text="预算 %s · 实付 %s · 差额 %s" % (
            ev._fmt_money(st["budget"]), ev._fmt_money(st["actual"]),
            ev._fmt_money(st["diff"])))
        self.money_line.configure(
            text="差额 = 预算 - 实付；负数表示超支。金额按登记值原样入包，不改账。" if self.expenses
            else "还没有结算明细。")

    def _fill_notes(self):
        self.note_tree.delete(*self.note_tree.get_children())
        by_section = {n.get("section"): n for n in self.notes}
        filled = 0
        for i, section in enumerate(EVENT_SUMMARY_SECTIONS):
            row = by_section.get(section) or {}
            content = (row.get("content") or "").replace("\n", " ")
            preview = content[:90] + ("…" if len(content) > 90 else "")
            state = "已填" if content.strip() else "待补"
            filled += 1 if content.strip() else 0
            self.note_tree.insert("", "end",
                                  tags=(str(row.get("id") or 0), "zebra" if i % 2 else "",
                                        "green" if content.strip() else "orange"),
                                  values=(section, preview or "（空，双击填写）", state))
        self.note_summary.configure(text="%d / 4 小节" % filled)

    def _refresh_readiness(self):
        self.chk_tree.delete(*self.chk_tree.get_children())
        if not self.current_pid:
            self.chk_summary.configure(text="")
            return
        ready = ev.readiness(self.repo, self.current_pid)
        for i, (name, ok, note) in enumerate(ready["checks"]):
            self.chk_tree.insert("", "end",
                                 tags=(str(i), "zebra" if i % 2 else "",
                                       "green" if ok else "orange"),
                                 values=(name, "通过" if ok else "待补", note))
        self.chk_summary.configure(
            text="可以生成结项包。" if ready["ok"] else
            "还有 %d 项待补：%s" % (len(ready["failed"]), "；".join(ready["failed"])))

    # ---------- 通用 ----------
    def _selected_id(self, tree):
        sel = tree.selection()
        if not sel:
            return None
        try:
            return int(tree.item(sel[0])["tags"][0])
        except (ValueError, IndexError, KeyError):
            return None

    def _log(self, act, obj):
        try:
            self.repo.add_log(act, obj, getattr(self.window, "operator_name", "系统"),
                              self.window.role_label())
        except Exception:
            pass

    # ---------- 策划 ----------
    def plan_dialog(self):
        if not self.current_pid:
            return
        rid = self._selected_id(self.plan_tree)
        row = next((r for r in self.plan if r["id"] == rid), None) if rid else None
        if row is None and self.plan:
            unfilled = [r for r in self.plan if not (r.get("content") or "").strip()]
            row = unfilled[0] if unfilled else self.plan[0]
        top = tk.Toplevel(self)
        top.title("编辑策划小节")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="小节", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        section_var = tk.StringVar(value=(row or {}).get("section", EVENT_PLAN_SECTIONS[0]))
        cb = ttk.Combobox(body, textvariable=section_var, values=list(EVENT_PLAN_SECTIONS),
                          state="readonly", width=28)
        cb.grid(row=0, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="内容", style="Muted.TLabel").grid(row=1, column=0, sticky="nw", pady=4)
        content = tk.Text(body, width=56, height=12, wrap="word")
        content.insert("1.0", (row or {}).get("content", ""))
        content.grid(row=1, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="写实际安排与取舍；界面不替你编活动方案。",
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=2,
                                             sticky="w", pady=(4, 0))

        def save():
            try:
                if row is not None:
                    if section_var.get() != row.get("section"):
                        messagebox.showwarning(
                            "策划", "已存在的小节不能改名，请另选一行或新建项目。", parent=top)
                        return
                    self.repo.update_event_plan(row["id"], {
                        "content": content.get("1.0", "end").strip()})
                else:
                    self.repo.add_event_plan(self.current_pid, {
                        "section": section_var.get(),
                        "content": content.get("1.0", "end").strip()})
            except Exception as e:
                messagebox.showerror("策划", str(e), parent=top)
                return
            self._log("更新活动策划", section_var.get())
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    # ---------- 名单 ----------
    def person_dialog(self, mode=None):
        if not self.current_pid:
            return
        editing = mode == "edit"
        row = None
        if editing:
            rid = self._selected_id(self.people_tree)
            if rid is None:
                messagebox.showinfo("名单", "先在表里选一个人。", parent=self)
                return
            row = next((r for r in self.people if r["id"] == rid), None)
            if row is None:
                return
        top = tk.Toplevel(self)
        top.title("编辑人员" if editing else "添加人员")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        vars_ = {
            "name": tk.StringVar(value=(row or {}).get("name", "")),
            "sid": tk.StringVar(value=(row or {}).get("sid", "")),
            "contact": tk.StringVar(value=(row or {}).get("contact", "")),
            "role": tk.StringVar(value=(row or {}).get("role", "参与者")),
            "status": tk.StringVar(value=(row or {}).get("status", "已报名")),
        }
        for i, (label, key, width) in enumerate((
                ("姓名", "name", 26), ("学号", "sid", 26), ("联系方式", "contact", 26))):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(
                row=i, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=vars_[key], width=width).grid(
                row=i, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="角色", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(body, textvariable=vars_["role"], values=list(EVENT_ROLES),
                     state="readonly", width=12).grid(row=3, column=1, sticky="w",
                                                      padx=(8, 0), pady=4)
        ttk.Label(body, text="状态", style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Combobox(body, textvariable=vars_["status"], values=list(EVENT_STATUS),
                     state="readonly", width=12).grid(row=4, column=1, sticky="w",
                                                      padx=(8, 0), pady=4)
        ttk.Label(body, text="备注", style="Muted.TLabel").grid(row=5, column=0, sticky="nw", pady=4)
        note = tk.Text(body, width=32, height=3, wrap="word")
        note.insert("1.0", (row or {}).get("note", ""))
        note.grid(row=5, column=1, sticky="we", padx=(8, 0), pady=4)

        def save():
            data = {k: v.get().strip() for k, v in vars_.items()}
            data["note"] = note.get("1.0", "end").strip()
            if not data["name"]:
                messagebox.showwarning("名单", "姓名不能为空。", parent=top)
                return
            try:
                if editing:
                    self.repo.update_event_person(row["id"], data)
                else:
                    self.repo.add_event_person(self.current_pid, data)
            except Exception as e:
                messagebox.showerror("名单", str(e), parent=top)
                return
            self._log("更新活动名单" if editing else "添加活动人员", data["name"])
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    def set_status(self, status):
        rid = self._selected_id(self.sign_tree)
        if rid is None:
            messagebox.showinfo("签到", "先在表里选一个人。", parent=self)
            return
        try:
            self.repo.update_event_person(rid, {"status": status})
        except Exception as e:
            messagebox.showerror("签到", str(e), parent=self)
            return
        self._load_project(self.current_pid)

    def remove_person(self):
        rid = self._selected_id(self.people_tree)
        if rid is None:
            return
        row = next((r for r in self.people if r["id"] == rid), None)
        if row is None or not messagebox.askyesno("名单", "删除「%s」？" % row.get("name"),
                                                   parent=self):
            return
        try:
            self.repo.remove_event_person(rid)
        except Exception as e:
            messagebox.showerror("名单", str(e), parent=self)
            return
        self._load_project(self.current_pid)

    def import_people(self):
        if not self.current_pid:
            return
        path = filedialog.askopenfilename(
            title="导入名单 CSV",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")], parent=self)
        if not path:
            return
        aliases = {
            "name": ("姓名", "名字", "人员", "name"),
            "sid": ("学号", "编号", "sid"),
            "role": ("角色", "身份", "role"),
            "status": ("状态", "签到", "status"),
            "contact": ("联系方式", "电话", "手机", "contact"),
            "note": ("备注", "说明", "note"),
        }
        try:
            loaded = dl.read_table(path)
        except Exception as e:
            messagebox.showerror("导入名单", str(e), parent=self)
            return
        idx = {}
        for key, names in aliases.items():
            for i, head in enumerate(loaded["headers"]):
                if head.strip().lower() in [n.lower() for n in names]:
                    idx[key] = i
                    break
        if "name" not in idx:
            messagebox.showwarning("导入名单", "CSV 里找不到「姓名」列。", parent=self)
            return
        added, skipped = 0, 0
        for row in loaded["rows"]:
            name = row[idx["name"]].strip()
            if not name:
                skipped += 1
                continue
            data = {"name": name,
                    "sid": row[idx["sid"]].strip() if "sid" in idx else "",
                    "role": row[idx["role"]].strip() if "role" in idx else "参与者",
                    "status": row[idx["status"]].strip() if "status" in idx else "已报名",
                    "contact": row[idx["contact"]].strip() if "contact" in idx else "",
                    "note": row[idx["note"]].strip() if "note" in idx else ""}
            if data["role"] not in EVENT_ROLES:
                data["role"] = "参与者"
            if data["status"] not in EVENT_STATUS:
                data["status"] = "已报名"
            try:
                self.repo.add_event_person(self.current_pid, data)
                added += 1
            except Exception:
                skipped += 1
        self._log("导入活动名单", "%s · %d 人" % (os.path.basename(path), added))
        self._load_project(self.current_pid)
        messagebox.showinfo("导入名单", "导入 %d 人，跳过 %d 行。" % (added, skipped),
                            parent=self)

    # ---------- 结算 ----------
    def expense_dialog(self, mode=None):
        if not self.current_pid:
            return
        editing = mode == "edit"
        row = None
        if editing:
            rid = self._selected_id(self.exp_tree)
            if rid is None:
                messagebox.showinfo("结算", "先在表里选一项。", parent=self)
                return
            row = next((r for r in self.expenses if r["id"] == rid), None)
            if row is None:
                return
        top = tk.Toplevel(self)
        top.title("编辑结算明细" if editing else "添加结算明细")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        item_var = tk.StringVar(value=(row or {}).get("item", ""))
        budget_var = tk.StringVar(value=str((row or {}).get("budget", "") or ""))
        actual_var = tk.StringVar(value=str((row or {}).get("actual", "") or ""))
        for i, (label, var) in enumerate((("项目", item_var), ("预算", budget_var),
                                          ("实付", actual_var))):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(
                row=i, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=var, width=32).grid(
                row=i, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="说明", style="Muted.TLabel").grid(row=3, column=0, sticky="nw", pady=4)
        note = tk.Text(body, width=34, height=3, wrap="word")
        note.insert("1.0", (row or {}).get("note", ""))
        note.grid(row=3, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="预算与实付都填数字，可留 0；差额自动算，不改银行卡或账目。",
                  style="Muted.TLabel", wraplength=360).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        def save():
            if not item_var.get().strip():
                messagebox.showwarning("结算", "项目不能为空。", parent=top)
                return
            data = {"item": item_var.get().strip(), "budget": budget_var.get().strip(),
                    "actual": actual_var.get().strip(),
                    "note": note.get("1.0", "end").strip()}
            try:
                if editing:
                    self.repo.update_event_expense(row["id"], data)
                else:
                    self.repo.add_event_expense(self.current_pid, data)
            except Exception as e:
                messagebox.showerror("结算", str(e), parent=top)
                return
            self._log("更新活动结算" if editing else "添加活动结算", data["item"])
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    def remove_expense(self):
        rid = self._selected_id(self.exp_tree)
        if rid is None:
            return
        row = next((r for r in self.expenses if r["id"] == rid), None)
        if row is None or not messagebox.askyesno("结算", "删除「%s」？" % row.get("item"),
                                                   parent=self):
            return
        try:
            self.repo.remove_event_expense(rid)
        except Exception as e:
            messagebox.showerror("结算", str(e), parent=self)
            return
        self._load_project(self.current_pid)

    # ---------- 总结 ----------
    def note_dialog(self):
        if not self.current_pid:
            return
        rid = self._selected_id(self.note_tree)
        row = next((r for r in self.notes if r["id"] == rid), None) if rid else None
        if row is None and self.notes:
            unfilled = [r for r in self.notes if not (r.get("content") or "").strip()]
            row = unfilled[0] if unfilled else self.notes[0]
        top = tk.Toplevel(self)
        top.title("编辑活动总结")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="小节", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        section_var = tk.StringVar(value=(row or {}).get("section", EVENT_SUMMARY_SECTIONS[0]))
        ttk.Combobox(body, textvariable=section_var, values=list(EVENT_SUMMARY_SECTIONS),
                     state="readonly", width=26).grid(row=0, column=1, sticky="we",
                                                      padx=(8, 0), pady=4)
        ttk.Label(body, text="内容", style="Muted.TLabel").grid(row=1, column=0, sticky="nw", pady=4)
        content = tk.Text(body, width=54, height=10, wrap="word")
        content.insert("1.0", (row or {}).get("content", ""))
        content.grid(row=1, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="按实际执行写；签到与金额由名单、结算表自动带入。",
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=2,
                                             sticky="w", pady=(4, 0))

        def save():
            if row is None:
                try:
                    self.repo.add_event_note(self.current_pid, {
                        "section": section_var.get(),
                        "content": content.get("1.0", "end").strip()})
                except Exception as e:
                    messagebox.showerror("活动总结", str(e), parent=top)
                    return
            else:
                if section_var.get() != row.get("section"):
                    messagebox.showwarning("活动总结", "已存在的小节不能改名。", parent=top)
                    return
                try:
                    self.repo.update_event_note(row["id"], {
                        "content": content.get("1.0", "end").strip()})
                except Exception as e:
                    messagebox.showerror("活动总结", str(e), parent=top)
                    return
            top.destroy()
            self._load_project(self.current_pid)

        bar = ttk.Frame(body)
        bar.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

    # ---------- 结项包 ----------
    def pick_out(self):
        folder = filedialog.askdirectory(title="选择结项包输出目录", parent=self)
        if folder:
            self.out_var.set(folder)

    def make_package(self):
        if not self.current_pid:
            return
        outdir = self.out_var.get().strip()
        if not outdir:
            messagebox.showinfo("活动结项包", "先选输出目录。", parent=self)
            return
        try:
            result = ev.make_package(self.repo, self.current_pid, outdir)
        except Exception as e:
            messagebox.showerror("活动结项包", str(e), parent=self)
            return
        self.last_package = result["files"][4] if len(result["files"]) > 4 else ""
        self.btn_open.configure(state="normal")
        self._log("生成活动结项包", result["summary"])
        self._load_project(self.current_pid)
        messagebox.showinfo(
            "活动结项包",
            "%s\n目录：%s%s" % (result["summary"], result["package"],
                               ("\nZIP：%s" % result["zip"]) if result["zip"] else ""),
            parent=self)

    def open_report(self):
        try:
            ev.open_report(self.last_package)
        except Exception as e:
            messagebox.showwarning("打开总结", str(e), parent=self)

    def open_folder(self):
        folder = self.out_var.get().strip()
        if folder and os.path.isdir(folder):
            try:
                os.startfile(folder)
            except Exception as e:
                messagebox.showerror("打开目录", str(e), parent=self)
        else:
            messagebox.showinfo("打开目录", "输出目录还不存在，先生成一次结项包。", parent=self)

    # ---------- 新建 / 编辑项目 ----------
    def project_dialog(self, mode=None):
        editing = mode == "edit" and self.current_pid
        project = self.repo.find_project(self.current_pid) if editing else None
        top = tk.Toplevel(self)
        top.title("编辑活动项目" if editing else "新建活动项目")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.grab_set()
        body = ttk.Frame(top, padding=16)
        body.pack(fill="both", expand=True)
        vars_ = {
            "name": tk.StringVar(value=(project or {}).get("name", "")),
            "owner": tk.StringVar(value=(project or {}).get("owner", "")),
            "start_date": tk.StringVar(value=(project or {}).get("start_date", "")),
            "due_date": tk.StringVar(value=(project or {}).get("due_date", "")),
        }
        for i, (label, key, width) in enumerate((
                ("活动名称", "name", 36), ("负责人", "owner", 24),
                ("活动日期", "start_date", 16), ("结束日期", "due_date", 16))):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(
                row=i, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=vars_[key], width=width).grid(
                row=i, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="活动目标", style="Muted.TLabel").grid(
            row=4, column=0, sticky="nw", pady=4)
        goal = tk.Text(body, width=42, height=4, wrap="word")
        goal.insert("1.0", (project or {}).get("goal", ""))
        goal.grid(row=4, column=1, sticky="we", padx=(8, 0), pady=4)
        ttk.Label(body, text="新建自动套 4 项交付物、8 个策划小节与 4 个总结小节；不接在线报名。",
                  style="Muted.TLabel", wraplength=430).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def save():
            name = vars_["name"].get().strip()
            if not name:
                messagebox.showwarning("活动项目", "活动名称不能为空。", parent=top)
                return
            data = {"name": name, "kind": "event",
                    "owner": vars_["owner"].get().strip(),
                    "start_date": vars_["start_date"].get().strip(),
                    "due_date": vars_["due_date"].get().strip(),
                    "goal": goal.get("1.0", "end").strip()}
            try:
                if editing:
                    self.repo.update_project(self.current_pid, data)
                    pid = self.current_pid
                else:
                    data.update({"stage": "定义", "status": "进行中"})
                    pid = self.repo.add_project(data)
                    added = self.repo.apply_project_template(pid, "event")
                    ev.seed_event(self.repo, pid)
                    self._log("新建活动项目", "%s；交付物 %d" % (name, added))
            except Exception as e:
                messagebox.showerror("活动项目", str(e), parent=top)
                return
            top.destroy()
            self.refresh(pid)

        bar = ttk.Frame(body)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="取消", style="Ghost.TButton",
                   command=top.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="right", padx=(0, 8))
        body.columnconfigure(1, weight=1)
        top.wait_window()

# -*- coding: utf-8 -*-
"""材料台账视图：搜索、筛选、查看、归档、驳回。"""

import csv
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

import archive
import theme
from theme import FONT, C
from ui_empty import EmptyState
from ui_error import show_error


class DocsView(ttk.Frame):
    PAGE_SIZE = 300
    COLS = ("code", "name", "cat", "who", "sid", "time", "status", "file")
    HEADS = {"code": "编号", "name": "材料名称", "cat": "类别", "who": "提交人",
             "sid": "学号", "time": "提交时间", "status": "状态", "file": "附件"}
    WIDTHS = {"code": 104, "name": 142, "cat": 64, "who": 56, "sid": 58,
              "time": 84, "status": 62, "file": 60}
    CATS = ["全部", "团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]
    TYPE_OPTIONS = [("全部", "全部"), ("general", "个人材料"), ("meeting", "主题班会记录"),
                    ("dorm", "宿舍走访记录"), ("pledg", "班级承诺书"),
                    ("talk", "违纪约谈记录"), ("custom", "自定义材料")]
    TYPE_LABEL = dict(TYPE_OPTIONS)
    STATUS_TAG = {"已归档": "", "已驳回": "rej",
                  "待审核": "pend", "待补材料": "pend"}

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self._total = 0
        self._shown = self.PAGE_SIZE
        self._row_iids = {}
        self._resize = None
        self._widths = self._load_widths()
        sort = theme.load_ui("doc_sort", {}) if isinstance(
            theme.load_ui("doc_sort", {}), dict) else {}
        self._sort_key = sort.get("key") if sort.get("key") in self.COLS else None
        self._sort_dir = "desc" if sort.get("dir") == "desc" else "asc"
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(16, 10))

        ttk.Label(top, text="搜索", style="Sub.TLabel").pack(side="left")
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *a: self._filter_refresh())
        search = ttk.Entry(top, textvariable=self.q, width=24)
        search.pack(side="left", padx=8)
        search.bind("<Return>", lambda e: self.refresh())

        ttk.Label(top, text="类别", style="Sub.TLabel").pack(side="left", padx=(18, 0))
        self.cat = tk.StringVar(value="全部")
        cb = ttk.Combobox(top, textvariable=self.cat, values=self.CATS,
                          width=12, state="readonly")
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: self._filter_refresh())

        ttk.Label(top, text="类型", style="Sub.TLabel").pack(side="left", padx=(18, 0))
        self.type = tk.StringVar(value="全部")
        tb = ttk.Combobox(top, textvariable=self.type,
                          values=[label for _, label in self.TYPE_OPTIONS],
                          width=14, state="readonly")
        tb.pack(side="left", padx=8)
        tb.bind("<<ComboboxSelected>>", lambda e: self._filter_refresh())

        ttk.Label(top, text="状态", style="Sub.TLabel").pack(side="left", padx=(18, 0))
        self.status = tk.StringVar(value="全部")
        sb = ttk.Combobox(top, textvariable=self.status,
                          values=["全部", "待审核", "已归档", "已驳回", "待补材料"],
                          width=12, state="readonly")
        sb.pack(side="left", padx=8)
        sb.bind("<<ComboboxSelected>>", lambda e: self._filter_refresh())

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=18)
        # 先把右侧详情栏占住，再让左侧表格吃剩余宽度；反过来会把面板挤出窗口
        self.detail = tk.Frame(body, bg=C["card"], width=284,
                               highlightthickness=1, highlightbackground=C["line"])
        self.detail.pack(side="right", fill="y", padx=(12, 0))
        self.detail.pack_propagate(False)
        wrap = tk.Frame(body, bg=C["card"], highlightthickness=1,
                        highlightbackground=C["line"])
        wrap.pack(side="left", fill="both", expand=True)
        # 列宽调大时让表格自己横向滚动，不能把右侧详情栏挤出窗口
        wrap.pack_propagate(False)
        self.tree = ttk.Treeview(wrap, columns=self.COLS, show="headings",
                                 selectmode="extended")
        for c in self.COLS:
            self.tree.heading(c, text=self._head_text(c), anchor="w")
            self.tree.column(c, width=self._widths[c], minwidth=54, anchor="w",
                             stretch=False)
        self.tree.tag_configure("zebra", background=C["zebra"])
        self.tree.tag_configure("pend", background=C["tag_orange"])
        self.tree.tag_configure("rej", background=C["tag_red"])

        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=(1, 0))
        ysb.grid(row=0, column=1, sticky="ns", padx=(0, 1), pady=1)
        hsb.grid(row=1, column=0, sticky="ew", padx=(1, 0), pady=(0, 1))

        self.empty = EmptyState(wrap, wraplength=360)
        self._build_detail()

        # 选中联动与快捷键
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_actions())
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Return>", lambda e: self.view())
        # 表头拖动分隔线调列宽；松开后落盘；单击表头排序
        self.tree.bind("<ButtonPress-1>", self._col_press, add="+")
        self.tree.bind("<B1-Motion>", self._col_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._col_release, add="+")
        self.tree.bind("<Motion>", self._col_hover, add="+")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=18, pady=12)
        self.btn_view = ttk.Button(bar, text="查看", command=self.view)
        self.btn_archive = ttk.Button(bar, text="归档", style="Accent.TButton",
                                      command=self.archive)
        self.btn_reject = ttk.Button(bar, text="驳回", style="Danger.TButton",
                                     command=self.reject)
        self.btn_csv = ttk.Button(bar, text="导出 CSV", command=self.export_csv)
        self.btn_place = ttk.Button(bar, text="归位文件", command=self.place_files)
        self.btn_files = ttk.Button(bar, text="文件室", command=self.open_in_files)
        self.view_btn = tk.Button(bar, text="视图 ▾", relief="flat", bd=0,
                                  bg=C["bg"], fg=C["text"],
                                  activebackground=C["bg_soft"], activeforeground=C["text"],
                                  font=(FONT, 10), padx=10, pady=5, cursor="hand2")
        self.view_menu = tk.Menu(self.view_btn, tearoff=0, bg=C["card"], fg=C["text"],
                                 activebackground=C["primary_soft"], activeforeground=C["primary"],
                                 bd=0)
        self.view_btn.bind("<Button-1>", self._post_views)
        self.more = tk.Button(bar, text="更多 ▾", relief="flat", bd=0,
                              bg=C["bg"], fg=C["text"],
                              activebackground=C["bg_soft"], activeforeground=C["text"],
                              font=(FONT, 10), padx=10, pady=5, cursor="hand2")
        menu = tk.Menu(self.more, tearoff=0, bg=C["card"], fg=C["text"],
                       activebackground=C["primary_soft"], activeforeground=C["primary"],
                       bd=0)
        menu.add_command(label="归位文件到归档目录", command=self.place_files)
        menu.add_command(label="在文件室查看归档文件", command=self.open_in_files)
        menu.add_command(label="打开归档目录", command=self.open_archive_dir)
        menu.add_separator()
        menu.add_command(label="导出当前视图 CSV", command=self.export_csv)
        menu.add_separator()
        menu.add_command(label="重置列宽", command=self.reset_widths)
        self.more_menu = menu
        self.more.bind("<Button-1>", self._post_more)
        self.hint = ttk.Label(bar, text="", style="Muted.TLabel")
        self.hint.pack(side="right")
        # 5000 条不一次性塞进 Treeview：默认先显示最近 300 条，按需追加。
        self.btn_more_rows = ttk.Button(bar, text="加载更多", command=self.load_more)

    def _build_detail(self):
        """右侧常驻详情栏；列表上下文不丢，审批节点与附件集中在这里。"""
        head = tk.Frame(self.detail, bg=C["card"])
        head.pack(fill="x", padx=14, pady=(12, 4))
        tk.Label(head, text="材料详情", bg=C["card"], fg=C["text"],
                 font=(FONT, 11, "bold"), anchor="w").pack(side="left")
        self.detail_count = tk.Label(head, text="", bg=C["card"], fg=C["sub"],
                                     font=(FONT, 9), anchor="e")
        self.detail_count.pack(side="right")
        self.detail_text = tk.Text(
            self.detail, width=29, height=1, wrap="word", bd=0, relief="flat",
            bg=C["card"], fg=C["text"], insertbackground=C["card"],
            font=(FONT, 9), padx=14, pady=4, cursor="arrow", state="disabled")
        dsv = ttk.Scrollbar(self.detail, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=dsv.set)
        self.detail_text.pack(side="left", fill="both", expand=True)
        dsv.pack(side="right", fill="y", pady=(0, 10), padx=(0, 2))
        self.detail_text.tag_configure("h1", font=(FONT, 13, "bold"), spacing3=2)
        self.detail_text.tag_configure("meta", foreground=C["sub"], font=(FONT, 9))
        self.detail_text.tag_configure("sec", font=(FONT, 9, "bold"), spacing1=12, spacing3=3)
        self.detail_text.tag_configure("muted", foreground=C["sub"], font=(FONT, 9))
        self.detail_text.tag_configure("accent", foreground=C["primary"], font=(FONT, 9, "bold"))
        self.detail_text.tag_configure("ok", foreground=C["green"], font=(FONT, 9, "bold"))
        self.detail_text.tag_configure("warn", foreground=C["orange"], font=(FONT, 9, "bold"))
        self.detail_text.tag_configure("bad", foreground=C["red"], font=(FONT, 9, "bold"))
        self.detail_text.tag_configure("line", foreground=C["line_strong"])
        self.detail_text.tag_configure("node", foreground=C["primary"], font=(FONT, 10, "bold"))
        self.detail_text.tag_configure("node_muted", foreground=C["sub"], font=(FONT, 10, "bold"))
        self._render_detail()

    # ---------- 列宽 / 排序 ----------
    def _head_text(self, col):
        text = self.HEADS[col]
        if self._sort_key == col:
            text += " ▲" if self._sort_dir == "asc" else " ▼"
        return text

    def _sync_headings(self):
        for c in self.COLS:
            self.tree.heading(c, text=self._head_text(c), anchor="w")

    def _load_widths(self):
        saved = theme.load_ui("doc_col_widths", {})
        out = dict(self.WIDTHS)
        if not isinstance(saved, dict):
            return out
        for c in self.COLS:
            try:
                w = int(saved.get(c, self.WIDTHS[c]))
            except (TypeError, ValueError):
                w = self.WIDTHS[c]
            out[c] = max(54, min(520, w))
        return out

    def _save_widths(self):
        try:
            theme.save_ui("doc_col_widths", self._widths)
        except Exception:
            pass

    def _apply_widths(self):
        for c in self.COLS:
            self.tree.column(c, width=self._widths[c])

    def reset_widths(self):
        self._widths = dict(self.WIDTHS)
        self._apply_widths()
        self._save_widths()

    def reset_filters(self):
        self.q.set("")
        self.cat.set("全部")
        self.type.set("全部")
        self.status.set("全部")
        self.refresh()
        self.window.toast("列宽已恢复默认")

    # ---------- 命名保存视图 ----------
    def _load_views(self):
        raw = theme.load_ui("doc_views", [])
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            out.append(item)
        return out[:20]

    def _save_views(self, views):
        try:
            theme.save_ui("doc_views", views)
        except Exception:
            pass

    def _snapshot_view(self, name):
        return {
            "name": name,
            "q": self.q.get(),
            "cat": self.cat.get(),
            "type": self.type.get(),
            "status": self.status.get(),
            "sort_key": self._sort_key,
            "sort_dir": self._sort_dir,
            "widths": dict(self._widths),
        }

    def _apply_view(self, name):
        views = self._load_views()
        view = next((v for v in views if v.get("name") == name), None)
        if not view:
            self.window.toast("视图不存在，可能已被删除")
            return
        self._shown = self.PAGE_SIZE
        widths = view.get("widths") if isinstance(view.get("widths"), dict) else {}
        for c in self.COLS:
            try:
                w = int(widths.get(c, self.WIDTHS[c]))
            except (TypeError, ValueError):
                w = self.WIDTHS[c]
            self._widths[c] = max(54, min(520, w))
        self._apply_widths()
        self._save_widths()
        self.q.set(str(view.get("q") or ""))
        self.cat.set(view.get("cat") or "全部")
        self.type.set(view.get("type") or "全部")
        self.status.set(view.get("status") or "全部")
        skey = view.get("sort_key")
        self._sort_key = skey if skey in self.COLS else None
        self._sort_dir = "desc" if view.get("sort_dir") == "desc" else "asc"
        self._sync_headings()
        self.refresh()
        self.window.toast("已套用视图「%s」" % name)

    def save_current_view(self):
        name = simpledialog.askstring(
            "保存当前视图", "给这套筛选、排序和列宽起个名字：", parent=self)
        if name is None:
            return
        name = name.strip()
        if not name:
            self.window.toast("视图名称不能为空")
            return
        if len(name) > 20:
            self.window.toast("视图名称最多 20 个字")
            return
        views = self._load_views()
        snap = self._snapshot_view(name)
        idx = next((i for i, v in enumerate(views) if v.get("name") == name), None)
        if idx is None:
            views.append(snap)
        else:
            views[idx] = snap
        self._save_views(views)
        self.window.toast("视图「%s」已保存" % name)

    def _delete_view(self, name):
        if not self.window.confirm("删除视图", "确定删除视图「%s」吗？" % name):
            return
        views = [v for v in self._load_views() if v.get("name") != name]
        self._save_views(views)
        self.window.toast("视图「%s」已删除" % name)

    def _post_views(self, event=None):
        menu = self.view_menu
        menu.delete(0, "end")
        views = self._load_views()
        if views:
            for v in views:
                menu.add_command(label=v.get("name"),
                                 command=lambda n=v.get("name"): self._apply_view(n))
        else:
            menu.add_command(label="还没有保存的视图", state="disabled")
        menu.add_separator()
        menu.add_command(label="保存当前视图…", command=self.save_current_view)
        if views:
            sub = tk.Menu(menu, tearoff=0, bg=C["card"], fg=C["text"],
                          activebackground=C["primary_soft"],
                          activeforeground=C["primary"], bd=0)
            for v in views:
                sub.add_command(label=v.get("name"),
                                command=lambda n=v.get("name"): self._delete_view(n))
            menu.add_cascade(label="删除视图", menu=sub)
        x = self.view_btn.winfo_rootx()
        y = self.view_btn.winfo_rooty() + self.view_btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()
        return "break"

    def _col_at(self, x):
        col = self.tree.identify_column(x)
        try:
            idx = int(str(col).replace("#", "")) - 1
            return self.COLS[idx] if 0 <= idx < len(self.COLS) else None
        except ValueError:
            return None

    def _col_press(self, event):
        if self.tree.identify_region(event.x, event.y) != "separator":
            return None
        col = self._col_at(event.x)
        if not col:
            return None
        self._resize = {"col": col, "x": event.x, "w": self._widths[col]}
        self.tree.configure(cursor="sb_h_double_arrow")
        return "break"

    def _col_motion(self, event):
        if not self._resize:
            return None
        delta = event.x - self._resize["x"]
        width = max(54, min(520, self._resize["w"] + delta))
        self._widths[self._resize["col"]] = width
        self.tree.column(self._resize["col"], width=width)
        return "break"

    def _col_release(self, event):
        if self._resize:
            self._resize = None
            self._save_widths()
            self.tree.configure(cursor="")
            return "break"
        if self.tree.identify_region(event.x, event.y) != "heading":
            return None
        col = self._col_at(event.x)
        if not col:
            return None
        if self._sort_key == col:
            self._sort_dir = "desc" if self._sort_dir == "asc" else "asc"
        else:
            self._sort_key = col
            self._sort_dir = "desc" if col == "time" else "asc"
        try:
            theme.save_ui("doc_sort", {"key": self._sort_key, "dir": self._sort_dir})
        except Exception:
            pass
        self._shown = self.PAGE_SIZE
        self._sync_headings()
        self.refresh()
        return "break"

    def _col_hover(self, event):
        if self._resize:
            return None
        region = self.tree.identify_region(event.x, event.y)
        self.tree.configure(cursor="sb_h_double_arrow" if region == "separator" else "")
        return None

    def _on_double(self, event):
        if self.tree.identify_region(event.x, event.y) in ("separator", "heading"):
            return "break"
        self.view()
        return "break"

    def _sort_rows(self, rows):
        if not self._sort_key:
            return rows
        key = self._sort_key
        reverse = self._sort_dir == "desc"

        def val(d):
            if key == "time":
                return str(d.get("time") or "")
            return str(d.get(key) or "")

        return sorted(rows, key=val, reverse=reverse)

    def _detail_reset(self):
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", "end")

    def _write(self, text, tag=None):
        self.detail_text.insert("end", text, tag or ())

    def _render_detail(self):
        ids = self._selected_ids()
        self._detail_reset()
        self.detail_count.config(text=(("%d 条" % len(ids)) if ids else ""))
        if not ids:
            self._write("未选择材料\n", "h1")
            self._write("在左侧单击一行，这里会显示材料信息、审批节点和最近操作。\n"
                        "Ctrl / Shift 可多选，批量归档或批量驳回。\n", "muted")
            self.detail_text.config(state="disabled")
            return
        doc = self._find_doc(ids[0])
        if not doc:
            self._write("材料记录不存在，可能已被过滤或删除。\n", "muted")
            self.detail_text.config(state="disabled")
            return
        if len(ids) > 1:
            self._write("已选 %d 条材料\n" % len(ids), "warn")
            self._write("批量归档 / 批量驳回会作用于全部已选材料；下方为第一条详情。\n", "muted")

        name = doc.get("name") or "未命名"
        status = doc.get("status") or ""
        status_tag = {"已归档": "ok", "已驳回": "bad",
                      "待审核": "warn", "待补材料": "warn"}.get(status, "muted")
        self._write(name + "\n", "h1")
        self._write("%s · %s · " % (doc.get("code") or "—", doc.get("cat") or "—"),
                    "meta")
        self._write(status, status_tag)
        self._write("\n")

        events = self.repo.doc_timeline(doc)
        self._write("\n流转时间线\n", "sec")
        self._write("共 %d 个节点，提交、审核、归档与归位均可回放。\n" % len(events),
                    "muted")
        act_tags = {"提交": "accent", "归档": "ok", "驳回": "bad", "归位": "muted"}
        for ev in events:
            act = ev.get("act") or "记录"
            self._write("● ", "node")
            self._write("%s  " % act, act_tags.get(act, "accent"))
            self._write("%s  %s（%s）\n" % (
                ev.get("time") or "—", ev.get("who") or "—",
                ev.get("role") or "—"), "muted")
            detail = (ev.get("detail") or "").strip()
            if detail:
                self._write("│  %s\n" % detail, "muted")
            self._write("│\n", "line")

        if status == "已归档":
            if not any((e.get("act") or "") == "归位" for e in events):
                self._write("○ ", "node_muted")
                self._write("归位  ", "muted")
                self._write("已归档，等待写入文件路径\n", "warn")
        elif status in ("已驳回", "待补材料"):
            self._write("○ ", "node_muted")
            self._write("补交  ", "muted")
            self._write("申请人重新提交后可再次审核\n", "muted")
        else:
            self._write("○ ", "node_muted")
            self._write("审核  ", "muted")
            self._write("等待经办人处理\n", "warn")

        tpl = self.repo.form_template(doc.get("form_type") or "general")
        self._write("\n基本信息\n", "sec")
        for label, value in (("编号", doc.get("code") or "—"), ("类型", tpl["label"]),
                             ("类别", doc.get("cat") or "—"),
                             ("提交人", "%s（%s）" % (doc.get("who") or "—",
                                                      doc.get("sid") or "—")),
                             ("提交时间", doc.get("time") or "—"),
                             ("说明", doc.get("note") or "无")):
            self._write("%s：%s\n" % (label, value), "muted")

        extra = doc.get("extra") or {}
        for f in tpl["fields"]:
            val = ""
            if isinstance(extra, dict):
                val = (extra.get(f["key"]) or "").strip()
            if val:
                self._write("%s：%s\n" % (f["label"], val), "muted")

        atts = doc.get("attachments") or []
        self._write("\n附件\n", "sec")
        if atts:
            for a in atts:
                line = "· %s" % (a.get("name") or "未命名")
                if a.get("path"):
                    line += "  %s" % a["path"]
                self._write(line + "\n", "muted")
        else:
            self._write((doc.get("file") or "无附件") + "\n", "muted")

        doc_path = doc.get("path") or ""
        if doc_path:
            self._write("\n本机路径\n", "sec")
            self._write(doc_path + "\n", "muted")
        if doc.get("arch"):
            self._write("\n归档文件\n", "sec")
            self._write(doc["arch"] + "\n", "muted")
            self._write("目录：%s\n" % os.path.dirname(doc["arch"]), "muted")
        reason = (doc.get("reason") or "").strip()
        if reason:
            self._write("\n审核备注\n", "sec")
            self._write(reason + "\n", "muted")

        self.detail_text.config(state="disabled")

    # ---------- 数据与状态 ----------
    def _selected_ids(self):
        ids = []
        for iid in self.tree.selection():
            try:
                ids.append(int(self.tree.item(iid)["tags"][0]))
            except (ValueError, IndexError, KeyError):
                continue
        return ids

    def _selected(self):
        ids = self._selected_ids()
        return ids[0] if ids else None

    def _find_doc(self, doc_id):
        return next((x for x in self.repo.list_docs() if x.get("id") == doc_id), None)

    def _update_actions(self):
        ids = self._selected_ids()
        has = bool(ids)
        state = "normal" if has else "disabled"
        self.btn_view.config(state=state)
        if self.window.can("docs:archive"):
            self.btn_archive.config(
                state=state,
                text=("批量归档 (%d)" % len(ids)) if len(ids) > 1 else "归档")
            self.btn_files.config(state=state)
        if self.window.can("docs:reject"):
            self.btn_reject.config(
                state=state,
                text=("批量驳回 (%d)" % len(ids)) if len(ids) > 1 else "驳回")
        tail = (" · 已选 %d 条" % len(ids)) if ids else " · Ctrl/Shift 多选"
        head = "共 %d 条" % self._total
        if self._can_page() and self._total > self._shown:
            head += " · 已显示 %d 条" % self._shown
        self.hint.config(text=head + tail)
        self._render_detail()

    def _filter_args(self):
        st = self.status.get()
        st = st if st and st != "全部" else None
        tlabel = self.type.get()
        tkey = None
        if tlabel and tlabel != "全部":
            tkey = next((k for k, v in self.TYPE_OPTIONS if v == tlabel), "")
        return self.q.get().strip(), self.cat.get(), st, tkey

    def _applicant_sid(self):
        if self.window.role != "applicant":
            return ""
        return str(getattr(self.window, "applicant_sid", "") or "").strip()

    def _can_page(self):
        """默认排序且非申请人视角才分页；自定义排序要保持全量顺序。"""
        return self._sort_key is None and not self._applicant_sid()

    def _filtered_rows(self, limit=None, offset=0):
        q, cat, st, ft = self._filter_args()
        sid = self._applicant_sid()
        page = limit is not None and self._sort_key is None and not sid
        rows = self.repo.list_docs(
            q, cat, status=st, form_type=ft,
            limit=limit if page else None, offset=offset if page else 0)
        # 申请人视角只看本人材料；学号在设置里配置，未配置时为空
        if sid:
            rows = [x for x in rows if x.get("sid") == sid]
        elif self.window.role == "applicant":
            rows = []
        return self._sort_rows(rows)

    def _filter_refresh(self):
        self._shown = self.PAGE_SIZE
        self.refresh()

    def _sync_more_rows(self):
        if self._can_page() and self._total > self._shown:
            if not self.btn_more_rows.winfo_manager():
                self.btn_more_rows.pack(side="right", padx=(0, 8))
            self.btn_more_rows.config(
                text="加载更多 (%d)" % min(self.PAGE_SIZE, self._total - self._shown))
        else:
            self.btn_more_rows.pack_forget()

    def load_more(self):
        """追加下一页，不整表重绘，避免滚动位置跳回顶部。"""
        if self._shown >= self._total:
            return
        before = len(self.tree.get_children())
        self._shown = min(self._shown + self.PAGE_SIZE, self._total)
        rows = self._filtered_rows(limit=self._shown)
        for i, d in enumerate(rows[before:], start=before):
            self._insert_doc(i, d)
        self._sync_more_rows()
        self._update_actions()

    def _insert_doc(self, i, d):
        status = d.get("status", "") or ""
        # 待审/驳回用极淡底色提示，其余走斑马纹；不给整行染字色，避免八列都变色
        status_tag = self.STATUS_TAG.get(status, "")
        row_tag = "zebra" if (i % 2 and not status_tag) else ""
        tags = tuple(t for t in (d.get("id"), row_tag, status_tag) if t)
        atts = d.get("attachments") or []
        file_disp = ("%d 个附件" % len(atts)) if atts else (
            "已归位" if d.get("arch") else (d.get("file") or "无附件"))
        iid = self.tree.insert("", "end", tags=tags, values=(
            d.get("code", ""), d.get("name", ""), d.get("cat", ""), d.get("who", ""),
            d.get("sid", ""), d.get("time", ""), status, file_disp))
        self._row_iids[d.get("id")] = iid
        return iid

    def refresh(self):
        rows = self._filtered_rows(limit=self._shown if self._can_page() else None)
        keep = self._selected_ids()
        self._sync_headings()
        self.tree.delete(*self.tree.get_children())
        self._row_iids = {}
        for i, d in enumerate(rows):
            self._insert_doc(i, d)
        if self._can_page():
            q, cat, st, ft = self._filter_args()
            self._total = self.repo.count_docs(q, cat, status=st, form_type=ft)
        else:
            self._total = len(rows)
        self._sync_more_rows()

        if rows:
            self.empty.hide()
        else:
            all_docs = self.repo.list_docs()
            filters_on = bool(self.q.get().strip()) or any((
                self.cat.get() != "全部", self.type.get() != "全部",
                self.status.get() != "全部"))
            if getattr(self.window, "role", "") == "applicant" and not str(
                    getattr(self.window, "applicant_sid", "") or "").strip():
                self.empty.set(
                    "请先填写申请人学号",
                    "未填写时不展示任何人的材料。填好后，这里只显示你自己的提交与审核进度。",
                    "填写学号", self.window.open_settings)
            elif not all_docs:
                if self.window.can("docs:create"):
                    self.empty.set("还没有材料",
                                   "台账目前为空。提交第一份后会进入待审核队列，归档时自动留痕。",
                                   "提交第一份材料", lambda: self.window.switch("submit"))
                else:
                    self.empty.set("还没有材料",
                                   "当前岗位只能查看，不能提交；切换到经办人岗位后可录入第一份。",
                                   "切换岗位", lambda: self.window._role_menu())
            elif filters_on:
                self.empty.set("没有符合条件的材料",
                               "现有材料被搜索词或筛选条件挡住了，放宽条件即可看到。",
                               "清除筛选", self.reset_filters)
            else:
                self.empty.set("当前视角没有可见材料",
                               "材料在库，但当前岗位看不到；切换到有查看权限的岗位即可。",
                               "切换岗位", lambda: self.window._role_menu())
            self.empty.show_place()

        # 刷新后把原来选中的行重新定位；筛选或数据变化导致不在列表里时不强行保留
        restored = [self._row_iids[i] for i in keep if i in self._row_iids]
        if restored:
            self.tree.selection_set(restored)
            self.tree.focus(restored[0])
            self.tree.see(restored[0])
        self._update_actions()

        # 按权限点控制审核/归位/导出：无权限的入口不出现，方法内也再拦一次
        can_archive = self.window.can("docs:archive")
        can_export = self.window.can("docs:export")
        for b in (self.btn_view, self.btn_place, self.btn_csv, self.view_btn, self.more,
                  self.btn_archive, self.btn_reject, self.btn_files):
            b.pack_forget()
        self.btn_view.pack(side="left")
        if can_archive:
            self.btn_archive.pack(side="left", padx=8)
            self.btn_place.pack(side="left", padx=8)
            self.btn_files.pack(side="left", padx=(0, 8))
        if can_export:
            self.btn_csv.pack(side="left", padx=8)
        self.view_btn.pack(side="left", padx=8)
        if can_archive or can_export:
            self.more.pack(side="left", padx=8)
        if self.window.can("docs:reject"):
            self.btn_reject.pack(side="right")
        self.more_menu.entryconfig("归位文件到归档目录",
                                   state="normal" if can_archive else "disabled")
        self.more_menu.entryconfig("在文件室查看归档文件",
                                   state="normal" if can_archive else "disabled")
        self.more_menu.entryconfig("导出当前视图 CSV",
                                   state="normal" if can_export else "disabled")
        self.more_menu.entryconfig("打开归档目录",
                                   state="normal" if can_archive else "disabled")
        self._update_actions()

    def _post_more(self, event=None):
        x = self.more.winfo_rootx()
        y = self.more.winfo_rooty() + self.more.winfo_height()
        try:
            self.more_menu.tk_popup(x, y)
        finally:
            self.more_menu.grab_release()
        return "break"

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
        self._render_detail()
        self.window.toast("详情已展开在右侧")

    def archive(self):
        if not self.window.can("docs:archive"):
            self.window.toast("当前视角无权归档")
            return
        ids = self._selected_ids()
        if not ids:
            self.window.toast("请先选择材料")
            return
        docs = [d for d in (self._find_doc(i) for i in ids) if d]
        if not docs:
            return
        todo = [d for d in docs if d.get("status") != "已归档"]
        if not todo:
            self.window.toast("所选材料均已归档")
            return
        if len(todo) == 1:
            prompt = "归档「%s」，可补充归档备注（可选）：" % todo[0].get("name", "")
        else:
            prompt = ("将归档选中的 %d 条材料（已归档的会自动跳过）。\n"
                      "归档备注会写入全部选中材料，可留空：" % len(todo))
        dlg = self._reason_dialog("批量归档确认" if len(todo) > 1 else "归档确认", prompt)
        if dlg is None:
            return
        ok = skip = 0
        fail = []
        place_fail = []
        log_fail = 0
        index_fail = False
        note = ""
        for doc in docs:
            if doc.get("status") == "已归档":
                skip += 1
                continue
            try:
                saved = self.repo.archive_doc(doc.get("id"), dlg["reason"],
                                              self.window.operator_name,
                                              self.window.role_label())
            except Exception as e:
                fail.append("%s（%s）" % (doc.get("name") or "未命名",
                                         type(e).__name__))
                continue
            if not saved:
                fail.append(doc.get("name") or "未命名")
                continue
            try:
                self.repo.add_log("归档", saved.get("name", ""),
                                  self.window.operator_name,
                                  self.window.role_label())
            except Exception:
                log_fail += 1
            placed = self._place_one(saved.get("id"),
                                     dict(saved, status="已归档"), quiet=True)
            note = placed.get("note", "")
            if not placed.get("ok"):
                place_fail.append("%s（%s）" % (
                    saved.get("name") or "未命名", note))
            if placed.get("index_error"):
                index_fail = True
            ok += 1
        self.window.refresh_all()
        msg = "已归档 %d 条，并写入操作日志" % ok
        if skip:
            msg += "，跳过已归档 %d 条" % skip
        if fail:
            msg += "，台账未写入 %d 条" % len(fail)
        if log_fail:
            msg += "，%d 条日志写入失败" % log_fail
        if index_fail:
            msg += "，归档索引表写入失败"
        if len(todo) == 1 and not fail and not place_fail:
            msg += note
        self.window.toast(msg[:120])
        if ok:
            self.window.mark_first_run(3 if self.window.role == "applicant" else 2)
        if fail:
            show_error(
                self.window, "部分材料没有归档成功",
                "有 %d 条材料未能写入台账：%s。" % (len(fail), "；".join(fail[:2])),
                "现有台账与文件都没有被删除；这些条目仍是原状态，未计入已归档。",
                "先单条重试；若连续失败，导出一次备份，再查看崩溃日志。",
                "原文件仍在原位置；备份导入可以恢复台账，未归档文件不会自动删除。",
                actions=[("知道了", lambda: None)])
        if place_fail:
            show_error(
                self.window, "归档文件没有全部复制完成",
                "台账已标记 %d 条为已归档，但其中有 %d 条复制失败：%s。"
                % (ok, len(place_fail), "；".join(place_fail[:2])),
                "台账记录还在；对应归档目录里可能缺少这些文件，原文件没有被移动或删除。",
                "先打开归档目录检查磁盘空间与写入权限，再重新归档这几条。",
                "本机原文件与网页端备份仍可作为兜底；失败文件不会自动删除。",
                actions=[("打开归档目录", self._open_archive_dir_safe),
                         ("知道了", lambda: None)])

    def _place_one(self, doc_id, doc, quiet=False):
        """复制到归档根并按目录归位，返回 ok / note / index_error。"""
        res = archive.place(doc)
        note = res.get("note") or "已处理"
        index_error = False
        if res.get("path"):
            try:
                self.repo.set_arch(doc_id, res["path"],
                                   self.window.operator_name,
                                   self.window.role_label())
            except Exception as e:
                return {"ok": False, "note": "台账路径写入失败（%s）"
                        % type(e).__name__, "index_error": False}
        try:
            index_path = archive.write_index(self.repo.list_docs())
            index_error = not bool(index_path)
        except Exception:
            index_error = True
        return {"ok": bool(res.get("ok")), "note": note,
                "index_error": index_error}

    def _open_archive_dir_safe(self):
        base = archive.root()
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            show_error(
                self.window, "归档目录暂时打不开",
                "建目录时被系统拒绝（%s）。" % type(e).__name__,
                "归档文件可能没有写入；台账记录仍保留。",
                "换一个可写的归档位置，或检查当前目录权限后重试。",
                "原文件仍在原位置，不会因为打不开目录而丢失。",
                actions=[("知道了", lambda: None)])
            return
        try:
            opened = archive.open_folder(base)
        except OSError:
            opened = False
        if not opened:
            show_error(
                self.window, "归档目录暂时打不开",
                "系统没有成功打开归档文件夹。",
                "文件仍在原位置，台账记录未变。",
                "可以在文件资源管理器里手动打开本机数据目录下的归档文件夹。",
                "需要时先导出备份，避免继续操作时误判文件位置。",
                actions=[("知道了", lambda: None)])

    def open_archive_dir(self):
        if not self.window.can("docs:archive"):
            self.window.toast("当前视角无权打开归档目录")
            return
        self._open_archive_dir_safe()

    def open_in_files(self):
        """把选中材料带到文件室，直接展开所在目录。"""
        if not self.window.can("docs:archive"):
            self.window.toast("当前视角无权访问文件室")
            return
        doc = self._find_doc(self._selected())
        if not doc:
            self.window.toast("先选中一条材料")
            return
        path = str(doc.get("arch") or doc.get("path") or "").strip()
        if not path:
            self.window.toast("这条材料还没有本地文件路径")
            return
        self.window.goto_files(path)

    def place_files(self):
        """把当前筛选结果中的已归档材料统一归位到归档根目录。"""
        if not self.window.can("docs:archive"):
            self.window.toast("当前视角无权归位文件")
            return
        rows = self._filtered_rows()
        target = [d for d in rows if d.get("status") == "已归档"]
        if not target:
            self.window.toast("当前筛选没有已归档材料可归位")
            return
        if not self.window.confirm(
                "归位确认",
                "将把当前筛选中的 %d 条已归档材料复制到归档目录。\n"
                "同名同大小跳过，同名不同内容会自动加 _v2，不会覆盖。\n"
                "确定继续吗？" % len(target)):
            return
        copied = 0
        for d in target:
            res = archive.place(d)
            if res.get("copied"):
                copied += 1
            if res.get("path"):
                self.repo.set_arch(d.get("id"), res["path"],
                                   self.window.operator_name,
                                   self.window.role_label())
        archive.write_index(self.repo.list_docs())
        self.window.refresh_all()
        self.window.toast("已处理 %d 条，复制 %d 个文件到归档目录" % (len(target), copied))

    def reject(self):
        if not self.window.can("docs:reject"):
            self.window.toast("当前视角无权驳回")
            return
        ids = self._selected_ids()
        if not ids:
            self.window.toast("请先选择材料")
            return
        docs = [d for d in (self._find_doc(i) for i in ids) if d]
        if not docs:
            return
        todo = [d for d in docs
                if d.get("status") not in ("已驳回", "已归档")]
        if not todo:
            self.window.toast("所选材料已驳回或已归档，无需再驳回")
            return
        if len(todo) == 1:
            prompt = "驳回「%s」，请填写驳回原因（可选）：" % todo[0].get("name", "")
        else:
            prompt = ("将驳回选中的 %d 条材料（已驳回/已归档的会自动跳过）。\n"
                      "驳回原因会写入全部选中材料，可留空：" % len(todo))
        dlg = self._reason_dialog("批量驳回确认" if len(todo) > 1 else "驳回确认", prompt)
        if dlg is None:
            return
        ok = skip = 0
        fail = []
        for doc in docs:
            if doc.get("status") in ("已驳回", "已归档"):
                skip += 1
                continue
            try:
                saved = self.repo.reject_doc(doc.get("id"), dlg["reason"],
                                             self.window.operator_name,
                                             self.window.role_label())
            except Exception as e:
                fail.append("%s：%s" % (doc.get("name") or "未命名", e))
                continue
            if saved:
                try:
                    self.repo.add_log("驳回", saved.get("name", ""),
                                      self.window.operator_name, self.window.role_label())
                except Exception:
                    pass
                ok += 1
        self.window.refresh_all()
        msg = "已驳回 %d 条，并写入操作日志" % ok
        if skip:
            msg += "，跳过 %d 条" % skip
        if fail:
            msg += "，失败 %d 条：%s" % (len(fail), "；".join(fail[:2]))
        self.window.toast(msg[:120])

    def export_csv(self):
        if not self.window.can("docs:export"):
            self.window.toast("当前视角无权导出材料")
            return
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
                    tpl = self.repo.form_template(d.get("form_type") or "general")
                    w.writerow([d.get("code", ""), tpl["label"], d.get("name", ""),
                                d.get("cat", ""), d.get("who", ""), d.get("sid", ""),
                                d.get("time", ""), d.get("status", ""), att_names,
                                d.get("note", ""), d.get("reason") or ""])
            self.window.toast("已导出 %d 条记录" % len(rows))
        except OSError as e:
            messagebox.showerror("导出失败", str(e))

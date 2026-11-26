# -*- coding: utf-8 -*-
"""文件工具：批量重命名 / 图片格式转换 / 按类别归位。

一个对话框三件事，规则都一样：
  - 先在列表里看清「原文件 → 新位置 / 新名字」，再点执行；
  - 只处理归档根内的文件，跳过和失败都写明原因；
  - 改完顺手把台账路径同步过去，并留一条操作日志。
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox

import archive
import filetools
import fileroom
from theme import FONT, C


class FileToolsDialog:
    """批量文件工具的预览与执行面板。"""

    TABS = (("rename", "批量重命名"), ("convert", "图片格式转换"),
            ("organize", "按类别归位"))

    def __init__(self, parent, repo, window, paths, source_label="",
                 on_done=None):
        self.repo = repo
        self.window = window
        self.paths = [p for p in (paths or []) if p]
        self.source_label = source_label
        self.on_done = on_done
        self.rows = {}          # tab -> 预览行
        self.undo = []          # 上次成功改名的反向清单
        self.tab = "rename"
        self._tab_buttons = {}
        self._panels = {}

        self.top = tk.Toplevel(parent)
        self.top.title("文件工具")
        self.top.geometry(self._geometry(940, 640))
        self.top.minsize(820, 560)
        self.top.configure(bg=C["bg"])
        self.top.transient(parent.winfo_toplevel())
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._switch("rename")
        self._center()

    def _geometry(self, width, height):
        """按主窗口位置居中摆放，屏幕放不下就贴左上角。"""
        try:
            parent = self.top.master.winfo_toplevel()
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            x = max(0, px + (pw - width) // 2)
            y = max(0, py + (ph - height) // 3)
            sw, sh = parent.winfo_screenwidth(), parent.winfo_screenheight()
            x = min(x, max(0, sw - width - 8))
            y = min(y, max(0, sh - height - 8))
            return "%dx%d+%d+%d" % (width, height, x, y)
        except Exception:
            return "%dx%d" % (width, height)

    def _center(self):
        self.top.update_idletasks()
        self.top.lift()

    # ---------- 搭界面 ----------
    def _build(self):
        wrap = tk.Frame(self.top, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=22, pady=16)

        tk.Label(wrap, text="文件工具", bg=C["bg"], fg=C["text"],
                 font=(FONT, 15, "bold"), anchor="w").pack(fill="x")
        tk.Label(wrap, text="只处理归档目录内的文件；先看预览再执行，同名不覆盖，"
                            "重命名可整体撤销。",
                 bg=C["bg"], fg=C["sub"], font=(FONT, 9), anchor="w").pack(
            fill="x", pady=(4, 2))

        scope = tk.Frame(wrap, bg=C["card"], highlightthickness=1,
                         highlightbackground=C["line"])
        scope.pack(fill="x", pady=(8, 10))
        self.scope_label = tk.Label(
            scope, bg=C["card"], fg=C["text"], font=(FONT, 9), anchor="w",
            padx=12, pady=7,
            text="对象：%d 个文件%s" % (len(self.paths),
                                     "（%s）" % self.source_label if self.source_label else ""))
        self.scope_label.pack(fill="x")
        if not self.paths:
            tk.Label(scope, text="先在文件列表里选中文件（Ctrl / Shift 可多选），"
                                 "或切进某个目录再打开这里。",
                     bg=C["card"], fg=C["orange"], font=(FONT, 9), anchor="w",
                     padx=12, pady=(0, 7)).pack(fill="x")

        bar = tk.Frame(wrap, bg=C["bg"])
        bar.pack(fill="x")
        for key, label in self.TABS:
            btn = tk.Button(bar, text=label, relief="flat", bd=0,
                            font=(FONT, 10), padx=14, pady=6, cursor="hand2",
                            command=lambda k=key: self._switch(k))
            btn.pack(side="left", padx=(0, 6))
            self._tab_buttons[key] = btn

        foot = tk.Frame(wrap, bg=C["bg"])
        foot.pack(fill="x", side="bottom", pady=(10, 0))
        self.status = tk.StringVar(value="还没有预览。")
        tk.Label(foot, textvariable=self.status, bg=C["bg"], fg=C["muted"],
                 font=(FONT, 9), anchor="w", justify="left",
                 wraplength=700).pack(side="left", pady=4)
        ttk.Button(foot, text="关闭", style="Ghost.TButton",
                   command=self.close).pack(side="right")

        self.body = tk.Frame(wrap, bg=C["bg"])
        self.body.pack(fill="both", expand=True, pady=(10, 0))
        self._panels["rename"] = self._build_rename(self.body)
        self._panels["convert"] = self._build_convert(self.body)
        self._panels["organize"] = self._build_organize(self.body)

        self.tree = ttk.Treeview(self.body, columns=("from", "to", "state"),
                                 show="headings", height=9, selectmode="browse")
        for col, head, width in (("from", "原文件", 340), ("to", "新名字 / 去向", 320),
                                 ("state", "状态", 220)):
            self.tree.heading(col, text=head)
            self.tree.column(col, width=width, anchor="w")
        self.tree.tag_configure("ok", foreground=C["green"])
        self.tree.tag_configure("skip", foreground=C["sub"])
        self.tree.tag_configure("fail", foreground=C["red"])

    def _form(self, parent):
        box = tk.Frame(parent, bg=C["card"], highlightthickness=1,
                       highlightbackground=C["line"])
        box.pack(fill="x")
        return box

    def _entry(self, parent, row, col, var, width=14):
        e = tk.Entry(parent, textvariable=var, width=width, relief="flat",
                     bd=0, bg=C["surface_alt"], fg=C["text"], font=(FONT, 9),
                     insertbackground=C["text"])
        e.grid(row=row, column=col, sticky="w", padx=(0, 14), pady=5, ipady=4)
        return e

    def _label(self, parent, row, col, text, color="sub"):
        tk.Label(parent, text=text, bg=C["card"], fg=C[color], font=(FONT, 9),
                 anchor="w").grid(row=row, column=col, sticky="w", padx=(12, 8),
                                  pady=5)

    def _build_rename(self, parent):
        box = self._form(parent)
        self.v_prefix = tk.StringVar()
        self.v_suffix = tk.StringVar()
        self.v_seq = tk.BooleanVar(value=True)
        self.v_start = tk.StringVar(value="1")
        self.v_step = tk.StringVar(value="1")
        self.v_pad = tk.StringVar(value="2")
        self.v_pos = tk.StringVar(value="末尾")
        self.v_re = tk.BooleanVar(value=False)
        self.v_pattern = tk.StringVar()
        self.v_repl = tk.StringVar()
        self.v_sort = tk.StringVar(value="按文件名")

        self._label(box, 0, 0, "前缀")
        self._entry(box, 0, 1, self.v_prefix, 18)
        self._label(box, 0, 2, "后缀")
        self._entry(box, 0, 3, self.v_suffix, 18)
        self._label(box, 0, 4, "支持 {date} {name} {n}")

        tk.Checkbutton(box, text="加序号", variable=self.v_seq, bg=C["card"],
                       fg=C["text"], activebackground=C["card"], font=(FONT, 9),
                       selectcolor=C["card"], bd=0,
                       highlightthickness=0).grid(row=1, column=0, sticky="w",
                                                   padx=(12, 0), pady=5)
        seq = tk.Frame(box, bg=C["card"])
        seq.grid(row=1, column=1, columnspan=4, sticky="w")
        for text, var, width in (("起始", self.v_start, 5), ("步长", self.v_step, 4),
                                 ("位数", self.v_pad, 3)):
            tk.Label(seq, text=text, bg=C["card"], fg=C["sub"],
                     font=(FONT, 9)).pack(side="left", padx=(0, 4))
            tk.Entry(seq, textvariable=var, width=width, relief="flat", bd=0,
                     bg=C["surface_alt"], fg=C["text"], font=(FONT, 9),
                     insertbackground=C["text"]).pack(side="left", padx=(0, 12),
                                                      ipady=4)
        tk.Label(seq, text="位置", bg=C["card"], fg=C["sub"],
                 font=(FONT, 9)).pack(side="left", padx=(0, 4))
        ttk.Combobox(seq, textvariable=self.v_pos, width=6, state="readonly",
                     values=("末尾", "开头", "只用序号")).pack(side="left")

        tk.Checkbutton(box, text="正则替换", variable=self.v_re, bg=C["card"],
                       fg=C["text"], activebackground=C["card"], font=(FONT, 9),
                       selectcolor=C["card"], bd=0,
                       highlightthickness=0).grid(row=2, column=0, sticky="w",
                                                   padx=(12, 0), pady=5)
        re_box = tk.Frame(box, bg=C["card"])
        re_box.grid(row=2, column=1, columnspan=4, sticky="w")
        self._entry(re_box, 0, 0, self.v_pattern, 22)
        tk.Label(re_box, text="→", bg=C["card"], fg=C["sub"],
                 font=(FONT, 9)).grid(row=0, column=1, padx=(0, 6))
        self._entry(re_box, 0, 2, self.v_repl, 18)
        tk.Label(re_box, text="作用在去扩展名的主干上", bg=C["card"], fg=C["sub"],
                 font=(FONT, 9)).grid(row=0, column=3, sticky="w")

        self._label(box, 3, 0, "排序")
        ttk.Combobox(box, textvariable=self.v_sort, width=10, state="readonly",
                     values=("按文件名", "按修改时间")).grid(
            row=3, column=1, sticky="w", pady=(2, 10))

        tools = tk.Frame(box, bg=C["card"])
        tools.grid(row=4, column=0, columnspan=5, sticky="w", padx=12, pady=(0, 12))
        ttk.Button(tools, text="预览改名结果", style="Ghost.TButton",
                   command=self.do_rename_preview).pack(side="left")
        ttk.Button(tools, text="执行重命名", style="Accent.TButton",
                   command=self.do_rename_apply).pack(side="left", padx=8)
        ttk.Button(tools, text="撤销上次改名", style="Ghost.TButton",
                   command=self.do_rename_undo).pack(side="left")
        return box

    def _build_convert(self, parent):
        box = self._form(parent)
        self.v_fmt = tk.StringVar(value="JPEG")
        self.QUALITY = {"高（92）": 92, "标准（88）": 88, "紧凑（80）": 80}
        self.v_quality_name = tk.StringVar(value="标准（88）")
        self.v_keep = tk.BooleanVar(value=True)

        self._label(box, 0, 0, "目标格式")
        ttk.Combobox(box, textvariable=self.v_fmt, width=8, state="readonly",
                     values=("JPEG", "PNG", "WEBP")).grid(row=0, column=1,
                                                          sticky="w", pady=(10, 5))
        self._label(box, 0, 2, "质量")
        ttk.Combobox(box, textvariable=self.v_quality_name, width=12,
                     state="readonly",
                     values=tuple(self.QUALITY)).grid(row=0, column=3, sticky="w",
                                                      pady=(10, 5))
        tk.Label(box, text="只对 JPEG / WEBP 生效，PNG 走无损。", bg=C["card"],
                 fg=C["sub"], font=(FONT, 9)).grid(row=0, column=4, sticky="w",
                                                   padx=(10, 0))
        tk.Checkbutton(box, text="保留原件（默认保留，只新增转换后的文件）",
                       variable=self.v_keep, bg=C["card"], fg=C["text"],
                       activebackground=C["card"], font=(FONT, 9),
                       selectcolor=C["card"], bd=0, highlightthickness=0).grid(
            row=1, column=0, columnspan=4, sticky="w", padx=12, pady=(0, 6))
        tk.Label(box, text="结果放回同一目录；已有同名文件自动加序号，不覆盖。",
                 bg=C["card"], fg=C["sub"], font=(FONT, 9), anchor="w").grid(
            row=2, column=0, columnspan=5, sticky="w", padx=12, pady=(0, 8))

        tools = tk.Frame(box, bg=C["card"])
        tools.grid(row=3, column=0, columnspan=5, sticky="w", padx=12, pady=(0, 12))
        ttk.Button(tools, text="预览转换清单", style="Ghost.TButton",
                   command=self.do_convert_preview).pack(side="left")
        ttk.Button(tools, text="开始转换", style="Accent.TButton",
                   command=self.do_convert_apply).pack(side="left", padx=8)
        return box

    def _build_organize(self, parent):
        box = self._form(parent)
        tk.Label(box, text="已登记的文件按台账类别移入「归档根 / 类别 /」；"
                           "台账里查不到的文件原样跳过，不会乱放。",
                 bg=C["card"], fg=C["text"], font=(FONT, 9), anchor="w",
                 wraplength=820, justify="left").pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(box, text="移动前后都会同步台账里的归档路径；文件名冲突自动加序号。",
                 bg=C["card"], fg=C["sub"], font=(FONT, 9), anchor="w",
                 wraplength=820, justify="left").pack(fill="x", padx=12, pady=(0, 8))
        tools = tk.Frame(box, bg=C["card"])
        tools.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(tools, text="预览归位方案", style="Ghost.TButton",
                   command=self.do_organize_preview).pack(side="left")
        ttk.Button(tools, text="执行归位", style="Accent.TButton",
                   command=self.do_organize_apply).pack(side="left", padx=8)
        return box

    # ---------- 页签切换 ----------
    def _switch(self, key):
        self.tab = key
        for name, panel in self._panels.items():
            if name == key:
                panel.pack(fill="x")
                self.tree.pack_forget()
                self.tree.pack(fill="both", expand=True, pady=(10, 0))
            else:
                panel.pack_forget()
        for name, btn in self._tab_buttons.items():
            active = name == key
            btn.configure(bg=C["primary_soft"] if active else C["bg"],
                          fg=C["primary"] if active else C["muted"])
        self._render(self.rows.get(key, []))

    # ---------- 预览渲染 ----------
    def _render(self, rows):
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            src = os.path.basename(row.get("src") or "")
            dst = row.get("new") or ""
            if not dst and row.get("dst"):
                try:
                    dst = os.path.relpath(row["dst"], archive.root())
                except Exception:
                    dst = os.path.basename(row["dst"])
            if row.get("state") == "ok":
                state = "待执行" + ("（%s）" % row["reason"] if row.get("reason") else "")
                tag = "ok"
            elif row.get("state") == "fail":
                state, tag = row.get("reason") or "不能用", "fail"
            else:
                state, tag = row.get("reason") or "跳过", "skip"
            self.tree.insert("", "end", values=(src, dst or "—", state), tags=(tag,))

    def _need_paths(self):
        if self.paths:
            return True
        messagebox.showinfo("文件工具", "先选中文件再来。文件列表支持 Ctrl / Shift 多选，"
                                        "也可以切进某个目录，对整目录操作。",
                            parent=self.top)
        return False

    # ---------- 重命名 ----------
    def _rename_opts(self):
        pos = {"末尾": "after", "开头": "before", "只用序号": "replace"}.get(
            self.v_pos.get(), "after")
        return {
            "prefix": self.v_prefix.get(), "suffix": self.v_suffix.get(),
            "replace": self.v_re.get(), "pattern": self.v_pattern.get(),
            "repl": self.v_repl.get(),
            "seq": self.v_seq.get(), "seq_start": self.v_start.get(),
            "seq_step": self.v_step.get(), "seq_pad": self.v_pad.get(),
            "seq_pos": pos,
            "sort": "mtime" if self.v_sort.get() == "按修改时间" else "name",
        }

    def do_rename_preview(self):
        if not self._need_paths():
            return
        plan = filetools.rename_plan(self.paths, self._rename_opts())
        self.rows["rename"] = plan["rows"]
        self.undo = []
        self._render(plan["rows"])
        self.status.set("预览：" + filetools.summarize(plan["rows"]) +
                        "。确认没问题再执行。")

    def do_rename_apply(self):
        rows = self.rows.get("rename") or []
        pending = [r for r in rows if r.get("state") == "ok"]
        if not pending:
            self.status.set("没有可执行的条目，先点「预览改名结果」。")
            return
        if not messagebox.askyesno(
                "执行重命名",
                "将改 %d 个文件的名字，动作会记进日志；改错了可以点「撤销上次改名」。\n继续？"
                % len(pending), parent=self.top):
            return
        result = filetools.rename_apply(rows)
        self.undo = result["undo"]
        pairs = [(item["to"], item["from"]) for item in self.undo]
        self._sync_docs(pairs)
        self._log("重命名", "%d 个文件%s" % (result["ok"],
                     "：" + os.path.basename(pending[0]["old"]) if pending else ""))
        self.rows["rename"] = []
        self._render([])
        text = "已改名 %d 个" % result["ok"]
        if self.undo:
            text += "，可撤销"
        if result["failed"]:
            text += "；失败 %d 个：%s" % (
                len(result["failed"]), result["failed"][0]["reason"])
        self.status.set(text + "。")
        self._after_write()

    def do_rename_undo(self):
        if not self.undo:
            self.status.set("没有可撤销的改名记录（本窗口只在执行成功后保留一次）。")
            return
        result = filetools.undo_apply(self.undo)
        pairs = [(item["from"], item["to"]) for item in self.undo]
        # 撤销后路径回到原处，台账也跟回去
        self._sync_docs([(dst, src) for src, dst in pairs])
        self._log("撤销改名", "%d 个文件" % result["ok"])
        self.undo = []
        self.status.set("已撤回 %d 个%s。" % (
            result["ok"], "；%d 个没撤回成功" % len(result["failed"]) if result["failed"] else ""))
        self._render([])
        self._after_write()

    # ---------- 转换 ----------
    def _quality(self):
        return self.QUALITY.get(self.v_quality_name.get(), 88)

    def do_convert_preview(self):
        if not self._need_paths():
            return
        plan = filetools.convert_plan(self.paths, self.v_fmt.get())
        self.rows["convert"] = plan["rows"]
        self._render(plan["rows"])
        self.status.set("预览：" + filetools.summarize(plan["rows"]) +
                        "（%s）。转换会新增文件，原件按勾选处理。" % plan["target"])

    def do_convert_apply(self):
        rows = self.rows.get("convert") or []
        pending = [r for r in rows if r.get("state") == "ok"]
        if not pending:
            self.status.set("没有可转换的条目，先点「预览转换清单」。")
            return
        keep = self.v_keep.get()
        if not messagebox.askyesno(
                "开始转换",
                "将转换 %d 个图片为 %s，原件%s。继续？"
                % (len(pending), self.v_fmt.get(), "保留" if keep else "转换成功后删除"),
                parent=self.top):
            return
        result = filetools.convert_apply(rows, quality=self._quality(),
                                         delete_original=not keep)
        self._log("格式转换", "%d 个文件转 %s" % (result["ok"], self.v_fmt.get()))
        text = "已转换 %d 个" % result["ok"]
        if result["failed"]:
            text += "；失败 %d 个：%s" % (len(result["failed"]), result["failed"][0]["reason"])
        self.status.set(text + "。")
        self.rows["convert"] = []
        self._render([])
        self._after_write()

    # ---------- 归位 ----------
    def do_organize_preview(self):
        if not self._need_paths():
            return
        plan = filetools.organize_plan(self.paths, self.repo.list_docs())
        self.rows["organize"] = plan["rows"]
        self._render(plan["rows"])
        self.status.set("预览：" + filetools.summarize(plan["rows"]) +
                        "。去向按台账类别算，无需手填。")

    def do_organize_apply(self):
        rows = self.rows.get("organize") or []
        pending = [r for r in rows if r.get("state") == "ok"]
        if not pending:
            self.status.set("没有可归位的条目，先点「预览归位方案」。")
            return
        if not messagebox.askyesno("执行归位",
                                   "将移动 %d 个文件到对应类别目录，台账路径会同步。继续？"
                                   % len(pending), parent=self.top):
            return
        result = filetools.organize_apply(rows)
        moved = [(item["src"], item["dst"]) for item in result["done"]]
        self._sync_docs(moved)
        self._log("按类别归位", "%d 个文件" % result["ok"])
        text = "已归位 %d 个" % result["ok"]
        if result["failed"]:
            text += "；失败 %d 个：%s" % (len(result["failed"]), result["failed"][0]["reason"])
        self.status.set(text + "。")
        self.rows["organize"] = []
        self._render([])
        self._after_write()

    # ---------- 台账与日志 ----------
    def _who(self):
        return getattr(self.window, "operator_name", "") or ""

    def _role(self):
        try:
            return self.window.role_label()
        except Exception:
            return ""

    def _sync_docs(self, pairs):
        """文件位置变了，台账里的路径跟着变，别让台账指向不存在的旧路径。"""
        if not pairs:
            return
        try:
            maps = fileroom.doc_maps(self.repo.list_docs())
        except Exception:
            return
        for old, new in pairs:
            doc = maps["paths"].get(fileroom.norm(old))
            if not doc:
                continue
            try:
                self.repo.set_arch(doc.get("id"), new, actor=self._who(),
                                   role=self._role())
            except Exception:
                continue

    def _log(self, act, obj):
        try:
            self.repo.add_log(act, obj, self._who(), self._role())
        except Exception:
            pass

    def _after_write(self):
        """改完文件把索引 CSV 重写一遍，免得文件室立刻提示「索引待修」。"""
        try:
            archive.write_index(self.repo.list_docs())
        except Exception:
            pass
        if callable(self.on_done):
            try:
                self.on_done()
            except Exception:
                pass

    def close(self):
        self.top.destroy()


def open_tools(parent, repo, window, paths, source_label="", on_done=None):
    """给文件室 view 留一个函数入口，避免各处重复构造。"""
    return FileToolsDialog(parent, repo, window, paths, source_label, on_done)

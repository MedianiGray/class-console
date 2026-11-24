# -*- coding: utf-8 -*-
"""文件室：目录树 + 文件列表 + 预览 + 缺失反查 + 拖入登记。

界面只做三件事：
  1. 让人看见文件到底在哪（目录树与位置列）；
  2. 选中文件就能预览，并知道它对应哪条材料；
  3. 缺失文件能直接反查责任学生，拖入文件能落位并登记。

索引与台账不一致时不静默改数据，只在底部提示，修复仍走完整性检查。
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import archive
import audit
import fileroom
import thumbs
from theme import FONT, C
from ui_empty import EmptyState

try:
    from PIL import Image, ImageTk
except Exception:  # 打包环境缺少 Pillow 时仍可运行，只是不显示图片缩略图
    Image = ImageTk = None


class FileRoomView(ttk.Frame):
    COLS = ("name", "size", "mtime", "where", "state", "code")
    HEADS = {"name": "文件 / 材料", "size": "大小", "mtime": "修改时间",
             "where": "位置", "state": "状态", "code": "编号"}
    WIDTHS = {"name": 210, "size": 62, "mtime": 108, "where": 150,
              "state": 64, "code": 84}
    CATS = ["团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]

    def __init__(self, master, repo, window):
        super().__init__(master)
        self.repo = repo
        self.window = window
        self.rel = ""
        self.maps = {"docs": {"paths": {}, "codes": {}},
                     "index": {"paths": {}, "codes": {}}, "missing": []}
        self._dir_iids = {}
        self._files = {}
        self._preview_photo = None
        self.q = tk.StringVar()
        self._build()

    # ---------- 搭界面 ----------
    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(4, 8))
        ttk.Button(top, text="选择文件登记", style="Accent.TButton",
                   command=self.pick_files).pack(side="left")
        ttk.Button(top, text="刷新", style="Ghost.TButton",
                   command=self.refresh).pack(side="left", padx=(8, 0))
        self.btn_missing = ttk.Button(top, text="缺失文件 0", style="Ghost.TButton",
                                      command=self.open_missing)
        self.btn_missing.pack(side="left", padx=(8, 0))
        ttk.Button(top, text="打开归档根", style="Ghost.TButton",
                   command=self.open_root).pack(side="left", padx=(8, 0))

        tk.Label(top, text="搜索", bg=C["bg"], fg=C["muted"],
                 font=(FONT, 9)).pack(side="left", padx=(18, 6))
        ent = ttk.Entry(top, textvariable=self.q, width=22)
        ent.pack(side="left")
        ent.bind("<KeyRelease>", lambda e: self._load_files())
        ent.bind("<Return>", lambda e: self._load_files())
        self.search_entry = ent

        crumb = tk.Frame(self, bg=C["bg"])
        crumb.pack(fill="x", padx=18, pady=(0, 8))
        self.crumb = tk.Label(crumb, text="", bg=C["bg"], fg=C["muted"],
                              font=(FONT, 9), anchor="w")
        self.crumb.pack(side="left", fill="x", expand=True)
        self.btn_up = ttk.Button(crumb, text="上一级", style="Ghost.TButton",
                                 command=self.go_up)
        self.btn_up.pack(side="right")

        body = tk.PanedWindow(self, orient="horizontal", bg=C["bg"],
                              bd=0, sashwidth=6, showhandle=False)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.paned = body

        left = tk.Frame(body, bg=C["card"], highlightthickness=1,
                        highlightbackground=C["line"])
        body.add(left, minsize=176, width=206)
        head = tk.Frame(left, bg=C["card"])
        head.pack(fill="x", padx=10, pady=(9, 4))
        tk.Label(head, text="归档目录", bg=C["card"], fg=C["text"],
                 font=(FONT, 10, "bold"), anchor="w").pack(side="left")
        self.dir_count = tk.Label(head, text="", bg=C["card"], fg=C["sub"],
                                  font=(FONT, 8))
        self.dir_count.pack(side="right")
        wrap = tk.Frame(left, bg=C["card"])
        wrap.pack(fill="both", expand=True)
        self.tree_dirs = ttk.Treeview(wrap, show="tree", selectmode="browse")
        self.tree_dirs.tag_configure("root", foreground=C["primary"])
        self.tree_dirs.tag_configure("sub", foreground=C["muted"])
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree_dirs.yview)
        self.tree_dirs.configure(yscrollcommand=ysb.set)
        self.tree_dirs.pack(side="left", fill="both", expand=True, padx=(4, 0),
                            pady=(0, 4))
        ysb.pack(side="right", fill="y", pady=(0, 4))
        self.tree_dirs.bind("<<TreeviewSelect>>", self._on_dir)

        center = tk.Frame(body, bg=C["card"], highlightthickness=1,
                          highlightbackground=C["line"])
        body.add(center, minsize=360, width=520)
        cw = tk.Frame(center, bg=C["card"])
        cw.pack(fill="both", expand=True, padx=1, pady=1)
        self.files = ttk.Treeview(cw, columns=self.COLS, show="headings",
                                  selectmode="browse")
        for c in self.COLS:
            self.files.heading(c, text=self.HEADS[c], anchor="w")
            self.files.column(c, width=self.WIDTHS[c], minwidth=56, anchor="w",
                              stretch=(c == "name"))
        self.files.tag_configure("zebra", background=C["zebra"])
        self.files.tag_configure("unreg", foreground=C["muted"])
        self.files.tag_configure("onlyidx", foreground=C["orange"])
        fys = ttk.Scrollbar(cw, orient="vertical", command=self.files.yview)
        self.files.configure(yscrollcommand=fys.set)
        self.files.pack(side="left", fill="both", expand=True)
        fys.pack(side="right", fill="y")
        fxs = ttk.Scrollbar(cw, orient="horizontal", command=self.files.xview)
        self.files.configure(xscrollcommand=fxs.set)
        self.fxs = fxs
        self.files.bind("<<TreeviewSelect>>", self._on_file)
        self.files.bind("<Double-1>", lambda e: self.open_selected())
        self.files.bind("<Configure>", self._fit_columns)
        self.empty = EmptyState(cw, wraplength=400)

        right = tk.Frame(body, bg=C["card"], highlightthickness=1,
                         highlightbackground=C["line"])
        body.add(right, minsize=270, width=330)
        self._build_preview(right)

        bottom = tk.Frame(self, bg=C["bg"])
        bottom.pack(fill="x", padx=18, pady=(0, 10))
        self.sync_btn = tk.Button(bottom, text="索引检查中…", relief="flat", bd=0,
                                  bg=C["bg"], fg=C["sub"], font=(FONT, 9),
                                  anchor="w", padx=0, pady=2, cursor="hand2",
                                  activebackground=C["bg"], activeforeground=C["text"],
                                  command=self.open_integrity)
        self.sync_btn.pack(side="left")
        self.hint = ttk.Label(bottom, text="", style="Muted.TLabel")
        self.hint.pack(side="left", padx=(18, 0))
        tk.Label(bottom, text="可直接把文件拖进窗口，落到当前目录并登记为待审核材料",
                 bg=C["bg"], fg=C["sub"], font=(FONT, 8)).pack(side="right")

    def _build_preview(self, parent):
        head = tk.Frame(parent, bg=C["card"])
        head.pack(fill="x", padx=14, pady=(12, 2))
        tk.Label(head, text="预览", bg=C["card"], fg=C["sub"],
                 font=(FONT, 9), anchor="w").pack(side="left")
        self.preview_state = tk.Label(head, text="", bg=C["card"], fg=C["sub"],
                                      font=(FONT, 9), anchor="e")
        self.preview_state.pack(side="right")
        self.preview_title = tk.Label(parent, text="选中一个文件",
                                      bg=C["card"], fg=C["text"],
                                      font=(FONT, 13, "bold"), anchor="w",
                                      justify="left", wraplength=292)
        self.preview_title.pack(fill="x", padx=14, pady=(2, 0))
        self.preview_meta = tk.Label(parent, text="", bg=C["card"], fg=C["sub"],
                                     font=(FONT, 9), anchor="w", justify="left",
                                     wraplength=292)
        self.preview_meta.pack(fill="x", padx=14, pady=(3, 8))
        self.preview_body = tk.Frame(parent, bg=C["surface_alt"], height=250)
        self.preview_body.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self.preview_body.pack_propagate(False)
        self.preview_actions = tk.Frame(parent, bg=C["card"])
        self.preview_actions.pack(fill="x", padx=14, pady=(0, 12))
        self._placeholder("选中文件看预览", "图片、PDF 首页、文本前 200 字都会显示在这里。")

    # ---------- 数据 ----------
    def refresh(self):
        base = archive.root()
        docs = self.repo.list_docs()
        self._doc_count = len(docs)
        self.maps = fileroom.build_status(docs, base)
        self._build_tree()
        self._load_files()
        missing = len(self.maps["missing"])
        self.btn_missing.config(text="缺失文件 %d" % missing,
                                style="Danger.TButton" if missing else "Ghost.TButton")
        try:
            check = audit.check_integrity(docs, base)
            issues = check["issues"]
        except Exception:
            issues = missing
        if issues:
            self.sync_btn.config(text="索引待修 %d 项 · 点开完整性检查" % issues,
                                 fg=C["orange"])
        else:
            self.sync_btn.config(text="索引、台账与磁盘一致", fg=C["green"])
        self.hint.config(text="%d 个目录 · 当前 %d 个文件 · %d 条材料" % (
            len(self._dir_iids) - 1, len(self._files) if self._files else 0,
            len(docs)))
        self.files.after(80, self._fit_columns)

    def _build_tree(self):
        base = archive.root()
        self.tree_dirs.delete(*self.tree_dirs.get_children())
        self._dir_iids = {}
        label = "归档根"
        self.tree_dirs.insert("", "end", iid="root", text="  " + label,
                              open=True, tags=("root",))
        self._dir_iids[""] = "root"
        dirs = fileroom.tree_dirs(base)
        for d in dirs:
            parent = self._dir_iids.get(d["parent"], "root")
            icon = "▸" if d["depth"] == 1 else "↳" if d["depth"] == 2 else "·"
            label = d["name"]
            head, sep, who = label.partition("-")
            if sep and head.isdigit() and d["depth"] == 2:
                label = who
            iid = "d%06d" % (len(self._dir_iids))
            self.tree_dirs.insert(parent, "end", iid=iid,
                                  text="%s %s" % (icon, label))
            self._dir_iids[d["rel"]] = iid
        self.dir_count.config(text="%d" % max(0, len(self._dir_iids) - 1))
        iid = self._dir_iids.get(self.rel, "root")
        try:
            self.tree_dirs.selection_set(iid)
            self.tree_dirs.see(iid)
        except tk.TclError:
            pass

    def _on_dir(self, _event=None):
        iid = self.tree_dirs.focus()
        rel = next((r for r, i in self._dir_iids.items() if i == iid), None)
        if rel is None:
            return
        self.rel = rel
        self._load_files()

    def _fit_columns(self, _event=None):
        """窄窗口先保文件名与登记状态，放得下再补编号、时间和位置。"""
        if self.q.get().strip():
            self.files.configure(displaycolumns=self.COLS)
            if not self.fxs.winfo_ismapped():
                self.fxs.pack(side="bottom", fill="x")
            return
        if self.fxs.winfo_ismapped():
            self.fxs.pack_forget()
        width = self.files.winfo_width()
        if width < 425:
            cols = ("name", "size", "state")
        elif width < 600:
            cols = ("name", "size", "state", "code")
        else:
            cols = ("name", "size", "mtime", "state", "code")
        self.files.configure(displaycolumns=cols)

    def _load_files(self):
        base = archive.root()
        q = self.q.get().strip()
        rows = fileroom.list_files(base, self.rel, q)
        self.files.delete(*self.files.get_children())
        self._fit_columns()
        self._files = {}
        for i, row in enumerate(rows):
            st = fileroom.file_status(row["path"], self.maps)
            tags = ["zebra"] if i % 2 else []
            if st["state"] == "未登记":
                tags.append("unreg")
            elif st["state"] == "仅索引":
                tags.append("onlyidx")
            label = row["name"]
            if st.get("label"):
                ext = os.path.splitext(row["name"])[1]
                label = st["label"] + ext
            iid = "f%06d" % i
            self.files.insert("", "end", iid=iid, tags=tuple(tags), values=(
                label, fileroom.human_size(row["size"]),
                fileroom.human_time(row["mtime"]),
                row["rel"], st["state"], st["code"]))
            self._files[iid] = (row, st)
        if q:
            self.crumb.config(text="全库搜索：%s · 命中 %d 个文件" % (q, len(rows)))
        elif self.rel:
            self.crumb.config(text="归档根 / " + self.rel.replace("/", " / "))
        else:
            self.crumb.config(text="归档根 / " + base.name)
        self.btn_up.config(state="normal" if self.rel else "disabled")
        self.hint.config(text="%d 个目录 · 当前 %d 个文件 · %d 条材料" % (
            max(0, len(self._dir_iids) - 1), len(rows),
            getattr(self, "_doc_count", 0)))
        if rows:
            self.empty.hide()
        elif q:
            self.empty.set("全库里没有匹配的文件",
                           "没有找到包含「%s」的文件；换个关键词，或清空搜索再试。" % q,
                           "清空搜索", self.clear_search)
            self.empty.show_place(relx=0.5, rely=0.42)
        else:
            if self.window.can("docs:create"):
                self.empty.set("这一层还没有文件",
                               "把材料拖进窗口，或点「选择文件登记」，落到当前目录并登记为待审核材料。",
                               "选择文件登记", self.pick_files)
            else:
                self.empty.set("这一层还没有文件",
                               "当前岗位只能查看；切换到经办人岗位后可登记文件。",
                               "切换岗位", lambda: self.window._role_menu())
            self.empty.show_place(relx=0.5, rely=0.42)
        self._placeholder("选中文件看预览", "图片、PDF 首页、文本前 200 字都会显示在这里。")

    def go_up(self):
        if not self.rel:
            return
        parts = fileroom.split_rel(self.rel)
        self.rel = "/".join(parts[:-1])
        self._build_tree()
        self._load_files()

    def reveal_path(self, path):
        """从台账或缺失清单跳进来：展开所在目录并选中文件。"""
        base = archive.root()
        p = str(path or "").strip()
        if not p or not os.path.exists(p):
            self.window.toast("文件不在本机，无法在文件室定位")
            return
        try:
            relp = os.path.relpath(p, str(base)).replace("\\", "/")
        except ValueError:
            self.window.toast("该文件不在归档目录内")
            archive.reveal(p)
            return
        if relp.startswith(".."):
            self.window.toast("该文件不在归档目录内，已在系统中定位")
            archive.reveal(p)
            return
        self.q.set("")
        self.rel = os.path.dirname(relp).replace("\\", "/")
        self._build_tree()
        self._load_files()
        target = os.path.basename(relp)
        for iid, (row, _st) in self._files.items():
            if row["name"] == target:
                self.files.selection_set(iid)
                self.files.focus(iid)
                self.files.see(iid)
                self._on_file()
                return

    # ---------- 预览 ----------
    def _placeholder(self, title, body):
        self._preview_photo = None
        self.preview_title.config(text=title)
        self.preview_meta.config(text="")
        self.preview_state.config(text="")
        for w in self.preview_body.winfo_children():
            w.destroy()
        for w in self.preview_actions.winfo_children():
            w.destroy()
        tk.Label(self.preview_body, text="▧", bg=C["surface_alt"], fg=C["sub"],
                 font=(FONT, 34)).pack(pady=(46, 6))
        tk.Label(self.preview_body, text=body, bg=C["surface_alt"], fg=C["muted"],
                 font=(FONT, 9), wraplength=270, justify="center").pack(padx=16)

    def _on_file(self, _event=None):
        iid = self.files.focus()
        if not iid or iid not in self._files:
            return
        row, st = self._files[iid]
        self._render_preview(row, st)

    def _render_preview(self, row, st):
        self._preview_photo = None
        for w in self.preview_body.winfo_children():
            w.destroy()
        for w in self.preview_actions.winfo_children():
            w.destroy()
        self.preview_title.config(text=row["name"])
        meta = "%s · %s" % (fileroom.human_size(row["size"]),
                            fileroom.human_time(row["mtime"]))
        if st["label"]:
            meta += "\n材料：%s" % st["label"]
        if st["who"] or st["sid"]:
            meta += "\n学生：%s %s" % (st["who"] or "—", st["sid"] or "")
        self.preview_meta.config(text=meta + "\n" + row["rel"])
        self.preview_state.config(
            text=st["state"], fg=(C["green"] if st["state"] == "台账有"
                                  else C["orange"] if st["state"] == "仅索引"
                                  else C["muted"]))

        kind = fileroom.preview_kind(row["path"])
        if kind == "text":
            text = fileroom.read_text(row["path"], 200)
            box = tk.Text(self.preview_body, height=8, wrap="word", bd=0,
                          relief="flat", bg=C["surface_alt"], fg=C["text"],
                          font=(FONT, 9), padx=10, pady=10,
                          highlightthickness=0)
            box.pack(fill="both", expand=True)
            box.insert("1.0", text or "（空文件）")
            box.config(state="disabled")
        elif kind == "image":
            photo = self._image_photo(row["path"])
            if photo is not None:
                self._preview_photo = photo
                tk.Label(self.preview_body, image=photo, bg=C["surface_alt"]).pack(
                    expand=True, padx=8, pady=8)
            else:
                self._preview_fallback("图片预览不可用", row["path"])
        elif kind == "pdf":
            photo = self._shell_photo(row["path"])
            if photo is not None:
                self._preview_photo = photo
                tk.Label(self.preview_body, image=photo, bg=C["surface_alt"]).pack(
                    expand=True, padx=8, pady=8)
            else:
                self._preview_fallback("PDF 首页预览未生成", row["path"])
        else:
            self._preview_fallback("这类文件不做内嵌预览", row["path"])

        ttk.Button(self.preview_actions, text="在资源管理器打开",
                   style="Ghost.TButton", command=lambda p=row["path"]: archive.reveal(p)).pack(
            side="left")
        if st["code"] and st["state"] == "台账有":
            ttk.Button(self.preview_actions, text="去台账",
                       command=lambda c=st["code"]: self.window.goto_doc(c)).pack(
                side="right")
        elif st["state"] == "未登记":
            ttk.Button(self.preview_actions, text="登记这份文件",
                       style="Accent.TButton",
                       command=lambda p=row["path"]: self.open_register([p])).pack(
                side="right")
        else:
            ttk.Button(self.preview_actions, text="重建索引",
                       command=self.open_integrity).pack(side="right")

    def _preview_fallback(self, title, path):
        tk.Label(self.preview_body, text="▤", bg=C["surface_alt"], fg=C["sub"],
                 font=(FONT, 32)).pack(pady=(42, 4))
        tk.Label(self.preview_body, text=title, bg=C["surface_alt"], fg=C["text"],
                 font=(FONT, 10, "bold")).pack()
        tk.Label(self.preview_body,
                 text="点下方「在资源管理器打开」，用系统默认程序查看。",
                 bg=C["surface_alt"], fg=C["muted"], font=(FONT, 9),
                 wraplength=270, justify="center").pack(padx=12, pady=(4, 0))
        tk.Label(self.preview_body, text=os.path.splitext(path)[1].upper() or "文件",
                 bg=C["surface_alt"], fg=C["sub"], font=(FONT, 8)).pack(pady=(6, 0))

    def _image_photo(self, path):
        if Image is None or ImageTk is None:
            return None
        try:
            img = Image.open(path)
            img.thumbnail((280, 250))
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _shell_photo(self, path):
        if ImageTk is None:
            return None
        try:
            img = thumbs.shell_thumbnail(path, 300)
            if img is None:
                return None
            img.thumbnail((290, 250))
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    # ---------- 操作 ----------
    def open_root(self):
        base = archive.root()
        if not base.exists():
            self.window.toast("归档根还不存在，先在设置里选一个目录")
            return
        archive.open_folder(base)

    def open_selected(self):
        iid = self.files.focus()
        if iid in self._files:
            archive.open_file(self._files[iid][0]["path"])

    def open_integrity(self):
        from ui_audit import open_integrity
        open_integrity(self, self.repo, self.window, on_done=self.refresh)

    def clear_search(self):
        self.q.set("")
        self._load_files()
        self.search_entry.focus_set()

    def pick_files(self):
        paths = filedialog.askopenfilenames(title="选择要登记进文件室的文件")
        if paths:
            self.open_register(list(paths))

    def open_register(self, paths):
        return RegisterDialog(self, self.repo, self.window, paths,
                              current_rel=self.rel, on_done=self.refresh)

    def accept_drop(self, paths):
        """主窗口拖入回调：当前目录信息完整就直接落位入账，否则弹确认。"""
        if not self.window.can("docs:archive"):
            self.window.toast("当前视角无权登记文件")
            return
        clean = [p for p in paths if os.path.exists(p)]
        if not clean:
            self.window.toast("拖入的文件都不在本机")
            return
        ctx = fileroom.infer_context(self.rel, self.repo.list_roster())
        if not ctx["complete"]:
            self.open_register(clean)
            return
        try:
            res = fileroom.register_files(
                self.repo, clean, base=archive.root(), rel=self.rel,
                cat=ctx["cat"], sid=ctx["sid"], who=ctx["who"],
                actor=self.window.operator_name, role=self.window.role_label(),
                note="文件室拖入")
            if res["ok"]:
                audit.rebuild_index(self.repo.list_docs(), archive.root())
        except Exception as e:
            messagebox.showerror("登记失败", str(e), parent=self)
            return
        if res["failed"]:
            messagebox.showwarning(
                "部分文件未登记",
                "成功 %d 份，失败 %d 份。\n\n%s" % (
                    res["ok"], len(res["failed"]),
                    "\n".join("- %s：%s" % (f["name"], f["detail"])
                              for f in res["failed"][:8])),
                parent=self)
        self.window.refresh_all()
        self.window.toast("已登记 %d 份到 %s · %s" % (res["ok"], ctx["who"], ctx["cat"]))

    def open_missing(self):
        return MissingDialog(self, self.repo, self.window,
                             on_done=self.refresh)


class RegisterDialog:
    """拖入 / 选择文件后的登记确认；字段尽量从当前目录与名单里带出。"""

    CATS = ["团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]

    def __init__(self, parent, repo, window, paths, current_rel="", on_done=None):
        self.repo = repo
        self.window = window
        self.paths = fileroom.expand_paths(paths)
        self.base = archive.root()
        self.current_rel = current_rel
        self.on_done = on_done
        ctx = fileroom.infer_context(current_rel, repo.list_roster())
        self.ctx = ctx
        self.top = tk.Toplevel(parent)
        self.top.title("登记文件到文件室")
        self.top.geometry("620x560")
        self.top.minsize(560, 500)
        self.top.configure(bg=C["bg"])
        self.top.transient(parent.winfo_toplevel())
        self.top.grab_set()
        self._build()
        self._update_target()

    def _build(self):
        wrap = tk.Frame(self.top, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=22, pady=18)
        tk.Label(wrap, text="登记 %d 份文件" % len(self.paths), bg=C["bg"],
                 fg=C["text"], font=(FONT, 15, "bold"), anchor="w").pack(fill="x")
        tk.Label(wrap, text="文件会复制到当前目录，登记为「待审核」材料；源文件不移动。",
                 bg=C["bg"], fg=C["sub"], font=(FONT, 9), anchor="w").pack(
            fill="x", pady=(4, 10))

        box = tk.Frame(wrap, bg=C["card"], highlightthickness=1,
                       highlightbackground=C["line"])
        box.pack(fill="x")
        lst = tk.Text(box, height=5, wrap="none", bd=0, relief="flat",
                      bg=C["card"], fg=C["text"], font=(FONT, 9),
                      padx=10, pady=8, highlightthickness=0)
        lst.pack(fill="x")
        for p in self.paths[:50]:
            lst.insert("end", os.path.basename(p) + "\n")
        if len(self.paths) > 50:
            lst.insert("end", "…另有 %d 份\n" % (len(self.paths) - 50))
        lst.config(state="disabled")

        form = tk.Frame(wrap, bg=C["bg"])
        form.pack(fill="x", pady=(12, 0))
        tk.Label(form, text="当前目录", bg=C["bg"], fg=C["sub"], font=(FONT, 9),
                 width=10, anchor="w").grid(row=0, column=0, sticky="w", pady=5)
        tk.Label(form, text=self.current_rel or "（归档根）", bg=C["bg"],
                 fg=C["text"], font=(FONT, 9), anchor="w").grid(
            row=0, column=1, columnspan=2, sticky="w")

        tk.Label(form, text="类别", bg=C["bg"], fg=C["sub"], font=(FONT, 9),
                 width=10, anchor="w").grid(row=1, column=0, sticky="w", pady=5)
        cats = sorted({d.get("cat") for d in self.repo.list_docs() if d.get("cat")}
                      | set(self.CATS))
        if self.ctx["cat"] and self.ctx["cat"] not in cats:
            cats.insert(0, self.ctx["cat"])
        self.var_cat = tk.StringVar(value=self.ctx["cat"] or (cats[0] if cats else ""))
        ttk.Combobox(form, textvariable=self.var_cat, values=cats,
                     state="readonly", width=24).grid(row=1, column=1, sticky="w")
        self.var_cat.trace_add("write", lambda *a: self._update_target())

        tk.Label(form, text="从名单选", bg=C["bg"], fg=C["sub"], font=(FONT, 9),
                 width=10, anchor="w").grid(row=2, column=0, sticky="w", pady=5)
        roster = self.repo.list_roster()
        labels = ["%s · %s" % (r.get("sid") or "", r.get("who") or "")
                  for r in roster]
        self.student_box = ttk.Combobox(form, values=labels, state="readonly",
                                        width=24)
        self.student_box.grid(row=2, column=1, sticky="w")
        self.student_box.bind("<<ComboboxSelected>>", self._pick_student)

        tk.Label(form, text="学号", bg=C["bg"], fg=C["sub"], font=(FONT, 9),
                 width=10, anchor="w").grid(row=3, column=0, sticky="w", pady=5)
        self.var_sid = tk.StringVar(value=self.ctx["sid"])
        self.var_sid.trace_add("write", lambda *a: self._update_target())
        ttk.Entry(form, textvariable=self.var_sid, width=18).grid(
            row=3, column=1, sticky="w")
        tk.Label(form, text="姓名", bg=C["bg"], fg=C["sub"], font=(FONT, 9),
                 width=8, anchor="w").grid(row=3, column=2, sticky="w", padx=(10, 4))
        self.var_who = tk.StringVar(value=self.ctx["who"])
        self.var_who.trace_add("write", lambda *a: self._update_target())
        ttk.Entry(form, textvariable=self.var_who, width=16).grid(
            row=3, column=3, sticky="w")

        tk.Label(form, text="备注", bg=C["bg"], fg=C["sub"], font=(FONT, 9),
                 width=10, anchor="w").grid(row=4, column=0, sticky="w", pady=5)
        self.var_note = tk.StringVar(value="文件室登记")
        ttk.Entry(form, textvariable=self.var_note, width=36).grid(
            row=4, column=1, columnspan=3, sticky="we")
        form.columnconfigure(1, weight=1)

        self.target_var = tk.StringVar()
        tk.Label(wrap, textvariable=self.target_var, bg=C["bg"], fg=C["muted"],
                 font=(FONT, 9), anchor="w", justify="left",
                 wraplength=560).pack(fill="x", pady=(12, 0))
        self.err = tk.Label(wrap, text="", bg=C["bg"], fg=C["red"], font=(FONT, 9),
                            anchor="w", justify="left", wraplength=560)
        self.err.pack(fill="x", pady=(4, 0))

        btns = tk.Frame(wrap, bg=C["bg"])
        btns.pack(fill="x", side="bottom", pady=(16, 0))
        ttk.Button(btns, text="取消", command=self.top.destroy).pack(
            side="right", padx=8)
        ttk.Button(btns, text="登记", style="Accent.TButton",
                   command=self._confirm).pack(side="right")

    def _pick_student(self, _event=None):
        text = self.student_box.get()
        if " · " in text:
            sid, who = text.split(" · ", 1)
            self.var_sid.set(sid.strip())
            self.var_who.set(who.strip())

    def _update_target(self):
        cat, who = self.var_cat.get().strip(), self.var_who.get().strip()
        if not cat or not who:
            self.target_var.set("落点：请先选类别并填写学生姓名")
            return
        try:
            folder = fileroom.target_dir(self.base, self.current_rel, cat,
                                         self.var_sid.get().strip(), who)
            self.target_var.set("落点：%s\n同名文件不覆盖，会自动加 _v2、_v3。" % folder)
        except Exception as e:
            self.target_var.set("落点无法计算：%s" % e)

    def _confirm(self):
        cat = self.var_cat.get().strip()
        who = self.var_who.get().strip()
        sid = self.var_sid.get().strip()
        if not cat or not who:
            self.err.config(text="类别与学生姓名不能为空。")
            return
        if not self.paths:
            self.err.config(text="没有可登记的文件。")
            return
        try:
            res = fileroom.register_files(
                self.repo, [str(p) for p in self.paths], base=self.base,
                rel=self.current_rel, cat=cat, sid=sid, who=who,
                actor=self.window.operator_name, role=self.window.role_label(),
                note=self.var_note.get().strip() or "文件室登记")
        except Exception as e:
            self.err.config(text="登记失败：%s" % e)
            return
        if res["ok"]:
            try:
                audit.rebuild_index(self.repo.list_docs(), self.base)
            except Exception:
                pass
        if res["failed"]:
            messagebox.showwarning(
                "部分文件未登记",
                "成功 %d 份，失败 %d 份。\n\n%s" % (
                    res["ok"], len(res["failed"]),
                    "\n".join("- %s：%s" % (f["name"], f["detail"])
                              for f in res["failed"][:8])),
                parent=self.top)
        self.window.refresh_all()
        self.window.toast("已登记 %d 份文件到 %s" % (res["ok"], cat))
        self.top.destroy()
        if self.on_done:
            self.on_done()


class MissingDialog:
    """缺失文件反查：按索引/台账定位学生，能补归位就补。"""

    COLS = ("code", "name", "who", "sid", "cat", "detail")
    HEADS = {"code": "编号", "name": "材料", "who": "学生", "sid": "学号",
             "cat": "类别", "detail": "缺失说明"}
    WIDTHS = {"code": 104, "name": 160, "who": 86, "sid": 86, "cat": 86,
              "detail": 260}

    def __init__(self, parent, repo, window, on_done=None):
        self.repo = repo
        self.window = window
        self.on_done = on_done
        self.rows = {}
        self.top = tk.Toplevel(parent)
        self.top.title("缺失文件反查")
        self.top.geometry("820x520")
        self.top.minsize(720, 440)
        self.top.configure(bg=C["bg"])
        self.top.transient(parent.winfo_toplevel())
        self.top.grab_set()
        self._build()
        self.refresh()

    def _build(self):
        head = tk.Frame(self.top, bg=C["bg"])
        head.pack(fill="x", padx=22, pady=(18, 6))
        tk.Label(head, text="台账说已归档，文件却不在本机", bg=C["bg"],
                 fg=C["text"], font=(FONT, 15, "bold"), anchor="w").pack(fill="x")
        self.summary = tk.Label(head, text="", bg=C["bg"], fg=C["sub"],
                                font=(FONT, 9), anchor="w", justify="left",
                                wraplength=760)
        self.summary.pack(fill="x", pady=(4, 0))

        box = tk.Frame(self.top, bg=C["card"])
        box.pack(fill="both", expand=True, padx=22, pady=(8, 8))
        self.tree = ttk.Treeview(box, columns=self.COLS, show="headings",
                                 selectmode="browse")
        for c in self.COLS:
            self.tree.heading(c, text=self.HEADS[c], anchor="w")
            self.tree.column(c, width=self.WIDTHS[c], anchor="w",
                             stretch=(c in ("name", "detail")))
        self.tree.tag_configure("zebra", background=C["zebra"])
        ysb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self.goto_doc())
        self.empty = EmptyState(box, wraplength=400)

        self.detail = tk.Label(self.top, text="", bg=C["card"], fg=C["muted"],
                               font=(FONT, 9), anchor="w", justify="left",
                               wraplength=770, padx=12, pady=8)
        self.detail.pack(fill="x", padx=22, pady=(0, 8))

        btns = tk.Frame(self.top, bg=C["bg"])
        btns.pack(fill="x", padx=22, pady=(0, 16))
        ttk.Button(btns, text="关闭", command=self.top.destroy).pack(side="right")
        ttk.Button(btns, text="完整性检查", style="Ghost.TButton",
                   command=self._integrity).pack(side="right", padx=8)
        self.btn_repair = ttk.Button(btns, text="重新归位", style="Ghost.TButton",
                                     command=self.repair)
        self.btn_repair.pack(side="right", padx=8)
        self.btn_goto = ttk.Button(btns, text="去台账", style="Accent.TButton",
                                   command=self.goto_doc)
        self.btn_goto.pack(side="right")

    def refresh(self):
        maps = fileroom.build_status(self.repo.list_docs(), archive.root())
        self.rows = {}
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(maps["missing"]):
            iid = "m%04d" % i
            self.tree.insert("", "end", iid=iid, tags=("zebra" if i % 2 else ""),
                             values=(row["code"], row["name"], row["who"],
                                     row["sid"], row["cat"], row["detail"]))
            self.rows[iid] = row
        self.summary.config(text="共 %d 份材料缺失。双击一行或点「去台账」按编号定位；"
                            "源文件仍在本机时，可点「重新归位」复制回归档目录。"
                            % len(self.rows))
        if self.rows:
            self.empty.hide()
        else:
            self.empty.set("没有缺失文件",
                           "索引与归档目录当前对得上，不需要重新归位或补档。",
                           "关闭本窗口", self.top.destroy)
            self.empty.show_place(relx=0.5, rely=0.45)
        self._on_select()

    def _on_select(self, _event=None):
        iid = self.tree.focus()
        row = self.rows.get(iid)
        if row:
            self.detail.config(text="%s · %s（%s %s）\n%s" % (
                row["code"], row["name"], row["who"], row["sid"], row["detail"]))
        else:
            self.detail.config(text="选中一条缺失记录后，这里显示责任学生与缺失原因。")

    def goto_doc(self):
        row = self.rows.get(self.tree.focus())
        if not row:
            return
        code = row.get("code")
        if not code:
            self.window.toast("该记录没有编号，先去台账按姓名查找")
            return
        self.top.destroy()
        self.window.goto_doc(code)

    def _integrity(self):
        self.top.destroy()
        from ui_audit import open_integrity
        open_integrity(self.window, self.repo, self.window,
                       on_done=self._refresh_parent)

    def _refresh_parent(self):
        if self.on_done:
            self.on_done()

    def repair(self):
        row = self.rows.get(self.tree.focus())
        if not row:
            return
        doc = row.get("doc") or {}
        src = archive.source_file(doc)
        if not src:
            messagebox.showwarning(
                "无法归位", "这条材料的源文件也不在本机，无法自动复制。\n"
                            "请按编号去台账核对，或让同学重新提交。", parent=self.top)
            return
        if not messagebox.askyesno(
                "重新归位", "将把源文件复制回归档目录，并写一条「归位」事件。\n"
                            "不会删除源文件。继续吗？", parent=self.top):
            return
        try:
            res = archive.place(doc, archive.root())
            if not res.get("path"):
                raise RuntimeError(res.get("note") or "归位失败")
            self.repo.set_arch(doc.get("id"), res["path"],
                               self.window.operator_name, self.window.role_label())
            audit.rebuild_index(self.repo.list_docs(), archive.root())
        except Exception as e:
            messagebox.showerror("归位失败", str(e), parent=self.top)
            return
        self.window.refresh_all()
        self.refresh()
        if self.on_done:
            self.on_done()

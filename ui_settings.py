# -*- coding: utf-8 -*-
"""设置中心：外观 / 界面 / 数据 / 关于。

所有改动即时生效并写入本机 settings.json，不重启也不丢当前视图。
"""

import json
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import archive
import theme
from theme import FONT, C
from database import app_data_dir
from version import VERSION, VERSION_LABEL

REPO_URL = "https://github.com/MedianiGray/class-console"


def open_settings(window):
    SettingsDialog(window)


class SettingsDialog:
    def __init__(self, window):
        self.window = window
        self.top = tk.Toplevel(window.winfo_toplevel())
        self.top.title("设置")
        self.top.transient(window.winfo_toplevel())
        self.top.resizable(False, False)
        self._center(560, 640)
        self._build()
        self.top.bind("<Escape>", lambda e: self.close())
        try:
            self.top.grab_set()
        except tk.TclError:
            pass

    def _center(self, w, h):
        top = self.window.winfo_toplevel()
        top.update_idletasks()
        x = top.winfo_rootx() + max(0, (top.winfo_width() - w) // 2)
        y = top.winfo_rooty() + max(0, (top.winfo_height() - h) // 3)
        self.top.geometry("%dx%d+%d+%d" % (w, h, x, y))

    # ---------- 构件 ----------
    def _section(self, parent, title):
        tk.Label(parent, text=title, bg=C["bg"], fg=C["muted"],
                 font=(FONT, 10, "bold"), anchor="w").pack(fill="x", pady=(16, 6))
        card = tk.Frame(parent, bg=C["card"], highlightthickness=1,
                        highlightbackground=C["line"])
        card.pack(fill="x")
        return card

    def _seg(self, parent, options, current, on_pick, padx=10, pady=7):
        """一排扁平选项：当前项用强调色淡底，其余灰字。"""
        box = tk.Frame(parent, bg=C["card"])
        for key, label in options:
            active = key == current
            btn = tk.Button(box, text=label, relief="flat", bd=0,
                            bg=C["primary_soft"] if active else C["card"],
                            fg=C["primary"] if active else C["muted"],
                            activebackground=C["primary_soft"] if active else C["bg_soft"],
                            activeforeground=C["primary"] if active else C["text"],
                            font=(FONT, 10), padx=padx, pady=pady, cursor="hand2",
                            command=lambda k=key: on_pick(k))
            btn.pack(side="left", padx=(0, 6))
        return box

    def _build(self):
        for ch in self.top.winfo_children():
            ch.destroy()
        self.top.configure(bg=C["bg"])
        theme.apply_tk_defaults(self.top)

        # 底部固定操作条：先占位，避免被内容挤掉
        footer = tk.Frame(self.top, bg=C["bg"])
        footer.pack(side="bottom", fill="x", padx=20, pady=(6, 12))
        ttk.Button(footer, text="关闭", command=self.close).pack(side="right")
        tk.Label(footer, text="改动即时生效，下次打开仍保留", bg=C["bg"],
                 fg=C["sub"], font=(FONT, 9)).pack(side="left")

        # 中部滚动区
        body = tk.Frame(self.top, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=(20, 8), pady=(4, 0))
        canvas = tk.Canvas(body, bg=C["bg"], highlightthickness=0, bd=0,
                           yscrollincrement=36)
        self._canvas = canvas
        ysb = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        wrap = tk.Frame(canvas, bg=C["bg"])
        holder = canvas.create_window((0, 0), window=wrap, anchor="nw")
        wrap.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(holder, width=e.width))
        canvas.bind("<Enter>", lambda e: self._bind_wheel(True))
        canvas.bind("<Leave>", lambda e: self._bind_wheel(False))

        # 外观
        card = self._section(wrap, "外观")
        inner = tk.Frame(card, bg=C["card"])
        inner.pack(fill="x", padx=14, pady=12)

        tk.Label(inner, text="明暗", bg=C["card"], fg=C["text"],
                 font=(FONT, 10)).pack(side="left", padx=(0, 10))
        self._seg(inner, [(m, theme.MODE_LABEL[m]) for m in theme.MODES],
                  theme.mode(), self._pick_mode).pack(side="left")

        tone = tk.Frame(card, bg=C["card"])
        tone.pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(tone, text="强调色", bg=C["card"], fg=C["text"],
                 font=(FONT, 10)).pack(anchor="w")
        chips = tk.Frame(tone, bg=C["card"])
        chips.pack(fill="x", pady=(8, 0))
        cur = theme.accent()
        for i, (name, spec) in enumerate(theme.ACCENTS.items()):
            sample = spec["dark" if theme.resolved() == "dark" else "light"][0]
            cell = tk.Frame(chips, bg=C["card"])
            cell.grid(row=i // 5, column=i % 5, sticky="w", padx=(0, 12), pady=(0, 8))
            sw = tk.Frame(cell, bg=sample, width=26, height=26, cursor="hand2",
                          highlightthickness=2,
                          highlightbackground=C["primary"] if cur == name else C["card"])
            sw.pack()
            sw.bind("<Button-1>", lambda e, n=name: self._pick_accent(n))
            tk.Label(cell, text=spec["label"], bg=C["card"],
                     fg=C["primary"] if cur == name else C["muted"],
                     font=(FONT, 9)).pack(pady=(4, 0))

        custom = tk.Frame(card, bg=C["card"])
        custom.pack(fill="x", padx=14, pady=(0, 14))
        tk.Label(custom, text="自定义", bg=C["card"], fg=C["text"],
                 font=(FONT, 9)).pack(side="left", padx=(0, 8))
        self.hex_var = tk.StringVar(value=cur if cur.startswith("#") else "")
        ent = ttk.Entry(custom, textvariable=self.hex_var, width=10)
        ent.pack(side="left")
        tk.Button(custom, text="取色", relief="flat", bd=0, bg=C["bg_soft"],
                  fg=C["text"], activebackground=C["bg_soft"],
                  activeforeground=C["text"], font=(FONT, 9), padx=9, pady=3,
                  cursor="hand2", command=self._pick_color).pack(side="left", padx=(8, 0))
        tk.Button(custom, text="应用", relief="flat", bd=0, bg=C["primary"],
                  fg=C["on_primary"], activebackground=C["primary_hover"],
                  activeforeground=C["on_primary"], font=(FONT, 9), padx=10, pady=3,
                  cursor="hand2", command=self._apply_hex).pack(side="left", padx=(6, 0))
        tk.Label(custom, text="任意 #RRGGBB", bg=C["card"], fg=C["sub"],
                 font=(FONT, 8)).pack(side="right")

        # 界面
        card2 = self._section(wrap, "界面")
        row = tk.Frame(card2, bg=C["card"])
        row.pack(fill="x", padx=14, pady=12)
        tk.Label(row, text="表格密度", bg=C["card"], fg=C["text"],
                 font=(FONT, 10)).pack(side="left", padx=(0, 10))
        self._seg(row, [("compact", "紧凑"), ("cozy", "标准"), ("relaxed", "宽松")],
                  theme.density(), self._pick_density).pack(side="left")

        row2 = tk.Frame(card2, bg=C["card"])
        row2.pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(row2, text="侧边栏", bg=C["card"], fg=C["text"],
                 font=(FONT, 10)).pack(side="left", padx=(0, 10))
        self._seg(row2, [("expanded", "展开"), ("collapsed", "收束")],
                  "collapsed" if self.window.collapsed else "expanded",
                  self._pick_sidebar).pack(side="left")

        row3 = tk.Frame(card2, bg=C["card"])
        row3.pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(row3, text="默认视图", bg=C["card"], fg=C["text"],
                 font=(FONT, 10)).pack(side="left", padx=(0, 10))
        views = [(k, lbl, _p) for k, lbl, _p, _i, _g in self.window.NAV]
        cur_view = theme.load_ui("start_view", "dashboard")
        self.view_var = tk.StringVar(
            value=next((lbl for k, lbl, _p in views if k == cur_view), views[0][1]))
        combo = ttk.Combobox(row3, textvariable=self.view_var,
                             values=[lbl for _k, lbl, _p in views], state="readonly", width=14)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", self._pick_start_view)

        row4 = tk.Frame(card2, bg=C["card"])
        row4.pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(row4, text="申请人学号", bg=C["card"], fg=C["text"],
                 font=(FONT, 10)).pack(side="left", padx=(0, 10))
        self.applicant_var = tk.StringVar(
            value=str(getattr(self.window, "applicant_sid", "") or ""))
        ent = ttk.Entry(row4, textvariable=self.applicant_var, width=16)
        ent.pack(side="left")
        ent.bind("<FocusOut>", self._save_applicant_sid)
        ent.bind("<Return>", self._save_applicant_sid)
        tk.Label(row4, text="用于「申请人」视角只显示本人材料", bg=C["card"],
                 fg=C["sub"], font=(FONT, 8)).pack(side="left", padx=(8, 0))

        # 归档
        card5 = self._section(wrap, "材料归档")
        apath = str(archive.root())
        tk.Label(card5, text=apath, bg=C["card"], fg=C["muted"], font=(FONT, 9),
                 anchor="w", wraplength=470, justify="left").pack(fill="x", padx=14,
                                                                 pady=(12, 4))
        tk.Label(card5, text="目录规则：类别 / 学号-姓名 / 编号_材料名.pdf",
                 bg=C["card"], fg=C["sub"], font=(FONT, 9), anchor="w").pack(
            fill="x", padx=14)
        abtns = tk.Frame(card5, bg=C["card"])
        abtns.pack(fill="x", padx=14, pady=(10, 6))
        ttk.Button(abtns, text="更换目录", command=self._pick_archive_root).pack(side="left")
        ttk.Button(abtns, text="打开目录", command=self._open_archive).pack(side="left", padx=8)
        ttk.Button(abtns, text="归位全部", command=self._place_all).pack(side="left")
        arow = tk.Frame(card5, bg=C["card"])
        arow.pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(arow, text="归档时", bg=C["card"], fg=C["text"],
                 font=(FONT, 10)).pack(side="left", padx=(0, 10))
        self._seg(arow, [("copy", "复制文件"), ("mkdir", "仅建目录")],
                  "copy" if archive.auto_copy() else "mkdir",
                  self._pick_archive_copy).pack(side="left")

        # 数据
        card3 = self._section(wrap, "数据")
        path = str(app_data_dir())
        tk.Label(card3, text=path, bg=C["card"], fg=C["muted"], font=(FONT, 9),
                 anchor="w", wraplength=470, justify="left").pack(fill="x", padx=14, pady=(12, 8))
        btns = tk.Frame(card3, bg=C["card"])
        btns.pack(fill="x", padx=14, pady=(0, 12))
        ttk.Button(btns, text="打开目录", command=self._open_dir).pack(side="left")
        ttk.Button(btns, text="备份到文件", command=self._backup).pack(side="left", padx=8)
        ttk.Button(btns, text="从文件恢复", style="Danger.TButton",
                   command=self._restore).pack(side="left")

        # 关于
        card4 = self._section(wrap, "关于")
        tk.Label(card4, text="班级操作台 v%s %s" % (VERSION, VERSION_LABEL),
                 bg=C["card"], fg=C["text"], font=(FONT, 10),
                 anchor="w").pack(fill="x", padx=14, pady=(12, 2))
        tk.Label(card4, text=REPO_URL, bg=C["card"], fg=C["sub"], font=(FONT, 9),
                 anchor="w").pack(fill="x", padx=14, pady=(0, 4))
        tk.Label(card4, text="数据只存在本机，卸载前请先备份。", bg=C["card"],
                 fg=C["sub"], font=(FONT, 9), anchor="w").pack(fill="x", padx=14,
                                                              pady=(0, 12))

    def _bind_wheel(self, on):
        if on:
            self.top.bind_all("<MouseWheel>", self._on_wheel)
        else:
            self.top.unbind_all("<MouseWheel>")

    def _on_wheel(self, event):
        for ch in self.top.winfo_children():
            if isinstance(ch, tk.Frame):
                for sub in ch.winfo_children():
                    if isinstance(sub, tk.Canvas):
                        try:
                            sub.yview_scroll(int(-event.delta / 120) or -1, "units")
                        except tk.TclError:
                            pass
                        return

    # ---------- 回调 ----------
    def _redraw(self):
        frac = 0.0
        try:
            frac = self._canvas.yview()[0]
        except (tk.TclError, AttributeError):
            pass
        self._build()
        try:
            self._canvas.yview_moveto(frac)
        except tk.TclError:
            pass

    def _pick_mode(self, mode):
        self.window.apply_appearance(mode=mode)
        self._redraw()

    def _pick_accent(self, name):
        self.window.apply_appearance(accent=name)
        self._redraw()

    def _pick_color(self):
        from tkinter import colorchooser
        cur = self.hex_var.get().strip() or C["primary"]
        rgb, hexval = colorchooser.askcolor(color=cur, parent=self.top,
                                            title="选择强调色")
        if not hexval:
            return
        self.hex_var.set(hexval.upper())
        self.window.apply_appearance(accent=hexval.upper())
        self._redraw()

    def _apply_hex(self):
        val = (self.hex_var.get() or "").strip()
        if len(val) != 7 or not val.startswith("#"):
            messagebox.showwarning("颜色格式", "请输入 6 位十六进制颜色，例如 #2F6FEB", parent=self.top)
            return
        try:
            int(val[1:], 16)
        except ValueError:
            messagebox.showwarning("颜色格式", "颜色值只能包含 0-9 与 A-F", parent=self.top)
            return
        self.window.apply_appearance(accent=val.upper())
        self._redraw()

    def _pick_density(self, value):
        self.window.apply_density(value)
        self._redraw()

    def _pick_sidebar(self, value):
        if (value == "collapsed") != self.window.collapsed:
            self.window.toggle_sidebar()
        self._redraw()

    def _pick_start_view(self, _e=None):
        label = self.view_var.get()
        key = next((k for k, lbl, _p, _i, _g in self.window.NAV if lbl == label), "dashboard")
        theme.save_ui("start_view", key)
        self.window.show_status("下次启动将打开「%s」" % label, temp=True)

    def _save_applicant_sid(self, _e=None):
        val = "".join(c for c in (self.applicant_var.get() or "") if c.isdigit())[:20]
        if val != (self.applicant_var.get() or ""):
            self.applicant_var.set(val)
        if val == str(getattr(self.window, "applicant_sid", "") or ""):
            return
        theme.save_ui("applicant_sid", val)
        self.window.applicant_sid = val
        self.window.refresh_all()

    # ---------- 归档 ----------
    def _pick_archive_root(self):
        cur = str(archive.root())
        path = filedialog.askdirectory(parent=self.top, title="选择归档根目录",
                                       initialdir=cur if os.path.isdir(cur) else "")
        if not path:
            return
        archive.save_root(path)
        self._redraw()
        self.window.show_status("归档根目录已切换", temp=True)

    def _open_archive(self):
        base = archive.root()
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if not archive.open_folder(base):
            messagebox.showerror("打开失败", "无法打开 %s" % base, parent=self.top)

    def _place_all(self):
        docs = [d for d in self.window.repo.list_docs() if d.get("status") == "已归档"]
        if not docs:
            messagebox.showinfo("暂无材料", "没有已归档材料可归位。", parent=self.top)
            return
        copied = 0
        for d in docs:
            res = archive.place(d)
            if res.get("copied"):
                copied += 1
            if res.get("path"):
                self.window.repo.set_arch(d.get("id"), res["path"])
        archive.write_index(self.window.repo.list_docs())
        self.window.refresh_all()
        self.window.toast("归位 %d 条，复制 %d 个文件" % (len(docs), copied))

    def _pick_archive_copy(self, value):
        archive.set_auto_copy(value == "copy")
        self._redraw()

    def _open_dir(self):
        try:
            os.startfile(str(app_data_dir()))
        except Exception as e:
            messagebox.showerror("打开失败", str(e), parent=self.top)

    def _backup(self):
        path = filedialog.asksaveasfilename(
            parent=self.top, title="备份到文件", defaultextension=".json",
            initialfile="class-console-backup.json",
            filetypes=[("JSON 备份", "*.json")])
        if not path:
            return
        try:
            data = self.window.repo.backup()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("备份失败", str(e), parent=self.top)
            return
        self.window.toast("已备份 %d 条材料" % len(data.get("docs", [])))

    def _restore(self):
        path = filedialog.askopenfilename(
            parent=self.top, title="从文件恢复",
            filetypes=[("JSON 备份", "*.json")])
        if not path:
            return
        if not messagebox.askyesno("恢复确认", "将用备份覆盖当前数据，确定继续吗？",
                                   parent=self.top):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.window.repo.restore(data.get("docs", []), data.get("logs", []),
                                     data.get("roster"), data.get("tasks"),
                                     data.get("attachments"))
        except Exception as e:
            messagebox.showerror("恢复失败", str(e), parent=self.top)
            return
        self.window.refresh_all()
        self.window.toast("备份已恢复")

    def close(self):
        self._save_applicant_sid()
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        self.top.destroy()

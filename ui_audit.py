# -*- coding: utf-8 -*-
"""审计弹窗：完整性检查与证据包导出。"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import audit
from theme import FONT, C


class EvidenceDialog:
    """选择类别 / 日期 / 是否附带文件，导出 ZIP 证据包。"""

    def __init__(self, parent, repo, window, on_done=None):
        self.repo = repo
        self.window = window
        self.on_done = on_done
        self.top = tk.Toplevel(parent)
        self.top.title("导出证据包")
        self.top.geometry("560x430")
        self.top.minsize(520, 400)
        self.top.configure(bg=C["bg"])
        self.top.transient(parent.winfo_toplevel())
        self.top.grab_set()
        self._build()

    def _build(self):
        wrap = tk.Frame(self.top, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=22, pady=18)
        tk.Label(wrap, text="把台账、索引、日志和文件树打成一个 ZIP",
                 bg=C["bg"], fg=C["text"], font=(FONT, 14, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(wrap, text="评审方不装软件也能看懂；可选附带原始文件。",
                 bg=C["bg"], fg=C["sub"], font=(FONT, 9),
                 anchor="w").pack(fill="x", pady=(4, 14))

        form = tk.Frame(wrap, bg=C["bg"])
        form.pack(fill="x")
        tk.Label(form, text="类别", bg=C["bg"], fg=C["sub"],
                 font=(FONT, 9), width=10, anchor="w").grid(row=0, column=0,
                                                            sticky="w", pady=5)
        cats = ["全部"] + sorted({d.get("cat") or "未分类"
                                  for d in self.repo.list_docs()})
        self.cat = tk.StringVar(value="全部")
        ttk.Combobox(form, textvariable=self.cat, values=cats,
                     state="readonly", width=24).grid(row=0, column=1, sticky="w")

        tk.Label(form, text="提交日期", bg=C["bg"], fg=C["sub"],
                 font=(FONT, 9), width=10, anchor="w").grid(row=1, column=0,
                                                            sticky="w", pady=5)
        dates = tk.Frame(form, bg=C["bg"])
        dates.grid(row=1, column=1, sticky="w")
        self.start = tk.StringVar()
        self.end = tk.StringVar()
        ttk.Entry(dates, textvariable=self.start, width=12).pack(side="left")
        tk.Label(dates, text="至", bg=C["bg"], fg=C["muted"],
                 font=(FONT, 9)).pack(side="left", padx=6)
        ttk.Entry(dates, textvariable=self.end, width=12).pack(side="left")
        tk.Label(dates, text="留空不限", bg=C["bg"], fg=C["muted"],
                 font=(FONT, 8)).pack(side="left", padx=8)

        self.with_files = tk.BooleanVar(value=False)
        ttk.Checkbutton(wrap, text="附带归档目录中的原始文件（可能较大）",
                        variable=self.with_files).pack(anchor="w", pady=(14, 6))
        tk.Label(wrap, text="包内固定包含：材料清单.csv、归档索引.csv、"
                           "操作日志.csv、文件树.txt、README.txt、manifest.json",
                 bg=C["bg"], fg=C["muted"], font=(FONT, 9),
                 wraplength=500, justify="left", anchor="w").pack(fill="x")

        btns = tk.Frame(wrap, bg=C["bg"])
        btns.pack(fill="x", side="bottom", pady=(18, 0))
        ttk.Button(btns, text="取消", command=self.top.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="导出 ZIP", style="Accent.TButton",
                   command=self._export).pack(side="right")

    def _export(self):
        path = filedialog.asksaveasfilename(
            parent=self.top, title="保存证据包", defaultextension=".zip",
            initialfile="班级材料证据包.zip",
            filetypes=[("ZIP 压缩包", "*.zip")])
        if not path:
            return
        try:
            res = audit.export_evidence(
                self.repo, path, self.cat.get(), self.start.get().strip(),
                self.end.get().strip(), self.with_files.get())
        except ValueError as e:
            messagebox.showwarning("无法导出", str(e), parent=self.top)
            return
        except Exception as e:
            messagebox.showerror("导出失败", str(e), parent=self.top)
            return
        msg = "证据包已导出：\n%s\n\n材料 %d 条 · 日志 %d 条 · 附带文件 %d 个" % (
            res["path"], res["docs"], res["logs"], res["files"])
        if res.get("warnings"):
            msg += "\n\n注意：\n- " + "\n- ".join(res["warnings"])
        messagebox.showinfo("导出完成", msg, parent=self.top)
        if self.window:
            self.window.toast("证据包已导出")
        self.top.destroy()
        if self.on_done:
            self.on_done()


class IntegrityDialog:
    """索引 ↔ 磁盘 ↔ 台账比对；修复动作逐项确认。"""

    SECTIONS = [
        ("missing_file", "归档文件缺失"),
        ("no_archive_path", "已归档但没有路径"),
        ("source_missing", "源文件缺失"),
        ("index_missing", "索引缺记录"),
        ("index_mismatch", "索引路径不一致"),
        ("index_orphan", "索引多余记录"),
        ("orphan_file", "磁盘未登记文件"),
    ]

    def __init__(self, parent, repo, window, on_done=None):
        self.repo = repo
        self.window = window
        self.on_done = on_done
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title("完整性检查")
        self.top.geometry("800x640")
        self.top.minsize(720, 560)
        self.top.configure(bg=C["bg"])
        self.top.transient(parent.winfo_toplevel())
        self.top.grab_set()
        self._build()
        self.refresh()

    def _build(self):
        head = tk.Frame(self.top, bg=C["bg"])
        head.pack(fill="x", padx=22, pady=(18, 6))
        tk.Label(head, text="索引、磁盘与台账三方比对", bg=C["bg"], fg=C["text"],
                 font=(FONT, 15, "bold"), anchor="w").pack(fill="x")
        self.summary = tk.Label(head, text="", bg=C["bg"], fg=C["sub"],
                                font=(FONT, 9), anchor="w", justify="left")
        self.summary.pack(fill="x", pady=(4, 0))

        btns = tk.Frame(self.top, bg=C["bg"])
        btns.pack(side="bottom", fill="x", padx=22, pady=(0, 16))
        ttk.Button(btns, text="关闭", command=self.top.destroy).pack(side="right")
        ttk.Button(btns, text="重新归位缺失文件", style="Ghost.TButton",
                   command=self._repair).pack(side="right", padx=8)
        ttk.Button(btns, text="重建索引", style="Ghost.TButton",
                   command=self._rebuild).pack(side="right")
        ttk.Button(btns, text="重新检查", command=self.refresh).pack(side="left")

        box = tk.Frame(self.top, bg=C["card"])
        box.pack(fill="both", expand=True, padx=22, pady=(8, 10))
        self.text = tk.Text(box, wrap="word", bg=C["card"], fg=C["text"],
                            relief="flat", font=(FONT, 10), padx=12, pady=10)
        ysb = ttk.Scrollbar(box, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=ysb.set)
        self.text.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.text.tag_configure("h", foreground=C["accent"], font=(FONT, 10, "bold"))
        self.text.tag_configure("ok", foreground=C["green"])
        self.text.tag_configure("bad", foreground=C["red"])
        self.text.tag_configure("muted", foreground=C["muted"])

    def refresh(self):
        self.result = audit.check_integrity(self.repo.list_docs())
        r = self.result
        counts = r["counts"]
        self.summary.config(
            text="归档根：%s\n检查时间：%s · 材料 %d 条（已归档 %d 条）" % (
                r["root"], r["checked_at"], r["total"], r["archived"]))
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        if r["ok"]:
            self.text.insert("end", "没有发现不一致。\n", "ok")
            self.text.insert("end", "索引、台账与归档目录当前互相对得上。\n", "muted")
        else:
            self.text.insert("end", "共发现 %d 个待核对项。\n" % r["issues"], "bad")
            self.text.insert("end", "修复只处理明确可修的部分，不删除任何磁盘文件。\n\n",
                             "muted")
            for key, label in self.SECTIONS:
                items = r.get(key) or []
                if not items:
                    continue
                self.text.insert("end", "%s（%d）\n" % (label, len(items)), "h")
                for it in items[:30]:
                    line = "  %s  %s" % (it.get("code") or "—", it.get("name") or "")
                    if it.get("detail"):
                        line += "  · " + it["detail"]
                    self.text.insert("end", line + "\n")
                if len(items) > 30:
                    self.text.insert("end", "  …另有 %d 条\n" % (len(items) - 30),
                                     "muted")
                self.text.insert("end", "\n")
        self.text.config(state="disabled")

    def _rebuild(self):
        if not messagebox.askyesno(
                "重建索引", "将按当前台账重写 _归档索引.csv，不移动或删除材料文件。\n"
                           "确定继续吗？", parent=self.top):
            return
        try:
            path = audit.rebuild_index(self.repo.list_docs())
            self.repo.add_log("完整性检查", "按台账重建归档索引",
                              self.window.operator_name, self.window.role_label())
        except Exception as e:
            messagebox.showerror("重建失败", str(e), parent=self.top)
            return
        self.window.toast("索引已按台账重建")
        if path:
            messagebox.showinfo("重建完成", "索引已写入：\n%s" % path, parent=self.top)
        if self.on_done:
            self.on_done()
        self.refresh()

    def _repair(self):
        if not messagebox.askyesno(
                "重新归位", "仅处理「已归档但文件缺失、且源文件仍在本机」的材料；\n"
                           "不会删除归档目录中的任何文件。继续吗？", parent=self.top):
            return
        try:
            res = audit.repair_placements(self.repo)
            self.repo.add_log("完整性检查",
                              "重新归位：成功 %d 条，失败 %d 条" % (
                                  len(res["placed"]), len(res["failed"])),
                              self.window.operator_name, self.window.role_label())
        except Exception as e:
            messagebox.showerror("归位失败", str(e), parent=self.top)
            return
        self.window.refresh_all()
        msg = "已重新归位 %d 条，失败 %d 条。" % (
            len(res["placed"]), len(res["failed"]))
        if res["failed"]:
            msg += "\n\n仍无法修复：\n" + "\n".join(
                "- %s %s：%s" % (f.get("code") or "", f.get("name") or "",
                                f.get("detail") or "")
                for f in res["failed"][:8])
        messagebox.showinfo("归位完成", msg, parent=self.top)
        if self.on_done:
            self.on_done()
        self.refresh()


def open_evidence(parent, repo, window, on_done=None):
    return EvidenceDialog(parent, repo, window, on_done)


def open_integrity(parent, repo, window, on_done=None):
    return IntegrityDialog(parent, repo, window, on_done=on_done)

# -*- coding: utf-8 -*-
"""桌宠式悬浮助手：无边框小卡片，常驻桌面。

形态（对齐飞书 AI 助手 / 钉钉 AI 助理那套）：
- 收起时一张 288×68 圆角条（头像 + 最近一句），点一下展开；
- 展开成对话面板，回车即问，回答就地显示；
- 默认贴主窗口右下角跟随，拖动即解除跟随；位置记忆；
- 全局热键 Ctrl+Alt+A 唤起/收起（被占用时如实降级）；
- 右键管「改名 / 跟随 / 开机显示 / 朗读 / 关闭」；
- 不占主窗口空间，关掉不影响主窗口。

问答和动作全走 assistant.py，这里只负责显示、拖动、朗读、切页面。
"""

import ctypes
from ctypes import wintypes
import queue
import threading
import tkinter as tk
from tkinter import simpledialog

import assistant
import theme
import tts

W_IDLE, H_IDLE = 288, 68
W_OPEN, H_OPEN = 322, 508    # 展开态多留一行给「这份」那类长回答
KEY = "#FF00FE"          # 透明色键，只用于圆角外的空隙

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
VK_A = 0x41
WM_HOTKEY = 0x0312


def _round_rect(canvas, x0, y0, x1, y1, r, fill, outline="", width=0):
    """在 Canvas 上画圆角矩形；半径按短边收敛，避免畸形。"""
    r = max(0, min(r, (x1 - x0) // 2, (y1 - y0) // 2))
    pts = [
        x0 + r, y0, x1 - r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1, y1 - r, x1 - r, y1, x1 - r, y1,
        x0 + r, y1, x0 + r, y1, x0, y1, x0, y1 - r,
        x0, y0 + r, x0, y0, x0, y0 + r, x0 + r, y0,
    ]
    return canvas.create_polygon(pts, smooth=True, fill=fill,
                                 outline=outline or fill, width=width or 1)


class AssistantPet(object):
    def __init__(self, window, repo):
        self.app = window
        self.root = window.winfo_toplevel()
        self.repo = repo
        self.lines = [("bot", "我在。我不改台账、不归档——只帮你查、写话术、念给你听、切页面。")]
        self.expanded = False
        self.busy = False
        self.last_reply = ""
        self._greeted = False
        self._drag = None
        self._ctx_cache = {"view": "", "doc": {}}
        self._queue = queue.Queue()
        self._hk = queue.Queue()
        self.hotkey = ""
        self.name = str(theme.load_ui("pet_name", "班级助手") or "班级助手")
        self.follow = bool(theme.load_ui("pet_follow", True))
        self._relayout_job = None
        self.assistant = assistant.Assistant(
            repo, speak=self._speak, open_view=self._open_view,
            context=self._context)

        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        try:
            self.win.attributes("-topmost", True)
            self.win.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        self.win.configure(bg=KEY)

        self.canvas = tk.Canvas(self.win, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        c = theme.C
        self.entry = tk.Entry(self.win, relief="flat", bd=0, bg=c["surface_alt"],
                              fg=c["text"], insertbackground=c["text"],
                              font=(theme.FONT, 10), highlightthickness=1,
                              highlightbackground=c["line"],
                              highlightcolor=c["primary"])
        self.entry.bind("<Return>", self._on_send)
        self.entry.bind("<Escape>", lambda e: self.collapse())
        self.send_btn = tk.Button(self.win, text="发", relief="flat", bd=0,
                                  bg=c["primary"], fg=c["on_primary"],
                                  activebackground=c["primary_hover"],
                                  activeforeground=c["on_primary"],
                                  font=(theme.FONT, 9), cursor="hand2",
                                  command=self._on_send)
        self.text = tk.Text(self.win, relief="flat", bd=0, bg=c["card"],
                            fg=c["text"], font=(theme.FONT, 9),
                            wrap="word", highlightthickness=0, padx=12, pady=8,
                            cursor="arrow", spacing1=2, spacing3=6)
        self.text.tag_configure("me", foreground=c["muted"], font=(theme.FONT, 9))
        self.text.tag_configure("bot", foreground=c["text"], font=(theme.FONT, 9))
        self.text.tag_configure("tip", foreground=c["sub"], font=(theme.FONT, 8))
        self.text.configure(state="disabled")
        self.text.bind("<Double-Button-1>", lambda e: self._copy_last())

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.win.bind("<Button-3>", self._menu)
        try:
            self.root.bind("<Configure>", self._on_root_configure, add="+")
        except tk.TclError:
            pass
        self._start_hotkey()

        self._build_chips()
        self._place_window()
        self.render()
        self.render_lines()
        self.win.after(120, self._poll)

    # ---------- 生命周期 ----------
    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def show(self):
        if self.alive():
            self.win.deiconify()
            self.win.lift()

    def toggle(self):
        self.collapse() if self.expanded else self.expand()

    def expand(self):
        if not self.alive():
            return
        self.expanded = True
        self._ctx_cache = self._snapshot()   # 展开时把「你在哪一页、选了谁」摆到明面上
        if not self._greeted:
            self._greeted = True
            self._greet()
        self.render()
        self.show()
        self.entry.focus_set()
        self.entry.icursor("end")

    def _greet(self):
        """第一次展开：不问也先给一条今天的状态，省得人还要想该问什么。"""
        try:
            self.lines.append(("bot", self.assistant.brief_text()))
        except Exception:
            return
        self.last_reply = self.lines[-1][1]
        self.render_lines()

    def collapse(self):
        if not self.alive():
            return
        self.expanded = False
        self.render()

    def destroy(self):
        theme.save_ui("pet_on", False)
        try:
            self.win.destroy()
        except tk.TclError:
            pass

    # ---------- 热键 ----------
    def _start_hotkey(self):
        """Windows 全局热键：注册和消息循环必须在同一线程，Tk 只读结果。"""
        threading.Thread(target=self._hotkey_worker, daemon=True).start()

    def _hotkey_worker(self):
        try:
            u = ctypes.windll.user32
        except Exception:
            self._hk.put(("unavail", ""))
            return
        mods = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
        try:
            ok = u.RegisterHotKey(None, 1, mods, VK_A)
        except Exception:
            ok = 0
        if not ok:
            self._hk.put(("busy", ""))
            return
        self._hk.put(("ok", "Ctrl+Alt+A"))
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self._hk.put(("hit", ""))

    def _poll_hotkey(self):
        try:
            while True:
                kind, note = self._hk.get_nowait()
                if kind == "ok":
                    self.hotkey = note
                    self.assistant.hotkey_note = "%s（全局，随时唤我）" % note
                elif kind == "busy":
                    self.hotkey = ""
                    self.assistant.hotkey_note = "被其他软件占用，按不通；点我或用顶栏「✦ 助手」"
                elif kind == "unavail":
                    self.hotkey = ""
                    self.assistant.hotkey_note = "这台机器注册不上，点我或用顶栏「✦ 助手」"
                elif kind == "hit":
                    self.toggle()
                    if self.expanded:
                        self.show()
                        self.entry.focus_set()
        except queue.Empty:
            pass

    # ---------- 跟随主窗口 ----------
    def _on_root_configure(self, event=None):
        if not self.follow:
            return
        if event is not None and event.widget is not self.root:
            return
        if self._relayout_job is not None:
            return
        self._relayout_job = self.win.after(180, self._relayout)

    def _relayout(self):
        self._relayout_job = None
        if self.follow and self.alive():
            self.render()

    # ---------- 位置 ----------
    def _place_window(self):
        pos = theme.load_ui("pet_pos", None)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
        else:
            x, y = sw - W_IDLE - 32, sh - H_IDLE - 96
        self._pos = [x, y]
        if self.follow:
            self._anchor_to_root(W_IDLE, H_IDLE)
        self._apply_geometry(W_IDLE, H_IDLE)

    def _anchor_to_root(self, w, h):
        """贴主窗口右下角内侧；展开时若主窗口右侧还有位置，就停到窗口外面，别压住详情栏。

        主窗口不可见时退回屏幕右下角。
        """
        try:
            if self.root.winfo_viewable():
                rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
                rw, rh = self.root.winfo_width(), self.root.winfo_height()
                sw = self.root.winfo_screenwidth()
                if w >= W_OPEN and rx + rw + 20 + w <= sw:
                    self._pos = [rx + rw + 20, ry + rh - h - 18]
                else:
                    self._pos = [rx + rw - w - 18, ry + rh - h - 18]
                return
        except tk.TclError:
            pass
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self._pos = [sw - w - 24, sh - h - 72]

    def _apply_geometry(self, w, h):
        """以 self._pos 为准落窗口；换尺寸时收回屏幕内，别压到任务栏。"""
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x, y = self._pos
        x = max(0, min(int(x), sw - w))
        y = max(0, min(int(y), sh - h - 40))
        self._pos = [x, y]
        self.win.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def _save_pos(self):
        theme.save_ui("pet_pos", [int(self._pos[0]), int(self._pos[1])])

    def _press(self, event):
        self._drag = {"x": event.x_root, "y": event.y_root,
                      "px": self._pos[0], "py": self._pos[1],
                      "moved": False}

    def _drag_move(self, event):
        if not self._drag:
            return
        dx = event.x_root - self._drag["x"]
        dy = event.y_root - self._drag["y"]
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag["moved"] = True
        self._pos = [self._drag["px"] + dx, self._drag["py"] + dy]
        self.win.geometry("+%d+%d" % (self._pos[0], self._pos[1]))

    def _release(self, event):
        if self._drag and self._drag["moved"]:
            if self.follow:      # 手动拖走就等于说「别跟着我」
                self.follow = False
                theme.save_ui("pet_follow", False)
            self._save_pos()
            self._apply_geometry(*self._window_size())
        elif self._drag:
            self.toggle()
        self._drag = None

    def _window_size(self):
        return (W_OPEN, H_OPEN) if self.expanded else (W_IDLE, H_IDLE)

    # ---------- 画 ----------
    def render(self):
        c = theme.C
        w, h = self._window_size()
        if self.follow:
            self._anchor_to_root(w, h)
        self._apply_geometry(w, h)
        self.canvas.configure(width=w, height=h)
        self.canvas.delete("all")
        for child in (self.entry, self.send_btn, self.text):
            child.place_forget()
        for chip, _ in self.chips:
            chip.place_forget()

        _round_rect(self.canvas, 2, 2, w - 2, h - 2, 18, c["card"],
                    outline=c["line"], width=1)

        # 头像 + 在线点
        self.canvas.create_oval(14, 14, 54, 54, fill=c["primary_soft"], outline="")
        self.canvas.create_text(34, 34, text=self.name[:1], fill=c["primary"],
                                font=(theme.FONT, 13, "bold"))
        self.canvas.create_oval(47, 47, 55, 55, fill=c["green"], outline=c["card"], width=2)

        self.canvas.create_text(62, 24, text=self.name, anchor="w", fill=c["text"],
                                font=(theme.FONT, 10, "bold"))
        if self.expanded:
            sub = "回车发送 · Esc 收起"
        else:
            sub = (self.last_reply or "问我：谁还没交材料").replace("\n", " ")
            if len(sub) > 16:
                sub = sub[:16] + "…"
        self.canvas.create_text(62, 46, text=sub, anchor="w", fill=c["sub"],
                                font=(theme.FONT, 8))
        self.canvas.create_text(w - 20, 32, text="▾" if self.expanded else "▴", anchor="e",
                                fill=c["muted"], font=(theme.FONT, 9))

        if not self.expanded:
            return

        self.canvas.create_line(10, 62, w - 10, 62, fill=c["line"])
        ctx = self._ctx_line()
        if ctx:
            self.canvas.create_text(14, 76, text=ctx, anchor="w", fill=c["sub"],
                                    font=(theme.FONT, 8))
        self.text.place(x=4, y=92, width=w - 8, height=h - 196)
        self.entry.place(x=12, y=h - 98, width=w - 70, height=30)
        self.send_btn.place(x=w - 52, y=h - 98, width=40, height=30)
        for i, (chip, _) in enumerate(self.chips):
            n = len(self.chips)
            step = (w - 24) // max(1, n)
            chip.place(x=12 + i * step, y=h - 58,
                       width=step - 4, height=24)
        self.canvas.create_text(w - 14, h - 22, text="右键设置 · 双击复制", anchor="e",
                                fill=c["sub"], font=(theme.FONT, 8))

    def _build_chips(self):
        c = theme.C
        self.chips = []
        for label, q in (("概览", "台账概览"), ("谁没交", "谁还没交材料"),
                         ("待审", "有哪些待审的"), ("这份", "这份什么情况"),
                         ("帮助", "你都能做什么")):
            b = tk.Button(self.win, text=label, relief="flat", bd=0, bg=c["surface_alt"],
                          fg=c["muted"], activebackground=c["bg_soft"],
                          activeforeground=c["text"], font=(theme.FONT, 8),
                          cursor="hand2", command=lambda q=q: self._ask(q))
            self.chips.append((b, q))

    # ---------- 问答 ----------
    def _on_send(self, event=None):
        text = self.entry.get().strip()
        if not text or self.busy:
            return "break"
        self.entry.delete(0, "end")
        self._ask(text)
        return "break"

    def _ask(self, text):
        if self.busy:
            return
        self.busy = True
        self._ctx_cache = self._snapshot()
        self.lines.append(("me", text))
        self._render_busy()
        threading.Thread(target=self._worker, args=(text,), daemon=True).start()

    def _worker(self, text):
        try:
            result = self.assistant.ask(text)
        except Exception as e:
            result = {"ok": False, "action": "error", "source": "local",
                      "text": "助手出错了：%s" % e}
        self._queue.put(result)

    def _poll(self):
        try:
            while True:
                self._finish(self._queue.get_nowait())
        except queue.Empty:
            pass
        self._poll_hotkey()
        if self.alive():
            self.win.after(120, self._poll)

    def _finish(self, result):
        self.busy = False
        text = result.get("text") or ""
        if result.get("action") == "error":
            self.lines.append(("tip", text))
        else:
            self.lines.append(("bot", text))
            self.last_reply = text
        try:
            self._ctx_cache = self._snapshot()   # 答完顺手刷新顶部那行上下文
        except Exception:
            pass
        self.render_lines()
        self.render()
        if result.get("action") == "open_view":
            self._raise_main()

    def render_lines(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for i, (role, content) in enumerate(self.lines):
            prefix = "" if i == 0 else "\n"
            if role == "me":
                self.text.insert("end", prefix + "你：" + content + "\n", "me")
            elif role == "bot":
                self.text.insert("end", prefix + "助手：" + content + "\n", "bot")
            else:
                self.text.insert("end", prefix + content + "\n", "tip")
        self.text.configure(state="disabled")
        self.text.see("end")

    def _render_busy(self):
        self.text.configure(state="normal")
        self.text.insert("end", "\n助手正在查…", "tip")
        self.text.see("end")
        self.text.configure(state="disabled")

    def _copy_last(self):
        if not self.last_reply:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.last_reply)
            self.lines.append(("tip", "已复制最近一条回答。"))
            self.render_lines()
        except tk.TclError:
            pass

    # ---------- 回调 ----------
    def _speak(self, text):
        try:
            return tts.speak(text)
        except Exception as e:
            return False, "朗读失败：%s" % e

    def _open_view(self, key):
        if hasattr(self.app, "switch"):
            self.app.switch(key)

    def _context(self):
        """Tk 只能主线程碰：这里只回发送前拍好的快照，供后台线程读。"""
        return {"view": self._ctx_cache.get("view", ""),
                "doc": dict(self._ctx_cache.get("doc") or {})}

    def _snapshot(self):
        """在主线程上取「当前视图 + 选中材料」。"""
        out = {"view": "", "doc": {}}
        try:
            out["view"] = getattr(self.app, "current", "") or ""
        except Exception:
            pass
        try:
            docs = (getattr(self.app, "views", {}) or {}).get("docs")
            if docs is not None and hasattr(docs, "_selected"):
                did = docs._selected()
                if did:
                    out["doc"] = docs._find_doc(did) or {}
        except Exception:
            pass
        return out

    def _ctx_line(self):
        """把上下文摆出来，人才敢说「这份」「他缺什么」。"""
        view = self._ctx_cache.get("view", "")
        label = view
        for key, name, _kw in assistant.VIEWS:
            if key == view:
                label = name
                break
        if not label:
            return ""
        doc = self._ctx_cache.get("doc") or {}
        if doc.get("name"):
            who = doc.get("who") or ""
            sid = doc.get("sid") or ""
            tail = ("%s %s" % (who, sid)).strip()
            line = "当前：%s · 选中 %s%s" % (label, doc.get("name"), (" " + tail) if tail else "")
        else:
            line = "当前：%s · 没选中具体材料" % label
        return line if len(line) <= 34 else line[:33] + "…"


    # ---------- 菜单 ----------
    def _menu(self, event):
        c = theme.C
        m = tk.Menu(self.win, tearoff=0, bg=c["surface_alt"], fg=c["text"],
                    activebackground=c["primary_soft"], activeforeground=c["text"],
                    bd=0)
        m.add_command(label="打开主窗口", command=self._raise_main)
        m.add_command(label="给助手改名…", command=self._rename)
        m.add_command(label="朗读最近一条", command=lambda: self._speak(self.last_reply))
        on = bool(theme.load_ui("pet_on", False))
        m.add_command(label="开机自动显示：%s" % ("开" if on else "关"),
                      command=self._toggle_autostart)
        m.add_command(label="跟随主窗口：%s" % ("开" if self.follow else "关"),
                      command=self._toggle_follow)
        m.add_command(label="全局热键：%s" % (self.hotkey or "不可用（点我即可）"),
                      command=lambda: None)
        m.add_separator()
        m.add_command(label="收起", command=self.collapse)
        m.add_command(label="关闭助手", command=self.destroy)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _raise_main(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def _toggle_autostart(self):
        theme.save_ui("pet_on", not bool(theme.load_ui("pet_on", False)))

    def _toggle_follow(self):
        self.follow = not self.follow
        theme.save_ui("pet_follow", self.follow)
        if self.follow:
            self.render()
        else:
            self._save_pos()

    def _rename(self):
        try:
            name = simpledialog.askstring("给助手改名", "叫什么？（留空恢复「班级助手」）",
                                          initialvalue=self.name, parent=self.root)
        except tk.TclError:
            return
        if name is None:
            return
        name = name.strip()[:8] or "班级助手"
        self.name = name
        theme.save_ui("pet_name", name)
        self.render()


def open_pet(window, repo):
    """主窗口入口：已有就复用，不再开第二个。"""
    pet = getattr(window, "assistant_pet", None)
    if pet is not None and pet.alive():
        pet.show()
        if not pet.expanded:
            pet.expand()
        return pet
    pet = AssistantPet(window, repo)
    window.assistant_pet = pet
    return pet

# -*- coding: utf-8 -*-
"""桌宠式悬浮助手：无边框小卡片，常驻桌面。

形态：
- 收起时一张 306×80 圆角卡（头像 + 最近一句），不抢焦点；
- 点一下展开成对话面板，回车即问，回答就地显示；
- 可拖动、记住位置；右键管「开机显示 / 朗读 / 关闭」；
- 不占主窗口空间，关掉不影响主窗口。

问答和动作全走 assistant.py，这里只负责显示、拖动、朗读、切页面。
"""

import queue
import threading
import tkinter as tk

import assistant
import theme
import tts

W_IDLE, H_IDLE = 306, 80
W_OPEN, H_OPEN = 322, 468
KEY = "#FF00FE"          # 透明色键，只用于圆角外的空隙


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
        self.lines = [("bot", "我在。问「谁还没交材料」或「250223 还缺什么」，"
                            "我能查台账、写催交话术、念给你听、切页面。")]
        self.expanded = False
        self.busy = False
        self.last_reply = ""
        self._drag = None
        self._queue = queue.Queue()
        self.assistant = assistant.Assistant(
            repo, speak=self._speak, open_view=self._open_view)

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
        self.render()
        self.show()
        self.entry.focus_set()
        self.entry.icursor("end")

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

    # ---------- 位置 ----------
    def _place_window(self):
        pos = theme.load_ui("pet_pos", None)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
        else:
            x, y = sw - W_IDLE - 32, sh - H_IDLE - 96
        self._pos = [x, y]
        self._apply_geometry(W_IDLE, H_IDLE)

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
        self.canvas.create_text(34, 34, text="助", fill=c["primary"],
                                font=(theme.FONT, 13, "bold"))
        self.canvas.create_oval(47, 47, 55, 55, fill=c["green"], outline=c["card"], width=2)

        self.canvas.create_text(64, 24, text="班级助手", anchor="w", fill=c["text"],
                                font=(theme.FONT, 10, "bold"))
        if self.expanded:
            sub = "回车发送 · Esc 收起"
        else:
            sub = (self.last_reply or "问我：谁还没交材料").replace("\n", " ")
            if len(sub) > 18:
                sub = sub[:18] + "…"
        self.canvas.create_text(64, 46, text=sub, anchor="w", fill=c["sub"],
                                font=(theme.FONT, 8))
        self.canvas.create_text(w - 20, 32, text="▾" if self.expanded else "▴", anchor="e",
                                fill=c["muted"], font=(theme.FONT, 9))

        if not self.expanded:
            return

        self.canvas.create_line(10, 62, w - 10, 62, fill=c["line"])
        self.text.place(x=4, y=64, width=w - 8, height=h - 168)
        self.entry.place(x=12, y=h - 98, width=w - 70, height=30)
        self.send_btn.place(x=w - 52, y=h - 98, width=40, height=30)
        for i, (chip, _) in enumerate(self.chips):
            chip.place(x=12 + i * ((w - 24) // 4), y=h - 58,
                       width=(w - 36) // 4, height=24)
        self.canvas.create_text(w - 14, h - 22, text="右键设置 · 双击复制", anchor="e",
                                fill=c["sub"], font=(theme.FONT, 8))

    def _build_chips(self):
        c = theme.C
        self.chips = []
        for label, q in (("概览", "台账概览"), ("谁没交", "谁还没交材料"),
                         ("待审", "有哪些待审的"), ("帮助", "你都能做什么")):
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
        self.render_lines()
        if not self.expanded:
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

    # ---------- 菜单 ----------
    def _menu(self, event):
        c = theme.C
        m = tk.Menu(self.win, tearoff=0, bg=c["surface_alt"], fg=c["text"],
                    activebackground=c["primary_soft"], activeforeground=c["text"],
                    bd=0)
        m.add_command(label="打开主窗口", command=self._raise_main)
        m.add_command(label="朗读最近一条", command=lambda: self._speak(self.last_reply))
        on = bool(theme.load_ui("pet_on", False))
        m.add_command(label="开机自动显示：%s" % ("开" if on else "关"),
                      command=self._toggle_autostart)
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

# -*- coding: utf-8 -*-
"""生成桌面 AI 分类建议的走查截图（临时库，不动真实数据）。

运行：py -3.14 tests/gui_ai_shot.py
输出：../v026-桌面-AI分类建议.png（可用 OUT 环境变量覆盖）
"""

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="cc-shot-appdata-")

import tkinter as tk  # noqa: E402
from PIL import ImageGrab  # noqa: E402

import main as app_main  # noqa: E402
import ai  # noqa: E402
from database import LocalRepository  # noqa: E402
from ui_main import MainWindow  # noqa: E402
from ui_settings import SettingsDialog  # noqa: E402

OUT = os.environ.get("OUT") or str(
    Path(__file__).resolve().parent.parent.parent / "v026-桌面-AI分类建议.png")


def _grab(win, path):
    win.update_idletasks()
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    img.save(path)
    return img


def main():
    app_main.enable_dpi_awareness()
    root = tk.Tk()
    root.geometry("1220x820+40+30")
    root.title("班级操作台 · AI 建议走查")
    repo = LocalRepository(Path(tempfile.mkdtemp()) / "shot.db")
    app = MainWindow(root, repo)
    root.update()
    app.role_var.set("handler")
    app._toggle_role()
    app.switch("collect")
    root.update()

    folder = tempfile.mkdtemp(prefix="cc-shot-files-")
    names = ("250219_黄志强_团日活动记录.docx", "250203_李雨桐_体测成绩统计表.xlsx",
             "250208_陈思颖_国家奖学金申请表.pdf", "250222_刘一帆_社团招新新闻稿.docx")
    for name in names:
        Path(folder, name).write_text("x", encoding="utf-8")
    cv = app.views["collect"]
    cv.folder = folder
    cv.scan()
    root.update()
    cv.suggest_categories()
    root.update()
    adv = app.ai_dialog
    deadline = time.time() + 5
    while time.time() < deadline and not adv.results:
        root.update()
        time.sleep(0.05)
    root.update_idletasks()
    root.lift()
    root.attributes("-topmost", True)
    root.focus_force()
    root.update()
    time.sleep(0.4)
    adv.top.lift()
    adv.top.attributes("-topmost", True)
    adv.top.focus_force()
    root.update()
    time.sleep(0.4)
    root.update()

    x = root.winfo_rootx()
    y = root.winfo_rooty()
    w = root.winfo_width()
    h = root.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    img.save(OUT)
    print("SHOT", OUT, img.size, "suggestions", len(adv.results))
    print("DIALOG", adv.top.winfo_geometry(), "viewable", adv.top.winfo_viewable(),
          "mapped", adv.top.winfo_ismapped(), "state", adv.top.state())
    for w in adv.top.winfo_children():
        print("CHILD", w.winfo_class(), w.winfo_x(), w.winfo_y(),
              w.winfo_width(), w.winfo_height())
        for c in w.winfo_children():
            if c.winfo_class() in ("TButton", "Label"):
                print("  ", c.winfo_class(), repr(c.cget("text"))[:36],
                      c.winfo_x(), c.winfo_y(), c.winfo_width(), c.winfo_height())
    full = ImageGrab.grab(all_screens=True)
    full.save(str(Path(OUT).with_name(Path(OUT).stem + "-全屏.png")))
    adv.apply()
    root.update()
    time.sleep(0.4)
    out_apply = str(Path(OUT).with_name(Path(OUT).stem.replace("AI分类建议", "AI回填") + ".png"))
    _grab(root, out_apply)
    print("APPLY SHOT", out_apply)
    root.update()

    ai.save_config({"enabled": False, "base_url": "https://api.siliconflow.cn/v1",
                    "model": "Qwen/Qwen2.5-7B-Instruct",
                    "api_key": "sk-demo-not-a-real-key", "timeout": 20})
    settings = SettingsDialog(app)
    root.update()
    wrap = settings._canvas.winfo_children()[0]
    kids = wrap.winfo_children()
    for i, ch in enumerate(kids):
        if ch.winfo_class() == "Label" and str(ch.cget("text")).startswith("AI 建议"):
            card = kids[i + 1]
            break
    else:
        card = None
    assert card is not None
    wrap.update_idletasks()
    total = max(1, wrap.winfo_height())
    visible = max(1, settings._canvas.winfo_height())
    top_y = max(0, card.winfo_y() - 48)
    settings._canvas.yview_moveto(min(1.0, top_y / total))
    settings.top.update()
    settings.top.lift()
    settings.top.attributes("-topmost", True)
    settings.top.focus_force()
    time.sleep(0.5)
    out2 = str(Path(OUT).with_name(Path(OUT).stem.replace("AI分类建议", "AI设置") + ".png"))
    _grab(settings.top, out2)
    print("SETTINGS SHOT", out2, "scroll", top_y, total, visible)
    settings.close()
    root.destroy()


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""启动分段计时：把冷启动拆成 Tk / 建库 / 外壳 / 外壳首帧 / 内容就绪，跑多次取中位。

外壳 = MainWindow(staged=True) 只建顶栏+侧栏+占位卡；内容 = 当前视图补齐。
这样能分别看「用户多久看到窗口」和「多久能用上内容」。

用法：
    xvfb-run -a python3 tests/startup_bench.py            # 常规口径
    xvfb-run -a python3 tests/startup_bench.py --profile  # 附带 cProfile 前 25 项

数据目录一次性隔离在本进程内，不改动本机真实数据；同时测「干净首次」
（空库建库 + 种子）与「已有数据」（已建库二次启动）两种口径。
"""
import cProfile
import io
import os
import pstats
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WARM_ROUNDS = int(os.environ.get("CC_BENCH_ROUNDS", "5"))


def _isolate(prefix):
    base = Path(tempfile.mkdtemp(prefix=prefix))
    os.environ["APPDATA"] = str(base / "appdata")
    os.environ["HOME"] = str(base / "home")
    Path(os.environ["APPDATA"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["HOME"]).mkdir(parents=True, exist_ok=True)


def _phases():
    """返回 (Tk, 建库, 外壳, 外壳首帧, 内容) 五段毫秒数。"""
    import tkinter as tk
    from database import build_repository
    from ui_main import MainWindow

    t0 = time.perf_counter()
    root = tk.Tk()
    root.geometry("1220x860")
    root.withdraw()
    t1 = time.perf_counter()
    repo = build_repository()
    t2 = time.perf_counter()
    app = MainWindow(root, repo, staged=True)
    t3 = time.perf_counter()
    root.deiconify()
    root.update_idletasks()
    root.update()
    t4 = time.perf_counter()
    app.start_content()
    root.update_idletasks()
    root.update()
    t5 = time.perf_counter()
    root.destroy()
    return ((t1 - t0) * 1000, (t2 - t1) * 1000, (t3 - t2) * 1000,
            (t4 - t3) * 1000, (t5 - t4) * 1000)


def _run(label, prefix):
    _isolate(prefix)
    rows = []
    for i in range(WARM_ROUNDS):
        if i == 0:
            rows.append(_phases())   # 首轮即干净首次：库还没建
            continue
        rows.append(_phases())
    clean = rows[0]
    warm = rows[1:] or [rows[0]]
    med = [statistics.median(r[i] for r in warm) for i in range(5)]

    def line(tag, row):
        return ("%s %s Tk=%.0f 建库=%.0f 外壳=%.0f 外壳首帧=%.0f 内容=%.0f "
                "｜窗口可见=%.0f 内容就绪=%.0f" % (
                    label, tag, row[0], row[1], row[2], row[3], row[4],
                    row[0] + row[1] + row[2] + row[3],
                    row[0] + row[1] + row[2] + row[3] + row[4]))

    print(line("干净首次", clean))
    print(line("已有数据中位（%d 次）" % len(warm), med))
    return clean, med


def _profile():
    _isolate("cc-prof-")
    from database import build_repository
    from ui_main import MainWindow
    import tkinter as tk

    pr = cProfile.Profile()
    pr.enable()
    root = tk.Tk()
    repo = build_repository()
    app = MainWindow(root, repo, staged=True)
    app.start_content()
    root.update_idletasks()
    root.update()
    pr.disable()
    root.destroy()
    buf = io.StringIO()
    pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(25)
    print(buf.getvalue())


def main():
    import tkinter  # noqa: F401
    _run("启动", "cc-bench-")
    if "--profile" in sys.argv:
        _profile()


if __name__ == "__main__":
    main()

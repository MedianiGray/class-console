# -*- coding: utf-8 -*-
"""A4 桌面性能基线。

临时 APPDATA + 临时 SQLite，不触碰本机真实数据：
  1. 写入 5000 条材料与 5000 条日志
  2. 计时 list_docs / 关键词筛选 / 类别筛选 / stats / list_logs
  3. 真实 Tk 台账刷新 5000 条
  4. 源码与打包 EXE 冷启动到主窗口、常驻内存

用法：
  python tests/perf_desktop.py
  python tests/perf_desktop.py --no-exe
退出码：0 全部达标；1 有指标未达标或测试失败。
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import gc
import json
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="cc-perf-appdata-")

from database import LocalRepository  # noqa: E402
from version import VERSION, VERSION_LABEL  # noqa: E402

DOCS = 5000
LOGS = 5000
LIMITS = {"query_ms": 100, "memory_mb": 150, "startup_ms": 1000}
TEST_TMP = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "Temp" / "cc-perf-desktop"

CATS = ["团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]
STATUSES = ["待审核", "已归档", "已驳回", "待补材料"]


def private_mb(pid=None):
    if os.name != "nt":
        return None
    class PMC_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    kernel32.GetCurrentProcess.restype = wt.HANDLE
    kernel32.OpenProcess.restype = wt.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD]
    handle = kernel32.GetCurrentProcess() if pid is None else kernel32.OpenProcess(0x0410, False, pid)
    if not handle:
        return None
    counters = PMC_EX()
    counters.cb = ctypes.sizeof(counters)
    ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    if pid is not None:
        kernel32.CloseHandle(handle)
    if not ok:
        return None
    return round(counters.PrivateUsage / 1048576, 1)


def machine_info():
    info = {
        "version": "%s %s" % (VERSION, VERSION_LABEL),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "cpu": os.environ.get("PROCESSOR_IDENTIFIER", ""),
        "logical_cpus": os.cpu_count(),
    }
    if os.name != "nt":
        return info
    try:
        total = ctypes.c_ulonglong()
        ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(total))
        info["ram_gb"] = round(total.value / 1048576, 1)
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber | ConvertTo-Json -Compress"],
            text=True, encoding="utf-8", timeout=15)
        info.update(json.loads(out))
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Processor | Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress"],
            text=True, encoding="utf-8", timeout=15)
        info.update(json.loads(out))
    except Exception:
        pass
    return info


def seed_database(path):
    repo = LocalRepository(path)
    conn = sqlite3.connect(str(path))
    conn.execute("DELETE FROM docs")
    conn.execute("DELETE FROM logs")
    conn.execute("DELETE FROM attachments")
    conn.execute("DELETE FROM doc_events")
    docs = []
    names = ["同学%d" % i for i in range(40)]
    for i in range(DOCS):
        docs.append((
            "性能基线材料%d" % i, CATS[i % len(CATS)], names[i % len(names)],
            str(250000 + i % 80), "性能基线样本", "",
            "2026-11-%02d 10:00" % (1 + i % 24), STATUSES[i % len(STATUSES)],
            "班级", "", "general", "",
        ))
    conn.executemany(
        "INSERT INTO docs (name,cat,who,sid,note,file,time,status,scope,path,form_type,extra) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", docs)
    logs = []
    for i in range(LOGS):
        logs.append(("2026-11-%02d 10:00" % (1 + i % 24), names[i % len(names)],
                     "经办人", "筛选测试", "材料%d" % i, "本机"))
    conn.executemany(
        "INSERT INTO logs (time,who,role,act,obj,src) VALUES (?,?,?,?,?,?)", logs)
    conn.commit()
    conn.close()
    return repo


def median_ms(fn, rounds=7):
    for _ in range(2):
        fn()
    values = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        values.append((time.perf_counter() - t0) * 1000)
    return round(statistics.median(values), 1)


def bench_query(repo):
    cases = [
        ("全部材料", lambda: repo.list_docs()),
        ("关键词筛选", lambda: repo.list_docs("同学7")),
        ("类别筛选", lambda: repo.list_docs("", "奖助材料")),
        ("统计", lambda: repo.stats()),
        ("日志查询", lambda: repo.list_logs()),
    ]
    out = []
    for name, fn in cases:
        samples = [median_ms(fn) for _ in range(3)]
        out.append({"name": name, "samples": samples, "medianMs": round(statistics.median(samples), 1)})
    return out


def all_windows():
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    CB = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    out = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value:
                    pid = wt.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    out.append((hwnd, buf.value, pid.value))
        return True

    user32.EnumWindows(CB(cb), 0)
    return out


def kill_tree(pid):
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    except Exception:
        pass


def prepare_appdata(label):
    """首次建库单独计时，不计入“已有数据冷启动”。"""
    appdata = Path(tempfile.mkdtemp(prefix="cc-perf-start-"))
    env = dict(os.environ, APPDATA=str(appdata))
    t0 = time.perf_counter()
    subprocess.run(
        [sys.executable, "-c",
         "from database import build_repository; build_repository()"],
        cwd=str(ROOT), env=env, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=0x08000000, timeout=120)
    return appdata, round((time.perf_counter() - t0) * 1000, 1)


def window_width(hwnd):
    if os.name != "nt":
        return 0
    rect = wt.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return 0
    return int(rect.right - rect.left)


def measure_startup(label, command, runs=3, prepare=True):
    results = []
    if os.name != "nt":
        return {"label": label, "skipped": "非 Windows", "runs": []}
    for index in range(1, runs + 1):
        # 先建好空库，启动计时只覆盖“已有数据 → 主窗口”，
        # 首次建库另记 prepareMs，避免把一次性初始化混进冷启动。
        if prepare:
            appdata, prep_ms = prepare_appdata(label)
        else:
            appdata, prep_ms = Path(tempfile.mkdtemp(prefix="cc-perf-clean-")), 0
        env = dict(os.environ, APPDATA=str(appdata))
        before = {item[0] for item in all_windows()}
        t0 = time.perf_counter()
        proc = subprocess.Popen(command, cwd=str(ROOT), env=env,
                                creationflags=0x08000000)
        found = None
        while time.perf_counter() - t0 < 30:
            for hwnd, title, pid in all_windows():
                if (hwnd not in before and "班级操作台" in title
                        and "正在打开" not in title
                        and window_width(hwnd) >= 900):
                    found = (hwnd, title, pid)
                    break
            if found:
                break
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        if not found:
            results.append({"startupMs": elapsed, "memoryMB": None,
                            "window": None, "ok": False,
                            "prepareMs": prep_ms})
            kill_tree(proc.pid)
            continue
        time.sleep(1.2)
        mem = private_mb(found[2])
        crash = appdata / "ClassConsole" / "crash.log"
        results.append({
            "startupMs": elapsed,
            "memoryMB": mem,
            "window": found[1],
            "pid": found[2],
            "crashLog": crash.exists(),
            "prepareMs": prep_ms,
            "ok": elapsed <= LIMITS["startup_ms"] and not crash.exists(),
        })
        kill_tree(proc.pid)
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    return {"label": label, "runs": results}


def bench_ui(repo):
    """真实 Tk 台账刷新；root 隐藏，不抢用户窗口。"""
    import tkinter as tk
    from ui_main import MainWindow

    root = tk.Tk()
    root.withdraw()
    t0 = time.perf_counter()
    window = MainWindow(root, repo)
    root.update_idletasks()
    init_ms = round((time.perf_counter() - t0) * 1000, 1)

    samples = []
    for _ in range(7):
        t0 = time.perf_counter()
        window.views["docs"].refresh()
        root.update_idletasks()
        samples.append((time.perf_counter() - t0) * 1000)
    samples_sorted = sorted(samples)
    refresh_ms = round(statistics.median(samples_sorted), 1)
    rows = len(window.views["docs"].tree.get_children())
    gc.collect()
    mem = private_mb()
    root.destroy()
    return {
        "initMs": init_ms,
        "refreshMs": refresh_ms,
        "refreshMaxMs": round(samples_sorted[-1], 1),
        "rows": rows,
        "memoryMB": mem,
    }


def locate_exe():
    dist = ROOT / "dist"
    exact = dist / ("class-console-v%s.exe" % VERSION)
    if exact.exists():
        return exact
    if dist.exists():
        items = sorted(dist.glob("class-console-v*.exe"), key=lambda p: p.stat().st_mtime)
        if items:
            return items[-1]
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-exe", action="store_true", help="只测源码，不测打包 EXE")
    args = parser.parse_args()

    info = machine_info()
    print("桌面性能基线 %s" % info.get("version"))
    print(json.dumps(info, ensure_ascii=False, indent=2))

    TEST_TMP.mkdir(parents=True, exist_ok=True)
    db_path = TEST_TMP / ("perf-%d.db" % os.getpid())
    if db_path.exists():
        db_path.unlink()
    repo = seed_database(db_path)
    print("\n数据量：材料 %d 条，日志 %d 条" % (len(repo.list_docs()), len(repo.list_logs())))

    query = bench_query(repo)
    print("\n数据层计时（三次中位数）：")
    for item in query:
        print("  %-8s %s ms  明细 %s" % (item["name"], item["medianMs"], item["samples"]))

    ui = bench_ui(repo)
    print("\n桌面台账刷新：%s ms（最慢 %s ms，%d 行，常驻 %s MB，初始化 %s ms）"
          % (ui["refreshMs"], ui["refreshMaxMs"], ui["rows"], ui["memoryMB"], ui["initMs"]))

    source = measure_startup("源码", [sys.executable, str(ROOT / "main.py")])
    print("\n源码冷启动：%s" % json.dumps(source, ensure_ascii=False))
    print("源码首次建库：%s ms（不计入冷启动）"
          % statistics.median([r["prepareMs"] for r in source["runs"]]))

    packaged = None
    exe = locate_exe()
    if not args.no_exe and exe:
        run_exe = TEST_TMP / exe.name
        if Path(exe).resolve() != run_exe.resolve():
            shutil.copy2(str(exe), str(run_exe))
        packaged = measure_startup("打包 EXE", [str(run_exe)])
        print("打包冷启动：%s" % json.dumps(packaged, ensure_ascii=False))
        print("打包首次建库：%s ms（不计入冷启动）"
              % statistics.median([r["prepareMs"] for r in packaged["runs"]]))

    checks = [
        ("5000 条全部查询", query[0]["medianMs"], LIMITS["query_ms"], "ms",
         query[0]["medianMs"] <= LIMITS["query_ms"]),
        ("5000 条关键词筛选", query[1]["medianMs"], LIMITS["query_ms"], "ms",
         query[1]["medianMs"] <= LIMITS["query_ms"]),
        ("5000 条类别筛选", query[2]["medianMs"], LIMITS["query_ms"], "ms",
         query[2]["medianMs"] <= LIMITS["query_ms"]),
        ("统计", query[3]["medianMs"], LIMITS["query_ms"], "ms",
         query[3]["medianMs"] <= LIMITS["query_ms"]),
        ("桌面台账首屏 300 条刷新", ui["refreshMs"], LIMITS["query_ms"], "ms",
         ui["refreshMs"] <= LIMITS["query_ms"]),
        ("常驻内存", ui["memoryMB"], LIMITS["memory_mb"], "MB",
         ui["memoryMB"] is not None and ui["memoryMB"] <= LIMITS["memory_mb"]),
        ("源码冷启动到主窗口（已有数据）", statistics.median([r["startupMs"] for r in source["runs"]]),
         LIMITS["startup_ms"], "ms",
         all(r["ok"] for r in source["runs"])),
    ]
    if packaged:
        checks.append(("打包 EXE 冷启动到主窗口（已有数据）",
                       statistics.median([r["startupMs"] for r in packaged["runs"]]),
                       LIMITS["startup_ms"], "ms",
                       all(r["ok"] for r in packaged["runs"])))

    print("\n判定：")
    for name, value, limit, unit, ok in checks:
        print("  %s %s: %s%s（阈值 %s%s）"
              % ("PASS" if ok else "FAIL", name,
                 "N/A" if value is None else value, unit, limit, unit))

    failed = [name for name, _, _, _, ok in checks if not ok]
    print("\n未达标项：" + ("、".join(failed) if failed else "无"))
    print("\nDESKTOP PERF %s" % ("PASS" if not failed else "FAIL"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())

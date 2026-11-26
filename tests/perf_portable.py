# -*- coding: utf-8 -*-
"""比较打包形态的启动耗时：onefile 与 onedir 同一口径。

用法：
  py -3.14 tests/perf_portable.py --exe "dist/班级操作台.exe"
  py -3.14 tests/perf_portable.py --exe "dist/班级操作台-便携/班级操作台-便携.exe" --clean-first
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import perf_desktop as p  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--clean-first", action="store_true")
    args = parser.parse_args()

    exe = Path(args.exe)
    if not exe.is_absolute():
        exe = ROOT / exe
    if not exe.exists():
        raise SystemExit("找不到可执行文件：%s" % exe)

    existing = p.measure_startup("已有数据", [str(exe)], runs=args.runs, ready=True)
    print(json.dumps(existing, ensure_ascii=False, indent=2))
    values = [r["startupMs"] for r in existing["runs"]]
    ready_values = [r["contentReadyMs"] for r in existing["runs"] if r.get("contentReadyMs")]
    print("已有数据中位：%.1f ms（%s）" % (statistics.median(values), values))
    if ready_values:
        print("内容就绪中位：%.1f ms（%s）" % (statistics.median(ready_values), ready_values))

    if args.clean_first:
        clean = p.measure_startup("干净目录首次", [str(exe)], runs=1, prepare=False, ready=True)
        print(json.dumps(clean, ensure_ascii=False, indent=2))
        print("干净目录首次：%.1f ms" % clean["runs"][0]["startupMs"])
        print("干净目录内容就绪：%s ms" % clean["runs"][0].get("contentReadyMs"))


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""打包单文件 exe，并复制为版本化发布资产。

单文件每次启动要解包，适合 U 盘带走；
固定机器优先用 tools/build_portable.py 产出的便携目录版。
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from version import VERSION  # noqa: E402

HIDDEN = [
    "ui_ai", "ui_audit", "ui_cmdk", "ui_collect", "ui_dashboard", "ui_docs",
    "ui_empty", "ui_error", "ui_files", "ui_hub", "ui_logs", "ui_reminders",
    "ui_roster", "ui_service", "ui_settings", "ui_submit", "ui_tasks",
    "ui_filetools", "filetools", "tts", "assistant", "ui_pet", "ui_projects",
]


# PIL 只在图片转换/缩略图里按需 import；numpy 又是 PIL 的可选依赖，启动路径完全用不到。
EXCLUDES = ["numpy", "numpy.libs", "scipy", "pandas", "matplotlib"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main():
    name = "班级操作台"
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onefile", "--windowed", "--name", name]
    for item in HIDDEN:
        args += ["--hidden-import", item]
    for item in EXCLUDES:
        args += ["--exclude-module", item]
    args.append("main.py")
    print("[1/3] PyInstaller onefile")
    subprocess.run(args, cwd=str(ROOT), check=True)

    source = ROOT / "dist" / (name + ".exe")
    target = ROOT / "dist" / ("class-console-v%s.exe" % VERSION)
    shutil.copy2(str(source), str(target))
    print("[2/3] Done")
    print("exe=%s bytes=%d" % (target, target.stat().st_size))
    print("[3/3] sha256=%s" % sha256(target))


if __name__ == "__main__":
    main()


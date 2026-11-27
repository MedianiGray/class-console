# -*- coding: utf-8 -*-
"""打包便携目录版：onedir + 版本化目录 + zip。

解压一次后不再每次解包，启动更接近源码运行；
输出 dist/class-console-v<版本>-portable.zip。
"""
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from version import VERSION  # noqa: E402

HIDDEN = [
    "ui_ai", "ui_audit", "ui_cmdk", "ui_collect", "ui_dashboard", "ui_docs",
    "ui_empty", "ui_error", "ui_files", "ui_hub", "ui_logs", "ui_reminders",
    "ui_roster", "ui_service", "ui_settings", "ui_submit", "ui_tasks",
    "ui_filetools", "filetools", "tts", "assistant", "ui_pet",
]


# PIL 只在图片转换/缩略图里按需 import；numpy 又是 PIL 的可选依赖，启动路径完全用不到，
# 排掉它能把包体瘦掉约 26MB，减少杀软首次扫描的文件数量。
EXCLUDES = ["numpy", "numpy.libs", "scipy", "pandas", "matplotlib"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main():
    name = "班级操作台-便携"
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onedir", "--windowed", "--name", name]
    for item in HIDDEN:
        args += ["--hidden-import", item]
    for item in EXCLUDES:
        args += ["--exclude-module", item]
    args.append("main.py")
    print("[1/3] PyInstaller onedir")
    subprocess.run(args, cwd=str(ROOT), check=True)

    source = ROOT / "dist" / name
    target = ROOT / "dist" / ("class-console-v%s-portable" % VERSION)
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(source), str(target))
    exe = target / (name + ".exe")
    exe.rename(target / "班级操作台.exe")

    # PyInstaller 有时会把 Win7 时代的 UCRT 运行库一起收进来（ucrtbase.dll 约 1.3MB
    # 加 api-ms-win-*.dll 43 个约 1MB）；本程序只支持 Win10/11，系统自带 UCRT，
    # 删掉不改行为，还能少让杀软扫 44 个文件。
    pruned = 0
    for dll in target.rglob("api-ms-win-*.dll"):
        dll.unlink()
        pruned += 1
    for dll in target.rglob("ucrtbase.dll"):
        dll.unlink()
        pruned += 1
    if pruned:
        print("[2/3] 去掉系统自带 UCRT 文件 %d 个" % pruned)

    zip_path = ROOT / "dist" / ("class-console-v%s-portable.zip" % VERSION)
    if zip_path.exists():
        zip_path.unlink()
    print("[2/3] Zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in target.rglob("*"):
            if item.is_file():
                zf.write(item, Path(target.name) / item.relative_to(target))

    files = [p for p in target.rglob("*") if p.is_file()]
    raw = sum(p.stat().st_size for p in files)
    print("[3/3] Done")
    print("folder=%s files=%d bytes=%d" % (target, len(files), raw))
    print("zip=%s bytes=%d" % (zip_path, zip_path.stat().st_size))
    print("sha256=%s" % sha256(zip_path))


if __name__ == "__main__":
    main()


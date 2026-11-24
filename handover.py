# -*- coding: utf-8 -*-
"""届别交接包：把台账、索引、日志、服务登记和设置打成可带走的 ZIP。"""

import datetime
import hashlib
import json
import os
import zipfile
from pathlib import Path

import archive
from version import VERSION, VERSION_LABEL


BACKUP_NAME = "数据备份.json"
README_NAME = "交接说明.txt"
MANIFEST_NAME = "manifest.json"


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _settings_file():
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "ClassConsole" / "settings.json"


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def export_handover(repo, dest, actor="", role=""):
    """导出交接包；不打包全部归档文件，只带索引与登记。"""
    dest = Path(dest)
    data = repo.backup()
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    root = archive.root()
    index = root / "_归档索引.csv"
    settings = _settings_file()
    counts = {
        "docs": len(data.get("docs") or []),
        "logs": len(data.get("logs") or []),
        "roster": len(data.get("roster") or []),
        "tasks": len(data.get("tasks") or []),
        "exemptions": len(data.get("exemptions") or []),
        "followups": len(data.get("followups") or []),
    }
    readme = """班级操作台 · 届别交接包

这个包用于换届交接，不是材料归档的替代品。

包内文件：
1. 数据备份.json：台账、名单、任务、日志、模板、流转事件、免交 / 延期、催交 / 回执。
2. 归档索引.csv：原学委电脑上归档目录的索引，便于核对文件位置。
3. 设置.json：原电脑的外观、归档目录等设置，只作参照，不会自动覆盖新电脑。
4. manifest.json：版本、生成时间、数量与备份哈希，用来核对包是否完整。

接手步骤：
1. 在新电脑安装同版本或更新版本的班级操作台。
2. 打开设置 → 数据 → 导入交接包，先看数量预览，再确认覆盖。
3. 在设置 → 归档里把归档目录指向本届材料所在文件夹。
4. 打开名单核对，确认人数；打开操作日志，确认服务留痕已带过来。
5. 原学委退出前，确认本届材料、交接包和归档目录都已备份。

注意：交接包不含原始材料文件，只含索引。原始文件请连同归档目录一起拷贝。
"""
    manifest = {
        "app": "班级操作台",
        "version": VERSION,
        "label": VERSION_LABEL,
        "created_at": _now(),
        "archive_root": str(root),
        "counts": counts,
        "backup_sha256": digest,
        "note": "交接包仅含索引，不含原始归档文件。",
    }
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(BACKUP_NAME, payload)
            z.writestr(README_NAME, readme.encode("utf-8"))
            z.writestr(MANIFEST_NAME, json.dumps(
                manifest, ensure_ascii=False, indent=2).encode("utf-8"))
            if index.exists():
                z.write(index, "归档索引.csv")
            if settings.exists():
                z.write(settings, "设置.json")
        os.replace(tmp, dest)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    try:
        repo.add_log("交接包", "%s（材料 %d / 名单 %d）" % (
            dest.name, counts["docs"], counts["roster"]),
            actor or "系统", role or "系统", src="本机")
    except Exception:
        pass
    return {"path": str(dest), "size": dest.stat().st_size, "counts": counts}


def read_handover(path):
    """读取交接包内备份；结构错误抛 ValueError，供界面直接提示。"""
    try:
        with zipfile.ZipFile(path, "r") as z:
            names = z.namelist()
            if BACKUP_NAME not in names:
                raise ValueError("交接包里没有数据备份.json")
            raw = z.read(BACKUP_NAME)
            data = json.loads(raw.decode("utf-8"))
            manifest = {}
            if MANIFEST_NAME in names:
                try:
                    manifest = json.loads(z.read(MANIFEST_NAME).decode("utf-8"))
                except (ValueError, UnicodeError):
                    manifest = {}
            if not isinstance(data, dict):
                raise ValueError("数据备份结构不正确")
            data["_handover_manifest"] = manifest
            return data
    except zipfile.BadZipFile:
        raise ValueError("不是有效的交接包 ZIP 文件")
    except OSError:
        raise ValueError("交接包无法读取（文件被占用或没有读取权限）")
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("交接包里的数据备份不是有效的 UTF-8 JSON")


def handover_summary(data):
    manifest = data.get("_handover_manifest") or {}
    counts = manifest.get("counts") or {}
    if not counts:
        counts = {
            "docs": len(data.get("docs") or []),
            "roster": len(data.get("roster") or []),
            "exemptions": len(data.get("exemptions") or []),
            "followups": len(data.get("followups") or []),
        }
    return "交接包版本：v%s %s\n生成时间：%s\n材料 %d 条 · 名单 %d 人 · 免交 / 延期 %d 条 · 催交 / 回执 %d 条\n原归档目录：%s" % (
        manifest.get("version") or VERSION,
        manifest.get("label") or VERSION_LABEL,
        manifest.get("created_at") or "未知",
        counts.get("docs", 0), counts.get("roster", 0),
        counts.get("exemptions", 0), counts.get("followups", 0),
        manifest.get("archive_root") or "未记录")

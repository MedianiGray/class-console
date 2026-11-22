# -*- coding: utf-8 -*-
"""归档落盘：按 类别 / 学号-姓名 / 材料文件 把材料归位到指定根目录。

目录约定（可在设置里改根目录）：
    归档根 / 团务材料 / 250222-刘一帆 / 体测成绩统计表.pdf
    归档根 / _归档索引.csv        ← 台账与文件的对照表，随归档刷新
"""
import csv
import os
import re
import shutil
from pathlib import Path

import theme

BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')
INDEX_NAME = "_归档索引.csv"


def safe(text, fallback="未命名", limit=60):
    """把材料名/姓名压成合法文件夹名。"""
    s = BAD_CHARS.sub("_", (text or "").strip()).strip(" .")
    s = re.sub(r"_{2,}", "_", s)
    return (s[:limit] or fallback)


def default_root():
    return Path(os.path.expanduser("~")) / "Documents" / "班级材料归档"


def root():
    """归档根目录：设置里选过就用，否则给默认路径（不自动建目录）。"""
    raw = theme.load_ui("archive_root", "")
    return Path(raw) if raw else default_root()


def save_root(path):
    theme.save_ui("archive_root", str(path))


def auto_copy():
    return bool(theme.load_ui("archive_copy", True))


def set_auto_copy(flag):
    theme.save_ui("archive_copy", bool(flag))


def category_dir(doc, base=None):
    return (Path(base) if base else root()) / safe(doc.get("cat"), "未分类")


def person_dir(doc, base=None):
    sid = safe(doc.get("sid"), "")
    who = safe(doc.get("who"), "")
    if sid and who:
        label = "%s-%s" % (sid, who)
    else:
        label = who or sid or "待补学号"
    return category_dir(doc, base) / label


def source_file(doc):
    """优先取台账 path 字段，其次附件里的本地文件。"""
    for key in ("path", "file"):
        v = (doc.get(key) or "").strip()
        if v and os.path.isfile(v):
            return v
    for att in (doc.get("attachments") or []):
        v = (att.get("path") or "").strip()
        if v and os.path.isfile(v):
            return v
    return ""


def target_for(doc, base=None):
    """返回目标文件路径；没有本地文件时返回空串（只建目录）。"""
    src = source_file(doc)
    if not src:
        return ""
    ext = os.path.splitext(src)[1]
    stem = safe(doc.get("name"), "材料", 50)
    code = safe(doc.get("code"), "", 24)
    fname = "%s_%s%s" % (code, stem, ext) if code else stem + ext
    return person_dir(doc, base) / fname


def place(doc, base=None, copy_files=None):
    """把一条材料归位：建目录 + 复制文件（同名同大小视为已归位）。

    返回 dict：dir / path / copied / note
    """
    do_copy = auto_copy() if copy_files is None else bool(copy_files)
    pdir = person_dir(doc, base)
    try:
        pdir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"dir": str(pdir), "path": "", "copied": False, "note": "建目录失败：%s" % e}
    tgt = target_for(doc, base)
    if not tgt:
        return {"dir": str(pdir), "path": "", "copied": False, "note": "无本地文件，仅建目录"}
    if not do_copy:
        return {"dir": str(pdir), "path": str(tgt), "copied": False, "note": "已关闭自动复制"}
    src = source_file(doc)
    try:
        if os.path.exists(tgt):
            if os.path.getsize(tgt) == os.path.getsize(src):
                return {"dir": str(pdir), "path": str(tgt), "copied": False,
                        "note": "已存在，跳过"}
            # 同名不同内容：递进编号，绝不覆盖已有归档文件
            stem, ext = os.path.splitext(tgt)
            n = 2
            while True:
                cand = Path("%s_v%d%s" % (stem, n, ext))
                if not os.path.exists(cand):
                    tgt = cand
                    break
                n += 1
        shutil.copy2(src, tgt)
    except (OSError, shutil.Error) as e:
        return {"dir": str(pdir), "path": "", "copied": False, "note": "复制失败：%s" % e}
    return {"dir": str(pdir), "path": str(tgt), "copied": True, "note": "已复制"}


def write_index(docs, base=None):
    """在归档根写一份台账对照表，方便脱离软件也能按文件找材料。"""
    base = Path(base) if base else root()
    try:
        base.mkdir(parents=True, exist_ok=True)
        with open(base / INDEX_NAME, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["编号", "材料名称", "类别", "学号", "姓名", "状态",
                        "本地文件", "归档文件"])
            for d in docs:
                w.writerow([d.get("code", ""), d.get("name", ""), d.get("cat", ""),
                            d.get("sid", ""), d.get("who", ""), d.get("status", ""),
                            d.get("path") or d.get("file") or "", d.get("arch") or ""])
        return str(base / INDEX_NAME)
    except OSError:
        return ""


def open_folder(path):
    try:
        os.startfile(str(path))
        return True
    except OSError:
        return False

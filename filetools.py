# -*- coding: utf-8 -*-
"""文件工具：批量重命名、图片格式转换、按类别归位。

三条原则贯穿全部操作：
  - 只动归档根内的文件，根外的路径一律拒绝（不碰用户的其它目录）；
  - 先出预览再执行，写入前不产生任何副作用；
  - 同名绝不覆盖，冲突时自动避让并显式标注；重命名可整体撤销。

本模块不依赖界面，也不直接写日志；调用方拿返回值决定怎么记。
"""

import datetime
import os
import re
import shutil
from pathlib import Path

import archive
import fileroom

TMP_SUFFIX = ".ccrtmp"
MAX_UNIQUE = 200
CONVERT_TARGETS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


def base_root(base=None):
    return Path(base) if base else Path(archive.root())


# ---------------- 公共过滤 ----------------

def filter_targets(paths, base=None):
    """把一批路径分成「可操作」与「带原因跳过」两拨。"""
    base = base_root(base)
    keep, skipped = [], []
    for raw in paths or []:
        path = str(raw or "").strip()
        if not path:
            continue
        if not os.path.exists(path):
            skipped.append({"src": path, "state": "skip", "reason": "文件不存在"})
            continue
        if not fileroom.is_within(base, path):
            skipped.append({"src": path, "state": "skip",
                            "reason": "不在归档目录内，不处理"})
            continue
        if not os.path.isfile(path):
            skipped.append({"src": path, "state": "skip", "reason": "不是文件"})
            continue
        keep.append(os.path.abspath(path))
    return keep, skipped


def _tokens(text, stem, index):
    """支持 {date} / {name} / {n} 三个占位，写错也不会崩。"""
    today = datetime.date.today().strftime("%Y%m%d")
    return (str(text or "").replace("{date}", today)
            .replace("{name}", stem).replace("{n}", str(index)))


def _occupied(folder, batch_srcs):
    """目录里已经占用的名字，排除本批次即将让位的源文件。"""
    freed = {fileroom.norm(p) for p in batch_srcs}
    try:
        names = os.listdir(folder)
    except OSError:
        return set()
    out = set()
    for name in names:
        full = fileroom.norm(os.path.join(folder, name))
        if full in freed:
            continue
        out.add(full)
    return out


# ---------------- 批量重命名 ----------------

def rename_plan(paths, opts=None, base=None):
    """按规则算出每个文件的新名字，不落盘。

    opts:
      prefix / suffix      前后缀，支持 {date} {name} {n}
      replace / pattern / repl  正则替换（作用在去掉扩展名的主干上）
      seq / seq_start / seq_step / seq_pad / seq_pos
      sort                 name | mtime
    """
    opts = dict(opts or {})
    keep, skipped = filter_targets(paths, base)
    sort_key = "mtime" if str(opts.get("sort") or "name") == "mtime" else "name"
    keep.sort(key=(lambda p: os.path.getmtime(p)) if sort_key == "mtime"
              else (lambda p: os.path.basename(p).lower()))

    prefix, suffix = opts.get("prefix") or "", opts.get("suffix") or ""
    use_re = bool(opts.get("replace"))
    pattern = opts.get("pattern") or ""
    repl = opts.get("repl") or ""
    if use_re:
        try:
            re.compile(pattern)
        except re.error as e:
            return {"rows": [{"src": p, "state": "fail",
                              "reason": "正则不可用：%s" % e} for p in keep] + skipped,
                    "ok": 0}

    seq = bool(opts.get("seq"))
    try:
        seq_start = int(opts.get("seq_start") or 1)
        seq_step = int(opts.get("seq_step") or 1)
        seq_pad = max(1, min(6, int(opts.get("seq_pad") or 2)))
    except (TypeError, ValueError):
        seq, seq_start, seq_step, seq_pad = False, 1, 1, 2
    seq_pos = str(opts.get("seq_pos") or "after")

    by_folder = {}
    for p in keep:
        by_folder.setdefault(os.path.dirname(p), []).append(p)
    occupied = {folder: _occupied(folder, items) for folder, items in by_folder.items()}
    assigned = {}
    rows = list(skipped)
    changed = 0

    for index, src in enumerate(keep, start=1):
        folder = os.path.dirname(src)
        name = os.path.basename(src)
        stem, ext = os.path.splitext(name)
        new_stem = stem
        if use_re:
            try:
                new_stem = re.sub(pattern, repl, stem)
            except re.error as e:
                rows.append({"src": src, "dst": src, "state": "fail",
                             "reason": "正则执行失败：%s" % e})
                continue
        new_stem = _tokens(prefix, stem, index) + new_stem + _tokens(suffix, stem, index)
        if seq:
            number = str(seq_start + (index - 1) * seq_step).zfill(seq_pad)
            if seq_pos == "replace":
                new_stem = number
            elif seq_pos == "before":
                new_stem = "%s-%s" % (number, new_stem)
            else:
                new_stem = "%s-%s" % (new_stem, number)
        new_stem = new_stem.strip().strip(".")
        if not new_stem:
            rows.append({"src": src, "dst": src, "state": "skip",
                         "reason": "规则算出的名字是空的，已跳过"})
            continue
        new_name = new_stem + ext
        if new_name == name:
            rows.append({"src": src, "dst": src, "state": "skip",
                         "reason": "名字没有变化"})
            continue

        target = os.path.join(folder, new_name)
        taken = occupied.get(folder, set()) | assigned.setdefault(folder, set())
        note = ""
        n = 1
        while fileroom.norm(target) in taken:
            n += 1
            if n > MAX_UNIQUE:
                break
            target = os.path.join(folder, "%s-%d%s" % (new_stem, n, ext))
            note = "与已有文件同名，已自动避让"
        if n > MAX_UNIQUE:
            rows.append({"src": src, "dst": src, "state": "fail",
                         "reason": "同名文件太多，没有安全的名字可用"})
            continue
        assigned[folder].add(fileroom.norm(target))
        changed += 1
        rows.append({"src": src, "dst": target,
                     "old": name, "new": os.path.basename(target),
                     "state": "ok", "reason": note})
    return {"rows": rows, "ok": changed}


def _two_phase(pairs):
    """先把源改成临时名，再改成目标，避免 a→b、b→a 这类互相占用。"""
    moved, failed = [], []
    staged = []
    for i, (src, dst) in enumerate(pairs):
        tmp = src + TMP_SUFFIX + str(i)
        try:
            os.rename(src, tmp)
            staged.append((tmp, dst, src))
        except OSError as e:
            failed.append({"src": src, "dst": dst, "reason": "改名前失败：%s" % e})
    for tmp, dst, src in staged:
        try:
            os.rename(tmp, dst)
            moved.append((src, dst))
        except OSError as e:
            failed.append({"src": src, "dst": dst, "reason": "改名失败：%s" % e})
            try:
                os.rename(tmp, src)
            except OSError:
                pass
    return moved, failed


def rename_apply(rows):
    """执行预览里状态为 ok 的条目，返回 {ok, failed, undo}。"""
    pending = [r for r in rows if r.get("state") == "ok" and r.get("dst")]
    moved, failed = _two_phase([(r["src"], r["dst"]) for r in pending])
    undo = [{"from": dst, "to": src} for src, dst in moved]
    return {"ok": len(moved), "failed": failed, "undo": undo}


def undo_apply(undo):
    """把一批改名原路撤回；撤回失败会保留当前状态并回报原因。"""
    pairs = [(item["from"], item["to"]) for item in (undo or [])
             if os.path.exists(item.get("from"))]
    moved, failed = _two_phase(pairs)
    return {"ok": len(moved), "failed": failed}


# ---------------- 图片格式转换 ----------------

def convert_plan(paths, target="JPEG", base=None):
    """列出哪些文件能转、会落到哪；非图片与已在目标格式的直接标跳过。"""
    ext = CONVERT_TARGETS.get(str(target).upper())
    if not ext:
        return {"rows": [{"src": p, "state": "fail",
                          "reason": "不支持的格式：%s" % target} for p in (paths or [])],
                "ok": 0, "target": target}
    keep, skipped = filter_targets(paths, base)
    rows = list(skipped)
    count = 0
    for src in keep:
        folder = os.path.dirname(src)
        stem, old_ext = os.path.splitext(os.path.basename(src))
        if old_ext.lower() not in fileroom.IMAGE_EXTS:
            rows.append({"src": src, "state": "skip", "reason": "不是图片"})
            continue
        if old_ext.lower() == ext.lower():
            rows.append({"src": src, "state": "skip", "reason": "已经是目标格式"})
            continue
        dst = os.path.join(folder, stem + ext)
        n = 1
        while os.path.exists(dst):
            n += 1
            if n > MAX_UNIQUE:
                break
            dst = os.path.join(folder, "%s-%d%s" % (stem, n, ext))
        rows.append({"src": src, "dst": dst, "state": "ok",
                     "reason": "" if n == 1 else "同名，已自动避让"})
        count += 1
    return {"rows": rows, "ok": count, "target": str(target).upper()}


def convert_apply(rows, quality=88, delete_original=False):
    """真正转码；先写新文件再删原件，任何一步失败都不动原件。"""
    try:
        from PIL import Image
    except ImportError:
        return {"ok": 0, "failed": [{"src": r.get("src"), "dst": r.get("dst"),
                                     "reason": "本机没有 Pillow，无法转换"}
                                    for r in rows if r.get("state") == "ok"]}
    target = ""
    pending = []
    for row in rows or []:
        if row.get("state") != "ok" or not row.get("dst"):
            continue
        target = os.path.splitext(row["dst"])[1].lower()
        pending.append(row)
    ok, failed = 0, []
    for row in pending:
        src, dst = row["src"], row["dst"]
        try:
            with Image.open(src) as im:
                frames = getattr(im, "n_frames", 1)
                if frames > 1:
                    im.seek(0)
                work = im.copy()
                if target in (".jpg", ".jpeg") and work.mode in ("RGBA", "LA", "P"):
                    work = work.convert("RGB")
                elif target == ".png" and work.mode == "P":
                    work = work.convert("RGBA")
                params = {}
                if target in (".jpg", ".jpeg"):
                    params = {"quality": int(quality), "optimize": True}
                elif target == ".webp":
                    params = {"quality": int(quality)}
                else:
                    params = {"optimize": True}
                work.save(dst, **params)
        except Exception as e:  # 损坏图片、权限、磁盘满都在这里兜住
            failed.append({"src": src, "dst": dst, "reason": "%s" % e})
            try:
                if os.path.exists(dst):
                    os.remove(dst)
            except OSError:
                pass
            continue
        if delete_original:
            try:
                os.remove(src)
            except OSError as e:
                failed.append({"src": src, "dst": dst,
                               "reason": "新文件已生成，但删原件失败：%s" % e})
                continue
        ok += 1
    return {"ok": ok, "failed": failed}


# ---------------- 按类别归位 ----------------

def organize_plan(paths, docs, base=None):
    """已登记的文件按台账类别归进「归档根/类别/」，未登记的先跳过。"""
    base = base_root(base)
    maps = fileroom.doc_maps(docs or [], base)
    keep, skipped = filter_targets(paths, base)
    rows = list(skipped)
    count = 0
    for src in keep:
        doc = maps["paths"].get(fileroom.norm(src))
        if not doc:
            rows.append({"src": src, "state": "skip",
                         "reason": "台账里没有这份文件，先登记再归位"})
            continue
        cat = str(doc.get("cat") or "").strip() or "未分类"
        folder = base / cat
        name = os.path.basename(src)
        if fileroom.norm(os.path.join(str(folder), name)) == fileroom.norm(src):
            rows.append({"src": src, "state": "skip", "reason": "已经在类别目录里"})
            continue
        target = fileroom.unique_target(folder, name)
        rows.append({"src": src, "dst": str(target), "state": "ok",
                     "cat": cat, "doc_id": doc.get("id"),
                     "reason": "" if Path(target).name == name else "同名，已自动避让"})
        count += 1
    return {"rows": rows, "ok": count}


def organize_apply(rows):
    """移动文件；成功一条就回报一条，调用方据此更新台账路径。"""
    ok, failed, done = 0, [], []
    for row in rows or []:
        if row.get("state") != "ok" or not row.get("dst"):
            continue
        try:
            shutil.move(row["src"], row["dst"])
        except (OSError, shutil.Error) as e:
            failed.append({"src": row["src"], "dst": row["dst"], "reason": "%s" % e})
            continue
        ok += 1
        done.append({"src": row["src"], "dst": row["dst"],
                     "doc_id": row.get("doc_id")})
    return {"ok": ok, "failed": failed, "done": done}


# ---------------- 汇总 ----------------

def summarize(rows):
    """把预览结果压成一句人话，界面顶部直接显示。"""
    ok = sum(1 for r in rows if r.get("state") == "ok")
    skip = sum(1 for r in rows if r.get("state") == "skip")
    fail = sum(1 for r in rows if r.get("state") == "fail")
    parts = ["%d 个待执行" % ok]
    if skip:
        parts.append("%d 个跳过" % skip)
    if fail:
        parts.append("%d 个有问题" % fail)
    return " · ".join(parts)

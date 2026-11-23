# -*- coding: utf-8 -*-
"""文件室：把归档目录、台账与索引放在同一张图上。

本模块不依赖界面，负责：
  - 扫描归档根目录与子目录，给每个文件标出「台账有 / 索引有 / 未登记」；
  - 按当前目录反推类别与学生，生成缺失文件清单；
  - 把拖入或选中的文件复制到当前目录并登记台账；
  - 同名不覆盖，所有写操作限定在归档根内。

界面只负责展示与确认；文件复制、编号与索引刷新都在这里完成。
"""

import csv
import datetime
import os
import re
import shutil
from pathlib import Path

import archive

INDEX_NAME = archive.INDEX_NAME
MAX_SCAN = 5000
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log", ".xml", ".ini", ".yml", ".yaml"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
PDF_EXTS = {".pdf"}
STUDENT_RE = re.compile(r"^([0-9A-Za-z]+)\s*-\s*(.+)$")


def norm(path):
    text = str(path or "").strip()
    if not text:
        return ""
    return os.path.normcase(os.path.abspath(text))


def is_within(base, path):
    try:
        base = Path(base).resolve()
        target = Path(path).resolve()
    except (OSError, ValueError):
        return False
    return target == base or base in target.parents


def human_size(size):
    try:
        n = float(size or 0)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024
    return ""


def human_time(value):
    try:
        return datetime.datetime.fromtimestamp(float(value)).strftime(
            "%Y-%m-%d %H:%M")
    except (OSError, OverflowError, TypeError, ValueError):
        return ""


def split_rel(rel):
    return [p for p in re.split(r"[\\/]+", str(rel or "")) if p]


def join_rel(*parts):
    return "/".join(p for p in parts if p)


def _reader(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def read_index(base=None):
    path = Path(base) if base else archive.root()
    return _reader(path / INDEX_NAME)


def index_maps(base=None):
    """索引里本地文件与归档文件两列都能反查。"""
    by_path, by_code = {}, {}
    for row in read_index(base):
        code = str(row.get("编号") or "").strip()
        if code:
            by_code[code] = row
        for key in ("归档文件", "本地文件"):
            p = str(row.get(key) or "").strip()
            if p:
                by_path[norm(p)] = row
    return {"paths": by_path, "codes": by_code}


def doc_maps(docs, base=None):
    """一条材料可能同时有源文件与归档文件，都建立路径映射。"""
    by_path, by_code = {}, {}
    base = Path(base) if base else archive.root()
    for d in docs:
        if not isinstance(d, dict):
            continue
        code = str(d.get("code") or "").strip()
        if code:
            by_code[code] = d
        for key in ("arch", "path", "file"):
            raw = str(d.get(key) or "").strip()
            if not raw:
                continue
            p = raw if os.path.isabs(raw) else str(base / raw)
            by_path[norm(p)] = d
        for att in (d.get("attachments") or []):
            raw = str((att or {}).get("path") or "").strip()
            if raw:
                by_path[norm(raw)] = d
    return {"paths": by_path, "codes": by_code}


def _abs_path(raw, base):
    text = str(raw or "").strip()
    if not text:
        return ""
    return text if os.path.isabs(text) else str(Path(base) / text)


def build_status(docs, base=None):
    """返回文件状态所需的映射与缺失清单，一次读取供整个视图复用。"""
    base = Path(base) if base else archive.root()
    dm = doc_maps(docs, base)
    im = index_maps(base)
    missing = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        status = str(d.get("status") or "")
        arch = _abs_path(d.get("arch"), base)
        if status != "已归档" and not arch:
            continue
        if not arch:
            missing.append({
                "code": d.get("code") or "", "name": d.get("name") or "未命名",
                "cat": d.get("cat") or "", "who": d.get("who") or "",
                "sid": d.get("sid") or "", "detail": "已归档但未记录归档路径",
                "doc": d})
        elif not os.path.exists(arch):
            missing.append({
                "code": d.get("code") or "", "name": d.get("name") or "未命名",
                "cat": d.get("cat") or "", "who": d.get("who") or "",
                "sid": d.get("sid") or "", "detail": arch, "doc": d})
    missing.sort(key=lambda x: (x["who"], x["code"]))
    return {"docs": dm, "index": im, "missing": missing}


def file_status(path, maps):
    key = norm(path)
    doc = maps["docs"]["paths"].get(key)
    row = maps["index"]["paths"].get(key)
    if doc:
        state = "台账有"
        code = str(doc.get("code") or "")
        label = str(doc.get("name") or "")
        who, sid, cat = doc.get("who") or "", doc.get("sid") or "", doc.get("cat") or ""
    elif row:
        state = "仅索引"
        code = str(row.get("编号") or "")
        label = str(row.get("材料名称") or "")
        who, sid, cat = row.get("姓名") or "", row.get("学号") or "", row.get("类别") or ""
    else:
        state = "未登记"
        code = label = who = sid = cat = ""
    return {"state": state, "code": code, "label": label,
            "who": who, "sid": sid, "cat": cat, "indexed": bool(doc or row)}


def list_files(base, rel="", q="", limit=MAX_SCAN):
    """列出当前目录文件；有关键词时在整个归档根内搜文件名。"""
    base = Path(base) if base else archive.root()
    if not base.exists():
        return []
    folder = base if not rel else base / rel
    rows = []
    candidates = []
    if q:
        try:
            candidates = sorted(base.rglob("*"))
        except OSError:
            candidates = []
    else:
        try:
            candidates = sorted(folder.iterdir())
        except OSError:
            return []
    needle = str(q or "").strip().lower()
    for p in candidates:
        if len(rows) >= limit:
            break
        if not p.is_file() or p.name == INDEX_NAME:
            continue
        try:
            relp = str(p.relative_to(base)).replace("\\", "/")
        except ValueError:
            continue
        if needle and needle not in p.name.lower() and needle not in relp.lower():
            continue
        try:
            st = p.stat()
            size, mtime = st.st_size, st.st_mtime
        except OSError:
            size, mtime = 0, 0
        rows.append({"path": str(p), "rel": relp, "name": p.name,
                     "size": size, "mtime": mtime, "dir": str(Path(relp).parent)
                     if "\\" in relp or "/" in relp else "",
                     "is_index": False})
    rows.sort(key=lambda x: (x["dir"].lower(), x["name"].lower()))
    return rows


def tree_dirs(base, limit=500):
    """递归列出归档根下的目录，按相对路径排序，供左侧树构建。"""
    base = Path(base) if base else archive.root()
    if not base.exists():
        return []
    nodes = []
    stack = [("", base)]
    while stack and len(nodes) < limit:
        rel, folder = stack.pop()
        try:
            entries = sorted([p for p in folder.iterdir() if p.is_dir()],
                             key=lambda p: p.name.lower())
        except OSError:
            continue
        for p in entries:
            child = join_rel(rel, p.name)
            nodes.append({"rel": child, "name": p.name,
                          "parent": rel, "depth": len(split_rel(child))})
            stack.append((child, p))
    nodes.sort(key=lambda x: x["rel"].lower())
    return nodes


def _cat_from_rel(rel, rules=None):
    rules = rules or archive.load_rule()
    parts = split_rel(rel)
    text = "/".join(parts)
    candidates = []
    for cat, mapped in (rules.get("category_map") or {}).items():
        mapped_parts = split_rel(mapped)
        if mapped_parts and parts[:len(mapped_parts)] == mapped_parts:
            candidates.append((len(mapped_parts), cat))
    if candidates:
        return max(candidates)[1], max(candidates)[0]
    if parts:
        return parts[0], 1
    return "", 0


def infer_context(rel, roster=None, rules=None):
    """从「类别/学号-姓名」目录反推类别与学生；推不出就留空。"""
    roster = roster or []
    cat, skip = _cat_from_rel(rel, rules)
    parts = split_rel(rel)
    sid, who = "", ""
    if len(parts) > skip:
        seg = parts[skip]
        m = STUDENT_RE.match(seg)
        if m:
            sid, who = m.group(1).strip(), m.group(2).strip()
        else:
            for r in roster:
                if str(r.get("sid") or "") == seg or str(r.get("who") or "") == seg:
                    sid, who = str(r.get("sid") or ""), str(r.get("who") or "")
                    break
            if not who and seg:
                who = seg
    return {"cat": cat, "sid": sid, "who": who, "complete": bool(cat and who),
            "rel": rel}


def target_dir(base, rel, cat, sid, who):
    """当前目录已经是完整材料目录就落原处，否则按归档规则算出材料目录。"""
    base = Path(base) if base else archive.root()
    ctx = infer_context(rel)
    if ctx["complete"] and (not cat or ctx["cat"] == cat) \
            and (not who or ctx["who"] == who):
        folder = base / rel
        try:
            folder.resolve().relative_to(base.resolve())
            return folder
        except (ValueError, OSError):
            pass
    doc = {"cat": cat, "sid": sid, "who": who, "code": "", "name": "", "status": ""}
    try:
        return archive.folder_for(doc, base=base)
    except ValueError:
        return base


def unique_target(folder, filename):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    if not target.exists():
        return target
    stem, ext = os.path.splitext(filename)
    n = 2
    while True:
        cand = folder / ("%s_v%d%s" % (stem, n, ext))
        if not cand.exists():
            return cand
        n += 1


def expand_paths(paths, limit=200):
    """把文件 / 文件夹混合的拖入项展开成文件列表，最多 200 个。"""
    out = []
    for raw in paths:
        p = Path(str(raw or ""))
        if not p.exists():
            continue
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            try:
                out.extend(sorted(x for x in p.rglob("*") if x.is_file()))
            except OSError:
                continue
        if len(out) >= limit:
            return out[:limit]
    return out


def register_files(repo, paths, base=None, rel="", cat="", sid="", who="",
                   actor="", role="", note="文件室登记", copy_files=True):
    """把文件落到当前/规则目录并逐条入账。

    返回 dict：ok（成功条数）、failed（失败明细）、targets（落点）、dir。
    只复制，不移动源文件；同名不同内容自动加 _v2，绝不覆盖。
    """
    base = Path(base) if base else archive.root()
    files = expand_paths(paths)
    if not files:
        return {"ok": 0, "failed": [], "targets": [], "dir": ""}
    if not cat or not who:
        ctx = infer_context(rel)
        cat = cat or ctx["cat"]
        who = who or ctx["who"]
        sid = sid or ctx["sid"]
    if not cat or not who:
        raise ValueError("需要类别与学生姓名才能登记")
    folder = target_dir(base, rel, cat, sid, who)
    folder.mkdir(parents=True, exist_ok=True)
    targets, failed = [], []
    for src in files:
        try:
            same = Path(src).resolve() == (folder / src.name).resolve() \
                and (folder / src.name).exists()
            if same:
                target = folder / src.name
            else:
                target = unique_target(folder, src.name)
                shutil.copy2(str(src), str(target))
            doc_id = repo.add_doc({
                "name": os.path.splitext(src.name)[0], "cat": cat,
                "who": who, "sid": sid, "note": note, "file": target.name,
                "path": str(target), "scope": "全员", "actor": actor,
                "actor_role": role or "本机"})
            targets.append({"id": doc_id, "path": str(target), "name": src.name})
        except Exception as e:
            failed.append({"name": src.name, "detail": str(e)})
    if targets:
        try:
            repo.add_log("文件室登记", "%d 份 · %s · %s" % (
                len(targets), who, cat), actor or who, role or "本机")
        except Exception:
            pass
    return {"ok": len(targets), "failed": failed, "targets": targets,
            "dir": str(folder)}


def preview_kind(path):
    ext = os.path.splitext(str(path or ""))[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in TEXT_EXTS:
        return "text"
    return "other"


def read_text(path, limit=200):
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read(limit * 6)
    except OSError:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def summary(docs, base=None):
    """文件室顶部的几个数字：材料、归档、缺失、目录、文件。"""
    base = Path(base) if base else archive.root()
    built = build_status(docs, base)
    archived = sum(1 for d in docs if d.get("status") == "已归档")
    dirs = len(tree_dirs(base))
    files = len(list_files(base, "", "", limit=MAX_SCAN))
    return {"docs": len(docs), "archived": archived,
            "missing": len(built["missing"]), "dirs": dirs, "files": files,
            "root": str(base)}

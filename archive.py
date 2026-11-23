# -*- coding: utf-8 -*-
"""归档落盘：按可配置规则把材料归位到指定根目录。

默认规则保持旧口径：
    归档根 / 类别 / 学号-姓名 / 编号_材料名.pdf
    归档根 / _归档索引.csv        ← 台账与文件的对照表，随归档刷新

规则可改目录模板、文件名模板与类别映射；模板变量见 RULE_VARS。
所有写操作限定在归档根内，非法模板与越界路径直接拒绝。
"""
import csv
import datetime
import os
import re
import shutil
import subprocess
from pathlib import Path

import theme

BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
INDEX_NAME = "_归档索引.csv"
RULE_KEY = "archive_rule"

DEFAULT_RULE = {
    "dir_template": "{category}/{student}",
    "file_template": "{code}_{name}",
    "category_map": {},
}

RULE_VARS = {
    "category": "类别对应子目录（先查类别映射）",
    "cat": "台账里的原始类别",
    "student": "学号-姓名，缺项自动兜底",
    "sid": "学号",
    "who": "姓名",
    "code": "材料编号",
    "name": "材料名称",
    "status": "审核状态",
    "date": "归档日期 YYYY-MM-DD",
    "ext": "原文件扩展名（含点）",
}


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


def default_rule():
    return {"dir_template": DEFAULT_RULE["dir_template"],
            "file_template": DEFAULT_RULE["file_template"],
            "category_map": {}}


def _clean_map(raw):
    out = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        key = str(k or "").strip()
        val = str(v or "").replace("\\", "/").strip().strip("/")
        if not key or not val:
            continue
        if val.startswith("/") or re.match(r"^[A-Za-z]:", val):
            raise ValueError("类别映射不能使用绝对路径：%s" % key)
        if any(seg.strip() == ".." for seg in val.split("/")):
            raise ValueError("类别映射不能包含 ..：%s" % key)
        out[key] = val
    return out


def normalize_rule(raw):
    """把外部数据收敛成合法结构；未知字段忽略，缺字段回默认。"""
    if not isinstance(raw, dict):
        return default_rule()
    dir_tpl = (DEFAULT_RULE["dir_template"] if "dir_template" not in raw
               else str(raw.get("dir_template") or "")).strip()
    file_tpl = (DEFAULT_RULE["file_template"] if "file_template" not in raw
                else str(raw.get("file_template") or "")).strip()
    return {"dir_template": dir_tpl, "file_template": file_tpl,
            "category_map": _clean_map(raw.get("category_map"))}


def validate_rule(raw):
    """校验模板变量与安全性，返回收敛后的规则；不合法抛 ValueError。"""
    rule = normalize_rule(raw)
    for label, tpl, is_file in (("目录模板", rule["dir_template"], False),
                                ("文件名模板", rule["file_template"], True)):
        if not tpl:
            raise ValueError("%s不能为空" % label)
        if tpl.count("{") != len(PLACEHOLDER.findall(tpl)) or tpl.count("}") != len(PLACEHOLDER.findall(tpl)):
            raise ValueError("%s存在未闭合的变量，请用 {变量名} 写法" % label)
        for name in PLACEHOLDER.findall(tpl):
            if name not in RULE_VARS:
                raise ValueError("%s含未知变量 {%s}" % (label, name))
        if tpl.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", tpl):
            raise ValueError("%s必须是相对路径" % label)
        if any(seg.strip() == ".." for seg in re.split(r"[\\/]+", tpl)):
            raise ValueError("%s不能包含 .." % label)
        if is_file and re.search(r"[\\/]", tpl):
            raise ValueError("文件名模板不能带目录分隔符")
    return rule


def load_rule():
    raw = theme.load_ui(RULE_KEY, {})
    try:
        return validate_rule(raw)
    except ValueError:
        return default_rule()


def save_rule(raw):
    rule = validate_rule(raw)
    theme.save_ui(RULE_KEY, rule)
    return rule


def rule_vars(doc, rules=None, ext=""):
    rules = rules or load_rule()
    cat = (doc.get("cat") or "").strip() or "未分类"
    mapped = rules["category_map"].get(cat) or cat
    sid = (doc.get("sid") or "").strip()
    who = (doc.get("who") or "").strip()
    student = ("%s-%s" % (sid, who)) if (sid and who) else (who or sid or "待补学号")
    return {
        "category": mapped, "cat": cat, "student": student,
        "sid": sid, "who": who,
        "code": (doc.get("code") or "").strip(),
        "name": (doc.get("name") or "").strip() or "材料",
        "status": (doc.get("status") or "").strip(),
        "date": datetime.date.today().isoformat(),
        "ext": ext,
    }


def _substitute(tpl, values):
    def repl(m):
        return str(values.get(m.group(1), ""))
    return PLACEHOLDER.sub(repl, tpl)


def _split_path(text):
    parts = [p for p in re.split(r"[\\/]+", text) if p.strip()]
    if not parts:
        raise ValueError("模板渲染后为空")
    return [safe(p, "未命名", 70) for p in parts]


def folder_parts(doc, rules=None):
    rules = rules or load_rule()
    text = _substitute(rules["dir_template"], rule_vars(doc, rules))
    if "{" in text or "}" in text:
        raise ValueError("目录模板存在未替换变量")
    return _split_path(text)


def safe_join(base, parts):
    base_path = Path(base).resolve()
    target = base_path.joinpath(*parts).resolve()
    if target != base_path and base_path not in target.parents:
        raise ValueError("归档路径越出归档根目录")
    return target


def folder_for(doc, base=None, rules=None):
    return safe_join(Path(base) if base else root(), folder_parts(doc, rules))


def category_dir(doc, base=None, rules=None):
    """类别对应目录；保留旧接口，按新类别映射生成。"""
    rules = rules or load_rule()
    cat = rules["category_map"].get((doc.get("cat") or "").strip() or "未分类") \
        or (doc.get("cat") or "").strip() or "未分类"
    return safe_join(Path(base) if base else root(), _split_path(cat))


def person_dir(doc, base=None, rules=None):
    """兼容旧名：按目录模板生成完整材料目录。"""
    return folder_for(doc, base, rules)


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


def clean_ext(ext):
    s = re.sub(r"[^A-Za-z0-9.]", "", ext or "")
    return s if s.startswith(".") and len(s) <= 12 else ""


def file_name(doc, ext="", rules=None):
    """按文件名模板生成文件名；模板含 {ext} 时不再自动追加扩展名。"""
    rules = rules or load_rule()
    ext = clean_ext(ext)
    tpl = rules["file_template"]
    values = rule_vars(doc, rules, ext)
    uses_ext = "{ext}" in tpl
    sentinel = "\x00EXT\x00"
    text = _substitute(tpl.replace("{ext}", sentinel), values)
    if "{" in text or "}" in text:
        raise ValueError("文件名模板存在未替换变量")
    stem = safe(text.replace(sentinel, ""), "材料", 80)
    if not values["code"] and "{code}" in tpl:
        stem = re.sub(r"^[_\\-\\s]+", "", stem) or values["name"]
    if uses_ext:
        stem = (stem + ext).strip()
    else:
        stem += ext
    if not stem:
        raise ValueError("文件名模板渲染后为空")
    return stem


def preview_path(doc, base=None, rules=None, ext=None):
    """给设置页做路径预览；没有本地文件时用 .pdf 示例扩展名。"""
    src = source_file(doc)
    suffix = ext if ext is not None else (os.path.splitext(src)[1] if src else ".pdf")
    folder = folder_for(doc, base, rules)
    return str(folder / file_name(doc, suffix, rules))


def target_for(doc, base=None, rules=None):
    """返回目标文件路径；没有本地文件时返回空串（只建目录）。"""
    src = source_file(doc)
    if not src:
        return ""
    return folder_for(doc, base, rules) / file_name(doc, os.path.splitext(src)[1], rules)


def place(doc, base=None, copy_files=None):
    """把一条材料归位：建目录 + 复制文件（同名同大小视为已归位）。

    返回 dict：dir / path / copied / note
    """
    do_copy = auto_copy() if copy_files is None else bool(copy_files)
    try:
        pdir = folder_for(doc, base)
        pdir.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as e:
        return {"dir": "", "path": "", "copied": False, "note": "建目录失败：%s" % e}
    try:
        tgt = target_for(doc, base)
    except ValueError as e:
        return {"dir": str(pdir), "path": "", "copied": False, "note": str(e)}
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
            stem, ext = os.path.splitext(str(tgt))
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


def open_file(path):
    """用系统默认程序打开一个文件；不在本机时返回 False。"""
    try:
        if path and os.path.exists(path):
            os.startfile(str(path))
            return True
    except OSError:
        pass
    return False


def reveal(path):
    """在资源管理器里定位文件；文件夹直接打开，文件选中它。"""
    target = str(path or "").strip()
    if not target:
        return False
    try:
        if os.path.isdir(target):
            return open_folder(target)
        if os.path.isfile(target) and os.path.dirname(target):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
            return True
    except OSError:
        pass
    return False

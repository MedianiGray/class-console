# -*- coding: utf-8 -*-
"""服务层文案与口径：缺项判断、催交话术、回执与免交状态。

界面只负责展示与确认；这里保持可单测的纯逻辑。
"""

from database import CAT_PREFIX, RECEIPT_RESPONSES


MATRIX_CATS = list(CAT_PREFIX.keys())


def doc_cat_status(docs, sid, cat):
    """按材料记录判该类状态；同一类别有归档记录时以归档为准。"""
    rows = [d for d in docs
            if d.get("sid") == sid and d.get("cat") == cat]
    status = {d.get("status") for d in rows}
    if "已归档" in status:
        return "已交"
    if "待审核" in status:
        return "待审"
    if "已驳回" in status or "待补材料" in status:
        return "补交"
    return ""


def cell_status(docs, sid, cat, exemptions=None, receipts=None):
    """矩阵格子：有材料优先，其次免交 / 延期，再看回执，最后才是无记录。"""
    base = doc_cat_status(docs, sid, cat)
    if base:
        return base
    ex = (exemptions or {}).get((sid, cat))
    if ex and ex.get("active"):
        return ex.get("kind") if ex.get("kind") in ("免交", "延期") else "免交"
    rec = (receipts or {}).get((sid, cat))
    if rec:
        response = rec.get("response")
        if response == "已提交":
            return "回执·已交"
        if response == "校外交":
            return "回执·校外"
        if response == "稍后补":
            return "回执·稍后"
    return "无记录"


def missing_categories(docs, sid, exemptions=None, receipts=None):
    """需要催交的类别：补交、无记录、只承诺稍后补；待审与已交不催。"""
    out = []
    for cat in MATRIX_CATS:
        status = cell_status(docs, sid, cat, exemptions, receipts)
        if status in ("补交", "无记录", "回执·稍后"):
            out.append(cat)
    return out


def chase_message(who, cats, deadline="", entry="班级操作台 → 提交材料"):
    """生成可直接粘贴的话术：说缺哪几类，不说人怎么样。"""
    cats = [c for c in (cats or []) if c]
    if not cats:
        return ""
    name = (who or "").strip()
    prefix = name if not name else (name if name.endswith("同学") else name + "同学")
    if not prefix:
        prefix = "同学"
    cats_text = "、".join(cats)
    lines = ["%s，这项还差你一份材料：%s。" % (prefix, cats_text)]
    if deadline:
        lines.append("麻烦在 %s 前提交。" % deadline)
    lines.append("入口：%s，网页版不用装软件。" % entry)
    lines.append("如果已经交了，或已在校外提交，回我「已提交」或「校外交」就行。")
    return "\n".join(lines)


def receipt_suggestion(response):
    """回执后的下一步提示，避免把回执当成已归档。"""
    if response == "已提交":
        return "回执只代表同学说已交，材料仍要在台账里核对或补录。"
    if response == "校外交":
        return "如确认校外已交，可同时登记「免交」，写清原因，之后不再催。"
    if response == "稍后补":
        return "已记下承诺补交；24 小时内不再重复提醒，到期后再看材料。"
    return ""


def wait_text(minutes):
    minutes = max(0, int(minutes or 0))
    if minutes < 60:
        return "%d 分钟" % minutes
    hours, mins = divmod(minutes, 60)
    if mins:
        return "%d 小时 %d 分钟" % (hours, mins)
    return "%d 小时" % hours


def valid_receipt(response):
    return response in RECEIPT_RESPONSES

# -*- coding: utf-8 -*-
"""v0.33 文档工具验收：四类工具、六道门、失败重试、取消、撤销。

跑完打印 DOCS OK；任一断言失败非零退出。
不依赖真实业务文件，全部在临时目录生成。
"""

import os
import sys
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import docs_tools as dt

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Pt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def make_text_pdf(path, pages, prefix):
    c = canvas.Canvas(path, pagesize=A4)
    for i in range(pages):
        c.setFont("Helvetica", 16)
        c.drawString(72, 760, "%s PAGE %d" % (prefix, i + 1))
        c.setFont("Helvetica", 11)
        c.drawString(72, 730, "Class console document smoke test.")
        c.showPage()
    c.save()


def make_scanned_pdf(path, png):
    c = canvas.Canvas(path, pagesize=A4)
    c.drawImage(png, 0, 0, width=A4[0], height=A4[1])
    c.showPage()
    c.save()


def make_text_png(path, lines, size=(1800, 1000)):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    y = 80
    for text, px in lines:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", px)
        d.text((70, y), text, font=font, fill=(10, 10, 10))
        y += px + 40
    img.save(path)


def make_docx(path):
    doc = Document()
    doc.add_heading("班级材料说明", level=1)
    doc.add_paragraph("这是 v0.33 文档工具验收用的 DOCX。")
    doc.add_paragraph("第一段：文字应当被重排进 PDF。")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "状态"
    table.cell(1, 0).text = "文档工具"
    table.cell(1, 1).text = "验收"
    doc.save(path)
    return doc


def snapshot_tree(paths):
    return {p: (os.path.getsize(p), round(os.path.getmtime(p), 3), dt.sha256(p))
            for p in paths}


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def check_manifest(result, expect_pass, min_out):
    assert_true(bool(result.get("manifest_csv")), "没有 CSV 清单")
    assert_true(bool(result.get("manifest_json")), "没有 JSON 清单")
    assert_true(os.path.isfile(result["manifest_csv"]), "CSV 清单不存在")
    with open(result["manifest_json"], "r", encoding="utf-8") as f:
        payload = __import__("json").load(f)
    assert_true(payload.get("params_text"), "清单没有参数解释")
    assert_true(payload.get("versions"), "清单没有引擎版本")
    assert_true(payload.get("passed", 0) >= min_out,
                "清单通过数不足：%s" % payload.get("passed"))
    for row in payload.get("rows") or []:
        if row.get("qc") == "通过":
            assert_true(len(row.get("sha256") or "") == 64, "输出缺少 SHA256")
            assert_true(os.path.isfile(row.get("out") or ""), "清单里的输出不存在")


def main():
    root = tempfile.mkdtemp(prefix="cc-docs-smoke-")
    src = os.path.join(root, "输入")
    os.makedirs(src)
    outs = {k: os.path.join(root, "输出_" + k) for k in dt.TOOL_ORDER}
    outs["undo"] = os.path.join(root, "输出_undo")
    for p in outs.values():
        os.makedirs(p, exist_ok=True)

    a = os.path.join(src, "甲-三页.pdf")
    b = os.path.join(src, "乙-两页.pdf")
    make_text_pdf(a, 3, "CLASS CONSOLE")
    make_text_pdf(b, 2, "SECOND PDF")
    scan_png = os.path.join(src, "_扫描底图.png")
    make_text_png(scan_png, [("班级操作台", 150), ("扫描件 第 1 页", 90),
                             ("CLASS CONSOLE 2026", 80)])
    scan = os.path.join(src, "扫描件.pdf")
    make_scanned_pdf(scan, scan_png)
    img1 = os.path.join(src, "图一.png")
    make_text_png(img1, [("班级操作台", 180), ("图片批处理验收", 90)], (2400, 1600))
    img2 = os.path.join(src, "图二.jpg")
    Image.new("RGB", (800, 600), (40, 120, 180)).save(img2)
    img3 = os.path.join(src, "图三.webp")
    Image.new("RGB", (1200, 900), (180, 80, 40)).save(img3, "WEBP")
    docx_path = os.path.join(src, "报告.docx")
    make_docx(docx_path)
    txt = os.path.join(src, "说明.txt")
    open(txt, "w", encoding="utf-8").write("不是 PDF")

    sources = [a, b, scan, scan_png, img1, img2, img3, docx_path]
    before = snapshot_tree(sources)

    # 1. PDF 拆分：区间 1-2，源 3 页 -> 输出 2 页
    r = dt.run_batch("pdf_split", [a, b], outs["pdf_split"], {"pages": "1-2"})
    assert_true(r["done"] == 2 and r["failed"] == 0, "拆分未全通过：%s" % r)
    for row in r["rows"]:
        assert_true(dt.pdf_info(row["out"])["pages"] == 2, "拆分页数不对")
    check_manifest(r, 2, 2)
    first_outputs = [row["out"] for row in r["rows"]]
    r2 = dt.run_batch("pdf_split", [a, b], outs["pdf_split"], {"pages": "1-2"})
    assert_true(r2["done"] == 2, "二次拆分未通过")
    assert_true(all(row["out"] not in first_outputs for row in r2["rows"]),
                "二次拆分覆盖了旧文件")
    print("1. PDF 拆分 OK")

    # 2. PDF 合并：3 + 2 -> 5 页
    r = dt.run_batch("pdf_merge", [a, b], outs["pdf_merge"], {"filename": "合并验收"})
    assert_true(r["done"] == 2 and r["failed"] == 0, "合并不通过：%s" % r)
    merged = r["rows"][0]["out"]
    assert_true(dt.pdf_info(merged)["pages"] == 5, "合并页数不是 5")
    check_manifest(r, 2, 2)
    assert_true(dt.sha256(merged) == r["rows"][0]["sha256"], "合并哈希不一致")
    print("2. PDF 合并 OK")

    # 3. OCR：图片 + 扫描 PDF -> TXT
    r = dt.run_batch("ocr", [img1, scan], outs["ocr"], {"dpi": 200, "keep_pages": True})
    assert_true(r["done"] == 2 and r["failed"] == 0, "OCR 未全通过：%s" % r)
    for row in r["rows"]:
        text = open(row["out"], "r", encoding="utf-8-sig").read()
        assert_true(len(text.strip()) >= 2, "OCR 文本为空")
        assert_true("班级" in text or "图片" in text or "CLASS" in text.upper()
                    or "第 1 页" in text,
                    "OCR 没认出关键字：%s" % text[:40])
    check_manifest(r, 2, 2)
    print("3. OCR OK")

    # 4. PDF -> DOCX：文字版取文字层，扫描件走 OCR
    r = dt.run_batch("pdf_to_docx", [a, scan], outs["pdf_to_docx"],
                     {"ocr_scanned": True})
    assert_true(r["done"] == 2 and r["failed"] == 0, "PDF 转 Word 未全通过：%s" % r)
    d1 = Document(r["rows"][0]["out"])
    text1 = "\n".join(p.text for p in d1.paragraphs)
    assert_true("CLASS CONSOLE" in text1.upper(), "文字版 PDF 没转出正文")
    d2 = Document(r["rows"][1]["out"])
    text2 = "\n".join(p.text for p in d2.paragraphs)
    assert_true("班级" in text2 or "扫描" in text2 or "第 1 页" in text2,
                "扫描 PDF 没走 OCR")
    check_manifest(r, 2, 2)
    print("4. PDF 转 WORD OK")

    # 5. DOCX -> PDF
    r = dt.run_batch("docx_to_pdf", [docx_path], outs["docx_to_pdf"],
                     {"keep_tables": True})
    assert_true(r["done"] == 1 and r["failed"] == 0, "Word 转 PDF 失败：%s" % r)
    assert_true(dt.pdf_info(r["rows"][0]["out"])["pages"] >= 1, "输出 PDF 无页")
    check_manifest(r, 1, 1)
    print("5. WORD 转 PDF OK")

    # 6. 图片批处理：JPG 最长边 800
    r = dt.run_batch("image_batch", [img1, img2, img3], outs["image_batch"],
                     {"format": "jpg", "max_edge": 800, "quality": 85})
    assert_true(r["done"] == 3 and r["failed"] == 0, "图片批处理未全通过：%s" % r)
    for row in r["rows"]:
        with Image.open(row["out"]) as im:
            assert_true(im.format == "JPEG", "输出不是 JPEG")
            assert_true(max(im.size) <= 800, "输出超过最长边")
    check_manifest(r, 3, 3)
    print("6. 图片批处理 OK")

    # 7. 取消：开跑前即停，不产出
    r = dt.run_batch("image_batch", [img1, img2], outs["image_batch"],
                     {"format": "png", "max_edge": 0}, cancel=lambda: True)
    assert_true(r["stopped"] == 2 and r["done"] == 0, "取消没有生效：%s" % r)
    print("7. 取消 OK")

    # 8. 失败可重试：空白图 OCR -> 需复核，并给出 retry_paths
    blank = os.path.join(src, "空白.png")
    Image.new("RGB", (600, 400), "white").save(blank)
    r = dt.run_batch("ocr", [blank], outs["ocr"], {"dpi": 150})
    assert_true(r["failed"] >= 1, "空白图 OCR 应判需复核")
    assert_true(blank in r["retry_paths"], "失败项没进 retry_paths")
    r_retry = dt.run_batch("ocr", r["retry_paths"], outs["ocr"], {"dpi": 150})
    assert_true(r_retry["total"] >= 1, "失败项无法重试")
    print("8. 失败可重试 OK")

    # 9. 撤销：只删本次产物，源不动
    r = dt.run_batch("image_batch", [img1], outs["undo"], {"format": "png", "max_edge": 600})
    assert_true(r["done"] == 1, "撤销用例没跑通")
    out_path = r["rows"][0]["out"]
    u = dt.undo(r["manifest_json"])
    assert_true(u["ok"] and u["removed"] >= 1, "撤销没删产物：%s" % u)
    assert_true(not os.path.exists(out_path), "撤销后产物还在")
    assert_true(os.path.exists(img1), "撤销动到了源文件")
    print("9. 撤销 OK")

    # 10. 源文件全程未动
    after = snapshot_tree(sources)
    assert_true(before == after, "源文件被改动")
    print("10. 源文件未动 OK")

    # 11. 预检能挡住不支持格式
    rows = dt.preflight("pdf_split", [txt], {"pages": ""})
    assert_true(rows and not rows[0]["ok"] and "格式" in rows[0]["reason"],
                "预检没挡住非 PDF")
    print("11. 预检拦截 OK")

    # 12. 参数解释与六道门字段
    for k in dt.TOOL_ORDER:
        text = dt.describe_params(k, dt.default_params(k))
        assert_true(bool(text), "%s 参数没有解释" % k)
    print("12. 六道门字段 OK")

    print("DOCS OK")
    shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""v0.33 文档工具：四类工具的同一套最小闭环。

四类工具：
  - PDF：按页/按区间拆分，多个 PDF 合并；
  - OCR：图片或 PDF 扫描页识别成 TXT（Windows 本机 OCR，不联网）；
  - 转换：DOCX→PDF（文字与表格重排）、PDF→DOCX（文字重排，扫描页可走 OCR）；
  - 图片批处理：格式转换、最长边缩放、质量压缩。

每类都按六道门走：
  1. 输入可识别：扩展名、可读性、页数/尺寸/段落数；
  2. 参数可解释：describe_params() 给出人话说明，并写进清单；
  3. 执行可取消：cancel 回调逐项检查；
  4. 输出可质检：页数、格式、尺寸、字符数、能否重新打开；
  5. 产物有清单/哈希：CSV + JSON，带每个输出的 SHA256；
  6. 全程可留痕/可撤销：源文件只读并比对哈希，undo() 只删本次清单里的输出。

不依赖界面；不承诺完整 Office 版式。
"""

import csv
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import version as _pkg_version

try:
    from pypdf import PdfReader, PdfWriter
    HAS_PYPDF = True
except Exception:                                    # pragma: no cover
    PdfReader = PdfWriter = None
    HAS_PYPDF = False

try:
    import pypdfium2 as pdfium
    HAS_PDFIUM = True
except Exception:                                    # pragma: no cover
    pdfium = None
    HAS_PDFIUM = False

try:
    from PIL import Image, ImageOps
    HAS_PIL = True
except Exception:                                    # pragma: no cover
    Image = ImageOps = None
    HAS_PIL = False

try:
    from docx import Document
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxPara
    HAS_DOCX = True
except Exception:                                    # pragma: no cover
    Document = DocxTable = DocxPara = None
    HAS_DOCX = False

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)
    from reportlab.lib import colors
    HAS_REPORTLAB = True
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
except Exception:                                    # pragma: no cover
    HAS_REPORTLAB = False

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
WORD_EXTS = {".docx"}

TOOLS = {
    "pdf_split": {
        "label": "PDF 拆分（按页 / 按区间）",
        "short": "PDF 拆分",
        "exts": PDF_EXTS,
        "accept": "PDF",
        "out_ext": ".pdf",
        "default": {"pages": ""},
        "hint": "页码范围：1-3,5；留空表示每页拆成一个 PDF",
    },
    "pdf_merge": {
        "label": "PDF 合并（按顺序合成一个）",
        "short": "PDF 合并",
        "exts": PDF_EXTS,
        "accept": "PDF",
        "out_ext": ".pdf",
        "default": {"filename": ""},
        "hint": "输出文件名可留空，默认「合并_时间.pdf」；输入按列表顺序合并",
    },
    "ocr": {
        "label": "OCR 识别（图片 / PDF → TXT）",
        "short": "OCR 识别",
        "exts": PDF_EXTS | IMAGE_EXTS,
        "accept": "图片或 PDF",
        "out_ext": ".txt",
        "default": {"dpi": 200, "keep_pages": True},
        "hint": "PDF 先按 DPI 渲染再识别；扫描件优先，文字版 PDF 用「PDF 转 Word」更快",
    },
    "pdf_to_docx": {
        "label": "PDF → DOCX（文字重排）",
        "short": "PDF 转 Word",
        "exts": PDF_EXTS,
        "accept": "PDF",
        "out_ext": ".docx",
        "default": {"ocr_scanned": True},
        "hint": "文字按页重排，不保原版式；扫描页可开启 OCR 补文字",
    },
    "docx_to_pdf": {
        "label": "DOCX → PDF（文字与表格重排）",
        "short": "Word 转 PDF",
        "exts": WORD_EXTS,
        "accept": "DOCX",
        "out_ext": ".pdf",
        "default": {"keep_tables": True},
        "hint": "保留段落与表格；复杂版式、浮动图片不保证与 Word 完全一致",
    },
    "image_batch": {
        "label": "图片批处理（格式 / 缩放 / 压缩）",
        "short": "图片批处理",
        "exts": IMAGE_EXTS,
        "accept": "图片",
        "out_ext": "",
        "default": {"format": "jpg", "max_edge": 1600, "quality": 85},
        "hint": "最长边填 0 表示不缩放；质量只对 JPG/WebP 生效",
    },
}
TOOL_ORDER = ("pdf_split", "pdf_merge", "ocr", "pdf_to_docx",
              "docx_to_pdf", "image_batch")
IMAGE_FORMATS = {"jpg": ".jpg", "png": ".png", "webp": ".webp"}


def tool(key):
    return TOOLS.get(str(key or "").strip()) or TOOLS["pdf_split"]


def tool_items():
    return [(k, TOOLS[k]["label"]) for k in TOOL_ORDER]


def default_params(key):
    return dict(tool(key).get("default") or {})


def _int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _bool(v):
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on", "是")
    return bool(v)


def normalize_params(key, params):
    p = default_params(key)
    p.update(dict(params or {}))
    k = str(key or "").strip()
    if k == "pdf_split":
        p["pages"] = str(p.get("pages") or "").strip()
    elif k == "pdf_merge":
        p["filename"] = str(p.get("filename") or "").strip()
    elif k == "ocr":
        p["dpi"] = max(100, min(400, _int(p.get("dpi"), 200)))
        p["keep_pages"] = _bool(p.get("keep_pages", True))
    elif k == "pdf_to_docx":
        p["ocr_scanned"] = _bool(p.get("ocr_scanned", True))
    elif k == "docx_to_pdf":
        p["keep_tables"] = _bool(p.get("keep_tables", True))
    elif k == "image_batch":
        fmt = str(p.get("format") or "jpg").lower().lstrip(".")
        if fmt == "jpeg":
            fmt = "jpg"
        p["format"] = fmt if fmt in IMAGE_FORMATS else "jpg"
        p["max_edge"] = max(0, min(10000, _int(p.get("max_edge"), 0)))
        p["quality"] = max(30, min(98, _int(p.get("quality"), 85)))
    return p


def describe_params(key, params):
    """把参数翻成人话；清单里也存一份，事后能解释当时怎么跑的。"""
    p = normalize_params(key, params)
    k = str(key or "").strip()
    if k == "pdf_split":
        pages = p.get("pages") or ""
        return ("每页拆成一个 PDF" if not pages else
                "按区间拆分：%s（超出页数会先判失败）" % pages)
    if k == "pdf_merge":
        name = p.get("filename") or "自动命名"
        return "按输入顺序合并；输出：%s" % name
    if k == "ocr":
        return "渲染 %d DPI；%s" % (p.get("dpi"), "保留「第 N 页」分页标记"
                                     if p.get("keep_pages") else "合并为连续文本")
    if k == "pdf_to_docx":
        return "按页提取文字重排；%s" % ("扫描页走 OCR" if p.get("ocr_scanned")
                                         else "只取 PDF 自带文字层")
    if k == "docx_to_pdf":
        return "段落%s重排为 A4 PDF；不承诺复杂版式" % (
            "与表格" if p.get("keep_tables") else "（表格忽略）")
    if k == "image_batch":
        scale = "保持原尺寸" if not p.get("max_edge") else "最长边缩到 %dpx" % p["max_edge"]
        return "转 %s；%s；质量 %d" % (str(p.get("format")).upper(), scale, p.get("quality"))
    return ""


def available(key, params=None):
    """返回 (可用, 原因)。OCR 依赖 Windows 自带识别引擎。"""
    k = str(key or "").strip()
    p = normalize_params(k, params or {})
    if k in ("pdf_split", "pdf_merge", "pdf_to_docx") and not HAS_PYPDF:
        return False, "缺少 pypdf，无法读写 PDF"
    if k == "docx_to_pdf" and not (HAS_DOCX and HAS_REPORTLAB):
        return False, "缺少 python-docx 或 reportlab，无法转 PDF"
    if k == "ocr":
        if not HAS_PDFIUM:
            return False, "缺少 pypdfium2，无法渲染 PDF 页"
        ok, why = ocr_available()
        if not ok:
            return False, why
    if k == "pdf_to_docx" and p.get("ocr_scanned"):
        if not HAS_PDFIUM:
            return False, "缺少 pypdfium2，无法给扫描页做 OCR"
        ok, why = ocr_available()
        if not ok:
            return False, why
    if k == "image_batch" and not HAS_PIL:
        return False, "缺少 Pillow，无法处理图片"
    return True, ""


_OCR_PROBE = None
_OCR_LANG = ""
_OCR_SCRIPT_PATH = ""

_OCR_SCRIPT = r"""param([string]$Path, [switch]$Probe)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
  $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
  $netTask = $asTask.Invoke($null, @($WinRtTask))
  $netTask.Wait(-1) | Out-Null
  $netTask.Result
}
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
function New-OcrEngine {
  $engine = $null
  try { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('zh-Hans-CN')) } catch {}
  if (-not $engine) {
    try { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('zh-Hans')) } catch {}
  }
  if (-not $engine) {
    try { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() } catch {}
  }
  return $engine
}
$engine = New-OcrEngine
if (-not $engine) { [Console]::Error.WriteLine('OCR_ENGINE_MISSING'); exit 2 }
if ($Probe) {
  [Console]::OutputEncoding = [Text.Encoding]::UTF8
  'OCR_LANG=' + $engine.RecognizerLanguage.LanguageTag
  exit 0
}
if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { [Console]::Error.WriteLine('OCR_INPUT_MISSING'); exit 3 }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path -LiteralPath $Path).Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$lines = @()
foreach ($line in $result.Lines) { $lines += $line.Text }
[Console]::Out.Write(($lines -join "`n"))
"""


def _ocr_script():
    global _OCR_SCRIPT_PATH
    if _OCR_SCRIPT_PATH and os.path.isfile(_OCR_SCRIPT_PATH):
        return _OCR_SCRIPT_PATH
    path = os.path.join(tempfile.gettempdir(), "class-console-ocr-win-v2.ps1")
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_OCR_SCRIPT)
        _OCR_SCRIPT_PATH = path
        return path
    except OSError:
        return ""


def _run(args, timeout=120):
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout,
                           encoding="utf-8", errors="replace", **kw)
        return p.returncode, p.stdout or "", p.stderr or ""
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "", str(e)


def ocr_available():
    global _OCR_PROBE, _OCR_LANG
    if _OCR_PROBE is not None:
        return _OCR_PROBE, "" if _OCR_PROBE else "本机没有可用的 Windows OCR 引擎"
    _OCR_PROBE = False
    if sys.platform != "win32":
        return False, "OCR 只接了 Windows 自带识别引擎"
    ps = shutil.which("powershell.exe") or shutil.which("powershell")
    if not ps:
        return False, "找不到 PowerShell，无法调用 Windows OCR"
    script = _ocr_script()
    if not script:
        return False, "OCR 脚本写不到临时目录"
    code, out, err = _run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-File", script, "-Probe"], 60)
    if code == 0 and "OCR_LANG=" in (out or ""):
        _OCR_PROBE = True
        _OCR_LANG = (out or "").strip().split("OCR_LANG=", 1)[-1].strip()
        return True, ""
    return False, (err or "").strip()[-160:] or "本机没有可用的 Windows OCR 引擎"


def ocr_lang():
    ocr_available()
    return _OCR_LANG or "zh-Hans-CN"


def _clean_ocr(text):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    # 中文识别结果常被逐字加空格；只收水平空格，保留换行。
    text = re.sub(r"(?<=[\u4e00-\u9fff\u3000-\u303f])[ \t]+(?=[\u4e00-\u9fff\u3000-\u303f])", "", text)
    for _ in range(3):
        text = re.sub(r"\b([A-Z])[ \t]+([A-Z]{2,})", r"\1\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ocr_image(path, timeout=180):
    ok, why = ocr_available()
    if not ok:
        return "", why
    script = _ocr_script()
    code, out, err = _run([shutil.which("powershell.exe") or "powershell.exe",
                           "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-File", script, "-Path", os.path.abspath(path)], timeout)
    if code != 0:
        return "", (err or "").strip()[-200:] or ("OCR 退出码 %s" % code)
    return _clean_ocr(out), ""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _safe_stem(stem):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(stem or "").strip())
    return stem[:120] or "未命名"


def _unique_path(path, src_abs=""):
    path = os.path.abspath(path)
    src_norm = os.path.normcase(os.path.abspath(src_abs)) if src_abs else ""
    if src_norm and os.path.normcase(path) == src_norm:
        base, ext = os.path.splitext(path)
        path = base + "-转换" + ext
    elif os.path.exists(path):
        base, ext = os.path.splitext(path)
        for i in range(1, 1000):
            cand = "%s-%d%s" % (base, i, ext)
            if not os.path.exists(cand):
                return cand
        raise OSError("同名文件太多，无法生成输出名")
    if os.path.exists(path):
        base, ext = os.path.splitext(path)
        for i in range(2, 1000):
            cand = "%s-%d%s" % (base, i, ext)
            if not os.path.exists(cand):
                return cand
        raise OSError("同名文件太多，无法生成输出名")
    return path


def _pdf_reader(path):
    if not HAS_PYPDF:
        raise RuntimeError("缺少 pypdf")
    reader = PdfReader(path)
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception as e:
            raise RuntimeError("PDF 加密且无法用空密码打开：%s" % e)
    return reader


def pdf_info(path):
    try:
        reader = _pdf_reader(path)
        pages = len(reader.pages)
        if pages <= 0:
            return {"ok": False, "pages": 0, "error": "PDF 没有页"}
        return {"ok": True, "pages": pages, "error": ""}
    except Exception as e:
        return {"ok": False, "pages": 0, "error": str(e)[-160:]}


def parse_ranges(expr, total):
    """解析 1-3,5 / 每页 / 空；返回 [(start,end,label)]，非法抛 ValueError。"""
    text = str(expr or "").strip()
    if not text or text.lower() in ("all", "每页", "逐页"):
        return [(i, i, "第%03d页" % i) for i in range(1, total + 1)]
    parts = [p for p in re.split(r"[,，;；\s]+", text) if p]
    out = []
    for part in parts:
        m = re.fullmatch(r"(\d+)?\s*[-~至]\s*(\d+)?", part)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else total
        elif re.fullmatch(r"\d+", part):
            a = b = int(part)
        else:
            raise ValueError("看不懂页码「%s」" % part)
        if a < 1 or b < 1 or a > total or b > total:
            raise ValueError("页码 %s 超出 1-%d" % (part, total))
        if a > b:
            raise ValueError("页码 %s 起止颠倒" % part)
        label = ("第%03d页" % a if a == b else "第%03d-%03d页" % (a, b))
        out.append((a, b, label))
    return out


def _base_row(src, name=""):
    return {"src": src, "sources": [src] if src else [],
            "name": name or os.path.basename(src), "ok": False, "reason": "",
            "size": 0, "meta": "", "pages": 0, "target": "", "part": "",
            "src_sha256": "", "src_size": 0, "src_mtime": 0, "out": "",
            "out_size": 0, "sha256": "", "pages_out": 0, "chars": 0,
            "detail_out": "", "qc": "", "note": ""}


def _file_check(row):
    src = row.get("src") or ""
    if not src:
        row["reason"] = "空路径"
        return False
    if not os.path.isfile(src):
        row["reason"] = "文件不存在"
        return False
    try:
        row["size"] = os.path.getsize(src)
    except OSError:
        row["size"] = 0
    if row["size"] <= 0:
        row["reason"] = "空文件"
        return False
    return True


def preflight(key, paths, params=None):
    """逐项预检；PDF 拆分按区间展开成多行，合并每个输入一行。"""
    k = str(key or "").strip()
    p = normalize_params(k, params)
    exts = tool(k)["exts"]
    rows = []
    for raw in paths or []:
        src = os.path.abspath(str(raw)) if str(raw or "").strip() else ""
        row = _base_row(src)
        if not _file_check(row):
            rows.append(row)
            continue
        ext = os.path.splitext(src)[1].lower()
        if ext not in exts:
            row["reason"] = "不是本工具支持的格式：%s" % (ext or "无扩展名")
            rows.append(row)
            continue
        try:
            if k in ("pdf_split", "pdf_merge", "pdf_to_docx", "ocr") and ext == ".pdf":
                info = pdf_info(src)
                if not info["ok"]:
                    row["reason"] = info["error"]
                    rows.append(row)
                    continue
                row["pages"] = info["pages"]
                row["meta"] = "%d 页" % info["pages"]
            elif k == "docx_to_pdf":
                doc = Document(src)
                n_par = len(doc.paragraphs)
                n_tab = len(doc.tables)
                row["meta"] = "%d 段 · %d 表" % (n_par, n_tab)
                if n_par == 0 and n_tab == 0:
                    row["reason"] = "文档没有可转换的文字或表格"
                    rows.append(row)
                    continue
            elif k == "image_batch" or (k == "ocr" and ext in IMAGE_EXTS):
                with Image.open(src) as im:
                    im.load()
                    row["meta"] = "%d×%d · %s" % (im.width, im.height,
                                                  (im.format or ext.lstrip(".")).upper())
                    row["pages"] = 1
            row["ok"] = True
        except Exception as e:
            row["reason"] = "%s: %s" % (type(e).__name__, str(e)[:150])
            rows.append(row)
            continue

        if k == "pdf_split":
            try:
                ranges = parse_ranges(p.get("pages"), row["pages"])
            except ValueError as e:
                row["ok"] = False
                row["reason"] = str(e)
                rows.append(row)
                continue
            stem = _safe_stem(os.path.splitext(row["name"])[0])
            for a, b, label in ranges:
                child = dict(row)
                child["part"] = label
                child["name"] = "%s · %s" % (row["name"], label)
                child["target_name"] = "%s_%s.pdf" % (stem, label)
                rows.append(child)
        else:
            rows.append(row)
    return rows


def plan(key, paths, outdir, params=None):
    """预检 + 输出路径；不落盘。"""
    k = str(key or "").strip()
    p = normalize_params(k, params)
    rows = preflight(k, paths, p)
    out_root = os.path.abspath(str(outdir or "").strip()) if str(outdir or "").strip() else ""
    if not out_root:
        for row in rows:
            row["ok"] = False
            row["reason"] = row["reason"] or "没有输出目录"
        return rows, out_root
    if not os.path.isdir(out_root):
        for row in rows:
            row["ok"] = False
            row["reason"] = row["reason"] or "输出目录不存在"
        return rows, out_root

    if k == "pdf_merge":
        name = p.get("filename") or ("合并_" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".pdf")
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        name = _safe_stem(os.path.splitext(name)[0]) + ".pdf"
        target = _unique_path(os.path.join(out_root, name))
        for row in rows:
            if row.get("ok"):
                row["target"] = target
        return rows, out_root

    for row in rows:
        if not row.get("ok"):
            continue
        if row.get("target_name"):
            cand = os.path.join(out_root, row["target_name"])
        else:
            stem = _safe_stem(os.path.splitext(row["name"])[0].split(" · ")[0])
            if k == "image_batch":
                ext = IMAGE_FORMATS[p["format"]]
                cand = os.path.join(out_root, stem + ext)
            elif k == "ocr":
                cand = os.path.join(out_root, stem + ".txt")
            elif k == "pdf_to_docx":
                cand = os.path.join(out_root, stem + ".docx")
            elif k == "docx_to_pdf":
                cand = os.path.join(out_root, stem + ".pdf")
            else:
                cand = os.path.join(out_root, stem + tool(k)["out_ext"])
        try:
            row["target"] = _unique_path(cand, row["src"])
        except OSError as e:
            row["ok"] = False
            row["reason"] = str(e)
    return rows, out_root


# ---------- 具体动作 ----------

def _pdf_split(row, params, ctx):
    reader = _pdf_reader(row["src"])
    a, b = row.get("_range") or (1, 1)
    writer = PdfWriter()
    for i in range(a - 1, b):
        writer.add_page(reader.pages[i])
    out = row["target"]
    with open(out, "wb") as f:
        writer.write(f)
    info = pdf_info(out)
    if not info["ok"]:
        return {"ok": False, "reason": "输出 PDF 打不开：%s" % info["error"]}
    if info["pages"] != (b - a + 1):
        return {"ok": False, "reason": "输出 %d 页，应为 %d 页" % (info["pages"], b - a + 1)}
    return {"out": out, "pages_out": info["pages"],
            "detail_out": "%d 页" % info["pages"]}


def _pdf_merge(rows, params, ctx):
    target = rows[0].get("target")
    writer = PdfWriter()
    total = 0
    for row in rows:
        reader = _pdf_reader(row["src"])
        for page in reader.pages:
            writer.add_page(page)
        total += len(reader.pages)
    with open(target, "wb") as f:
        writer.write(f)
    info = pdf_info(target)
    if not info["ok"]:
        return False, "输出 PDF 打不开：%s" % info["error"], 0
    if info["pages"] != total:
        return False, "输出 %d 页，应为 %d 页" % (info["pages"], total), 0
    return True, "合并 %d 个 PDF，共 %d 页" % (len(rows), total), total


def _render_pdf_page(path, index, dpi, out_png):
    doc = pdfium.PdfDocument(path)
    try:
        page = doc[index]
        bitmap = page.render(scale=max(1.0, dpi / 72.0))
        pil = bitmap.to_pil()
        pil.save(out_png, format="PNG")
        return True
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _ocr_pdf(row, params, ctx):
    pages = row.get("pages") or 0
    dpi = params.get("dpi") or 200
    parts = []
    for i in range(pages):
        png = os.path.join(ctx["tmp"], "page-%03d.png" % (i + 1))
        if not _render_pdf_page(row["src"], i, dpi, png):
            return {"ok": False, "reason": "第 %d 页渲染失败" % (i + 1)}
        text, why = _ocr_image(png)
        try:
            os.remove(png)
        except OSError:
            pass
        if why:
            return {"ok": False, "reason": "第 %d 页 OCR 失败：%s" % (i + 1, why)}
        if params.get("keep_pages"):
            parts.append("【第 %d 页】\n%s" % (i + 1, text))
        elif text:
            parts.append(text)
        if ctx.get("cancel") and ctx["cancel"]():
            return {"ok": False, "reason": "用户停止"}
    body = "\n\n".join(parts).strip()
    return _write_text(row["target"], body, pages=pages, ctx=ctx)


def _write_text(target, body, pages=0, ctx=None):
    with open(target, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write(body)
    chars = len(re.sub(r"\s+", "", body))
    if chars < 2:
        return {"out": target, "pages_out": pages, "chars": chars,
                "detail_out": "%d 字符" % chars, "review": "未识别出有效文字"}
    return {"out": target, "pages_out": pages, "chars": chars,
            "detail_out": "%d 字符" % chars}


def _ocr_one(row, params, ctx):
    ext = os.path.splitext(row["src"])[1].lower()
    if ext == ".pdf":
        return _ocr_pdf(row, params, ctx)
    src = row["src"]
    temp_png = ""
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"):
        try:
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                temp_png = os.path.join(ctx["tmp"], "ocr-input.png")
                im.save(temp_png, "PNG")
            src = temp_png
        except Exception as e:
            return {"ok": False, "reason": "图片转 PNG 失败：%s" % e}
    try:
        text, why = _ocr_image(src)
    finally:
        if temp_png:
            try:
                os.remove(temp_png)
            except OSError:
                pass
    if why:
        return {"ok": False, "reason": why}
    return _write_text(row["target"], text, pages=1, ctx=ctx)


def _page_text(reader, index):
    try:
        return reader.pages[index].extract_text() or ""
    except Exception:
        return ""


def _pdf_to_docx(row, params, ctx):
    reader = _pdf_reader(row["src"])
    pages = len(reader.pages)
    doc = Document()
    doc.add_heading("由 PDF 转写：%s" % os.path.basename(row["src"]), level=1)
    doc.add_paragraph("说明：按页提取文字重排，不保留原版式；扫描页可走 OCR。")
    ocr_used = 0
    empty_pages = 0
    body_chars = 0
    for i in range(pages):
        text = _page_text(reader, i)
        if len(re.sub(r"\s+", "", text)) < 20 and params.get("ocr_scanned"):
            png = os.path.join(ctx["tmp"], "docx-page-%03d.png" % (i + 1))
            if _render_pdf_page(row["src"], i, 200, png):
                try:
                    ocr_text, why = _ocr_image(png)
                finally:
                    try:
                        os.remove(png)
                    except OSError:
                        pass
                if not why and len(re.sub(r"\s+", "", ocr_text)) > len(re.sub(r"\s+", "", text)):
                    text = ocr_text
                    ocr_used += 1
        doc.add_heading("第 %d 页" % (i + 1), level=2)
        if text.strip():
            for line in text.splitlines():
                if line.strip():
                    doc.add_paragraph(line.rstrip())
                    body_chars += len(re.sub(r"\s+", "", line))
        else:
            empty_pages += 1
            doc.add_paragraph("（本页没有提取到文字）")
        if ctx.get("cancel") and ctx["cancel"]():
            return {"ok": False, "reason": "用户停止"}
    out = row["target"]
    doc.save(out)
    check = Document(out)
    if not check.paragraphs:
        return {"ok": False, "reason": "输出 DOCX 打不开或没有段落"}
    if body_chars < 2:
        return {"ok": False, "reason": "输出 DOCX 没有有效文字"}
    note = "%d 页；%d 页走了 OCR" % (pages, ocr_used)
    if empty_pages:
        note += "；%d 页无文字" % empty_pages
    return {"out": out, "pages_out": pages, "chars": body_chars,
            "detail_out": "%d 页" % pages, "note": note}


def _iter_docx_blocks(doc):
    body = doc.element.body
    for child in body.iterchildren():
        tag = str(child.tag)
        if tag.endswith("}p"):
            yield "p", DocxPara(child, doc)
        elif tag.endswith("}tbl"):
            yield "table", DocxTable(child, doc)


def _docx_to_pdf(row, params, ctx):
    doc = Document(row["src"])
    story = []
    base = ParagraphStyle("doc-body", fontName="STSong-Light", fontSize=10.5,
                          leading=17, wordWrap="CJK", spaceAfter=4)
    small = ParagraphStyle("doc-small", parent=base, fontSize=9, leading=14)
    skipped_img = 0
    for kind, block in _iter_docx_blocks(doc):
        if kind == "p":
            text = (block.text or "").strip()
            try:
                if block._element.xpath(".//pic:pic"):
                    skipped_img += 1
            except Exception:
                pass
            if not text:
                story.append(Spacer(1, 5))
                continue
            style_name = ""
            try:
                style_name = block.style.name or ""
            except Exception:
                pass
            size = 10.5
            if style_name.lower().startswith("heading") or style_name.startswith("标题"):
                lvl = 1
                try:
                    lvl = int(style_name.split()[-1])
                except (ValueError, IndexError):
                    pass
                size = {1: 18, 2: 15, 3: 13, 4: 12}.get(lvl, 11)
            st = ParagraphStyle("doc-h%d" % size, parent=base, fontSize=size,
                                leading=size * 1.65, spaceBefore=7, spaceAfter=5,
                                textColor=colors.black)
            story.append(Paragraph(_xml(text), st))
        elif kind == "table" and params.get("keep_tables", True):
            data = []
            for r in block.rows:
                data.append([Paragraph(_xml(c.text or ""), small) for c in r.cells])
            if not data:
                continue
            cols = max(len(r) for r in data)
            avail = A4[0] - 36 * mm
            table = Table(data, colWidths=[avail / max(1, cols)] * cols, repeatRows=1)
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888888")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(Spacer(1, 4))
            story.append(table)
            story.append(Spacer(1, 6))
        if ctx.get("cancel") and ctx["cancel"]():
            return {"ok": False, "reason": "用户停止"}
    if not story:
        story = [Paragraph("（文档没有可转换的内容）", base)]
    out = row["target"]
    pdf = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm,
                            rightMargin=18 * mm, topMargin=18 * mm,
                            bottomMargin=18 * mm, title=os.path.basename(out),
                            author="班级操作台")
    pdf.build(story)
    info = pdf_info(out)
    if not info["ok"]:
        return {"ok": False, "reason": "输出 PDF 打不开：%s" % info["error"]}
    note = "文字与表格重排为 A4"
    if skipped_img:
        note += "；%d 处图片未嵌入" % skipped_img
    return {"out": out, "pages_out": info["pages"],
            "detail_out": "%d 页" % info["pages"], "note": note}


def _image_batch(row, params, ctx):
    fmt = params["format"]
    ext = IMAGE_FORMATS[fmt]
    max_edge = params.get("max_edge") or 0
    quality = params.get("quality") or 85
    with Image.open(row["src"]) as im:
        im.load()
        im = ImageOps.exif_transpose(im)
        orig_w, orig_h = im.size
        if max_edge and max(orig_w, orig_h) > max_edge:
            scale = max_edge / float(max(orig_w, orig_h))
            im = im.resize((max(1, int(orig_w * scale)), max(1, int(orig_h * scale))),
                           Image.LANCZOS)
        if fmt in ("jpg", "webp") and im.mode not in ("RGB", "L"):
            if im.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", im.size, "white")
                im = im.convert("RGBA")
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
        out = row["target"]
        if fmt == "jpg":
            im.save(out, "JPEG", quality=quality, optimize=True)
        elif fmt == "webp":
            im.save(out, "WEBP", quality=quality, method=6)
        else:
            im.save(out, "PNG", optimize=True)
        out_w, out_h = im.size
    with Image.open(out) as check:
        check.load()
        real = (check.format or "").upper()
    wanted = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}[fmt]
    if real != wanted:
        return {"ok": False, "reason": "输出格式 %s，应为 %s" % (real, wanted)}
    if max_edge and max(out_w, out_h) > max_edge:
        return {"ok": False, "reason": "输出 %d×%d，超过最长边 %d" % (out_w, out_h, max_edge)}
    return {"out": out, "detail_out": "%d×%d · %s" % (out_w, out_h, wanted),
            "note": "原图 %d×%d" % (orig_w, orig_h)}


def _xml(text):
    from xml.sax.saxutils import escape
    return escape(str(text or "")).replace("\n", "<br/>")


def _snapshot(path):
    return (os.path.getsize(path), round(os.path.getmtime(path), 3), sha256(path))


def run_batch(key, paths, outdir, params=None, progress=None, cancel=None):
    """跑一遍并质检，最后写 CSV/JSON 清单。不抛未处理异常。"""
    k = str(key or "").strip()
    p = normalize_params(k, params)
    started = datetime.datetime.now()
    rows, out_root = plan(k, paths, outdir, p)
    result = {
        "ok": False, "tool": k, "tool_label": tool(k)["label"],
        "total": len(rows), "done": 0, "failed": 0, "stopped": 0,
        "rows": rows, "params": p, "params_text": describe_params(k, p),
        "outdir": out_root, "manifest_csv": "", "manifest_json": "",
        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"), "ended_at": "",
        "error": "", "retry_paths": [], "ocr_lang": ocr_lang() if HAS_PDFIUM else "",
        "versions": _versions(),
    }
    ok, why = available(k, p)
    if not ok:
        result["error"] = why
        return result
    if not out_root or not os.path.isdir(out_root):
        result["error"] = "先选择一个存在的输出目录"
        return result
    if not rows:
        result["error"] = "没有输入文件"
        return result

    tmp = tempfile.mkdtemp(prefix="cc-docs-")
    ctx = {"tmp": tmp, "cancel": cancel, "params": p}
    try:
        if k == "pdf_merge":
            _run_merge(rows, p, ctx, result, progress)
        else:
            for i, row in enumerate(rows):
                if cancel and cancel():
                    row["qc"] = "已停止"
                    row["note"] = "用户停止，未执行"
                    result["stopped"] += 1
                    if progress:
                        progress(i + 1, len(rows), row)
                    continue
                if not row.get("ok"):
                    row["qc"] = "跳过"
                    row["note"] = row.get("reason") or "预检未通过"
                    result["failed"] += 1
                    if progress:
                        progress(i + 1, len(rows), row)
                    continue
                if row.get("part"):
                    # 拆分行需要把区间带进动作层
                    m = re.match(r"第(\d+)(?:-(\d+))?页", row.get("part") or "")
                    if m:
                        row["_range"] = (int(m.group(1)),
                                         int(m.group(2) or m.group(1)))
                _run_one(k, row, p, ctx, result)
                if progress:
                    progress(i + 1, len(rows), row)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    result["ended_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result["retry_paths"] = _unique([r.get("src") for r in rows
                                     if r.get("qc") in ("失败", "需复核")])
    try:
        result.update(write_manifest(rows, out_root, k, p, result))
    except (OSError, ValueError) as e:
        result["error"] = "清单写入失败：%s" % e
    result["ok"] = result["done"] > 0 and result["failed"] == 0 and \
        result["stopped"] == 0 and not result["error"]
    return result


def _unique(items):
    out, seen = [], set()
    for x in items:
        if not x:
            continue
        key = os.path.normcase(os.path.abspath(x))
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out


def _run_merge(rows, p, ctx, result, progress):
    if ctx["cancel"] and ctx["cancel"]():
        for row in rows:
            row["qc"] = "已停止"
            row["note"] = "用户停止，未执行"
            result["stopped"] += 1
        return
    bad = [r for r in rows if not r.get("ok")]
    if bad:
        for row in rows:
            row["qc"] = "跳过"
            row["note"] = row.get("reason") or "有输入未通过预检，未执行合并"
            result["failed"] += 1
        if progress:
            progress(1, 1, rows[0])
        return
    before = {}
    for row in rows:
        try:
            before[row["src"]] = _snapshot(row["src"])
            row["src_size"], row["src_mtime"], row["src_sha256"] = before[row["src"]]
        except OSError as e:
            for r in rows:
                r["qc"] = "失败"
                r["note"] = "源文件读不了：%s" % e
                result["failed"] += 1
            return
    target = rows[0]["target"]
    try:
        good, note, pages_out = _pdf_merge(rows, p, ctx)
        if not good:
            raise RuntimeError(note)
        size = os.path.getsize(target)
        sha = sha256(target)
        reasons = []
        for row in rows:
            try:
                if _snapshot(row["src"]) != before[row["src"]]:
                    reasons.append("%s 被改动" % row["name"])
            except OSError:
                reasons.append("%s 事后读不了" % row["name"])
        for row in rows:
            row.update({"out": target, "out_name": os.path.basename(target),
                        "out_size": size, "sha256": sha, "pages_out": pages_out,
                        "detail_out": "%d 页" % pages_out if pages_out else note})
            if reasons:
                row["qc"] = "需复核"
                row["note"] = "；".join(reasons)
            else:
                row["qc"] = "通过"
                row["note"] = note + "；源文件未动"
        if reasons:
            result["failed"] += len(rows)
        else:
            result["done"] += len(rows)
    except Exception as e:
        for row in rows:
            row["qc"] = "失败"
            row["note"] = "合并失败：%s" % str(e)[-200:]
            result["failed"] += 1
    if progress:
        progress(1, 1, rows[0])


def _run_one(k, row, p, ctx, result):
    try:
        before = _snapshot(row["src"])
        row["src_size"], row["src_mtime"], row["src_sha256"] = before
    except OSError as e:
        row["qc"] = "失败"
        row["note"] = "源文件读不了：%s" % e
        result["failed"] += 1
        return
    try:
        if k == "pdf_split":
            action = _pdf_split(row, p, ctx)
        elif k == "ocr":
            action = _ocr_one(row, p, ctx)
        elif k == "pdf_to_docx":
            action = _pdf_to_docx(row, p, ctx)
        elif k == "docx_to_pdf":
            action = _docx_to_pdf(row, p, ctx)
        elif k == "image_batch":
            action = _image_batch(row, p, ctx)
        else:
            action = {"ok": False, "reason": "未知工具"}
        if action.get("ok") is False:
            row["qc"] = "失败"
            row["note"] = action.get("reason") or "执行失败"
            if os.path.isfile(row.get("target") or ""):
                try:
                    row["out_size"] = os.path.getsize(row["target"])
                    row["sha256"] = sha256(row["target"])
                except OSError:
                    pass
            result["failed"] += 1
            return
        out = action.get("out") or row.get("target")
        row["out"] = out
        row["out_name"] = os.path.basename(out)
        if not os.path.isfile(out):
            row["qc"] = "失败"
            row["note"] = "执行完没有输出文件"
            result["failed"] += 1
            return
        row["out_size"] = os.path.getsize(out)
        row["sha256"] = sha256(out) if row["out_size"] > 0 else ""
        row["pages_out"] = action.get("pages_out") or row.get("pages_out") or 0
        row["chars"] = action.get("chars") or 0
        row["detail_out"] = action.get("detail_out") or ""
        reasons = []
        if row["out_size"] <= 0:
            reasons.append("输出为空")
        if action.get("review"):
            reasons.append(action["review"])
        try:
            if _snapshot(row["src"]) != before:
                reasons.append("源文件被改动")
        except OSError:
            reasons.append("源文件事后读不了")
        row["note"] = action.get("note") or ""
        if reasons:
            row["qc"] = "需复核"
            row["note"] = "；".join([x for x in [row["note"]] + reasons if x])
            result["failed"] += 1
        else:
            row["qc"] = "通过"
            row["note"] = "；".join([x for x in [row["note"], "源文件未动"] if x])
            result["done"] += 1
    except Exception as e:
        row["qc"] = "失败"
        row["note"] = "%s: %s" % (type(e).__name__, str(e)[:200])
        result["failed"] += 1


def _versions():
    out = {}
    for name, mod in (("pypdf", "pypdf"), ("pypdfium2", "pypdfium2"),
                      ("reportlab", "reportlab"), ("python-docx", "python-docx"),
                      ("Pillow", "Pillow")):
        try:
            out[name] = _pkg_version(mod)
        except Exception:
            out[name] = ""
    return out


MANIFEST_HEAD = ("序号", "工具", "输入文件", "输出文件", "页数/尺寸", "字符数",
                 "输出字节", "源SHA256", "输出SHA256", "质检", "说明")


def write_manifest(rows, outdir, key="pdf_split", params=None, result=None):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.join(os.path.abspath(outdir), "_文档清单_" + stamp)
    csv_path, json_path = base + ".csv", base + ".json"
    if os.path.exists(csv_path) or os.path.exists(json_path):
        base += "-1"
        csv_path, json_path = base + ".csv", base + ".json"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(MANIFEST_HEAD)
        for i, r in enumerate(rows, 1):
            detail = r.get("detail_out") or ""
            if r.get("pages") and not r.get("pages_out"):
                detail = "%d 页" % r.get("pages")
            w.writerow([
                i, tool(key)["short"], os.path.basename(r.get("src") or ""),
                os.path.basename(r.get("out") or ""), detail, r.get("chars") or 0,
                r.get("out_size") or 0, r.get("src_sha256") or "",
                r.get("sha256") or "", r.get("qc") or "", r.get("note") or "",
            ])
    payload = {
        "tool": key, "tool_label": tool(key)["label"],
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "params": params or {}, "params_text": describe_params(key, params or {}),
        "outdir": os.path.abspath(outdir),
        "versions": _versions(), "ocr_lang": ocr_lang() if HAS_PDFIUM else "",
        "total": len(rows),
        "passed": sum(1 for r in rows if r.get("qc") == "通过"),
        "started_at": (result or {}).get("started_at") or "",
        "ended_at": (result or {}).get("ended_at") or "",
        "rows": rows,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {"manifest_csv": csv_path, "manifest_json": json_path}


def undo(manifest_json):
    """只删清单里记录、且确实在输出目录下的产物；不碰源文件。"""
    try:
        with open(manifest_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return {"ok": False, "error": "读不到清单：%s" % e, "removed": 0}
    outdir = os.path.abspath(data.get("outdir") or "")
    if not outdir or not os.path.isdir(outdir):
        return {"ok": False, "error": "清单里的输出目录不存在", "removed": 0}
    removed, skipped = 0, []
    for row in data.get("rows") or []:
        out = os.path.abspath(row.get("out") or "")
        src = os.path.abspath(row.get("src") or "")
        if not out or not os.path.isfile(out):
            continue
        if src and os.path.normcase(out) == os.path.normcase(src):
            skipped.append(out)
            continue
        try:
            if os.path.commonpath([outdir, out]) != outdir:
                skipped.append(out)
                continue
            os.remove(out)
            removed += 1
        except (OSError, ValueError):
            skipped.append(out)
    try:
        os.remove(manifest_json)
        csv_path = os.path.splitext(manifest_json)[0] + ".csv"
        if os.path.isfile(csv_path):
            os.remove(csv_path)
    except OSError:
        pass
    return {"ok": True, "removed": removed, "skipped": skipped,
            "error": "" if not skipped else "有 %d 个文件没删（不在输出目录或与源相同）" % len(skipped)}


def summary_text(result):
    if not result:
        return "还没有开始。"
    if result.get("error"):
        return "没跑起来：%s" % result["error"]
    total = result.get("total") or 0
    done = result.get("done") or 0
    failed = result.get("failed") or 0
    stopped = result.get("stopped") or 0
    text = "共 %d 项：通过 %d，失败/跳过 %d" % (total, done, failed)
    if stopped:
        text += "，停止 %d" % stopped
    text += "。"
    if result.get("manifest_csv"):
        text += " 清单：%s" % os.path.basename(result["manifest_csv"])
    return text

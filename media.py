# -*- coding: utf-8 -*-
"""v0.32 媒体样板：音频批量转码的最小闭环。

只做四件事，顺序不能省：
  1. 预检：文件存在、能读出音频流、时长/采样率/声道可核对；
  2. 转码：按固定预设逐个输出，源文件只读不写；
  3. 质检：输出存在、时长达标、编码/采样率/声道符合预设；源文件哈希不变；
  4. 交付：写 CSV + JSON 清单，带每个输出的 SHA256。

不依赖界面。调用方可以用 progress / cancel 回调把它放进对话框。
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
from pathlib import Path

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus",
              ".wma", ".aiff", ".aif", ".amr", ".ape"}

PRESETS = {
    "mp3_192": {
        "label": "MP3 192k / 44.1kHz / 立体声",
        "ext": ".mp3", "codec": "mp3", "sample_rate": 44100, "channels": 2,
        "args": ["-vn", "-map", "0:a:0", "-ar", "44100", "-ac", "2",
                 "-c:a", "libmp3lame", "-b:a", "192k"],
    },
    "mp3_128": {
        "label": "MP3 128k / 44.1kHz / 立体声",
        "ext": ".mp3", "codec": "mp3", "sample_rate": 44100, "channels": 2,
        "args": ["-vn", "-map", "0:a:0", "-ar", "44100", "-ac", "2",
                 "-c:a", "libmp3lame", "-b:a", "128k"],
    },
    "m4a_128": {
        "label": "M4A AAC 128k / 44.1kHz / 立体声",
        "ext": ".m4a", "codec": "aac", "sample_rate": 44100, "channels": 2,
        "args": ["-vn", "-map", "0:a:0", "-ar", "44100", "-ac", "2",
                 "-c:a", "aac", "-b:a", "128k"],
    },
    "wav_16k": {
        "label": "WAV 16-bit / 16kHz / 单声道（转写用）",
        "ext": ".wav", "codec": "pcm_s16le", "sample_rate": 16000, "channels": 1,
        "args": ["-vn", "-map", "0:a:0", "-ar", "16000", "-ac", "1",
                 "-c:a", "pcm_s16le"],
    },
}
PRESET_ORDER = ("mp3_192", "mp3_128", "m4a_128", "wav_16k")


def preset(key):
    return PRESETS.get(str(key or "").strip()) or PRESETS["mp3_192"]


def preset_items():
    return [(k, PRESETS[k]["label"]) for k in PRESET_ORDER]


def _which(name):
    """优先环境变量，其次 PATH，最后找本机常见安装位。"""
    env = os.environ.get(name.upper() + "_BIN") or os.environ.get(name.upper())
    if env and os.path.isfile(env):
        return env
    found = shutil.which(name)
    if found:
        return found
    for base in (r"I:\ProgramFiles\ffmpeg\bin", r"C:\ProgramFiles\ffmpeg\bin",
                 r"C:\ffmpeg\bin"):
        path = os.path.join(base, name + ".exe")
        if os.path.isfile(path):
            return path
    return ""


def ffmpeg_path():
    return _which("ffmpeg")


def ffprobe_path():
    return _which("ffprobe")


def available():
    return bool(ffmpeg_path() and ffprobe_path())


def _run(args, timeout=30):
    """隐藏窗口地跑外部命令，返回 (code, stdout, stderr)。"""
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout,
                           encoding="utf-8", errors="replace", **kw)
        return p.returncode, p.stdout or "", p.stderr or ""
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "", str(e)


_FF_VERSION = None


def ffmpeg_version():
    global _FF_VERSION
    if _FF_VERSION is not None:
        return _FF_VERSION
    ff = ffmpeg_path()
    if not ff:
        _FF_VERSION = ""
        return _FF_VERSION
    code, out, _ = _run([ff, "-version"], 20)
    _FF_VERSION = out.splitlines()[0].strip() if code == 0 and out else ""
    return _FF_VERSION


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def probe(path):
    """读音频流与容器信息；读不出就返回 error 字段，不猜。"""
    fp = ffprobe_path()
    if not fp:
        return {"ok": False, "error": "找不到 ffprobe"}
    code, out, err = _run([
        fp, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ], 90)
    if code != 0:
        return {"ok": False, "error": (err or "ffprobe 读取失败").strip()[-160:]}
    try:
        data = json.loads(out or "{}")
    except ValueError:
        return {"ok": False, "error": "ffprobe 返回不是 JSON"}
    streams = [s for s in (data.get("streams") or [])
               if s.get("codec_type") == "audio"]
    if not streams:
        return {"ok": False, "error": "没有音频流"}
    s = streams[0]
    fmt = data.get("format") or {}
    duration = _float(s.get("duration")) or _float(fmt.get("duration")) or 0.0
    return {
        "ok": duration > 0,
        "duration": round(duration, 2),
        "codec": str(s.get("codec_name") or ""),
        "sample_rate": int(_float(s.get("sample_rate"))),
        "channels": int(_float(s.get("channels"))),
        "bit_rate": int(_float(s.get("bit_rate")) or _float(fmt.get("bit_rate"))),
        "format": str(fmt.get("format_name") or ""),
        "size": int(_float(fmt.get("size")) or 0),
        "error": "" if duration > 0 else "时长为 0",
    }


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _safe_stem(stem):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(stem or "").strip())
    return stem[:120] or "未命名"


def _unique_path(path, src_abs=""):
    """同名不覆盖；与源文件同路径时加「-转码」。最多避让 999 次。"""
    path = os.path.abspath(path)
    src_norm = os.path.normcase(os.path.abspath(src_abs)) if src_abs else ""
    if src_norm and os.path.normcase(path) == src_norm:
        base = os.path.splitext(path)[0] + "-转码" + os.path.splitext(path)[1]
        path = base
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for i in range(1, 1000):
        cand = "%s-%d%s" % (base, i, ext)
        if not os.path.exists(cand):
            return cand
    raise OSError("同名文件太多，无法生成输出名")


def preflight(paths):
    """逐个预检，返回可操作标记与原因；不改任何文件。"""
    rows = []
    for raw in paths or []:
        src = str(raw or "").strip()
        row = {"src": src, "name": os.path.basename(src), "ok": False,
               "reason": "", "size": 0, "duration": 0.0, "codec": "",
               "sample_rate": 0, "channels": 0}
        if not src:
            row["reason"] = "空路径"
            rows.append(row)
            continue
        if not os.path.isfile(src):
            row["reason"] = "文件不存在"
            rows.append(row)
            continue
        src = os.path.abspath(src)
        row["src"] = src
        ext = os.path.splitext(src)[1].lower()
        try:
            row["size"] = os.path.getsize(src)
        except OSError:
            row["size"] = 0
        if ext not in AUDIO_EXTS:
            row["reason"] = "不是支持的音频格式：%s" % (ext or "无扩展名")
        elif row["size"] <= 0:
            row["reason"] = "空文件"
        else:
            info = probe(src)
            row.update({k: info.get(k) for k in
                        ("duration", "codec", "sample_rate", "channels")})
            if info.get("ok"):
                row["ok"] = True
            else:
                row["reason"] = info.get("error") or "读不出音频"
        rows.append(row)
    return rows


def plan(paths, outdir, preset_key="mp3_192"):
    """只算输出路径，不落盘。返回预检行 + target 字段。"""
    pr = preset(preset_key)
    out_root = os.path.abspath(str(outdir or "").strip())
    rows = preflight(paths)
    if not out_root:
        for row in rows:
            row["ok"] = False
            row["reason"] = row["reason"] or "没有输出目录"
        return rows, out_root
    if not os.path.isdir(out_root):
        rows = [dict(r) for r in rows]
        for row in rows:
            row["ok"] = False
            row["reason"] = row["reason"] or "输出目录不存在"
        return rows, out_root
    for row in rows:
        if not row["ok"]:
            continue
        stem = _safe_stem(os.path.splitext(row["name"])[0])
        cand = os.path.join(out_root, stem + pr["ext"])
        try:
            row["target"] = _unique_path(cand, row["src"])
        except OSError as e:
            row["ok"] = False
            row["reason"] = str(e)
    return rows, out_root


def _qc_reasons(info, dur_in, pr):
    why = []
    if not info.get("ok"):
        why.append(info.get("error") or "输出读不出")
        return why
    dur_out = info.get("duration") or 0.0
    tol = max(0.35, min(1.0, (dur_in or 1) * 0.01))
    if abs(dur_out - dur_in) > tol:
        why.append("时长差 %.2f 秒" % abs(dur_out - dur_in))
    if str(info.get("codec") or "").lower() != pr["codec"]:
        why.append("编码 %s，预设 %s" % (info.get("codec") or "空", pr["codec"]))
    if int(info.get("sample_rate") or 0) != pr["sample_rate"]:
        why.append("采样率 %s，预设 %s" % (info.get("sample_rate") or 0,
                                          pr["sample_rate"]))
    if int(info.get("channels") or 0) != pr["channels"]:
        why.append("声道 %s，预设 %s" % (info.get("channels") or 0,
                                         pr["channels"]))
    return why


def run_batch(paths, outdir, preset_key="mp3_192", progress=None, cancel=None,
              timeout=600):
    """按顺序转码并质检，最后写 CSV/JSON 清单。

    progress(i, total, row) 在每个文件结束时回调；cancel() 返回真就停。
    返回结构可直接给界面与测试用，不抛未处理异常。
    """
    pr = preset(preset_key)
    started = datetime.datetime.now()
    rows, out_root = plan(paths, outdir, preset_key)
    result = {
        "ok": False, "total": len(rows), "done": 0, "failed": 0,
        "rows": rows, "preset": preset_key, "preset_label": pr["label"],
        "outdir": out_root, "manifest_csv": "", "manifest_json": "",
        "ffmpeg_version": ffmpeg_version(),
        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"), "ended_at": "",
        "error": "",
    }
    if not available():
        result["error"] = "找不到 ffmpeg / ffprobe，无法转码"
        return result
    if not out_root or not os.path.isdir(out_root):
        result["error"] = "先选择一个存在的输出目录"
        return result
    runnable = [r for r in rows if r.get("ok")]
    if not runnable:
        result["error"] = "没有可转码的文件；先看预检原因"
        return result

    ff = ffmpeg_path()
    for i, row in enumerate(rows):
        if cancel and cancel():
            row["qc"] = "已停止"
            row["note"] = "用户停止，未执行"
            continue
        if not row.get("ok"):
            row["qc"] = "跳过"
            row["note"] = row.get("reason") or "预检未通过"
            result["failed"] += 1
            if progress:
                progress(i + 1, len(rows), row)
            continue
        src = row["src"]
        target = row["target"]
        row.update({"out": target, "out_name": os.path.basename(target),
                    "qc": "失败", "note": "", "sha256": "",
                    "src_sha256": "", "src_size": 0, "src_mtime": 0,
                    "out_size": 0, "duration_out": 0.0, "codec": "",
                    "sample_rate": 0, "channels": 0})
        try:
            row["src_size"] = os.path.getsize(src)
            row["src_mtime"] = round(os.path.getmtime(src), 3)
            row["src_sha256"] = sha256(src)
        except OSError as e:
            row["note"] = "源文件读不了：%s" % e
            result["failed"] += 1
            if progress:
                progress(i + 1, len(rows), row)
            continue
        args = [ff, "-nostdin", "-hide_banner", "-loglevel", "error",
                "-i", src] + pr["args"] + [target]
        code, _, err = _run(args, timeout)
        if code != 0 or not os.path.isfile(target):
            row["note"] = "ffmpeg 失败：%s" % ((err or "").strip()[-180:]
                                              or "没有输出文件")
            result["failed"] += 1
        else:
            info = probe(target)
            row.update({"out_size": os.path.getsize(target),
                        "duration_out": info.get("duration") or 0.0,
                        "codec": info.get("codec") or "",
                        "sample_rate": int(info.get("sample_rate") or 0),
                        "channels": int(info.get("channels") or 0)})
            reasons = _qc_reasons(info, row.get("duration") or 0.0, pr)
            if row["out_size"] > 0:
                row["sha256"] = sha256(target)
            else:
                reasons.append("输出为空")
            # 源文件必须原样：大小、修改时间、哈希三项都核对
            try:
                src_after = (os.path.getsize(src), round(os.path.getmtime(src), 3),
                             sha256(src))
                src_before = (row["src_size"], row["src_mtime"], row["src_sha256"])
                if src_after != src_before:
                    reasons.append("源文件被改动")
            except OSError:
                reasons.append("源文件事后读不了")
            if reasons:
                row["qc"] = "需复核"
                row["note"] = "；".join(reasons)
                result["failed"] += 1
            else:
                row["qc"] = "通过"
                row["note"] = "时长/编码/采样率/声道符合预设；源文件未动"
                result["done"] += 1
        if progress:
            progress(i + 1, len(rows), row)

    result["ended_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        result.update(write_manifest(rows, out_root, preset_key))
    except (OSError, ValueError) as e:
        result["error"] = "清单写入失败：%s" % e
    result["ok"] = result["done"] > 0 and result["failed"] == 0 and \
        not result["error"]
    return result


MANIFEST_HEAD = ("序号", "源文件", "输出文件", "源时长", "输出时长", "编码",
                 "采样率", "声道", "源SHA256", "输出SHA256", "质检", "说明")


def write_manifest(rows, outdir, preset_key="mp3_192"):
    """在输出目录写一份 CSV + 一份 JSON，名字带时间，不覆盖旧清单。"""
    pr = preset(preset_key)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.join(os.path.abspath(outdir), "_媒体清单_" + stamp)
    csv_path, json_path = base + ".csv", base + ".json"
    if os.path.exists(csv_path) or os.path.exists(json_path):
        base = base + "-1"
        csv_path, json_path = base + ".csv", base + ".json"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(MANIFEST_HEAD)
        for i, r in enumerate(rows, 1):
            w.writerow([
                i, os.path.basename(r.get("src") or ""),
                os.path.basename(r.get("out") or ""), r.get("duration") or 0,
                r.get("duration_out") or 0, r.get("codec") or "",
                r.get("sample_rate") or 0, r.get("channels") or 0,
                r.get("src_sha256") or "", r.get("sha256") or "",
                r.get("qc") or "", r.get("note") or "",
            ])
    payload = {
        "preset": preset_key, "preset_label": pr["label"],
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ffmpeg_version": ffmpeg_version(),
        "total": len(rows),
        "passed": sum(1 for r in rows if r.get("qc") == "通过"),
        "rows": rows,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {"manifest_csv": csv_path, "manifest_json": json_path}


def summary_text(result):
    """给界面状态栏的一句话，不隐藏失败。"""
    if not result:
        return "还没有开始。"
    if result.get("error"):
        return "没跑起来：%s" % result["error"]
    total = result.get("total") or 0
    done = result.get("done") or 0
    failed = result.get("failed") or 0
    text = "共 %d 个：通过 %d，失败/跳过 %d。" % (total, done, failed)
    if result.get("manifest_csv"):
        text += " 清单：%s" % os.path.basename(result["manifest_csv"])
    return text

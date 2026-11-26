# -*- coding: utf-8 -*-
"""本地语音朗读：调用 Windows 自带语音（SAPI / System.Speech）。

口径：
- 不装第三方包、不联网、不上传文本；只在用户点「朗读」时发声，不自动播报。
- 只用系统已安装的语音；优先中文（zh-CN / zh-TW / zh-HK），找不到就明确告知，
  不拿英文语音去念中文（那只会念成一串怪音）。
- 朗读在独立进程里跑，可随时停止；失败只返回原因，不影响主流程。
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading

_CREATE_NO_WINDOW = 0x08000000
_LOCK = threading.Lock()
_PROBE = {"done": False, "voice": None, "voices": [], "reason": ""}
_CURRENT = {"proc": None, "tmp": None}


def _powershell():
    exe = shutil.which("powershell.exe") or shutil.which("powershell")
    return exe


def _run(args, env=None, timeout=15):
    """跑一次 PowerShell，返回 (exit_code, stdout, stderr)。"""
    exe = _powershell()
    if not exe:
        return 127, "", "找不到 powershell.exe"
    flags = _CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        p = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=env, creationflags=flags)
    except subprocess.TimeoutExpired:
        return 124, "", "查询系统语音超时"
    except OSError as e:
        return 126, "", str(e)
    return p.returncode, p.stdout or "", p.stderr or ""


_PROBE_SCRIPT = (
    "Add-Type -AssemblyName System.Speech;"
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$s.GetInstalledVoices() | ForEach-Object { if ($_.Enabled) { "
    "$_.VoiceInfo.Culture.Name + '|' + $_.VoiceInfo.Name } };"
    "$s.Dispose()"
)


def probe(force=False):
    """探测系统语音。返回 {"ok": bool, "voice": 中文语音名或 None, "voices": [...], "reason": str}。"""
    with _LOCK:
        if _PROBE["done"] and not force:
            return {"ok": _PROBE["voice"] is not None,
                    "voice": _PROBE["voice"], "voices": list(_PROBE["voices"]),
                    "reason": _PROBE["reason"]}
        if os.name != "nt":
            _PROBE.update(done=True, voice=None, voices=[],
                          reason="系统语音朗读只支持 Windows")
            return {"ok": False, "voice": None, "voices": [],
                    "reason": "系统语音朗读只支持 Windows"}
        code, out, err = _run(_PROBE_SCRIPT)
        if code != 0:
            why = (err or out or "").strip().splitlines()
            _PROBE.update(done=True, voice=None, voices=[],
                          reason="系统语音不可用：%s" % (why[-1] if why else "未知原因"))
            return {"ok": False, "voice": None, "voices": [],
                    "reason": _PROBE["reason"]}
        items = []
        for line in (out or "").splitlines():
            line = line.strip()
            if "|" in line:
                culture, name = line.split("|", 1)
                items.append((culture.strip(), name.strip()))
        zh = None
        for culture, name in items:
            if culture.lower().startswith("zh"):
                zh = name
                break
        reason = "" if zh else "未找到中文语音（请在系统设置里补装中文语音包）"
        _PROBE.update(done=True, voice=zh, voices=[n for _, n in items], reason=reason)
        return {"ok": zh is not None, "voice": zh,
                "voices": [n for _, n in items], "reason": reason}


def speak(text, rate=0, volume=100):
    """朗读一段文本。返回 (ok, reason)。同一次只允许一个朗读进程。"""
    text = (text or "").strip()
    if not text:
        return False, "没有可朗读的内容"
    info = probe()
    if not info["ok"]:
        return False, info["reason"]
    stop()
    fd, path = tempfile.mkstemp(prefix="cc-tts-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text[:4000])
    except OSError as e:
        return False, "写入临时文件失败：%s" % e

    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "if ($env:CC_TTS_VOICE) { $s.SelectVoice($env:CC_TTS_VOICE) };"
        "$s.Rate = [int]$env:CC_TTS_RATE;"
        "$s.Volume = [int]$env:CC_TTS_VOL;"
        "$t = [IO.File]::ReadAllText($env:CC_TTS_FILE, [Text.Encoding]::UTF8);"
        "$s.Speak($t); $s.Dispose()"
    )
    env = dict(os.environ)
    env.update({"CC_TTS_FILE": path, "CC_TTS_VOICE": info["voice"],
                "CC_TTS_RATE": str(max(-10, min(10, int(rate)))),
                "CC_TTS_VOL": str(max(0, min(100, int(volume))))})
    exe = _powershell()
    if not exe:
        return False, "找不到 powershell.exe"
    flags = _CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env, creationflags=flags)
    except OSError as e:
        _cleanup(path)
        return False, "启动朗读失败：%s" % e
    with _LOCK:
        _CURRENT["proc"] = proc
        _CURRENT["tmp"] = path
    return True, ""


def is_speaking():
    with _LOCK:
        proc = _CURRENT["proc"]
    return bool(proc and proc.poll() is None)


def stop():
    """停止当前朗读并清掉临时文件。"""
    with _LOCK:
        proc = _CURRENT["proc"]
        tmp = _CURRENT["tmp"]
        _CURRENT["proc"] = None
        _CURRENT["tmp"] = None
    if proc and proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    _cleanup(tmp)


def _cleanup(path):
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def describe():
    """给界面用的一句话状态。"""
    info = probe()
    if not info["ok"]:
        return info["reason"]
    n = len(info["voices"])
    return "可用语音：%s（共 %d 个）" % (info["voice"], n)

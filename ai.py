# -*- coding: utf-8 -*-
"""桌面端 AI 分类建议：API-only，默认关，未配置或失败时回退本地规则。

设计边界：
- 只把「文件名 + 允许类别」发给 API，不读文件正文；
- 只返回建议，不写台账、不改状态、不归档；
- API Key 只存本机 settings.json，不打印、不写日志、不随错误回显。
"""

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_CONFIG = {
    "enabled": False,
    "base_url": "https://api.siliconflow.cn/v1",
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "api_key": "",
    "timeout": 20,
}

# 文件名关键词 → 类别。命中即有建议，但始终让人工确认。
RULES = (
    ("奖助材料", ("奖学金", "助学金", "励志", "资助", "贫困", "困难", "贷款",
                 "家庭经济", "勤工", "补助", "低保")),
    ("学分材料", ("学分", "成绩", "体测", "综测", "素质", "第二课堂", "课程",
                 "考试", "绩点", "学籍")),
    ("宣传材料", ("新闻", "宣传", "海报", "推文", "公众号", "照片", "视频",
                 "摄影", "招新", "活动稿")),
    ("团务材料", ("团日", "团课", "团员", "青年大学习", "团费", "团支部",
                 "推优", "入团", "团委", "团组织")),
    ("班级事务", ("班会", "签到", "安全", "承诺", "登记", "统计", "通知",
                 "名单", "请假", "班级")),
)


def _settings_path():
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "ClassConsole" / "settings.json"


def _read_settings():
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_settings(data):
    path = _settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def load_config():
    """读取 AI 配置；任何脏值都收敛成安全默认。"""
    raw = _read_settings().get("ai", {})
    if not isinstance(raw, dict):
        raw = {}
    cfg = dict(DEFAULT_CONFIG)
    cfg["enabled"] = bool(raw.get("enabled", False))
    for key in ("base_url", "model", "api_key"):
        val = raw.get(key)
        if isinstance(val, str):
            cfg[key] = val.strip()
    cfg["base_url"] = cfg["base_url"].rstrip("/")
    try:
        timeout = int(raw.get("timeout", DEFAULT_CONFIG["timeout"]))
    except (TypeError, ValueError):
        timeout = DEFAULT_CONFIG["timeout"]
    cfg["timeout"] = max(5, min(40, timeout))
    return cfg


def save_config(cfg):
    """只写 ai 段，保留主题、界面等其它本机设置。"""
    data = _read_settings()
    merged = dict(DEFAULT_CONFIG)
    for key in merged:
        if key in cfg:
            merged[key] = cfg[key]
    merged["enabled"] = bool(merged["enabled"])
    merged["base_url"] = str(merged["base_url"] or "").strip().rstrip("/")
    merged["model"] = str(merged["model"] or "").strip()
    merged["api_key"] = str(merged["api_key"] or "").strip()
    try:
        merged["timeout"] = max(5, min(40, int(merged["timeout"])))
    except (TypeError, ValueError):
        merged["timeout"] = DEFAULT_CONFIG["timeout"]
    data["ai"] = merged
    return _write_settings(data)


def api_ready(cfg=None):
    cfg = cfg or load_config()
    return bool(cfg.get("enabled") and cfg.get("base_url")
                and cfg.get("model") and cfg.get("api_key"))


def status_text(cfg=None):
    cfg = cfg or load_config()
    if api_ready(cfg):
        return "API 已启用", "api"
    if cfg.get("enabled"):
        return "API 未配全，走本地规则", "local"
    return "API 默认关，走本地规则", "local"


def _clean_name(name):
    try:
        return os.path.splitext(os.path.basename(str(name or "")))[0].strip()
    except (TypeError, ValueError):
        return str(name or "").strip()


def local_suggest(name, categories):
    """文件名关键词规则；不读正文、不猜提交人。"""
    categories = list(categories or [])
    stem = _clean_name(name)
    hits = []
    for cat, words in RULES:
        if cat not in categories:
            continue
        found = [w for w in words if w in stem]
        if found:
            hits.append((len(found), cat, found))
    if hits:
        hits.sort(key=lambda x: (-x[0], categories.index(x[1])))
        _, cat, found = hits[0]
        conf = 0.78 if len(found) > 1 else 0.66
        reason = "文件名含「%s」，倾向%s" % ("、".join(found[:2]), cat)
        return {"file": str(name or ""), "cat": cat, "confidence": conf,
                "source": "本地规则", "reason": reason}
    fallback = "班级事务" if "班级事务" in categories else (categories[0] if categories else "")
    return {"file": str(name or ""), "cat": fallback, "confidence": 0.32,
            "source": "本地规则",
            "reason": "没有明显关键词；先按%s，需人工确认" % (fallback or "默认类别")}


def _extract_json(text):
    text = str(text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    left, right = text.find("{"), text.rfind("}")
    if left < 0 or right <= left:
        return None
    try:
        return json.loads(text[left:right + 1])
    except ValueError:
        return None


def _api_suggest(name, categories, cfg):
    """返回 (建议, 失败原因)；成功时原因为空。不把 Key 或服务端原文带出去。"""
    url = cfg["base_url"] + "/chat/completions"
    system = (
        "你是班级材料分类助手。只根据文件名判断类别，只能从给定类别中选择一个；"
        "不读文件正文，不猜测提交人。只输出一个 JSON 对象，格式："
        '{"category":"类别名","confidence":0到1的小数,"reason":"不超过20字的依据"}。'
    )
    user = "文件名：%s\n可选类别：%s" % (name, "、".join(categories))
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": 160,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer " + cfg["api_key"],
        }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 20)) as resp:
            body = resp.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return None, "鉴权失败"
        if e.code == 429:
            return None, "限流或额度不足"
        if e.code >= 500:
            return None, "服务端错误"
        return None, "HTTP %d" % e.code
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            return None, "超时"
        return None, "网络不可达"
    except TimeoutError:
        return None, "超时"
    except (OSError, ValueError):
        return None, "请求失败"
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        return None, "回包缺字段"
    parsed = _extract_json(content)
    if not isinstance(parsed, dict):
        return None, "内容不是 JSON"
    cat = str(parsed.get("category") or "").strip()
    if cat not in categories:
        return None, "类别越界"
    try:
        confidence = float(parsed.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reason = str(parsed.get("reason") or "").strip()[:60]
    if not reason:
        reason = "按文件名判断"
    return {"file": str(name or ""), "cat": cat, "confidence": confidence,
            "source": "API", "reason": reason}, ""


def suggest_category(name, categories, cfg=None):
    """单份文件建议；API 失败时必定有本地兜底结果。"""
    cfg = cfg or load_config()
    if api_ready(cfg):
        result, error = _api_suggest(str(name or ""), list(categories or []), cfg)
        if result:
            return result
        result = local_suggest(name, categories)
        result["reason"] = "API 没返回（%s），按文件名兜底：%s" % (
            error or "未知原因", result["reason"])
        return result
    return local_suggest(name, categories)


def chat_json(system, user, cfg=None, max_tokens=240):
    """通用一次问答，要求模型只回一个 JSON 对象。

    返回 (dict, "") 或 (None, 原因)。原因沿用分类建议那套口径，
    不把 Key、也不把服务端原文带回界面。
    """
    cfg = cfg or load_config()
    if not api_ready(cfg):
        return None, "API 未启用"
    url = cfg["base_url"] + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer " + cfg["api_key"],
        }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 20)) as resp:
            body = resp.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return None, "鉴权失败"
        if e.code == 429:
            return None, "限流或额度不足"
        if e.code >= 500:
            return None, "服务端错误"
        return None, "HTTP %d" % e.code
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            return None, "超时"
        return None, "网络不可达"
    except TimeoutError:
        return None, "超时"
    except (OSError, ValueError):
        return None, "请求失败"
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        return None, "回包缺字段"
    parsed = _extract_json(content)
    if not isinstance(parsed, dict):
        return None, "内容不是 JSON"
    return parsed, ""


def format_lines(results):
    """把建议整理成可复制的纯文本，不包含路径与 Key。"""
    lines = []
    for i, r in enumerate(results or [], 1):
        lines.append("%d. %s → %s（%.0f%%，%s）%s" % (
            i, r.get("file", ""), r.get("cat", ""),
            float(r.get("confidence", 0)) * 100, r.get("source", ""),
            r.get("reason", "")))
    return "\n".join(lines)

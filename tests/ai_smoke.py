# -*- coding: utf-8 -*-
"""桌面 AI 建议逻辑回归：不联网、不读写真实设置。

运行：py -3.14 tests/ai_smoke.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="cc-ai-appdata-")

import ai  # noqa: E402

CATS = ["团务材料", "奖助材料", "学分材料", "宣传材料", "班级事务"]
PASS = 0


def ok(name, cond):
    global PASS
    if not cond:
        raise SystemExit("FAIL %s" % name)
    PASS += 1
    print("PASS", name)


def main():
    cfg = ai.load_config()
    ok("默认关闭", cfg["enabled"] is False)
    ok("默认无 Key", cfg["api_key"] == "")
    ok("默认不可调用", ai.api_ready(cfg) is False)

    r = ai.local_suggest("250203_李雨桐_团日活动记录.docx", CATS)
    ok("团日归团务", r["cat"] == "团务材料")
    ok("来源本地", r["source"] == "本地规则")
    ok("置信度可解释", 0.6 <= r["confidence"] <= 0.9)

    r = ai.local_suggest("体测成绩统计表.xlsx", CATS)
    ok("体测归学分", r["cat"] == "学分材料")

    r = ai.local_suggest("家庭经济困难认定表.pdf", CATS)
    ok("困难归奖助", r["cat"] == "奖助材料")

    r = ai.local_suggest("社团招新新闻稿.docx", CATS)
    ok("新闻稿归宣传", r["cat"] == "宣传材料")

    r = ai.local_suggest("IMG_20261126.jpg", CATS)
    ok("无关键词兜底班级", r["cat"] == "班级事务")
    ok("兜底置信度低", r["confidence"] < 0.5)

    r = ai.local_suggest("团日活动.docx", ["宣传材料"])
    ok("不在类别内不硬塞", r["cat"] == "宣传材料")

    # 保存配置保留其它设置，并收敛超时
    path = Path(os.environ["APPDATA"]) / "ClassConsole" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"theme": "dark", "ui": {"sidebar": "collapsed"}},
                               ensure_ascii=False), encoding="utf-8")
    saved = ai.save_config({"enabled": True, "base_url": " https://example.com/v1/ ",
                            "model": "m", "api_key": "sk-test",
                            "timeout": "999"})
    ok("配置保存成功", saved is True)
    raw = json.loads(path.read_text(encoding="utf-8"))
    ok("保留主题", raw.get("theme") == "dark")
    ok("保留界面", raw.get("ui", {}).get("sidebar") == "collapsed")
    ok("地址去掉尾斜杠", raw["ai"]["base_url"] == "https://example.com/v1")
    ok("超时上限", raw["ai"]["timeout"] == 40)
    cfg = ai.load_config()
    ok("Key 已保存", cfg["api_key"] == "sk-test")
    ok("启用后可调用", ai.api_ready(cfg) is True)

    # API 成功路径：只发文件名，不把 Key 回显到建议
    captured = {}

    class FakeResp:
        def __init__(self, body):
            self.body = body

        def read(self, _n=None):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=20):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["auth"] = req.headers.get("Authorization")
        reply = {"choices": [{"message": {"content":
                 '```json\n{"category":"奖助材料","confidence":0.91,"reason":"文件名含奖学金"}\n```'}}]}
        return FakeResp(json.dumps(reply, ensure_ascii=False).encode("utf-8"))

    origin = ai.urllib.request.urlopen
    ai.urllib.request.urlopen = fake_urlopen
    try:
        r = ai.suggest_category("国家奖学金申请表.docx", CATS, cfg)
    finally:
        ai.urllib.request.urlopen = origin
    ok("API 类别", r["cat"] == "奖助材料")
    ok("API 置信度", abs(r["confidence"] - 0.91) < 0.001)
    ok("API 来源", r["source"] == "API")
    ok("请求只带文件名与类别", "国家奖学金申请表.docx" in
       captured["body"]["messages"][1]["content"])
    ok("请求 Key 走 Bearer", captured["auth"] == "Bearer sk-test")
    ok("建议不含 Key", "sk-test" not in json.dumps(r, ensure_ascii=False))

    # API 失败路径：必须回退本地，不阻断
    def fake_fail(req, timeout=20):
        raise ai.urllib.error.URLError("down")

    ai.urllib.request.urlopen = fake_fail
    try:
        r = ai.suggest_category("团日活动记录.docx", CATS, cfg)
    finally:
        ai.urllib.request.urlopen = origin
    ok("失败回退本地", r["source"] == "本地规则")
    ok("失败仍有类别", r["cat"] == "团务材料")
    ok("失败理由可解释", "API 没返回" in r["reason"])
    ok("失败不含 Key", "sk-test" not in json.dumps(r, ensure_ascii=False))

    def fake_401(req, timeout=20):
        raise ai.urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    ai.urllib.request.urlopen = fake_401
    try:
        r = ai.suggest_category("团日活动记录.docx", CATS, cfg)
    finally:
        ai.urllib.request.urlopen = origin
    ok("401 标鉴权失败", "鉴权失败" in r["reason"] and r["source"] == "本地规则")

    def fake_429(req, timeout=20):
        raise ai.urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)

    ai.urllib.request.urlopen = fake_429
    try:
        r = ai.suggest_category("团日活动记录.docx", CATS, cfg)
    finally:
        ai.urllib.request.urlopen = origin
    ok("429 标额度不足", "额度不足" in r["reason"] and r["source"] == "本地规则")

    def fake_timeout(req, timeout=20):
        raise TimeoutError("timed out")

    ai.urllib.request.urlopen = fake_timeout
    try:
        r = ai.suggest_category("团日活动记录.docx", CATS, cfg)
    finally:
        ai.urllib.request.urlopen = origin
    ok("超时标超时", "超时" in r["reason"] and r["source"] == "本地规则")

    # 非法 JSON / 越界类别退回本地
    def fake_bad(req, timeout=20):
        reply = {"choices": [{"message": {"content": "不是 JSON"}}]}
        return FakeResp(json.dumps(reply, ensure_ascii=False).encode("utf-8"))

    ai.urllib.request.urlopen = fake_bad
    try:
        r = ai.suggest_category("体测成绩.xlsx", CATS, cfg)
    finally:
        ai.urllib.request.urlopen = origin
    ok("坏回包不信任", r["source"] == "本地规则" and r["cat"] == "学分材料")

    ok("JSON 去围栏", ai._extract_json('```json\n{"a":1}\n```') == {"a": 1})
    ok("JSON 截取对象", ai._extract_json('说明 {"a":2} 尾巴') == {"a": 2})
    ok("JSON 坏文本", ai._extract_json("没有对象") is None)

    lines = ai.format_lines([{"file": "a.docx", "cat": "团务材料",
                              "confidence": 0.8, "source": "本地规则",
                              "reason": "含团日"}])
    ok("复制清单含类别", "团务材料" in lines and "80%" in lines)
    ok("复制清单不含 Key", "sk-test" not in lines)

    # 关闭 API 后仍可用本地规则
    ai.save_config({"enabled": False, "base_url": "", "model": "",
                    "api_key": "", "timeout": 20})
    ok("关闭后状态", ai.status_text()[0].startswith("API 默认关"))
    r = ai.suggest_category("班会签到表.xlsx", CATS)
    ok("关闭后本地建议", r["source"] == "本地规则" and r["cat"] == "班级事务")

    print("\nAI SMOKE OK %d" % PASS)


if __name__ == "__main__":
    main()

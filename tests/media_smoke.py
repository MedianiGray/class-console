# -*- coding: utf-8 -*-
"""v0.32 媒体样板的独立回归：20 个音频一次转码、质检、清单、源文件不动。

运行：
    py -3.14 tests/media_smoke.py
"""

import csv
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import media  # noqa: E402


def make_tone(path, seconds=1.0, freq=440):
    ff = media.ffmpeg_path()
    code, _, err = media._run([
        ff, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=%d:duration=%s" % (freq, seconds),
        "-ar", "48000", "-ac", "2", str(path),
    ], 30)
    if code != 0:
        raise SystemExit("生成测试音频失败：%s" % err)


def main():
    if not media.available():
        raise SystemExit("本机没有 ffmpeg/ffprobe，媒体样板无法验收")
    root = Path(tempfile.mkdtemp(prefix="cc-media-"))
    src_dir = root / "输入"
    out_dir = root / "输出"
    src_dir.mkdir()
    out_dir.mkdir()
    files = []
    for i in range(20):
        p = src_dir / ("第%02d段_测试音频.wav" % (i + 1))
        make_tone(p, 1.0, 300 + i * 20)
        files.append(str(p))
    # 混入一个非音频文件，必须被预检拦下
    note = src_dir / "说明.txt"
    note.write_text("不是音频", encoding="utf-8")
    files.append(str(note))

    rows = media.preflight(files)
    assert len(rows) == 21
    assert sum(1 for r in rows if r["ok"]) == 20, rows
    assert not rows[-1]["ok"] and "不是支持" in rows[-1]["reason"], rows[-1]

    result = media.run_batch(files, str(out_dir), "mp3_192")
    assert result["total"] == 21, result["total"]
    assert result["done"] == 20, result
    assert result["failed"] == 1, result
    assert result["manifest_csv"] and os.path.isfile(result["manifest_csv"])
    assert result["manifest_json"] and os.path.isfile(result["manifest_json"])
    outputs = [Path(r["out"]) for r in result["rows"] if r.get("out")]
    assert len(outputs) == 20
    for p in outputs:
        assert p.is_file() and p.stat().st_size > 1024, p
        assert p.suffix.lower() == ".mp3", p
    for r in result["rows"]:
        if r.get("out"):
            assert r["qc"] == "通过", r
            assert len(r["sha256"]) == 64, r
            assert r["src_sha256"] == media.sha256(r["src"]), r
            assert os.path.getsize(r["src"]) == r["src_size"], r
    with open(result["manifest_csv"], "r", encoding="utf-8-sig", newline="") as f:
        csv_rows = list(csv.reader(f))
    assert len(csv_rows) == 22, len(csv_rows)  # 表头 + 21 行
    assert csv_rows[0][0] == "序号"

    # 再跑一次：不得覆盖上一批输出；源文件仍不动
    before = {str(p) for p in out_dir.glob("*.mp3")}
    result2 = media.run_batch(files, str(out_dir), "mp3_192")
    after = {str(p) for p in out_dir.glob("*.mp3")}
    assert result2["done"] == 20, result2
    assert len(after) == 40, (len(before), len(after))
    assert before.issubset(after), "第二批覆盖了第一批输出"
    for src in files[:20]:
        assert media.sha256(src) == next(r["src_sha256"] for r in result["rows"]
                                          if r["src"] == src), src

    # 转写预设：采样率与声道必须按预设落地
    sub = files[:2]
    result3 = media.run_batch(sub, str(out_dir), "wav_16k")
    assert result3["done"] == 2, result3
    for r in result3["rows"]:
        assert r["qc"] == "通过" and r["sample_rate"] == 16000 and r["channels"] == 1, r

    print("MEDIA OK")
    print("输入 20 段 + 1 个非音频；第一轮通过 20、跳过 1；第二轮输出不覆盖；")
    print("清单：%s" % result["manifest_csv"])


if __name__ == "__main__":
    main()

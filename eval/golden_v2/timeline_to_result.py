"""timeline.txt(AliMeeting 真值转写) → board 同构 meeting_result.json。

用途:把 golden_v2 的 30 场干净转写喂进 PC 全流程(pc_full_minutes),得到 n=30 的
**纯摘要/结构化质量**评测(隔离 ASR/分离噪声)。金标本就从这份 timeline 生成 → 同源对比最公平。

timeline 行格式:  [seg-000001][00:33-00:35][001-M] 文本<sil>...
输出 segment 字段对齐板端 harness(segment_id/index/start_ms/end_ms/speaker_id/text/status)。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(r"C:/Users/Admin/meet")
TL_DIR = ROOT / "eval/golden_v2/timelines"

_LINE = re.compile(r"^\[(seg-\d+)\]\[(\d+(?::\d+)+)-(\d+(?::\d+)+)\]\[([^\]]+)\]\s*(.*)$")
_TAG = re.compile(r"<[^>]*>")  # <sil> <$> <%> 等 AliMeeting 标注


def _to_ms(t: str) -> int:
    parts = [int(x) for x in t.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)  # 补成 h:m:s
    h, m, s = parts[-3], parts[-2], parts[-1]
    return (h * 3600 + m * 60 + s) * 1000


def _clean(text: str) -> str:
    return re.sub(r"\s+", "", _TAG.sub("", text)).strip()


def build_result(mid: str) -> dict:
    """读 mid.timeline.txt → meeting_result.json 结构(transcript.segments)。"""
    lines = (TL_DIR / f"{mid}.timeline.txt").read_text(encoding="utf-8").splitlines()
    segments: list[dict] = []
    spk_map: dict[str, str] = {}
    for i, line in enumerate(lines):
        m = _LINE.match(line.strip())
        if not m:
            continue
        seg_id, t0, t1, spk_tok, text = m.groups()
        num = re.match(r"\d+", spk_tok)
        spk = f"speaker_{int(num.group()) if num else 0}"
        spk_map.setdefault(spk_tok, spk)
        clean = _clean(text)
        segments.append({
            "segment_id": seg_id,
            "index": i,
            "start_ms": _to_ms(t0),
            "end_ms": _to_ms(t1),
            "speaker_id": spk,
            "text": clean,
            "status": "ok" if clean else "transcript_empty",
        })
    speaker_ids = sorted({s["speaker_id"] for s in segments})
    return {
        "meeting": {"meeting_id": mid, "source": "golden_v2_timeline_clean"},
        "transcript": {
            "segment_count": len(segments),
            "nonempty_segment_count": sum(1 for s in segments if s["text"]),
            "speaker_ids": speaker_ids,
            "segments": segments,
        },
    }


def main() -> int:
    mid = sys.argv[1]
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else (ROOT / f"eval/_pc_clean/{mid}/meeting_result.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    res = build_result(mid)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    ne = res["transcript"]["nonempty_segment_count"]
    print(f"{mid}: 段={res['transcript']['segment_count']} 非空={ne} "
          f"发言人={res['transcript']['speaker_ids']} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

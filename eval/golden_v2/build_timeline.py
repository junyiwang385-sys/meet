"""A 阶段:官方 Praat TextGrid → 带 seg-id 的参考时间线 + speech_end。

自包含,无外部依赖。seg 编号规则与旧 eval kit 一致(非空 interval 按时间排序后从 1 编),
保证 refs 与既有金标可对齐。

用法:
  python build_timeline.py <path.TextGrid>   # 打印统计 + 写 <同名>.timeline.txt
"""
from __future__ import annotations

import argparse
import re
import pathlib


def parse_textgrid(path: str | pathlib.Path) -> list[dict]:
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    rows: list[dict] = []
    tiers = re.split(r"\n\s*item \[\d+\]:", text)
    for tier in tiers[1:]:
        nm = re.search(r'name = "([^"]*)"', tier)
        speaker = nm.group(1) if nm else "unknown"
        for m in re.finditer(
            r'xmin = ([\d.]+)\s*xmax = ([\d.]+)\s*text = "((?:[^"\\]|\\.)*)"', tier
        ):
            start, end, txt = float(m.group(1)), float(m.group(2)), m.group(3).strip()
            if txt:
                rows.append({
                    "start_ms": int(start * 1000),
                    "end_ms": int(end * 1000),
                    "speaker_id": speaker,
                    "text": txt,
                })
    rows.sort(key=lambda r: (r["start_ms"], r["end_ms"], r["speaker_id"]))
    for i, r in enumerate(rows, 1):
        r["segment_id"] = f"seg-{i:06d}"
    return rows


def speech_end_ms(segments: list[dict]) -> int:
    return max((s["end_ms"] for s in segments), default=0)


def _mmss(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def render_timeline(segments: list[dict]) -> str:
    return "\n".join(
        f'[{s["segment_id"]}][{_mmss(s["start_ms"])}-{_mmss(s["end_ms"])}][{s["speaker_id"]}] {s["text"]}'
        for s in segments
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("textgrid", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, default=None)
    args = ap.parse_args()
    segs = parse_textgrid(args.textgrid)
    speakers = sorted({s["speaker_id"] for s in segs})
    end = speech_end_ms(segs)
    out = args.out or args.textgrid.with_suffix(".timeline.txt")
    out.write_text(render_timeline(segs), encoding="utf-8")
    print(f"segments={len(segs)} speakers={speakers} speech_end_s={end/1000:.1f} -> {out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""分块粒度对照实验:一次喂几章会崩?(批量轴,验 CLAUDE.md "7K字断崖")

内容固定(整场会),只变每次调用喂进的章节数 chunk_size k:
  k=1  每次1章(最细,map-reduce基线)
  k=2  每次2章 ...
  k=N  一次喂全部章(最粗,长输入极端)
每个 chunk 一次 LLM 调用出摘要,拼起来算关键点召回。无 carryover,隔离"输入长度/复合度"效应。
k 越大→单次输入越长→若 4B 归纳崩,召回随 k 下降,断崖点即"喂到几章崩"。

用法(Ollama 需在跑):
  set PYTHONIOENCODING=utf-8
  python eval/chunk_size_experiment.py --meeting-result <g2.json> --golden eval/golden/R002S05C01.keypoints.json \
    --sizes 1,2,3,4,6,8 --out eval/reports/chunk_size_g2
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval" / "summary"))

from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession  # noqa: E402
import keypoint_recall as KR  # noqa: E402

_DIGIT = re.compile(r"[0-9零一二三四五六七八九十百千万]")

SYS = "你是会议纪要助手。只输出一个 JSON 对象,不要多余文字。"
PROMPT = (
    "任务:为下面这段会议内容写纪要。先抽关键点再成文。\n"
    "- key_points:本段所有重要结论/决定/数字/事项,尽量抓全,不遗漏(尤其数字、专名);\n"
    "- summary:120~400字,涵盖上面 key_points。\n"
    '输出 JSON:{{"key_points":["..."],"summary":"..."}}\n\n会议内容:\n{text}'
)


def load_chapters(mr_path: Path):
    d = json.loads(mr_path.read_text(encoding="utf-8"))
    segs = (d.get("transcript") or {}).get("segments") or []
    idx = {s["segment_id"]: i for i, s in enumerate(segs)}
    chapters = (d.get("summary") or {}).get("chapters") or []
    out = []
    for ch in chapters:
        a, b = ch.get("start_ref"), ch.get("end_ref")
        member = segs[idx[a]: idx[b] + 1] if a in idx and b in idx else \
            [s for s in segs if s["start_ms"] < ch.get("end_ms", 0) and s["end_ms"] > ch.get("start_ms", 0)]
        out.append("".join((s.get("text") or "").strip() for s in member if (s.get("text") or "").strip()))
    return out


def loads_tolerant(t: str) -> dict:
    try:
        return json.loads(t)
    except Exception:
        s = t.find("{")
        if s < 0:
            return {}
        depth = 0
        for i in range(s, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[s:i + 1])
                    except Exception:
                        return {}
        return {}


def lowfreq_golden(golden: dict) -> dict:
    kps = [kp for kp in golden.get("key_points", []) if any(_DIGIT.search(str(a)) for a in kp.get("anchors", []))]
    return {**golden, "key_points": kps}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meeting-result", required=True, type=Path)
    ap.add_argument("--golden", required=True, type=Path)
    ap.add_argument("--sizes", default="1,2,3,4,6,8")
    ap.add_argument("--model", default="qwen3:4b")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    chapters = load_chapters(args.meeting_result)
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    golden_lf = lowfreq_golden(golden)
    n = len(chapters)
    args.out.mkdir(parents=True, exist_ok=True)
    session = OllamaSession(OllamaConfig(model=args.model, max_tokens=1200), args.out / "_llm")

    rows = []
    for k in [int(x) for x in args.sizes.split(",")]:
        summaries, in_chars = [], []
        for start in range(0, n, k):
            text = "\n".join(chapters[start:start + k])
            in_chars.append(len(text))
            msgs = [{"role": "system", "content": SYS},
                    {"role": "user", "content": PROMPT.format(text=text) + "\n/no_think"}]
            resp = session.request(msgs, args.out / f"k{k}_c{start}", max_tokens=1200,
                                   request_kind="chunk-exp")
            parsed = loads_tolerant(resp.get("content", ""))
            summaries.append({"key_points": parsed.get("key_points", []), "summary": parsed.get("summary", "")})
        minutes = {"chunks": summaries}
        rec = KR.score(minutes, golden)["recall"]
        rec_lf = KR.score(minutes, golden_lf)["recall"] if golden_lf["key_points"] else None
        row = {"k": k, "chunks": len(summaries),
               "avg_in_chars": round(sum(in_chars) / len(in_chars)),
               "max_in_chars": max(in_chars), "recall": rec, "lowfreq_recall": rec_lf}
        rows.append(row)
        print(f"k={k:>2}  块数={row['chunks']}  单块均字={row['avg_in_chars']:>5} 最长={row['max_in_chars']:>5}  "
              f"召回={rec}  低频={rec_lf}")

    (args.out / "chunk_size.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    L = ["# 分块粒度对照:一次喂几章会崩", "",
         f"- 源:`{args.meeting_result.name}`  {n} 章  模型:{args.model}  金标:{args.golden.name}",
         "- 内容固定,只变每次喂进的章节数 k;无 carryover。k↑=单次输入↑。", "",
         "| k(章/次) | 块数 | 单块均字 | 单块最长字 | 关键点召回 | 低频召回 |",
         "|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['k']} | {r['chunks']} | {r['avg_in_chars']} | {r['max_in_chars']} | {r['recall']} | {r['lowfreq_recall']} |")
    L += ["", "## 读法", "- 召回随 k 增大而下降的拐点 = '喂到几章/多长输入崩'。",
          "- 对照 CLAUDE.md '7K字断崖':看召回明显掉时单块字数是否接近该量级。"]
    (args.out / "RESULTS_chunk_size.md").write_text("\n".join(L), encoding="utf-8")
    print(f"\n→ {args.out / 'RESULTS_chunk_size.md'}")


if __name__ == "__main__":
    main()

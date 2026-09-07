#!/usr/bin/env python3
"""批量摘要对照:一次喂 b 段(带分界标记)产 b 段摘要,到几段质量崩?(复合任务轴)

区别于 chunk_size_experiment(那是把 b 段合成"一段"摘要):
本实验一次喂 b 段、提示词用【第N段】标分界,要求**分别**产出 b 段摘要(顺序对应)。
测"一次让 4B 干 b 件摘要"随 b 增大的退化:
  - 结构完整率:是否真返回 b 段、不合并/不漏
  - 关键点召回:批量是否丢点
  - 段间串味:某段摘要是否混入别段内容

b=1 即单段(基线)。无 carryover(carryover 是另一条轴,见 context_experiment)。

用法(Ollama 在跑):
  python eval/batch_summary_experiment.py --meeting-result <g2.json> --golden eval/golden/R002S05C01.keypoints.json \
    --batches 1,2,3,4 --out eval/reports/batch_g2
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


def load_chapters(mr_path: Path):
    d = json.loads(mr_path.read_text(encoding="utf-8"))
    segs = (d.get("transcript") or {}).get("segments") or []
    idx = {s["segment_id"]: i for i, s in enumerate(segs)}
    out = []
    for ch in (d.get("summary") or {}).get("chapters") or []:
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


def build_prompt(chaps: list[str]) -> str:
    b = len(chaps)
    body = "\n".join(f"【第{i+1}段】\n{c}" for i, c in enumerate(chaps))
    return (
        f"下面是会议连续的 {b} 个段落,已用【第N段】标出分界。\n"
        f"请为【每一段】分别写一段摘要,严格按段落对应,**不要把不同段的内容混在一起**。\n"
        f"- 每段 summary 80~200 字,只概括该段本身的要点。\n"
        f'输出 JSON:{{"summaries":[{{"seg":1,"summary":"..."}}, ...]}},共 {b} 条,顺序对应第1~{b}段。\n\n'
        f"{body}\n/no_think"
    )


def lowfreq(golden: dict) -> dict:
    kps = [k for k in golden.get("key_points", []) if any(_DIGIT.search(str(a)) for a in k.get("anchors", []))]
    return {**golden, "key_points": kps}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meeting-result", required=True, type=Path)
    ap.add_argument("--golden", required=True, type=Path)
    ap.add_argument("--batches", default="1,2,3,4")
    ap.add_argument("--model", default="qwen3:4b")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    chapters = load_chapters(args.meeting_result)
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    glf = lowfreq(golden)
    n = len(chapters)
    args.out.mkdir(parents=True, exist_ok=True)
    session = OllamaSession(OllamaConfig(model=args.model, max_tokens=1600), args.out / "_llm")

    rows = []
    for b in [int(x) for x in args.batches.split(",")]:
        all_sums, groups, struct_ok = [], 0, 0
        for start in range(0, n, b):
            chaps = chapters[start:start + b]
            groups += 1
            resp = session.request(
                [{"role": "system", "content": SYS}, {"role": "user", "content": build_prompt(chaps)}],
                args.out / f"b{b}_g{start}", max_tokens=1600, request_kind="batch-exp")
            parsed = loads_tolerant(resp.get("content", ""))
            sums = parsed.get("summaries") or []
            if len(sums) == len(chaps):        # 结构完整:返回段数==输入段数
                struct_ok += 1
            for s in sums:
                all_sums.append(str(s.get("summary", "")) if isinstance(s, dict) else str(s))
        minutes = {"summaries": all_sums}
        rec = KR.score(minutes, golden)["recall"]
        rec_lf = KR.score(minutes, glf)["recall"] if glf["key_points"] else None
        avg_chars = round(sum(len(s) for s in all_sums) / max(1, len(all_sums)))
        row = {"batch": b, "groups": groups, "returned_summaries": len(all_sums),
               "expected": n, "struct_ok_rate": round(struct_ok / groups, 2),
               "recall": rec, "lowfreq_recall": rec_lf, "avg_chars": avg_chars}
        rows.append(row)
        print(f"b={b}  组数={groups}  返回段数={len(all_sums)}/{n}  结构完整率={row['struct_ok_rate']}  "
              f"召回={rec}  低频={rec_lf}  段均字={avg_chars}")

    (args.out / "batch.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    L = ["# 批量摘要对照:一次喂几段(带分界)产几段摘要", "",
         f"- 源:`{args.meeting_result.name}`  {n} 章  模型:{args.model}", "",
         "| b(段/次) | 组数 | 返回段数 | 结构完整率 | 关键点召回 | 低频召回 | 段均字 |",
         "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['batch']} | {r['groups']} | {r['returned_summaries']}/{r['expected']} | "
                 f"{r['struct_ok_rate']} | {r['recall']} | {r['lowfreq_recall']} | {r['avg_chars']} |")
    L += ["", "## 读法", "- 结构完整率<1 = 4B 开始合并/漏段(复合任务退化的先兆)。",
          "- 召回随 b 增大下降 = 一次干太多件摘要开始丢点。两者拐点即'批量到几段崩'。"]
    (args.out / "RESULTS_batch.md").write_text("\n".join(L), encoding="utf-8")
    print(f"\n→ {args.out / 'RESULTS_batch.md'}")


if __name__ == "__main__":
    main()

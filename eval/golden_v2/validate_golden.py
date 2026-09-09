"""C 阶段:金标结构门校验(确定性)。

检查覆盖/边界/parts 划分/ref 合法/anchor∈refs(归一化)/decisions·action 合规。
结构性错误可回灌生成模型重生成;语义正确性由 D 阶段(verify_golden)另判。

用法:
  python validate_golden.py <golden.json> <path.TextGrid>
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from normalize import norm  # noqa: E402
from build_timeline import parse_textgrid  # noqa: E402


def _all_refs(g: dict) -> list[str]:
    out: list[str] = []
    ov = g.get("overview")
    if isinstance(ov, dict):
        out += ov.get("refs", []) or []
    for key in ("fine_chapters", "core_facts", "decisions", "action_items", "speakers"):
        for it in g.get(key, []) or []:
            out += it.get("refs", []) or []
            for rr in ("start_ref", "end_ref"):
                if it.get(rr):
                    out.append(it[rr])
    return out


def validate(golden: dict, segments: list[dict]) -> dict:
    ids = {s["segment_id"] for s in segments}
    text_by_id = {s["segment_id"]: s["text"] for s in segments}
    speaker_ids = {s["speaker_id"] for s in segments}
    pos = {s["segment_id"]: i for i, s in enumerate(segments)}
    last_speech = segments[-1]["segment_id"] if segments else None
    errs: list[str] = []

    if not isinstance(golden.get("overview"), dict):
        errs.append("overview should be object {text, refs}, got "
                    f"{type(golden.get('overview')).__name__}")

    fc = golden.get("fine_chapters", []) or []
    if not (12 <= len(fc) <= 18):
        errs.append(f"fine_chapters count={len(fc)} (need 12-18)")
    if fc:
        if fc[0].get("start_ref") != "seg-000001":
            errs.append(f"fine[0].start={fc[0].get('start_ref')} != seg-000001")
        if fc[-1].get("end_ref") != last_speech:
            errs.append(f"fine[-1].end={fc[-1].get('end_ref')} != last_speech({last_speech})")
        for i, (a, b) in enumerate(zip(fc, fc[1:])):
            ae, bs = a.get("end_ref"), b.get("start_ref")
            if ae not in pos or bs not in pos:
                errs.append(f"fine[{i}] boundary ref not found")
                continue
            if pos[bs] != pos[ae] + 1:
                errs.append(f"fine[{i}]->[{i+1}] gap/overlap ({ae}->{bs})")

    part_fids = [fid for p in golden.get("parts", []) or [] for fid in p.get("fine_ids", [])]
    if sorted(part_fids) != sorted(f.get("id") for f in fc):
        errs.append("parts is not a partition of fine_chapters")

    for r in _all_refs(golden):
        if r not in ids:
            errs.append(f"bad ref {r}")

    cfs = golden.get("core_facts", []) or []
    if not (8 <= len(cfs) <= 14):
        errs.append(f"core_facts count={len(cfs)} (need 8-14)")
    for cf in cfs:
        anch = cf.get("anchors", []) or []
        if not (2 <= len(anch) <= 5):
            errs.append(f"{cf.get('id')} anchors={len(anch)} (need 2-5)")
        reft = norm("".join(text_by_id.get(r, "") for r in cf.get("refs", []) or []))
        for a in anch:
            if norm(a) not in reft:
                errs.append(f"{cf.get('id')} anchor {a!r} not in its refs text")

    for d in golden.get("decisions", []) or []:
        if d.get("status") not in ("decision", "proposal"):
            errs.append(f"{d.get('id')} bad status {d.get('status')!r}")
        if d.get("owner") and d["owner"] not in speaker_ids:
            errs.append(f"{d.get('id')} bad owner {d['owner']!r}")

    for ai in golden.get("action_items", []) or []:
        if ai.get("owner") and ai["owner"] not in speaker_ids:
            errs.append(f"{ai.get('id')} bad owner {ai.get('owner')!r}")
        dl = ai.get("deadline")
        if dl is not None and not isinstance(dl, str):
            errs.append(f"{ai.get('id')} bad deadline type")

    return {"ok": not errs, "error_count": len(errs), "errors": errs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("golden", type=pathlib.Path)
    ap.add_argument("textgrid", type=pathlib.Path)
    args = ap.parse_args()
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    segs = parse_textgrid(args.textgrid)
    result = validate(golden, segs)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

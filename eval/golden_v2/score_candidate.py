"""候选纪要 → 金标符合度:core_facts 锚词半命中召回(+低频数字子集)。

候选可以是任意纪要文本(md/txt/json 拍平)。判定与 keypoint_recall 一致:
一条 fact 的 anchors 命中 >= ceil(len/2) 记该 fact 被覆盖。
低频子集 = anchors 里含数字的 fact(数字/低频信息更难被竞品抓到)。

用法:
  python score_candidate.py <golden.json> <candidate.(md|txt|json)>
"""
from __future__ import annotations
import argparse, json, math, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from normalize import norm  # noqa: E402

_DIGIT = re.compile(r"\d")


def load_candidate_text(path: pathlib.Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".json":
        try:
            return norm(json.dumps(json.loads(raw), ensure_ascii=False))
        except Exception:
            pass
    return norm(raw)


def score(golden: dict, cand_text: str) -> dict:
    facts = golden.get("core_facts", [])
    hit, missed, lf_total, lf_hit = 0, [], 0, 0
    detail = []
    for f in facts:
        anchors = [norm(a) for a in f.get("anchors", []) if str(a).strip()]
        if not anchors:
            continue
        n = sum(1 for a in anchors if a in cand_text)
        need = math.ceil(len(anchors) / 2)
        ok = n >= need
        is_lf = any(_DIGIT.search(norm(a)) for a in f.get("anchors", []))
        if is_lf:
            lf_total += 1
            lf_hit += 1 if ok else 0
        if ok:
            hit += 1
        else:
            missed.append({"id": f.get("id"), "text": f.get("text"), "anchors": f.get("anchors"), "n_hit": n, "need": need})
        detail.append({"id": f.get("id"), "hit": ok, "n_hit": n, "of": len(anchors), "low_freq": is_lf})
    total = hit + len(missed)
    return {
        "meeting": golden.get("meeting"),
        "core_fact_recall": round(hit / total, 3) if total else None,
        "recalled": hit, "total": total,
        "lowfreq_recall": round(lf_hit / lf_total, 3) if lf_total else None,
        "lowfreq": f"{lf_hit}/{lf_total}",
        "missed": missed,
        "detail": detail,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("golden", type=pathlib.Path)
    ap.add_argument("candidate", type=pathlib.Path)
    args = ap.parse_args()
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    text = load_candidate_text(args.candidate)
    r = score(golden, text)
    print(json.dumps({k: v for k, v in r.items() if k != "detail"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

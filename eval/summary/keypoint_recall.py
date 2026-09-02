"""摘要关键点召回评测。

衡量"生成的纪要覆盖了多少必须出现的关键信息"——纪要系统最核心的质量维度。

金标准：人工为每场会标一份"关键点清单"（key_points.json），每个关键点给几个
判定用的锚词（人名/数字/术语），出现即算命中。数字做中文↔阿拉伯归一（三百=300）。

用法：
  python keypoint_recall.py --minutes 生成的纪要.json --golden 关键点金标准.json

金标准格式（eval/golden/<meeting>.keypoints.json）：
{
  "meeting": "R002S05C01",
  "key_points": [
    {"id": "kp1", "desc": "餐饮四层把关保障食材安全", "anchors": ["四层", "把关", "食材"]},
    {"id": "kp2", "desc": "上半年净利润70万",           "anchors": ["净利润", "70万"]},
    ...
  ]
}
判定：一个关键点的 anchors 中命中 >= ceil(len/2) 个，算该点被覆盖（召回）。
"""

from __future__ import annotations

import argparse
import json
import math
import re

_NUM = {"零": "0", "幺": "1", "一": "1", "二": "2", "三": "3", "四": "4",
        "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}


def normalize(text: str) -> str:
    text = re.sub(r"\s", "", text)
    text = "".join(_NUM.get(c, c) for c in text)
    return text


def minutes_to_text(minutes: dict) -> str:
    """把纪要 JSON 拍平成一段文本（覆盖所有模块，供锚词检索）。"""
    return normalize(json.dumps(minutes, ensure_ascii=False))


def score(minutes: dict, golden: dict) -> dict:
    body = minutes_to_text(minutes)
    hit, missed = [], []
    for kp in golden.get("key_points", []):
        anchors = [normalize(a) for a in kp.get("anchors", []) if a.strip()]
        if not anchors:
            continue
        n_hit = sum(1 for a in anchors if a in body)
        need = math.ceil(len(anchors) / 2)
        (hit if n_hit >= need else missed).append(kp.get("id") or kp.get("desc", ""))
    total = len(hit) + len(missed)
    recall = len(hit) / total if total else 0.0
    return {
        "meeting": golden.get("meeting", ""),
        "total_keypoints": total,
        "recalled": len(hit),
        "recall": round(recall, 3),
        "missed_ids": missed,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="摘要关键点召回评测")
    ap.add_argument("--minutes", required=True, help="生成的纪要 JSON")
    ap.add_argument("--golden", required=True, help="关键点金标准 JSON")
    args = ap.parse_args()
    minutes = json.load(open(args.minutes, encoding="utf-8"))
    golden = json.load(open(args.golden, encoding="utf-8"))
    result = score(minutes, golden)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""确定性话题分割（A 层）。

把 transcript 切成"候选章节块"，不依赖 LLM。信号全部是 CPU 可算、确定可复现的：
speaker 切换、VAD 长静音 gap、字符 bigram 词汇内聚度下降。刻意偏向"过切"——
本层只保证边界不漏，语义合并交给后续 B 层的相邻块 yes/no 判定。

设计动机见 docs/architecture/纪要生成-现状评估与策略重构.md 第三节 A 层：
不再让 4B int4 徒手输出 core_start_ref/core_end_ref，把边界决策收回到确定性代码。
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..llm.chunking import BudgetPolicy, estimate_text_tokens


SEGMENTATION_VERSION = "topic-segmentation.v1"


@dataclass(frozen=True)
class SegmentationConfig:
    """A 层阈值。默认值偏保守，宁可过切也不漏切。"""

    vad_gap_ms: int = 1500
    cohesion_window_segments: int = 3
    cohesion_threshold: float = 0.20
    cohesion_min_chars: int = 12
    gap_weight: float = 1.0
    speaker_weight: float = 0.5
    cohesion_weight: float = 0.6
    boundary_score_threshold: float = 1.0
    # 块尺寸下限：过短的块并入相邻，避免碎块浪费 B 层调用与提示词开销。
    min_block_chars: int = 400
    # 软目标：块攒过这个 token 数就在最弱内聚点切开，即使没有强语义边界，
    # 让长而平滑（单人/单主题）的内容也落进 4B 的舒适区，而不是一路撑到硬上限。
    target_block_tokens: int = 1800
    # 单块原文的 token 硬上限（兜底）；None 表示由预算推导（留出 B 层提示词开销）。
    max_block_tokens: int | None = None
    block_overhead_tokens: int = 512


def _char_bigrams(text: str) -> Counter:
    stripped = "".join(text.split())
    if len(stripped) < 2:
        return Counter([stripped]) if stripped else Counter()
    return Counter(stripped[i : i + 2] for i in range(len(stripped) - 1))


def _cosine(left: Counter, right: Counter) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    dot = sum(left[key] * right[key] for key in common)
    if dot == 0:
        return 0.0
    norm_left = math.sqrt(sum(value * value for value in left.values()))
    norm_right = math.sqrt(sum(value * value for value in right.values()))
    return dot / (norm_left * norm_right)


def _window_text(segments: list[dict[str, Any]], start: int, end: int) -> str:
    return "".join(str(segments[i].get("text") or "") for i in range(start, end))


def _boundary_signals(
    segments: list[dict[str, Any]],
    index: int,
    config: SegmentationConfig,
) -> tuple[float, list[str]]:
    """返回位置 index（在其之前断开）的边界得分与命中的信号名。"""
    prev = segments[index - 1]
    cur = segments[index]
    reasons: list[str] = []
    score = 0.0

    gap_ms = int(cur["start_ms"]) - int(prev["end_ms"])
    if gap_ms >= config.vad_gap_ms:
        score += config.gap_weight
        reasons.append("gap")

    prev_speaker = str(prev.get("speaker_id") or "unknown")
    cur_speaker = str(cur.get("speaker_id") or "unknown")
    speaker_changed = (
        prev_speaker != cur_speaker
        and prev_speaker != "unknown"
        and cur_speaker != "unknown"
    )
    if speaker_changed:
        score += config.speaker_weight
        reasons.append("speaker")

    window = config.cohesion_window_segments
    before = _window_text(segments, max(0, index - window), index)
    after = _window_text(segments, index, min(len(segments), index + window))
    if len(before) >= config.cohesion_min_chars and len(after) >= config.cohesion_min_chars:
        similarity = _cosine(_char_bigrams(before), _char_bigrams(after))
        if similarity < config.cohesion_threshold:
            score += config.cohesion_weight
            reasons.append("cohesion")
    return score, reasons


def _make_block(
    block_number: int,
    seg_slice: list[dict[str, Any]],
    opened_by: list[str],
) -> dict[str, Any]:
    speaker_ids = sorted(
        {str(item.get("speaker_id") or "unknown") for item in seg_slice}
    )
    return {
        "block_id": f"blk-{block_number:06d}",
        "segment_ids": [str(item["segment_id"]) for item in seg_slice],
        "start_ms": int(seg_slice[0]["start_ms"]),
        "end_ms": int(seg_slice[-1]["end_ms"]),
        "speaker_ids": speaker_ids,
        "text_chars": sum(len(str(item.get("text") or "")) for item in seg_slice),
        "segment_count": len(seg_slice),
        "opened_by": opened_by or ["start"],
    }


def _block_text_tokens(seg_slice: list[dict[str, Any]], policy: BudgetPolicy) -> int:
    text = "".join(str(item.get("text") or "") for item in seg_slice)
    return estimate_text_tokens(text, policy)


def _split_over_cap(
    seg_slice: list[dict[str, Any]],
    opened_by: list[str],
    policy: BudgetPolicy,
    config: SegmentationConfig,
    cap_tokens: int,
    reason: str,
) -> list[tuple[list[dict[str, Any]], list[str]]]:
    """超过 cap_tokens 的块按最弱内聚点递归切开；实在切不动时按中点硬切。

    同一函数服务软目标（target_block_tokens）与硬上限（max_block_tokens）——
    段尺寸驱动的切分，右半块用 reason 标注来源（size_split）。
    """
    if len(seg_slice) <= 1 or _block_text_tokens(seg_slice, policy) <= cap_tokens:
        return [(seg_slice, opened_by)]
    best_pos = None
    best_similarity = None
    for i in range(1, len(seg_slice)):
        window = config.cohesion_window_segments
        before = _window_text(seg_slice, max(0, i - window), i)
        after = _window_text(seg_slice, i, min(len(seg_slice), i + window))
        similarity = _cosine(_char_bigrams(before), _char_bigrams(after))
        if best_similarity is None or similarity < best_similarity:
            best_similarity = similarity
            best_pos = i
    split_at = best_pos if best_pos is not None else len(seg_slice) // 2
    left = seg_slice[:split_at]
    right = seg_slice[split_at:]
    return [
        *_split_over_cap(left, opened_by, policy, config, cap_tokens, reason),
        *_split_over_cap(right, [reason], policy, config, cap_tokens, reason),
    ]


def segment_blocks(
    segments: list[dict[str, Any]],
    policy: BudgetPolicy,
    config: SegmentationConfig | None = None,
) -> dict[str, Any]:
    """把非空 transcript 段切成候选章节块（确定性）。

    返回 {version, blocks, coverage_complete, boundary_reason_counts, ...}，
    其中每个 block 覆盖一段连续 segment，作为 B 层逐块摘要的输入单元。
    """
    config = config or SegmentationConfig()
    nonempty = [item for item in segments if str(item.get("text") or "").strip()]
    max_tokens = (
        config.max_block_tokens
        if config.max_block_tokens is not None
        else max(1, policy.input_token_budget - config.block_overhead_tokens)
    )
    if not nonempty:
        return {
            "version": SEGMENTATION_VERSION,
            "blocks": [],
            "nonempty_segment_count": 0,
            "coverage_complete": True,
            "boundary_reason_counts": {},
            "max_block_tokens": max_tokens,
        }

    # 1. 逐相邻对打分，得到原始边界位置及其命中信号。
    boundary_reasons: dict[int, list[str]] = {}
    for index in range(1, len(nonempty)):
        score, reasons = _boundary_signals(nonempty, index, config)
        if score >= config.boundary_score_threshold:
            boundary_reasons[index] = reasons

    # 2. 按边界切块。
    raw_blocks: list[tuple[list[dict[str, Any]], list[str]]] = []
    start = 0
    opened_by = ["start"]
    for index in range(1, len(nonempty)):
        if index in boundary_reasons:
            raw_blocks.append((nonempty[start:index], opened_by))
            start = index
            opened_by = boundary_reasons[index]
    raw_blocks.append((nonempty[start:], opened_by))

    # 3. 合并过短块（< min_block_chars）到相邻块，避免碎块浪费 B 层调用。
    merged: list[tuple[list[dict[str, Any]], list[str]]] = []
    for seg_slice, reasons in raw_blocks:
        chars = sum(len(str(item.get("text") or "")) for item in seg_slice)
        if merged and chars < config.min_block_chars:
            prev_slice, prev_reasons = merged[-1]
            merged[-1] = (prev_slice + seg_slice, prev_reasons)
        else:
            merged.append((seg_slice, list(reasons)))
    # 首块若过短且后面还有块，向后并入。
    if len(merged) >= 2:
        first_slice, first_reasons = merged[0]
        first_chars = sum(len(str(item.get("text") or "")) for item in first_slice)
        if first_chars < config.min_block_chars:
            second_slice, _ = merged[1]
            merged[1] = (first_slice + second_slice, first_reasons)
            merged.pop(0)

    # 4. 尺寸切分：软目标优先（min 到 target），硬上限兜底；长而平滑的块被切到舒适区。
    size_cap = min(max_tokens, config.target_block_tokens)
    budgeted: list[tuple[list[dict[str, Any]], list[str]]] = []
    for seg_slice, reasons in merged:
        budgeted.extend(
            _split_over_cap(seg_slice, reasons, policy, config, size_cap, "size_split")
        )

    blocks = [
        _make_block(number, seg_slice, reasons)
        for number, (seg_slice, reasons) in enumerate(budgeted, 1)
    ]

    covered = [seg_id for block in blocks for seg_id in block["segment_ids"]]
    expected = [str(item["segment_id"]) for item in nonempty]
    reason_counts: Counter = Counter()
    for block in blocks:
        for reason in block["opened_by"]:
            reason_counts[reason] += 1

    return {
        "version": SEGMENTATION_VERSION,
        "blocks": blocks,
        "nonempty_segment_count": len(nonempty),
        "block_count": len(blocks),
        "coverage_complete": covered == expected,
        "boundary_reason_counts": dict(reason_counts),
        "max_block_tokens": max_tokens,
        "config": {
            "vad_gap_ms": config.vad_gap_ms,
            "cohesion_window_segments": config.cohesion_window_segments,
            "cohesion_threshold": config.cohesion_threshold,
            "boundary_score_threshold": config.boundary_score_threshold,
            "min_block_chars": config.min_block_chars,
        },
    }

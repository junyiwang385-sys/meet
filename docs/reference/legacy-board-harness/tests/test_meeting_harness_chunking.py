import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meeting_harness.chunking import BudgetPolicy, ChunkingError, build_chunk_plan
from meeting_harness.transcript import render_timeline


def make_segments(count=6, text_size=40):
    return [
        {
            "segment_id": f"seg-{index:06d}",
            "index": index,
            "start_ms": index * 1000,
            "end_ms": index * 1000 + 900,
            "speaker_id": f"speaker_{index % 2}",
            "text": "会" * text_size,
            "status": "ok",
        }
        for index in range(1, count + 1)
    ]


def builder(segments, chunk_id):
    return [{"role": "user", "content": chunk_id + "\n" + render_timeline(segments)}]


def test_chunk_plan_covers_every_segment_once_as_main():
    segments = make_segments()
    policy = BudgetPolicy(
        ctx=320,
        output_tokens=80,
        safety_tokens=20,
        chars_per_token=1.0,
        fixed_overhead_tokens=0,
        overlap_segments=1,
    )
    plan = build_chunk_plan(segments, policy, builder)
    assert plan["coverage_complete"] is True
    assert plan["covered_segment_ids"] == [item["segment_id"] for item in segments]
    assert len(plan["chunks"]) > 1
    for left, right in zip(plan["chunks"], plan["chunks"][1:]):
        assert right["context_segment_ids"] in (
            [],
            left["main_segment_ids"][-1:],
        )
        assert right["estimated_prompt_tokens"] <= right["input_token_budget"]


def test_chunk_plan_is_deterministic():
    segments = make_segments()
    policy = BudgetPolicy(ctx=320, output_tokens=80, safety_tokens=20, fixed_overhead_tokens=0)
    assert build_chunk_plan(segments, policy, builder) == build_chunk_plan(
        segments, policy, builder
    )


def test_oversized_single_segment_fails():
    segments = make_segments(count=1, text_size=1000)
    policy = BudgetPolicy(ctx=200, output_tokens=80, safety_tokens=20, fixed_overhead_tokens=0)
    with pytest.raises(ChunkingError, match="segment_exceeds_chunk_budget"):
        build_chunk_plan(segments, policy, builder)


def test_empty_segments_do_not_require_chunks():
    segments = make_segments(count=2)
    for segment in segments:
        segment["text"] = ""
    plan = build_chunk_plan(segments, BudgetPolicy(200, 80, 20), builder)
    assert plan["chunks"] == []
    assert plan["coverage_complete"] is True

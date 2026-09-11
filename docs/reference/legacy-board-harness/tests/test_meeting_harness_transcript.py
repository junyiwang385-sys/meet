import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meeting_harness.transcript import canonicalize_rows, render_timeline


def sample_rows():
    return [
        {
            "index": 12,
            "start": 1.2344,
            "end": 2.3456,
            "speaker": "A",
            "status": "ok",
            "text": "  第一段\n内容  ",
            "job_id": "seg_0012_A_1.234_2.346",
            "audio_name": "seg_0012_A_1.234_2.346.wav",
        },
        {
            "index": 3,
            "start": 0.0,
            "end": 1.0,
            "speaker": "unknown",
            "status": "transcript_empty",
            "text": "",
            "job_id": "seg_0003_unknown_0.000_1.000",
        },
    ]


def test_canonical_segments_use_stable_ids_and_sort_by_time():
    segments, stats = canonicalize_rows(sample_rows())

    assert [item["segment_id"] for item in segments] == ["seg-000003", "seg-000012"]
    assert segments[1]["speaker_id"] == "speaker_A"
    assert segments[1]["start_ms"] == 1234
    assert segments[1]["end_ms"] == 2346
    assert segments[1]["text"] == "第一段 内容"
    assert stats["segment_count"] == 2
    assert stats["empty_segment_count"] == 1


def test_timeline_omits_empty_segments_but_uses_segment_ids():
    segments, _ = canonicalize_rows(sample_rows())
    timeline = render_timeline(segments)

    assert "seg-000003" not in timeline
    assert "[seg-000012][0m01s-0m02s][speaker_A] 第一段 内容" in timeline


def test_duplicate_index_is_rejected():
    rows = sample_rows()
    rows[1]["index"] = 12

    try:
        canonicalize_rows(rows)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate index should fail")

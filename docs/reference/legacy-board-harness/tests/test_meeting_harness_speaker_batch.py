import json

from meeting_harness.product_summary import (
    _build_compact_ref_map,
    _build_compact_speaker_map,
    _validate_speaker_batch,
)


def _segment(index: int, speaker_id: str) -> dict[str, object]:
    return {
        "segment_id": f"seg-{index:06d}",
        "speaker_id": speaker_id,
        "text": f"发言 {index}",
        "index": index,
    }


def test_speaker_batch_uses_the_same_global_aliases_as_the_prompt() -> None:
    segments = [
        _segment(1, "speaker_4"),
        _segment(2, "unknown"),
        _segment(3, "speaker_2"),
        _segment(4, "speaker_1"),
        _segment(5, "speaker_0"),
        _segment(6, "speaker_3"),
    ]
    documents = [
        {"speaker_id": "speaker_2", "segments": [segments[2]]},
        {"speaker_id": "speaker_1", "segments": [segments[3]]},
        {"speaker_id": "speaker_4", "segments": [segments[0]]},
        {"speaker_id": "unknown", "segments": [segments[1]]},
    ]
    _, compact_ref_map = _build_compact_ref_map(segments)
    _, compact_speaker_map = _build_compact_speaker_map(
        [segment["speaker_id"] for segment in segments]
    )
    local_speaker_map, _ = _build_compact_speaker_map(
        [document["speaker_id"] for document in documents]
    )
    assert len(set(local_speaker_map.values())) == len(local_speaker_map)

    content = json.dumps(
        {
            "speakers": [
                {"speaker_id": "sp3", "overview": "概括二", "refs": ["r3"]},
                {"speaker_id": "sp1", "overview": "概括一", "refs": ["r4"]},
                {"speaker_id": "sp4", "overview": "概括四", "refs": ["r1"]},
                {"speaker_id": "sp2", "overview": "概括未知", "refs": ["r2"]},
            ]
        },
        ensure_ascii=False,
    )

    result = _validate_speaker_batch(
        content,
        "stop",
        False,
        documents,
        compact_ref_map=compact_ref_map,
        compact_speaker_map=compact_speaker_map,
    )

    assert result == [
        {
            "speaker_id": "speaker_2",
            "overview": "概括二",
            "refs": ["seg-000003"],
        },
        {
            "speaker_id": "speaker_1",
            "overview": "概括一",
            "refs": ["seg-000004"],
        },
        {
            "speaker_id": "speaker_4",
            "overview": "概括四",
            "refs": ["seg-000001"],
        },
        {
            "speaker_id": "unknown",
            "overview": "概括未知",
            "refs": ["seg-000002"],
        },
    ]

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meeting_harness.validation import (
    SummaryValidationError,
    validate_llm_result,
    validate_summary_object,
)


SEGMENTS = [
    {
        "segment_id": "seg-000001",
        "index": 1,
        "start_ms": 1000,
        "end_ms": 4000,
        "speaker_id": "speaker_A",
        "text": "张三负责整理文档，截止时间是周五。",
        "status": "ok",
    },
    {
        "segment_id": "seg-000002",
        "index": 2,
        "start_ms": 5000,
        "end_ms": 9000,
        "speaker_id": "speaker_B",
        "text": "我们决定采用方案一。",
        "status": "ok",
    },
]


def valid_payload():
    return {
        "title": "项目评审会",
        "overview": {"text": "会议讨论任务和方案。", "refs": ["seg-000001", "seg-000002"]},
        "chapters": [
            {"title": "方案讨论", "overview": "讨论并确定方案。", "refs": ["seg-000002"]}
        ],
        "speakers": [
            {"speaker_id": "speaker_A", "overview": "负责后续文档。", "refs": ["seg-000001"]}
        ],
        "key_points": [{"text": "采用方案一。", "refs": ["seg-000002"]}],
        "decisions": [{"text": "采用方案一。", "refs": ["seg-000002"]}],
        "action_items": [
            {
                "task": "整理文档",
                "owner": "speaker_A",
                "deadline": "周五",
                "refs": ["seg-000001"],
            }
        ],
        "open_questions": [],
        "risks": [],
        "keywords": [{"keyword": "方案一", "refs": ["seg-000002"]}],
    }


def test_parse_content_accepts_literal_control_character_in_string():
    from meeting_harness.validation import parse_content

    value = parse_content('{"text": "第一行\n第二行"}')
    assert value["text"] == "第一行\n第二行"


def test_parse_content_preserves_escaped_controls():
    from meeting_harness.validation import parse_content

    value = parse_content('{"text": "第一行\\n第二行\\t完成"}')
    assert value["text"] == "第一行\n第二行\t完成"


def test_valid_summary_backfills_chapter_time_and_speakers():
    summary, quality = validate_llm_result(
        json.dumps(valid_payload(), ensure_ascii=False),
        "stop",
        SEGMENTS,
        context_truncated=False,
    )

    chapter = summary["chapters"][0]
    assert chapter["start_ms"] == 5000
    assert chapter["end_ms"] == 9000
    assert chapter["speaker_ids"] == ["speaker_B"]
    assert summary["action_items"][0]["owner"] == "speaker_A"
    assert summary["action_items"][0]["deadline"] == "周五"
    assert quality["status"] == "pass"


def test_invalid_refs_and_cross_speaker_refs_are_removed():
    payload = valid_payload()
    payload["key_points"] = [{"text": "未知内容", "refs": ["seg-missing"]}]
    payload["speakers"][0]["refs"].append("seg-000002")

    summary, quality = validate_llm_result(
        json.dumps(payload, ensure_ascii=False),
        "stop",
        SEGMENTS,
        context_truncated=False,
    )

    assert summary["key_points"] == []
    assert summary["speakers"][0]["refs"] == ["seg-000001"]
    assert quality["counts"]["invalid_refs"] == 1


def test_unsupported_owner_deadline_and_placeholders_are_cleared():
    payload = valid_payload()
    payload["action_items"][0]["owner"] = "speaker_B"
    payload["action_items"][0]["deadline"] = "下周一"
    payload["risks"] = [{"text": "风险、限制或依赖项", "refs": ["seg-000001"]}]

    summary, _ = validate_llm_result(
        json.dumps(payload, ensure_ascii=False),
        "stop",
        SEGMENTS,
        context_truncated=False,
    )

    assert summary["action_items"][0]["owner"] is None
    assert summary["action_items"][0]["deadline"] is None
    assert summary["risks"] == []


def test_empty_transcript_refs_are_not_accepted_as_evidence():
    segments = SEGMENTS + [
        {
            "segment_id": "seg-000003",
            "index": 3,
            "start_ms": 10000,
            "end_ms": 11000,
            "speaker_id": "unknown",
            "text": "",
            "status": "transcript_empty",
        }
    ]
    payload = valid_payload()
    payload["risks"] = [{"text": "虚构风险", "refs": ["seg-000003"]}]

    summary, quality = validate_llm_result(
        json.dumps(payload, ensure_ascii=False),
        "stop",
        segments,
        context_truncated=False,
    )

    assert summary["risks"] == []
    assert any(item["type"] == "drop_empty_text_ref" for item in quality["repairs"])


def test_validate_summary_object_normalizes_already_parsed_merge_result():
    summary, quality = validate_summary_object(valid_payload(), SEGMENTS)
    assert summary["chapters"][0]["start_ms"] == 5000
    assert quality["status"] == "pass"


def test_length_finish_reason_is_rejected():
    try:
        validate_llm_result(
            json.dumps(valid_payload(), ensure_ascii=False),
            "length",
            SEGMENTS,
            context_truncated=False,
        )
    except SummaryValidationError as exc:
        assert "finish_reason" in str(exc)
    else:
        raise AssertionError("length finish reason should fail")

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meeting_harness.compat_export import build_compat_bundle, validate_compat_bundle


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

SUMMARY = {
    "title": "项目评审会",
    "overview": {"text": "会议讨论任务和方案。", "refs": ["seg-000001", "seg-000002"]},
    "chapters": [
        {
            "title": "方案讨论",
            "overview": "讨论并确定方案。",
            "speaker_ids": ["speaker_B"],
            "start_ms": 5000,
            "end_ms": 9000,
            "refs": ["seg-000002"],
        }
    ],
    "speakers": [
        {"speaker_id": "speaker_A", "overview": "负责后续文档。", "refs": ["seg-000001"]}
    ],
    "speaker_key_points": [
        {"speaker_id": "speaker_B", "text": "采用方案一。", "refs": ["seg-000002"]}
    ],
    "key_points": [],
    "decisions": [{"text": "采用方案一。", "refs": ["seg-000002"]}],
    "action_items": [
        {"task": "整理文档", "owner": "speaker_A", "deadline": "周五", "refs": ["seg-000001"]}
    ],
    "open_questions": [],
    "risks": [],
    "keywords": [{"keyword": "方案一", "refs": ["seg-000002"]}],
}


def test_compat_bundle_maps_transcript_chapters_and_summary():
    bundle = build_compat_bundle(
        "mtg_test",
        {"duration_ms": 9000, "source_audio": "/audio.wav"},
        SEGMENTS,
        SUMMARY,
    )
    validate_compat_bundle(bundle)
    paragraph = bundle["transcription.json"]["Transcription"]["Paragraphs"][0]
    assert paragraph["ParagraphId"] == "seg-000001"
    assert paragraph["Words"][0]["SentenceId"] == 1
    chapter = bundle["auto_chapters.json"]["AutoChapters"][0]
    assert chapter == {
        "Id": 1,
        "Start": 5000,
        "End": 9000,
        "Headline": "方案讨论",
        "Summary": "讨论并确定方案。",
    }
    summarization = bundle["summarization.json"]["Summarization"]
    assert summarization["ParagraphSummary"] == "会议讨论任务和方案。"
    assert summarization["ConversationalSummary"][0]["SpeakerName"] == "speaker_A"


def test_compat_assistance_uses_evidence_times():
    bundle = build_compat_bundle("mtg_test", {}, SEGMENTS, SUMMARY)
    assistance = bundle["meeting_assistance.json"]["MeetingAssistance"]
    assert assistance["Keywords"] == ["方案一"]
    assert assistance["KeySentences"][0]["Start"] == 5000
    assert assistance["Actions"][0]["SentenceId"] == 1
    assert set(assistance["Actions"][0]) == {"Id", "SentenceId", "Start", "End", "Text"}

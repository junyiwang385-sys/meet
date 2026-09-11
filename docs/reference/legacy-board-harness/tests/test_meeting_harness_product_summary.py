import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meeting_harness.artifacts import atomic_write_json, atomic_write_text
from meeting_harness.display import build_frontend_result, render_meeting_display
from meeting_harness.llm import LlmConfig
from meeting_harness.product_summary import ProductSummaryConfig, run_product_summary_stage
from meeting_harness.transcript import render_timeline


def segments(count=6, size=100):
    return [
        {
            "segment_id": f"seg-{index:06d}",
            "index": index,
            "start_ms": (index - 1) * 60000,
            "end_ms": index * 60000,
            "speaker_id": f"speaker_{index % 2}",
            "text": f"第{index}段" + "内容" * size,
            "status": "ok",
        }
        for index in range(1, count + 1)
    ]


def llm_config(ctx=16000, max_tokens=3000):
    return LlmConfig(
        board_scripts_dir=pathlib.Path("."),
        model_dir=pathlib.Path("."),
        server=pathlib.Path("rkllm3-server"),
        host="127.0.0.1",
        port=18245,
        ctx=ctx,
        predict=max_tokens,
        max_tokens=max_tokens,
        temperature=0.0,
        server_temp=0.0,
        server_top_k=1,
        server_top_p=1.0,
        server_repeat_penalty=1.05,
        ready_timeout=10,
        request_timeout=10,
    )


class FullSession:
    starts = 0
    requests = 0

    def __init__(self, config, out_dir, sampler):
        self.config = config
        self.out_dir = out_dir
        self.ready_seconds = 0.01
        self.files = {"model": "fake.rknn"}
        self.request_count = 0

    def start(self):
        type(self).starts += 1

    def close(self):
        return None

    def request(self, messages, request_dir, **kwargs):
        type(self).requests += 1
        self.request_count += 1
        payload = {
            "title": "家长会",
            "overview": {"text": "会议讨论学习和家庭教育。", "refs": ["seg-000001"]},
            "chapters": [
                {
                    "title": "学习情况",
                    "overview": "讨论学生学习表现。",
                    "core_start_ref": "seg-000002",
                    "core_end_ref": "seg-000003",
                    "refs": ["seg-000002", "seg-000003"],
                },
                {
                    "title": "家庭教育",
                    "overview": "讨论家庭教育方式。",
                    "core_start_ref": "seg-000004",
                    "core_end_ref": "seg-000005",
                    "refs": ["seg-000004", "seg-000005"],
                },
            ],
            "speakers": [
                {"speaker_id": "speaker_1", "overview": "介绍学习情况。", "refs": ["seg-000001"]}
            ],
            "action_items": [
                {"task": "检查作业", "owner": "speaker_1", "deadline": None, "refs": ["seg-000001"]}
            ],
        }
        return response(request_dir, kwargs["request_id"], payload)


class SlidingSession:
    starts = 0
    requests = 0

    def __init__(self, config, out_dir, sampler):
        self.config = config
        self.out_dir = out_dir
        self.ready_seconds = 0.01
        self.files = {"model": "fake.rknn"}
        self.request_count = 0

    def start(self):
        type(self).starts += 1

    def close(self):
        return None

    def request(self, messages, request_dir, **kwargs):
        type(self).requests += 1
        self.request_count += 1
        request_id = kwargs["request_id"]
        text = "\n".join(message["content"] for message in messages)
        timeline_refs = re.findall(r"(?m)^\[(r\d+)\]", text)
        if timeline_refs:
            refs = list(dict.fromkeys(timeline_refs))
        else:
            refs = list(dict.fromkeys(re.findall(r'"(r\d+)"', text)))
        if request_id.startswith("window-"):
            assert refs
            is_final = bool(timeline_refs) and timeline_refs[-1] == "r8"
            split = len(refs) if is_final else max(1, len(refs) - 1)
            start_ref = refs[0]
            end_ref = refs[split - 1]
            carryover = refs[split] if split < len(refs) else None
            payload = {
                "completed_chapters": [
                    {
                        "title": f"章节 {start_ref}",
                        "summary": "当前窗口的完整章节摘要。",
                        "core_start_ref": start_ref,
                        "core_end_ref": end_ref,
                        "key_refs": [start_ref],
                    }
                ],
                "action_candidates": (
                    [{"task": "完成后续检查", "owner": None, "deadline": None, "refs": [start_ref]}]
                    if start_ref == "r1"
                    else []
                ),
                "carryover_start_ref": carryover,
            }
        elif request_id.startswith("speaker-batch-"):
            batch_speaker_ids = re.findall(r"(?m)^===== (sp\d+) =====$", text)
            payload = {
                "speakers": [
                    {
                        "speaker_id": speaker_id,
                        "overview": f"{speaker_id} 的会议发言总结。",
                        "refs": re.findall(
                            rf"(?m)^\[(r\d+)\]\[[^\]]+\]\[{re.escape(speaker_id)}\]",
                            text,
                        ),
                    }
                    for speaker_id in batch_speaker_ids
                ]
            }
        elif request_id == "full-summary":
            payload = {
                "title": "长会议",
                "overview": {"text": "这是根据全部章节生成的全文摘要。", "refs": [refs[0]]},
            }
        elif request_id == "action-review":
            payload = {
                "action_items": [
                    {"task": "完成后续检查", "owner": None, "deadline": None, "refs": [refs[0]]}
                ]
            }
        else:
            raise AssertionError(request_id)
        return response(request_dir, request_id, payload)


def response(request_dir, request_id, payload):
    content = json.dumps(payload, ensure_ascii=False)
    request_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(request_dir / "final_json.txt", content)
    atomic_write_json(
        request_dir / "status.json",
        {"request_id": request_id, "finish_reason": "stop", "context_truncated": False},
    )
    return {
        "request_id": request_id,
        "content": content,
        "thinking": "模拟思考",
        "finish_reason": "stop",
        "context_truncated": False,
        "usage": {},
        "timings": {},
    }


def test_forced_sliding_path_outputs_all_product_features(monkeypatch, tmp_path):
    import meeting_harness.product_summary as module

    monkeypatch.setattr(module, "RkllmServerSession", SlidingSession)
    source = segments()
    result = run_product_summary_stage(
        config=ProductSummaryConfig(llm_config(20000, 3000), 500, 2.0, 0, False),
        segments=source,
        speaker_ids=["speaker_0", "speaker_1"],
        timeline=render_timeline(source),
        out_dir=tmp_path / "llm",
        sampler=None,
    )
    assert result["policy"] == "sliding_chapter_windows"
    assert result["request_count"] > 1
    assert result["summary"]["overview"]["text"].startswith("这是根据")
    assert result["summary"]["chapters"]
    assert {item["speaker_id"] for item in result["summary"]["speakers"]} == {
        "speaker_0",
        "speaker_1",
    }
    assert result["summary"]["action_items"][0]["task"] == "完成后续检查"


def test_forced_sliding_resume_reuses_validated_requests(monkeypatch, tmp_path):
    import meeting_harness.product_summary as module

    SlidingSession.starts = 0
    SlidingSession.requests = 0
    monkeypatch.setattr(module, "RkllmServerSession", SlidingSession)
    source = segments()
    out_dir = tmp_path / "llm"
    first = run_product_summary_stage(
        config=ProductSummaryConfig(llm_config(20000, 3000), 500, 2.0, 0, False),
        segments=source,
        speaker_ids=["speaker_0", "speaker_1"],
        timeline=render_timeline(source),
        out_dir=out_dir,
        sampler=None,
    )
    requests = SlidingSession.requests
    second = run_product_summary_stage(
        config=ProductSummaryConfig(llm_config(20000, 3000), 500, 2.0, 0, True),
        segments=source,
        speaker_ids=["speaker_0", "speaker_1"],
        timeline=render_timeline(source),
        out_dir=out_dir,
        sampler=None,
    )
    assert first["summary"] == second["summary"]
    assert second["request_count"] == 0
    assert second["validated_request_count"] == 0
    assert second["reused_request_count"] == requests
    assert SlidingSession.requests == requests


def test_sliding_path_outputs_chapters_summary_actions_and_display(monkeypatch, tmp_path):
    import meeting_harness.product_summary as module

    monkeypatch.setattr(module, "RkllmServerSession", SlidingSession)
    source = segments(count=8, size=180)
    result = run_product_summary_stage(
        config=ProductSummaryConfig(llm_config(5500, 900), 200, 1.0, 0, False),
        segments=source,
        speaker_ids=["speaker_0", "speaker_1"],
        timeline=render_timeline(source),
        out_dir=tmp_path / "llm",
        sampler=None,
    )
    assert result["policy"] == "sliding_chapter_windows"
    assert result["plan"]["window_count"] > 1
    assert result["summary"]["overview"]["text"].startswith("这是根据")
    assert result["summary"]["chapters"]
    assert result["summary"]["action_items"]
    assert {item["speaker_id"] for item in result["summary"]["speakers"]} == {
        "speaker_0",
        "speaker_1",
    }

    frontend = build_frontend_result(
        {"meeting_id": "mtg", "duration_ms": source[-1]["end_ms"]},
        source,
        result["summary"],
        context_policy=result["policy"],
    )
    display = render_meeting_display(frontend)
    assert "========== 全文摘要 ==========" in display
    assert "========== 章节速览 ==========" in display
    assert "========== 待办事项 ==========" in display
    assert "当前处理路径未生成发言人总结" not in display
    assert "发言人0：" in display
    assert "发言人1：" in display
    assert "[seg-000001][0m00s-1m00s]" in display


def test_sliding_resume_reuses_all_requests(monkeypatch, tmp_path):
    import meeting_harness.product_summary as module

    SlidingSession.starts = 0
    SlidingSession.requests = 0
    monkeypatch.setattr(module, "RkllmServerSession", SlidingSession)
    source = segments(count=8, size=180)
    out_dir = tmp_path / "llm"
    first = run_product_summary_stage(
        config=ProductSummaryConfig(llm_config(5500, 900), 200, 1.0, 0, False),
        segments=source,
        speaker_ids=["speaker_0", "speaker_1"],
        timeline=render_timeline(source),
        out_dir=out_dir,
        sampler=None,
    )
    starts = SlidingSession.starts
    requests = SlidingSession.requests
    second = run_product_summary_stage(
        config=ProductSummaryConfig(llm_config(5500, 900), 200, 1.0, 0, True),
        segments=source,
        speaker_ids=["speaker_0", "speaker_1"],
        timeline=render_timeline(source),
        out_dir=out_dir,
        sampler=None,
    )
    assert second["summary"] == first["summary"]
    assert second["request_count"] == 0
    assert second["validated_request_count"] == 0
    assert second["reused_request_count"] == requests
    assert SlidingSession.starts == starts
    assert SlidingSession.requests == requests


def test_window_normalizes_string_null_carryover():
    import meeting_harness.product_summary as module

    source = segments(count=2, size=1)
    payload = {
        "completed_chapters": [
            {
                "title": "完整章节",
                "summary": "覆盖整个窗口。",
                "start_ref": "seg-000001",
                "end_ref": "seg-000002",
                "key_refs": ["seg-000001"],
            }
        ],
        "action_candidates": [],
        "carryover_start_ref": "null",
    }
    chapters, actions, next_offset, quality = module._validate_window(
        json.dumps(payload, ensure_ascii=False),
        "stop",
        False,
        source,
        is_final=False,
    )
    assert len(chapters) == 1
    assert actions == []
    assert next_offset == len(source)
    assert quality["repairs"][0]["type"] == "normalize_string_null_carryover"


def test_window_expands_core_chapter_to_full_completed_range():
    import meeting_harness.product_summary as module

    source = segments(count=3, size=1)
    payload = {
        "completed_chapters": [
            {
                "title": "已完成章节",
                "summary": "核心内容位于窗口前两条。",
                "core_start_ref": "seg-000001",
                "core_end_ref": "seg-000002",
                "key_refs": ["seg-000001"],
            }
        ],
        "action_candidates": [],
        "carryover_start_ref": None,
    }
    chapters, _, next_offset, quality = module._validate_window(
        json.dumps(payload, ensure_ascii=False),
        "stop",
        False,
        source,
        is_final=False,
    )
    assert chapters[0]["core_end_ref"] == "seg-000002"
    assert chapters[0]["end_ref"] == "seg-000003"
    assert next_offset == len(source)
    assert quality["checks"]["continuous_ranges_assigned_by_harness"] is True


def test_final_window_merges_tail_into_last_core_chapter():
    import meeting_harness.product_summary as module

    source = segments(count=3, size=1)
    payload = {
        "completed_chapters": [
            {
                "title": "最后章节",
                "summary": "核心内容位于窗口前两条。",
                "core_start_ref": "seg-000001",
                "core_end_ref": "seg-000002",
                "key_refs": ["seg-000001"],
            }
        ],
        "action_candidates": [],
        "carryover_start_ref": None,
    }
    chapters, _, next_offset, _ = module._validate_window(
        json.dumps(payload, ensure_ascii=False),
        "stop",
        False,
        source,
        is_final=True,
    )
    assert chapters[0]["start_ref"] == "seg-000001"
    assert chapters[0]["end_ref"] == "seg-000003"
    assert chapters[0]["refs"] == ["seg-000001"]
    assert next_offset == len(source)


def test_window_assigns_gaps_to_previous_core_chapter():
    import meeting_harness.product_summary as module

    source = segments(count=10, size=1)
    payload = {
        "completed_chapters": [
            {
                "title": "第一章",
                "summary": "第一段核心讨论。",
                "core_start_ref": "seg-000003",
                "core_end_ref": "seg-000004",
                "key_refs": ["seg-000003"],
            },
            {
                "title": "第二章",
                "summary": "第二段核心讨论。",
                "core_start_ref": "seg-000007",
                "core_end_ref": "seg-000008",
                "key_refs": ["seg-000007"],
            },
        ],
        "action_candidates": [],
        "carryover_start_ref": None,
    }
    chapters, _, next_offset, _ = module._validate_window(
        json.dumps(payload, ensure_ascii=False),
        "stop",
        False,
        source,
        is_final=False,
    )
    assert chapters[0]["start_ref"] == "seg-000001"
    assert chapters[0]["end_ref"] == "seg-000006"
    assert chapters[1]["start_ref"] == "seg-000007"
    assert chapters[1]["end_ref"] == "seg-000010"
    assert next_offset == len(source)


def test_window_drops_action_candidate_without_completed_evidence():
    import meeting_harness.product_summary as module

    source = segments(count=3, size=1)
    payload = {
        "completed_chapters": [
            {
                "title": "已完成章节",
                "summary": "只覆盖窗口前两条。",
                "start_ref": "seg-000001",
                "end_ref": "seg-000002",
                "key_refs": ["seg-000001"],
            }
        ],
        "action_candidates": [
            {
                "task": "尾部尚未完成的任务",
                "owner": None,
                "deadline": None,
                "refs": ["seg-000003"],
            }
        ],
        "carryover_start_ref": "seg-000003",
    }
    _, actions, next_offset, quality = module._validate_window(
        json.dumps(payload, ensure_ascii=False),
        "stop",
        False,
        source,
        is_final=False,
    )
    assert next_offset == 2
    assert actions == []
    assert any(
        item["type"] == "drop_action_candidate_without_completed_evidence"
        for item in quality["repairs"]
    )


def test_window_keeps_valid_action_refs_and_drops_invalid_ones():
    import meeting_harness.product_summary as module

    source = segments(count=3, size=1)
    payload = {
        "completed_chapters": [
            {
                "title": "已完成章节",
                "summary": "只覆盖窗口前两条。",
                "start_ref": "seg-000001",
                "end_ref": "seg-000002",
                "key_refs": ["seg-000001"],
            }
        ],
        "action_candidates": [
            {
                "task": "保留有已完成章节证据的任务",
                "owner": None,
                "deadline": None,
                "refs": ["seg-000001", "seg-000003"],
            }
        ],
        "carryover_start_ref": "seg-000003",
    }
    _, actions, _, quality = module._validate_window(
        json.dumps(payload, ensure_ascii=False),
        "stop",
        False,
        source,
        is_final=False,
    )
    assert actions[0]["refs"] == ["seg-000001"]
    assert any(
        item["type"] == "drop_action_candidate_refs_outside_completed_chapters"
        for item in quality["repairs"]
    )


def test_action_review_rejects_truncated_response(monkeypatch, tmp_path):
    import meeting_harness.product_summary as module

    class TruncatedActionSession(SlidingSession):
        def request(self, messages, request_dir, **kwargs):
            result = super().request(messages, request_dir, **kwargs)
            if kwargs["request_id"] == "action-review":
                result["context_truncated"] = True
                atomic_write_json(
                    request_dir / "status.json",
                    {
                        "request_id": "action-review",
                        "finish_reason": "stop",
                        "context_truncated": True,
                    },
                )
            return result

    monkeypatch.setattr(module, "RkllmServerSession", TruncatedActionSession)
    source = segments(count=8, size=180)
    try:
        run_product_summary_stage(
            config=ProductSummaryConfig(llm_config(5500, 900), 200, 1.0, 0, False),
            segments=source,
            speaker_ids=["speaker_0", "speaker_1"],
            timeline=render_timeline(source),
            out_dir=tmp_path / "llm",
            sampler=None,
        )
    except module.SummaryValidationError as exc:
        assert "action review input was truncated" in str(exc)
    else:
        raise AssertionError("truncated action review should fail")

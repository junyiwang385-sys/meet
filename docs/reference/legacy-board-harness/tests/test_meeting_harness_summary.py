import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meeting_harness.artifacts import atomic_write_json, atomic_write_text
from meeting_harness.llm import LlmConfig
from meeting_harness.summary import SummaryRunConfig, run_summary_stage
from meeting_harness.transcript import render_timeline


def make_segments(count=8, text_size=700):
    return [
        {
            "segment_id": f"seg-{index:06d}",
            "index": index,
            "start_ms": index * 1000,
            "end_ms": index * 1000 + 900,
            "speaker_id": f"speaker_{index % 2}",
            "text": "会议内容" + "安" * text_size,
            "status": "ok",
        }
        for index in range(1, count + 1)
    ]


def minimal_summary(ref):
    return {
        "title": None,
        "overview": {"text": "会议内容摘要", "refs": [ref]},
        "chapters": [],
        "speakers": [],
        "key_points": [],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
        "risks": [],
        "keywords": [],
    }


class FakeSession:
    starts = 0
    requests = 0

    def __init__(self, config, out_dir, sampler):
        self.config = config
        self.out_dir = out_dir
        self.sampler = sampler
        self.ready_seconds = None
        self.files = {"model": "fake.rknn"}
        self.request_count = 0

    def start(self):
        type(self).starts += 1
        self.ready_seconds = 0.01

    def request(self, messages, request_dir, **kwargs):
        type(self).requests += 1
        self.request_count += 1
        text = "\n".join(message["content"] for message in messages)
        refs = sorted(set(re.findall(r"seg-\d{6}", text)))
        assert refs
        payload = minimal_summary(refs[0])
        content = json.dumps(payload, ensure_ascii=False)
        request_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(request_dir / "final_json.txt", content)
        status = {
            "finish_reason": "stop",
            "context_truncated": False,
            "request_id": kwargs.get("request_id"),
        }
        atomic_write_json(request_dir / "status.json", status)
        return {
            "content": content,
            "thinking": "模拟思考",
            "thinking_source": "inline_think",
            "finish_reason": "stop",
            "context_truncated": False,
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            "timings": {},
            "request_elapsed_seconds": 0.02,
        }

    def close(self):
        return None


def make_config(resume):
    llm = LlmConfig(
        board_scripts_dir=pathlib.Path("."),
        model_dir=pathlib.Path("."),
        server=pathlib.Path("rkllm3-server"),
        host="127.0.0.1",
        port=18245,
        ctx=5000,
        predict=1000,
        max_tokens=1000,
        temperature=0.0,
        server_temp=0.0,
        server_top_k=1,
        server_top_p=1.0,
        server_repeat_penalty=1.05,
        ready_timeout=10,
        request_timeout=10,
    )
    return SummaryRunConfig(
        llm=llm,
        safety_tokens=500,
        chars_per_token=1.0,
        fixed_overhead_tokens=0,
        overlap_segments=1,
        resume=resume,
    )


def test_chunk_merge_uses_one_server_and_resume_reuses_all(monkeypatch, tmp_path):
    import meeting_harness.summary as summary_module

    FakeSession.starts = 0
    FakeSession.requests = 0
    monkeypatch.setattr(summary_module, "RkllmServerSession", FakeSession)
    segments = make_segments()
    timeline = render_timeline(segments)
    model_identity = {"model": "fake", "sha256": "abc"}

    first = run_summary_stage(
        config=make_config(resume=False),
        segments=segments,
        speaker_ids=["speaker_0", "speaker_1"],
        timeline=timeline,
        out_dir=tmp_path / "llm",
        sampler=None,
        model_identity=model_identity,
    )

    assert first["policy"] == "whole_segment_chunk_merge"
    assert first["request_count"] > 1
    assert first["validated_request_count"] == first["request_count"]
    assert FakeSession.starts == 1
    assert FakeSession.requests == first["request_count"]
    assert first["quality"]["checks"]["full_meeting_coverage"] is True
    assert first["plan"]["merge_request_count"] > 0
    assert first["plan"]["reused_merge_count"] == 0

    starts_before_resume = FakeSession.starts
    requests_before_resume = FakeSession.requests
    second = run_summary_stage(
        config=make_config(resume=True),
        segments=segments,
        speaker_ids=["speaker_0", "speaker_1"],
        timeline=timeline,
        out_dir=tmp_path / "llm",
        sampler=None,
        model_identity=model_identity,
    )

    assert second["request_count"] == 0
    assert second["validated_request_count"] == 0
    assert second["reused_request_count"] > 1
    assert second["plan"]["merge_request_count"] == 0
    assert second["plan"]["reused_merge_count"] > 0
    assert FakeSession.starts == starts_before_resume
    assert FakeSession.requests == requests_before_resume

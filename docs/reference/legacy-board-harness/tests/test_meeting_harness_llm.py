import pathlib
import sys
import urllib.error

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meeting_harness.llm import LlmConfig, LlmRunError, RkllmServerSession, split_assistant_output


def test_split_inline_thinking_and_final_json():
    result = split_assistant_output(
        {"content": '<think>分析会议内容</think>\n{"title": null}'}
    )
    assert result["thinking"] == "分析会议内容"
    assert result["final_content"] == '{"title": null}'
    assert result["thinking_source"] == "inline_think"


def test_split_dedicated_reasoning_content():
    result = split_assistant_output(
        {"reasoning_content": "内部推理", "content": '{"title": null}'}
    )
    assert result["thinking"] == "内部推理"
    assert result["final_content"] == '{"title": null}'
    assert result["thinking_source"] == "reasoning_content"


def test_dedicated_and_inline_thinking_are_both_preserved():
    result = split_assistant_output(
        {
            "reasoning_content": "独立推理",
            "content": '<think>内联推理</think>{"title": null}',
        }
    )
    assert result["thinking"] == "独立推理\n\n内联推理"
    assert result["final_content"] == '{"title": null}'
    assert result["thinking_source"] == "reasoning_content+inline"


def test_split_closing_only_thinking_output():
    result = split_assistant_output(
        {"content": '分析内容</think>\n```json\n{"title": null}\n```'}
    )
    assert result["thinking"] == "分析内容"
    assert result["final_content"] == '{"title": null}'


def test_unclosed_thinking_is_rejected():
    with pytest.raises(LlmRunError, match="closing"):
        split_assistant_output({"content": "<think>没有结束"})


def test_empty_final_content_is_rejected():
    with pytest.raises(LlmRunError, match="no final content"):
        split_assistant_output({"content": "<think>只有思考</think>"})


def test_http_failure_counts_as_attempted_request(monkeypatch, tmp_path):
    config = LlmConfig(
        board_scripts_dir=tmp_path,
        model_dir=tmp_path,
        server=pathlib.Path("rkllm3-server"),
        host="127.0.0.1",
        port=18245,
        ctx=16384,
        predict=4096,
        max_tokens=4096,
        temperature=0.0,
        server_temp=0.0,
        server_top_k=1,
        server_top_p=1.0,
        server_repeat_penalty=1.05,
        ready_timeout=10,
        request_timeout=10,
    )
    session = object.__new__(RkllmServerSession)
    session.config = config
    session.out_dir = tmp_path
    session.sampler = None
    session.files = {}
    session.log_path = tmp_path / "server.log"
    session.log_path.write_text("")
    session.log_handle = None
    session.process = type("Process", (), {"poll": lambda self: None, "pid": 1})()
    session.ready_seconds = 0.1
    session.request_count = 0
    session.successful_response_count = 0

    def fail_request(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("meeting_harness.llm.urllib.request.urlopen", fail_request)
    with pytest.raises(LlmRunError, match="HTTP request failed"):
        session.request(
            [{"role": "user", "content": "test"}],
            tmp_path / "request",
        )
    assert session.request_count == 1
    assert session.successful_response_count == 0

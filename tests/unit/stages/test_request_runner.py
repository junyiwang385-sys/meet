"""_RequestRunner 直接单测：断点复用 / 校验失败重试 / 计数器accounting。

覆盖此前没有测试网的路径——run_request 从 run_product_summary_stage 闭包提成类前，
其重试/复用/计数逻辑靠板端真跑才暴露。这里用 fake session + fake validator 隔离验证。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from meeting_agent.llm.llm import LlmRunError
from meeting_agent.stages import _requests
from meeting_agent.stages._requests import _RequestRunner
from meeting_agent.stages.validation import SummaryValidationError


def _config(resume: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        resume=resume,
        llm=SimpleNamespace(ctx=8192, predict=1024, max_tokens=1024, temperature=0.0),
    )


class FakeSession:
    """按脚本逐次返回；("ok", content) 正常返回并写 final_json/status，("raise", msg) 抛 LlmRunError。"""

    def __init__(self, scripted: list[tuple[str, str]]):
        self.scripted = list(scripted)
        self.calls: list[tuple[str, str, int]] = []

    def request(self, messages, request_dir, *, max_tokens, phase, request_id,
                request_kind, attempt, estimated_prompt_tokens, run_log):
        self.calls.append((request_id, request_kind, attempt))
        kind, payload = self.scripted.pop(0)
        request_dir.mkdir(parents=True, exist_ok=True)
        if kind == "raise":
            raise LlmRunError(payload)
        (request_dir / "final_json.txt").write_text(payload, encoding="utf-8")
        (request_dir / "status.json").write_text("{}", encoding="utf-8")
        return {
            "content": payload,
            "finish_reason": "stop",
            "context_truncated": False,
            "request_id": request_id,
            "usage": {},
            "timings": {},
            "thinking": "",
            "request_elapsed_seconds": 0.1,
        }


def _runner(session: FakeSession, *, resume: bool = False) -> _RequestRunner:
    return _RequestRunner(
        config=_config(resume),
        run_log=None,
        ensure_session=lambda: session,
        model_identity=lambda: {"model": "fake"},
    )


class RequestRunnerTests(unittest.TestCase):
    def _run(self, runner, session, validator, tmp):
        return runner.run(
            messages=[{"role": "user", "content": "hi"}],
            request_dir=Path(tmp) / "req",
            request_id="r1",
            request_kind="block-summary",
            phase="test",
            estimate=100,
            validator=validator,
        )

    def test_happy_path_counts(self):
        session = FakeSession([("ok", '{"x":1}')])
        runner = _runner(session)
        with TemporaryDirectory() as tmp:
            out = self._run(runner, session, lambda c, fr, tr: {"ok": c}, tmp)
        self.assertEqual(out, {"ok": '{"x":1}'})
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(runner.retry_count, 0)
        self.assertEqual(runner.validation_failed_count, 0)
        self.assertEqual(runner.reused_count, 0)
        self.assertEqual(len(runner.request_records), 1)
        self.assertEqual(runner.request_attempts[-1]["status"], "validated")

    def test_validation_fail_then_retry_success(self):
        session = FakeSession([("ok", "bad"), ("ok", "good")])
        runner = _runner(session)
        state = {"n": 0}

        def validator(content, finish_reason, truncated):
            state["n"] += 1
            if state["n"] == 1:
                raise SummaryValidationError("LLM content is not valid JSON: boom")
            return {"ok": content}

        with TemporaryDirectory() as tmp:
            out = self._run(runner, session, validator, tmp)
        self.assertEqual(out, {"ok": "good"})
        self.assertEqual(len(session.calls), 2)          # 重试确实又发了一次
        self.assertEqual(runner.retry_count, 1)
        self.assertEqual(runner.validation_failed_count, 1)
        self.assertEqual(len(runner.request_records), 1)  # 只记最终通过的

    def test_non_retryable_validation_raises(self):
        session = FakeSession([("ok", "bad")])
        runner = _runner(session)

        def validator(content, finish_reason, truncated):
            raise SummaryValidationError("some unrelated validation problem")

        with TemporaryDirectory() as tmp:
            with self.assertRaises(SummaryValidationError):
                self._run(runner, session, validator, tmp)
        self.assertEqual(len(session.calls), 1)          # 不可重试→只发一次
        self.assertEqual(runner.validation_failed_count, 1)
        self.assertEqual(runner.retry_count, 0)

    def test_request_failed_records_attempt_and_raises(self):
        session = FakeSession([("raise", "server down")])
        runner = _runner(session)
        with TemporaryDirectory() as tmp:
            with self.assertRaises(LlmRunError):
                self._run(runner, session, lambda c, fr, tr: {"ok": c}, tmp)
        self.assertEqual(runner.request_attempts[-1]["status"], "request_failed")
        self.assertEqual(len(runner.request_records), 0)

    def test_resume_reuses_without_calling_session(self):
        session = FakeSession([])  # 若被调用会 IndexError
        runner = _runner(session, resume=True)
        with TemporaryDirectory() as tmp:
            with mock.patch.object(_requests, "_load_reusable_request", return_value={"cached": True}):
                out = self._run(runner, session, lambda c, fr, tr: {"ok": c}, tmp)
        self.assertEqual(out, {"cached": True})
        self.assertEqual(runner.reused_count, 1)
        self.assertEqual(len(session.calls), 0)          # 复用命中→根本没发请求


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from meeting_agent.llm.llm import LlmConfig, LlmRunError, RkllmServerSession, split_assistant_output


class RequestLoggingTests(unittest.TestCase):
    def test_split_failure_is_a_bounded_llm_error(self):
        with self.assertRaises(LlmRunError):
            split_assistant_output({"content": "<think>unfinished"})

    def test_request_emits_request_failed_when_thinking_block_is_unclosed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "board_meeting_chain_profile.py").write_text(
                "def terminate_process(process):\n    process.terminate()\n",
                encoding="utf-8",
            )
            model = root / "model"
            model.mkdir()
            for name in ("model.rknn", "model.weight", "model.tokenizer.gguf", "model.embed.bin"):
                (model / name).write_bytes(b"x")
            config = LlmConfig(
                board_scripts_dir=scripts,
                model_dir=model,
                server=Path("server"),
                host="127.0.0.1",
                port=18245,
                ctx=1024,
                predict=128,
                max_tokens=128,
                temperature=0.0,
                server_temp=0.0,
                server_top_k=1,
                server_top_p=1.0,
                server_repeat_penalty=1.0,
                ready_timeout=1,
                request_timeout=1,
            )
            out_dir = root / "out"
            session = RkllmServerSession(config, out_dir)
            session.process = SimpleNamespace(poll=lambda: None, pid=123)
            events = []
            run_log = SimpleNamespace(emit=lambda *args, **kwargs: events.append((args, kwargs)))
            response = {
                "choices": [{"message": {"content": "<think>unfinished"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2},
            }
            with patch("meeting_agent.llm.llm.urllib.request.urlopen") as urlopen:
                urlopen.return_value.read.return_value = json.dumps(response).encode("utf-8")
                with self.assertRaises(LlmRunError):
                    session.request(
                        [{"role": "user", "content": "demo"}],
                        out_dir / "request",
                        run_log=run_log,
                    )
            failed = [kwargs for args, kwargs in events if args and args[0] == "request_failed"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["error"]["code"], "invalid_response")
            self.assertEqual(failed[0]["error"]["request_id"], "request")
            self.assertEqual(session.transport_request_count, 1)
            self.assertEqual(session.http_response_count, 1)
            self.assertEqual(session.response_parse_success_count, 0)
            urlopen.return_value.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

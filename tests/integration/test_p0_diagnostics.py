from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import meeting_agent.adapters.board.board_agent_api_v0 as board_agent
from meeting_agent.adapters.board.board_harness_worker_v0 import read_run_sidecars
from meeting_agent.adapters.gateway.meeting_agent_gateway_v0 import GatewayRequestHandler


class P0DiagnosticsIntegrationTests(unittest.TestCase):
    def test_failure_diagnostics_flow_from_sidecars_to_gateway_without_content_leak(self):
        identity = {
            "trace_id": "trace-p0",
            "meeting_id": "meeting-p0",
            "task_id": "task-p0",
            "run_id": "run-p0",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            (out_dir / "run_manifest.json").write_text(
                json.dumps({"identity": identity}), encoding="utf-8"
            )
            (out_dir / "run_metrics.json").write_text(
                json.dumps(
                    {
                        "identity": identity,
                        "status": "failed",
                        "artifact_count": 3,
                        "llm": {
                            "request_count": 1,
                            "request_attempts": [{"request_dir": "C:/private/prompt"}],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (out_dir / "error_report.json").write_text(
                json.dumps(
                    {
                        "identity": identity,
                        "status": "failed",
                        "error": {
                            "stage": "llm_summary",
                            "code": "validation_failed",
                            "cause": "finish_reason_length",
                            "message": "model output reached limit",
                            "request_id": "req-p0",
                            "finish_reason": "length",
                            "context_truncated": False,
                            "prompt": "DO NOT FORWARD",
                        },
                        "stage_details": {
                            "status": "failed",
                            "log_tail": "PRIVATE LOG",
                            "error": {"prompt": "DO NOT FORWARD"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (out_dir / "run_events.jsonl").write_text("{}\n", encoding="utf-8")
            (out_dir / "stage_status.json").write_text("{}", encoding="utf-8")

            worker_projection = read_run_sidecars(out_dir)
            old_task = board_agent._task
            try:
                board_agent._task = {
                    "task_id": "task-p0",
                    "meeting_id": "meeting-p0",
                    "state": "processing",
                    "stage": "llm_summary",
                    "seq": 1,
                    "updated_at": "now",
                }
                task_snapshot = board_agent.mark_harness_failed(
                    "task-p0",
                    "harness_failed",
                    "Harness returned failed",
                    {
                        "status": "failed",
                        "stage": "llm_summary",
                        "return_code": 1,
                        "run_id": "run-p0",
                        "identity": identity,
                        "diagnostic_source": worker_projection["diagnostic_source"],
                        "diagnostics": worker_projection["diagnostics"],
                        "metrics": worker_projection["metrics"],
                        "artifact_refs": worker_projection["artifact_refs"],
                        "elapsed_seconds": 12.3,
                        "worker_log": "C:/private/worker.log",
                        "result_path": "C:/private/meeting_result.json",
                        "error": {
                            "stage": "llm_summary",
                            "code": "validation_failed",
                            "message": "model output reached limit",
                            "prompt": "DO NOT FORWARD",
                        },
                    },
                )
                self.assertIsNotNone(task_snapshot)
                assert task_snapshot is not None

                gateway_probe = object.__new__(GatewayRequestHandler)
                record = {
                    "detail": {"meeting_id": "meeting-p0"},
                    "board_task_id": "task-p0",
                    "board_task_kind": "harness_meeting_v0",
                }
                diagnostics = gateway_probe._failed_diagnostics(
                    record, task_snapshot, None
                )

                serialized_worker = json.dumps(worker_projection, ensure_ascii=False)
                serialized_task = json.dumps(task_snapshot, ensure_ascii=False)
                serialized_gateway = json.dumps(diagnostics, ensure_ascii=False)
                for serialized in (
                    serialized_worker,
                    serialized_task,
                    serialized_gateway,
                ):
                    self.assertNotIn("DO NOT FORWARD", serialized)
                    self.assertNotIn("PRIVATE LOG", serialized)
                    self.assertNotIn("C:/private", serialized)

                self.assertEqual(diagnostics["stage"], "llm_summary")
                self.assertEqual(diagnostics["code"], "validation_failed")
                self.assertEqual(diagnostics["cause"], "finish_reason_length")
                self.assertEqual(diagnostics["run_id"], "run-p0")
                self.assertEqual(diagnostics["request_id"], "req-p0")
                self.assertEqual(diagnostics["finish_reason"], "length")
                self.assertFalse(diagnostics["context_truncated"])
                self.assertEqual(
                    diagnostics["artifact_refs"]["run_metrics"], "run_metrics.json"
                )
                safe_metrics = task_snapshot["error"]["metrics"]
                self.assertEqual(safe_metrics["llm"]["request_count"], 1)
                self.assertNotIn("request_attempts", safe_metrics["llm"])
            finally:
                board_agent._task = old_task


if __name__ == "__main__":
    unittest.main()

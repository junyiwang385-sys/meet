import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path


from meeting_agent.storage.artifacts import HarnessPaths, sha256_file  # noqa: E402
from meeting_agent.contracts.identity import RunIdentity
from meeting_agent.observability.runlog import RunLogContext  # noqa: E402


class HarnessRunLogTests(unittest.TestCase):
    def make_context(self, temp_dir: str) -> tuple[HarnessPaths, RunLogContext]:
        root = Path(temp_dir) / "run"
        root.mkdir(parents=True, exist_ok=True)
        paths = HarnessPaths.from_root(root)
        paths.create_directories()
        identity = RunIdentity(
            trace_id="trace-1",
            meeting_id="meeting-1",
            task_id="task-1",
            run_id="run-1",
        )
        return paths, RunLogContext(paths, identity)

    def test_emit_writes_jsonl_and_increments_seq(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths, ctx = self.make_context(temp_dir)

            first = ctx.emit("run_started", details={"resume": False})
            second = ctx.stage_started("segmentation", details={"command": ["python", "-m", "demo"]})
            third = ctx.emit("note", message="x" * 7005)

            lines = paths.run_events.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            first_line = json.loads(lines[0])
            second_line = json.loads(lines[1])
            third_line = json.loads(lines[2])

            self.assertEqual(first_line["schema_version"], "run-event.v1")
            self.assertEqual(first_line["seq"], 1)
            self.assertEqual(second_line["seq"], 2)
            self.assertEqual(third_line["seq"], 3)
            self.assertEqual(first["trace_id"], "trace-1")
            self.assertEqual(second["stage"], "segmentation")
            self.assertEqual(len(third_line["message"]), 6000)
            self.assertTrue(third_line["message"].endswith("x" * 6000))

    def test_manifest_error_report_and_metrics_are_written(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            paths, ctx = self.make_context(temp_dir)
            source_audio = Path(temp_dir) / "audio.wav"
            source_audio.write_bytes(b"demo-audio")
            source_sha = sha256_file(source_audio)
            source_size = source_audio.stat().st_size

            args = SimpleNamespace(
                trace_id="trace-1",
                meeting_id="meeting-1",
                task_id="task-1",
                run_id="run-1",
                resume=False,
                overwrite=True,
                ctx=16384,
                predict=3072,
                max_tokens=3072,
            )
            result = {
                "status": "failed",
                "run_id": "run-1",
                "meeting": {
                    "meeting_id": "meeting-1",
                    "source_audio_sha256": source_sha,
                    "source_audio_size_bytes": source_size,
                },
                "runtime": {
                    "stages": {
                        "segmentation": {"status": "succeeded", "elapsed_seconds": 1.5},
                        "batch_asr": {"status": "failed", "elapsed_seconds": 2.0},
                    },
                    "llm": {"request_count": 1, "validated_request_count": 1},
                    "memory": {"rss_mb": 12},
                    "total_elapsed_seconds": 3.25,
                },
                "errors": [{"stage": "batch_asr", "code": "process_failed", "message": "failed"}],
                "artifacts": {"timeline": {"path": "timeline.txt"}},
            }
            state = {
                "status": "failed",
                "stages": {
                    "segmentation": {"status": "succeeded", "elapsed_seconds": 1.5},
                    "batch_asr": {
                        "status": "failed",
                        "elapsed_seconds": 2.0,
                        "log_tail": "tail text",
                    },
                },
                "error": {"stage": "batch_asr", "code": "process_failed", "message": "failed"},
            }

            manifest = ctx.write_manifest(args=args, source_audio=source_audio, result=result)
            report = ctx.write_error_report(state["error"], result=result, state=state)
            metrics = ctx.write_metrics(result=result, state=state, memory={"rss_mb": 12})

            self.assertEqual(manifest["schema_version"], "run-manifest.v1")
            self.assertEqual(manifest["identity"]["trace_id"], "trace-1")
            self.assertEqual(manifest["source_audio"]["sha256"], source_sha)
            self.assertEqual(manifest["sidecars"]["run_events"], "run_events.jsonl")

            self.assertEqual(report["schema_version"], "error-report.v1")
            self.assertEqual(report["error"]["category"], "resource")
            self.assertTrue(report["error"]["retryable"])
            self.assertEqual(report["stage_details"]["status"], "failed")
            self.assertEqual(report["log_tail"], "tail text")
            self.assertFalse(report["diagnosis"]["agent_enabled"])

            self.assertEqual(metrics["schema_version"], "run-metrics.v1")
            self.assertEqual(metrics["status"], "failed")
            self.assertEqual(metrics["stage_counts"]["succeeded"], 1)
            self.assertEqual(metrics["stage_counts"]["failed"], 1)
            self.assertEqual(metrics["artifact_count"], 1)
            self.assertEqual(metrics["error_count"], 1)
            self.assertEqual(metrics["memory"]["rss_mb"], 12)

            self.assertTrue(paths.run_manifest.is_file())
            self.assertTrue(paths.error_report.is_file())
            self.assertTrue(paths.run_metrics.is_file())

    def test_stage_failed_event_carries_normalized_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _, ctx = self.make_context(temp_dir)
            event = ctx.stage_failed(
                "segmentation",
                {"stage": "segmentation", "code": "process_failed", "message": "boom"},
            )
            self.assertEqual(event["event"], "stage_failed")
            self.assertEqual(event["error"]["category"], "resource")
            self.assertTrue(event["error"]["retryable"])

    def test_finish_reason_length_keeps_retry_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _, ctx = self.make_context(temp_dir)
            event = ctx.emit(
                "validation_failed",
                stage="llm_speaker_batch",
                error={
                    "stage": "llm_speaker_batch",
                    "code": "validation_failed",
                    "message": "speaker batch finish_reason is 'length'",
                    "return_code": 7,
                    "request_id": "speaker-batch-1",
                    "attempt": 1,
                },
            )
            error = event["error"]
            self.assertEqual(error["cause"], "finish_reason_length")
            self.assertEqual(error["return_code"], 7)
            self.assertEqual(error["request_id"], "speaker-batch-1")
            self.assertTrue(error["technical_retryable"])
            self.assertTrue(error["product_retryable"])


if __name__ == "__main__":
    unittest.main()

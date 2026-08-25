from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from meeting_agent.adapters.board.board_harness_worker_v0 import read_run_sidecars, _safe_sidecar_identity


class WorkerSidecarTests(unittest.TestCase):
    def test_null_identity_is_safe(self):
        self.assertEqual(_safe_sidecar_identity(None), {})
        self.assertEqual(_safe_sidecar_identity({"run_id": "run-1"}), {"run_id": "run-1"})

    def test_sidecar_projection_is_bounded_and_keeps_canonical_refs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            (out_dir / "run_manifest.json").write_text(
                json.dumps({"identity": None}), encoding="utf-8"
            )
            (out_dir / "run_metrics.json").write_text(
                json.dumps({
                    "schema_version": "run-metrics.v1",
                    "identity": {"run_id": "run-1"},
                    "status": "failed",
                    "llm": {"transport_request_count": 2},
                    "memory": {},
                    "error_count": 1,
                    "artifact_count": 3,
                }),
                encoding="utf-8",
            )
            (out_dir / "error_report.json").write_text(
                json.dumps({
                    "schema_version": "error-report.v1",
                    "identity": {"run_id": "run-1"},
                    "status": "failed",
                    "error": {"stage": "llm_summary", "message": "x" * 2000},
                    "stage_details": {"status": "failed"},
                }),
                encoding="utf-8",
            )
            projection = read_run_sidecars(out_dir)
            self.assertEqual(projection["identity"], {"run_id": "run-1"})
            self.assertEqual(projection["diagnostic_source"], "harness_error_report")
            self.assertEqual(projection["artifact_refs"]["run_metrics"], "run_metrics.json")
            self.assertLessEqual(
                len(projection["diagnostics"]["error"]["message"]), 600
            )


if __name__ == "__main__":
    unittest.main()

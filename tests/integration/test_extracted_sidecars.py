import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from meeting_agent.contracts.identity import RunIdentity
from meeting_agent.observability.runlog import RunLogContext
from meeting_agent.storage.artifacts import HarnessPaths


class ExtractedSidecarIntegrationTests(unittest.TestCase):
    def test_runlog_metrics_and_error_report_share_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "run"
            paths = HarnessPaths.from_root(root)
            paths.create_directories()
            identity = RunIdentity("trace-1", "meeting-1", "task-1", "run-1")
            context = RunLogContext(paths, identity)
            context.emit("run_started", stage="pipeline")
            result = {
                "status": "failed",
                "runtime": {"stages": {"llm_summary": {"status": "failed"}}, "llm": {}, "memory": {}},
                "errors": [{"stage": "llm_summary", "code": "validation_failed", "message": "finish_reason length"}],
                "artifacts": {},
            }
            state = {"stages": {"llm_summary": {"status": "failed"}}}
            report = context.write_error_report(state["stages"]["llm_summary"], result=result, state=state)
            metrics = context.write_metrics(result=result, state=state)
            self.assertEqual(report["identity"], identity.as_dict())
            self.assertEqual(metrics["identity"], identity.as_dict())
            self.assertTrue(paths.error_report.is_file())
            self.assertTrue(paths.run_metrics.is_file())


if __name__ == "__main__":
    unittest.main()

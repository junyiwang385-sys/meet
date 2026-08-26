import json
import pathlib
import tempfile
import unittest

from meeting_agent.observability.run_report import build_run_report, render_markdown


def _write(path: pathlib.Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


class RunReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        llm = self.root / "03_llm_summary"
        _write(self.root / "run_manifest.json", {
            "identity": {"run_id": "mtg_test"},
            "harness_version": "2.0.0",
            "config": {"ctx": 16384, "max_tokens": 3072, "input_chars_per_token": 1.3},
        })
        _write(self.root / "stage_status.json", {
            "status": "succeeded",
            "stages": {"llm_summary": {"elapsed_seconds": 100.0}},
        })
        _write(self.root / "run_metrics.json", {
            "total_elapsed_seconds": 150.0,
            "llm": {"request_count": 10, "retry_count": 3, "validation_failed_count": 3},
        })
        _write(self.root / "meeting_result.json", {
            "meeting": {"duration_ms": 60000},
            "quality": {"status": "pass", "warnings": []},
        })
        _write(llm / "plan.json", {
            "version": "product-summary.v25", "policy": "deterministic_blocks_map_reduce",
            "block_count": 3, "chapter_count": 3, "overview_source": "chapter_summaries",
            "speaker_count": 2, "action_candidate_count": 1,
        })
        _write(llm / "segmentation.json", {
            "version": "topic-segmentation.v2",
            "boundary_reason_counts": {"start": 1, "speaker": 2},
            "blocks": [
                {"text_chars": 100, "segment_count": 2, "opened_by": ["start"]},
                {"text_chars": 200, "segment_count": 3, "opened_by": ["speaker"]},
                {"text_chars": 150, "segment_count": 2, "opened_by": ["speaker"]},
            ],
            "config": {"cohesion_depth_threshold": 0.30},
        })
        _write(llm / "chapters.json", [
            {"title": "A", "overview": "x" * 80},
            {"title": "B", "overview": "y" * 200},
            {"title": "C", "overview": "z" * 50},
        ])
        _write(llm / "full_summary.json", {"title": "T", "overview": {"text": "o" * 197}})
        _write(self.root / "meeting_summary.json", {
            "title": "T", "overview": {"text": "o"}, "chapters": [1, 2, 3],
            "speakers": [1, 2], "action_items": [1],
            "key_points": [], "decisions": [], "open_questions": [], "risks": [], "keywords": [],
        })
        # 两个块目录：一个正常，一个带 attempt-2（重试）+ thinking
        for i, (summ, thinking, retried) in enumerate([
            ("s" * 84, "think" * 100, False),
            ("s" * 90, "think" * 120, True),
        ], 1):
            bd = llm / "blocks" / f"blk-{i:06d}"
            _write(bd / "validated_block.json", {"summary": summ, "continues_previous": i == 2})
            _write(bd / "status.json", {
                "finish_reason": "stop",
                "usage": {"prompt_tokens": 800, "completion_tokens": 500},
            })
            _write(bd / "messages.json", [{"role": "user", "content": "u" * 1400}])
            (bd / "thinking.txt").write_text(thinking, encoding="utf-8")
            if retried:
                _write(bd / "attempt-2" / "status.json", {"finish_reason": "stop", "usage": {}})

    def tearDown(self):
        self.tmp.cleanup()

    def test_report_sections_and_stats(self):
        r = build_run_report(self.root)
        self.assertEqual(r["identity"]["run_id"], "mtg_test")
        self.assertEqual(r["identity"]["source_audio_seconds"], 60.0)
        self.assertEqual(r["segmentation"]["blocks_opened_by_speaker"], 2)
        self.assertEqual(r["blocks"]["count"], 2)
        self.assertEqual(r["blocks"]["summary_chars"]["avg"], 87.0)
        self.assertEqual(r["blocks"]["continues_previous_count"], 1)
        self.assertEqual(r["blocks"]["retried_block_ids"], ["blk-000002"])
        self.assertEqual(r["reduce"]["overview_chars"], 197)
        self.assertEqual(r["reduce"]["empty_schema_fields"],
                         ["key_points", "decisions", "open_questions", "risks", "keywords"])

    def test_chars_per_token_calibration(self):
        r = build_run_report(self.root)
        # 两块各 prompt 800 tok / 1400 chars → 实测 1.75
        self.assertEqual(r["llm_economics"]["chars_per_token_actual"], 1.75)

    def test_flags_fire(self):
        r = build_run_report(self.root)
        joined = " ".join(r["flags"])
        self.assertIn("块摘要偏短", joined)
        self.assertIn("overview 偏短", joined)
        self.assertIn("overview 走了有损", joined)
        self.assertIn("think 未关", joined)
        self.assertIn("重试率偏高", joined)
        self.assertIn("chars_per_token", joined)
        self.assertIn("空 schema 字段", joined)

    def test_markdown_renders(self):
        md = render_markdown(build_run_report(self.root))
        self.assertIn("# 运行聚合报告", md)
        self.assertIn("优化红旗", md)

    def test_missing_files_do_not_crash(self):
        empty = pathlib.Path(tempfile.mkdtemp())
        try:
            r = build_run_report(empty)
            self.assertEqual(r["blocks"]["count"], 0)
            self.assertIsInstance(r["flags"], list)
        finally:
            import shutil
            shutil.rmtree(empty)


if __name__ == "__main__":
    unittest.main()

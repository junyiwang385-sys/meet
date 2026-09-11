from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from evals.run_e2e_eval import _collect_summary, _report, load_manifest, main

TIMELINE = "[seg-000001][0m00s-0m10s][speaker_1] 确认下周完成方案。\n"


class E2ERunnerTests(unittest.TestCase):
    def test_collects_core_content_coverage_separately_from_legacy(self):
        cases = []
        for status, importance in (("covered", "critical"), ("partial", "major")):
            cases.append(
                {
                    "candidate": {"status": "success"},
                    "judge": {
                        "result": {
                            "status": "success",
                            "result": {
                                "coverage_metric": {"name": "core_content_coverage"},
                                "claim_evaluations": [
                                    {"status": "supported", "severity": "none"}
                                ],
                                "fact_coverage": [
                                    {"status": status, "importance": importance}
                                ],
                            },
                        }
                    },
                }
            )

        metrics = _collect_summary(cases)

        self.assertEqual(metrics["faithfulness"], 1.0)
        self.assertEqual(metrics["core_content_coverage"], 0.8)
        self.assertEqual(metrics["core_content_coverage_macro"], 0.75)
        self.assertEqual(metrics["core_content_coverage_case_count"], 2)
        self.assertIsNone(metrics["weighted_completeness"])

        report = _report({"groups": {"all": metrics}, "cases": []})
        self.assertIn("Core content coverage", report)

    def test_load_manifest_resolves_relative_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "name": "case_1",
                                "audio_file": "audio.wav",
                                "reference_timeline_file": "reference.txt",
                                "expected_file": "expected.json",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            case = load_manifest(manifest)[0]
            self.assertEqual(case.audio_path, (root / "audio.wav").resolve())
            self.assertEqual(case.group, "e2e")

    def test_reuse_pipeline_without_judge(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            pipeline_root = root / "pipelines"
            pipeline = pipeline_root / "case_1"
            pipeline.mkdir(parents=True)
            audio = root / "audio.wav"
            audio.write_bytes(b"RIFF-test")
            reference = root / "reference.txt"
            reference.write_text(TIMELINE, encoding="utf-8")
            expected = root / "expected.json"
            expected.write_text(
                json.dumps(
                    {
                        "overview": {
                            "text": "会议确认下周完成方案。",
                            "refs": ["seg-000001"],
                        },
                        "chapters": [
                            {
                                "title": "方案确认",
                                "overview": "会议确认下周完成方案。",
                                "start_ref": "seg-000001",
                                "end_ref": "seg-000001",
                                "refs": ["seg-000001"],
                            }
                        ],
                        "speakers": [
                            {
                                "speaker_id": "speaker_1",
                                "overview": "确认下周完成方案。",
                                "refs": ["seg-000001"],
                            }
                        ],
                        "action_items": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "name": "case_1",
                                "audio_file": audio.name,
                                "reference_timeline_file": reference.name,
                                "expected_file": expected.name,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (pipeline / "timeline.txt").write_text(
                "[seg-000001][0m00s-0m00s][speaker_1] 确认下周完成方案。\n",
                encoding="utf-8",
            )
            canonical_dir = pipeline / "03_llm_summary"
            canonical_dir.mkdir()
            (canonical_dir / "canonical_segments.json").write_text(
                json.dumps(
                    [
                        {
                            "segment_id": "seg-000001",
                            "index": 1,
                            "start_ms": 100,
                            "end_ms": 900,
                            "speaker_id": "speaker_1",
                            "text": "确认下周完成方案。",
                            "status": "ok",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (pipeline / "meeting_summary.json").write_text(
                json.dumps(
                    {
                        "title": "方案确认",
                        "overview": {
                            "text": "会议确认下周完成方案。",
                            "refs": ["seg-000001"],
                        },
                        "chapters": [
                            {
                                "title": "方案确认",
                                "overview": "会议确认下周完成方案。",
                                "start_ref": "seg-000001",
                                "end_ref": "seg-000001",
                                "start_ms": 0,
                                "end_ms": 10000,
                                "speaker_ids": ["speaker_1"],
                                "refs": ["seg-000001"],
                            }
                        ],
                        "speakers": [
                            {
                                "speaker_id": "speaker_1",
                                "overview": "确认下周完成方案。",
                                "refs": ["seg-000001"],
                            }
                        ],
                        "key_points": [],
                        "decisions": [],
                        "action_items": [],
                        "open_questions": [],
                        "risks": [],
                        "keywords": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (pipeline / "meeting_result.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "runtime": {
                            "total_elapsed_seconds": 12.5,
                            "context_policy": "single_request_all_features",
                            "stages": {
                                "llm_summary": {
                                    "status": "succeeded",
                                    "elapsed_seconds": 4.0,
                                }
                            },
                            "llm": {
                                "request_count": 1,
                                "requests": [{"request_elapsed_seconds": 3.5}],
                            },
                            "memory": {"board_used_peak_mb": 1024.0},
                        },
                        "errors": [],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "output"
            return_code = main(
                [
                    "--manifest",
                    str(manifest),
                    "--pipeline-output-root",
                    str(pipeline_root),
                    "--reuse-pipeline",
                    "--skip-judge",
                    "--output-root",
                    str(output),
                    "--run-id",
                    "test-run",
                ]
            )
            self.assertEqual(return_code, 0)
            aggregate = json.loads(
                (output / "test-run" / "aggregate.json").read_text(encoding="utf-8")
            )
            metrics = aggregate["groups"]["all"]
            self.assertEqual(metrics["pipeline_completion_rate"], 1.0)
            self.assertEqual(metrics["e2e"]["cer_corpus"], 0.0)
            self.assertEqual(metrics["e2e"]["speaker_accuracy_macro"], 1.0)
            self.assertEqual(metrics["e2e"]["llm_model_call_elapsed_seconds_mean"], 3.5)


if __name__ == "__main__":
    unittest.main()

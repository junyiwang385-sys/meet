import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "src" / "meeting_agent" / "adapters" / "board" / "minutes"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
MODULE_PATH = SCRIPT_DIR / "meeting_overview_map_reduce_v0.py"
SPEC = importlib.util.spec_from_file_location("meeting_overview_map_reduce_v0", MODULE_PATH)
assert SPEC and SPEC.loader
overview = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = overview
SPEC.loader.exec_module(overview)


def turn(turn_id, start, end, speaker, text):
    return {
        "id": turn_id,
        "start": start,
        "end": end,
        "speaker": speaker,
        "speaker_kind": "main",
        "texts": [text],
        "text": text,
        "chunk_ids": [turn_id],
    }


def map_value(window_id, chapters, warnings=None):
    starts = [chapter["start"] for chapter in chapters]
    ends = [chapter["end"] for chapter in chapters]
    return {
        "schema_version": "meeting_overview_map_v0",
        "window_id": window_id,
        "time_range": {
            "start": min(starts) if starts else 0.0,
            "end": max(ends) if ends else 0.0,
        },
        "chapters": chapters,
        "warnings": warnings or [],
    }


def chapter(title, turn_ids, start, end):
    return {
        "title": title,
        "summary": f"{title}摘要",
        "key_points": [f"{title}要点"],
        "turn_ids": turn_ids,
        "start": start,
        "end": end,
    }


class MeetingOverviewMapReduceTests(unittest.TestCase):
    def setUp(self):
        self.turns = [
            turn(1, 0.0, 4.0, "speaker_1", "介绍会议目标。"),
            turn(2, 4.2, 8.0, "speaker_2", "讨论当前情况。"),
            turn(3, 8.5, 12.0, "speaker_1", "进入第二个议题。"),
            turn(4, 12.5, 16.0, "speaker_3", "继续讨论第二个议题。"),
            turn(5, 16.5, 20.0, "speaker_1", "会议收尾。"),
        ]

    def test_map_materializes_turns_and_sorts_chapters(self):
        window = {"window_id": 1, "start": 0.0, "end": 16.0}
        raw = {
            "chapters": [
                {
                    "title": "第二部分",
                    "summary": "第二部分摘要",
                    "key_points": ["要点二"],
                    "turn_ids": [4, 3],
                },
                {
                    "title": "第一部分",
                    "summary": "第一部分摘要",
                    "key_points": ["要点一"],
                    "turn_ids": [1, 2],
                },
            ],
            "warnings": [],
        }
        materialized, errors = overview.materialize_map_output(
            raw, window, self.turns[:4]
        )
        self.assertEqual(errors, [])
        self.assertEqual(
            [item["title"] for item in materialized["chapters"]],
            ["第一部分", "第二部分"],
        )
        self.assertEqual(materialized["chapters"][1]["turn_ids"], [3, 4])
        self.assertEqual(materialized["chapters"][1]["start"], 8.5)
        self.assertEqual(materialized["chapters"][1]["end"], 16.0)

    def test_map_normalizes_turn_labels_and_rejects_unknown_turn(self):
        window = {"window_id": 1, "start": 0.0, "end": 8.0}
        valid = {
            "chapters": [{
                "title": "开场",
                "summary": "摘要",
                "key_points": [],
                "turn_ids": ["turn 0001", "２"],
            }],
            "warnings": [],
        }
        materialized, errors = overview.materialize_map_output(
            valid, window, self.turns[:2]
        )
        self.assertEqual(errors, [])
        self.assertEqual(materialized["chapters"][0]["turn_ids"], [1, 2])

        invalid = json.loads(json.dumps(valid, ensure_ascii=False))
        invalid["chapters"][0]["turn_ids"] = [1, 99]
        errors = overview.validate_map_model_output(invalid, window, self.turns[:2])
        self.assertTrue(any("unknown turn 99" in error for error in errors))

    def test_single_turn_window_repairs_empty_or_placeholder_reference(self):
        window = {"window_id": 8, "start": 0.0, "end": 4.0}
        for reference in ([], [None], ["一个整数"]):
            with self.subTest(reference=reference):
                raw = {
                    "chapters": [{
                        "title": "单一章节",
                        "summary": "摘要",
                        "key_points": [],
                        "turn_ids": reference,
                    }],
                    "warnings": [],
                }
                materialized, errors = overview.materialize_map_output(
                    raw, window, self.turns[:1]
                )
                self.assertEqual(errors, [])
                self.assertEqual(materialized["chapters"][0]["turn_ids"], [1])

    def test_map_rejects_turn_reused_by_two_chapters(self):
        window = {"window_id": 1, "start": 0.0, "end": 12.0}
        raw = {
            "chapters": [
                {"title": "一", "summary": "", "key_points": [], "turn_ids": [1, 2]},
                {"title": "二", "summary": "", "key_points": [], "turn_ids": [2, 3]},
            ],
            "warnings": [],
        }
        errors = overview.validate_map_model_output(raw, window, self.turns[:3])
        self.assertTrue(any("reuses turn 2" in error for error in errors))

    def test_reduce_sources_hide_turn_ids(self):
        values = [
            map_value(1, [chapter("开场", [1, 2], 0.0, 8.0)]),
            map_value(2, [chapter("议题", [3, 4], 8.5, 16.0)]),
        ]
        prompt_values, lookup, source_ids, warnings = overview.build_reduce_sources(values, self.turns)
        prompt_chapter = prompt_values[0]["chapters"][0]
        self.assertNotIn("turn_ids", prompt_chapter)
        self.assertEqual(prompt_chapter["source_id"], source_ids[0])
        self.assertEqual(lookup[source_ids[0]]["turn_ids"], [1, 2])
        self.assertEqual(warnings, [])

    def test_reduce_materializes_and_sorts_reverse_model_output(self):
        values = [
            map_value(1, [chapter("开场", [1, 2], 0.0, 8.0)]),
            map_value(2, [chapter("议题", [3, 4], 8.5, 16.0)]),
        ]
        _, lookup, source_ids, warnings = overview.build_reduce_sources(values, self.turns)
        raw = {
            "meeting_title": "测试会议",
            "overall_topic": "流程测试",
            "executive_summary": "会议依次讨论两个阶段。",
            "chapters": [
                {
                    "title": "议题",
                    "summary": "第二阶段",
                    "key_points": [],
                    "source_ids": [source_ids[1]],
                },
                {
                    "title": "开场",
                    "summary": "第一阶段",
                    "key_points": [],
                    "source_ids": [source_ids[0]],
                },
            ],
            "warnings": [],
        }
        self.assertEqual(
            overview.validate_reduce_model_output(
                raw, lookup, source_ids, warnings, self.turns
            ),
            [],
        )
        materialized, errors = overview.materialize_reduce_output(
            raw, lookup, source_ids, warnings, self.turns
        )
        self.assertEqual(errors, [])
        self.assertEqual(
            [item["title"] for item in materialized["chapters"]],
            ["开场", "议题"],
        )
        self.assertEqual(materialized["chapters"][0]["turn_ids"], [1, 2])
        self.assertEqual(materialized["chapters"][1]["start"], 8.5)

    def test_reduce_rejects_unknown_duplicate_missing_and_noncontiguous_sources(self):
        values = [
            map_value(1, [chapter("一", [1], 0.0, 4.0)]),
            map_value(2, [chapter("二", [2], 4.2, 8.0)]),
            map_value(3, [chapter("三", [3], 8.5, 12.0)]),
        ]
        _, lookup, source_ids, warnings = overview.build_reduce_sources(values, self.turns)
        base = {
            "meeting_title": "测试",
            "overall_topic": "测试",
            "executive_summary": "测试",
            "warnings": [],
        }

        unknown = {
            **base,
            "chapters": [{
                "title": "错误",
                "summary": "",
                "key_points": [],
                "source_ids": ["v9-chapter-9"],
            }],
        }
        errors = overview.validate_reduce_contract(unknown, lookup, source_ids, warnings)
        self.assertTrue(any("unknown source" in error for error in errors))
        self.assertTrue(any("missing source_ids" in error for error in errors))

        duplicate = {
            **base,
            "chapters": [
                {
                    "title": "一",
                    "summary": "",
                    "key_points": [],
                    "source_ids": [source_ids[0], source_ids[0]],
                },
                {
                    "title": "其余",
                    "summary": "",
                    "key_points": [],
                    "source_ids": source_ids[1:],
                },
            ],
        }
        errors = overview.validate_reduce_contract(duplicate, lookup, source_ids, warnings)
        self.assertTrue(any("duplicates source" in error for error in errors))

        noncontiguous = {
            **base,
            "chapters": [
                {
                    "title": "不连续",
                    "summary": "",
                    "key_points": [],
                    "source_ids": [source_ids[0], source_ids[2]],
                },
                {
                    "title": "中间",
                    "summary": "",
                    "key_points": [],
                    "source_ids": [source_ids[1]],
                },
            ],
        }
        errors = overview.validate_reduce_contract(
            noncontiguous, lookup, source_ids, warnings
        )
        self.assertTrue(any("contiguous source range" in error for error in errors))

    def test_overlapping_map_windows_assign_shared_turn_to_earlier_source(self):
        values = [
            map_value(1, [chapter("一", [1, 2], 0.0, 8.0)]),
            map_value(2, [chapter("二", [2, 3], 4.2, 12.0)]),
        ]
        _, lookup, source_ids, warnings = overview.build_reduce_sources(
            values, self.turns
        )
        self.assertEqual(lookup[source_ids[0]]["turn_ids"], [1, 2])
        self.assertEqual(lookup[source_ids[1]]["turn_ids"], [3])
        raw = {
            "meeting_title": "测试",
            "overall_topic": "测试",
            "executive_summary": "测试",
            "chapters": [
                {"title": "一", "summary": "", "key_points": [], "source_ids": [source_ids[0]]},
                {"title": "二", "summary": "", "key_points": [], "source_ids": [source_ids[1]]},
            ],
            "warnings": [],
        }
        self.assertEqual(
            overview.validate_reduce_model_output(
                raw, lookup, source_ids, warnings, self.turns
            ),
            [],
        )

    def test_warnings_are_preserved_even_when_model_omits_them(self):
        values = [
            map_value(
                1,
                [chapter("开场", [1], 0.0, 4.0)],
                warnings=["低质量转写", "低质量转写"],
            ),
            map_value(2, [chapter("议题", [2], 4.2, 8.0)], warnings=["缺失窗口"]),
        ]
        _, lookup, source_ids, warnings = overview.build_reduce_sources(values, self.turns)
        raw = {
            "meeting_title": "测试",
            "overall_topic": "测试",
            "executive_summary": "测试",
            "chapters": [{
                "title": "全部",
                "summary": "",
                "key_points": [],
                "source_ids": source_ids,
            }],
            "warnings": ["模型新增但不会进入正式结果的警告"],
        }
        self.assertEqual(
            overview.validate_reduce_model_output(
                raw, lookup, source_ids, warnings, self.turns
            ),
            [],
        )
        materialized, errors = overview.materialize_reduce_output(
            raw, lookup, source_ids, warnings, self.turns
        )
        self.assertEqual(errors, [])
        self.assertEqual(materialized["warnings"], ["低质量转写", "缺失窗口"])

    def test_previous_level_overview_normalizes_for_hierarchical_reduce(self):
        value = {
            "schema_version": "meeting_overview_v0",
            "meeting_title": "测试",
            "overall_topic": "测试",
            "executive_summary": "测试",
            "chapters": [chapter("议题", [2, 3], 4.2, 12.0)],
            "warnings": [],
            "_source_time_range": {"start": 0.0, "end": 16.0},
        }
        normalized = overview.normalize_reduce_inputs([value])
        self.assertEqual(normalized[0]["schema_version"], "meeting_overview_map_v0")
        self.assertEqual(normalized[0]["time_range"], {"start": 0.0, "end": 16.0})
        self.assertNotIn("meeting_title", normalized[0])

    def test_failed_placeholder_is_partial_signal(self):
        value = overview.placeholder_for_failed_window(
            {"window_id": 1, "start": 0.0, "end": 3.0}, "bad JSON"
        )
        self.assertTrue(overview.is_failed_map_placeholder(value))
        value["chapters"] = [chapter("有效", [1], 0.0, 3.0)]
        self.assertFalse(overview.is_failed_map_placeholder(value))

    def test_markdown_renderer_keeps_chronology_and_trace(self):
        value = {
            "schema_version": "meeting_overview_v0",
            "meeting_title": "测试会议",
            "overall_topic": "章节流程",
            "executive_summary": "依次讨论两个阶段。",
            "chapters": [
                chapter("开场", [1, 2], 0.0, 8.0),
                chapter("议题", [3, 4], 8.5, 16.0),
            ],
            "warnings": ["低质量转写"],
        }
        markdown = overview.render_overview_markdown(value)
        self.assertIn("# 测试会议", markdown)
        self.assertIn("`00:00:00.000` - `00:00:08.000`", markdown)
        self.assertIn("证据 Turn：1, 2", markdown)
        self.assertLess(markdown.index("### 1. 开场"), markdown.index("### 2. 议题"))
        self.assertIn("## 警告", markdown)

    def test_schema_files_parse(self):
        for name in (
            "meeting_overview_map_v0.schema.json",
            "meeting_overview_v0.schema.json",
        ):
            data = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual(data["type"], "object")

    def test_plan_only_writes_traceable_artifacts(self):
        fixture = ROOT / "tests" / "fixtures" / "meeting_turns_v0.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code = overview.main([
                "--turns-file", str(fixture),
                "--out-dir", temp_dir,
                "--plan-only",
                "--no-resume",
            ])
            result = json.loads((Path(temp_dir) / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(result["status"], "planned")
            for name in (
                "source_turns.json",
                "window_plan.json",
                "input_snapshot.json",
                "canonical_transcript.txt",
            ):
                self.assertTrue((Path(temp_dir) / name).is_file(), name)

    def test_infrastructure_payload_disables_thinking(self):
        class Args:
            model_name = "default"
            temperature = 0.0
            response_format_json_object = True
            host = "127.0.0.1"
            port = 1
            request_timeout = 1

        original = overview.infra.urllib.request.urlopen

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}]}'

        overview.infra.urllib.request.urlopen = lambda *_args, **_kwargs: Response()
        try:
            payload, _ = overview.infra.post_chat(Args(), "prompt", 32)
        finally:
            overview.infra.urllib.request.urlopen = original
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})


if __name__ == "__main__":
    unittest.main()

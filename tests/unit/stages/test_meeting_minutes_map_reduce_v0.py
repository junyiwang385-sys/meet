import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "meeting_agent"
    / "adapters"
    / "board"
    / "minutes"
    / "meeting_minutes_map_reduce_v0.py"
)
SPEC = importlib.util.spec_from_file_location("meeting_minutes_map_reduce_v0", MODULE_PATH)
assert SPEC and SPEC.loader
minutes = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = minutes
SPEC.loader.exec_module(minutes)


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


class MeetingMinutesMapReduceTests(unittest.TestCase):
    def setUp(self):
        self.turns = [
            turn(1, 0.0, 4.0, "speaker_1", "讨论安全检查。需要确认通道畅通。"),
            turn(2, 4.2, 8.0, "speaker_2", "决定明天复查，负责人暂未明确。"),
            turn(3, 8.5, 12.0, "speaker_1", "高处作业存在坠落风险。"),
        ]

    def test_load_turns_accepts_array_and_sorts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "turns.json"
            path.write_text(json.dumps(list(reversed(self.turns)), ensure_ascii=False), encoding="utf-8")
            loaded = minutes.load_turns(path)
        self.assertEqual([item["id"] for item in loaded], [1, 2, 3])

    def test_window_plan_preserves_all_turns(self):
        plan = minutes.build_window_plan(
            self.turns, target_chars=75, max_turns=2, overlap_turns=0
        )
        active = [item for item in plan["windows"] if item["active"]]
        covered = [turn_id for item in active for turn_id in item["turn_ids"]]
        self.assertEqual(sorted(set(covered)), [1, 2, 3])
        self.assertGreaterEqual(len(active), 2)
        self.assertIn("[turn 0001]", plan["windows"][0]["transcript"])

    def test_overlap_is_exactly_one_source_turn(self):
        plan = minutes.build_window_plan(
            self.turns, target_chars=1000, max_turns=2, overlap_turns=1
        )
        windows = [item for item in plan["windows"] if item["active"]]
        self.assertGreaterEqual(len(windows), 2)
        for left, right in zip(windows, windows[1:]):
            overlap = set(left["turn_ids"]) & set(right["turn_ids"])
            self.assertEqual(len(overlap), 1)

    def test_oversized_turn_is_split(self):
        long_turn = turn(1, 0.0, 10.0, "speaker_1", "第一句。" * 80)
        units = minutes.prepare_units([long_turn], target_chars=50)
        self.assertGreater(len(units), 1)
        self.assertTrue(all(item["source_turn_id"] == 1 for item in units))
        self.assertAlmostEqual(units[0]["start"], 0.0)
        self.assertAlmostEqual(units[-1]["end"], 10.0)

    def test_map_model_output_materializes_turn_ids(self):
        window = {"window_id": 1, "start": 0.0, "end": 8.0}
        value = {
            "participants": [{
                "speaker": "speaker_1",
                "summary": "讨论安全检查",
                "turn_ids": [1],
            }],
            "topics": [],
            "decisions": [],
            "action_items": [],
            "risks": [],
            "open_questions": [],
            "warnings": [],
        }
        self.assertEqual(minutes.validate_map_model_output(value, window, self.turns[:2]), [])
        materialized, errors = minutes.materialize_map_output(value, window, self.turns[:2])
        self.assertEqual(errors, [])
        self.assertEqual(
            materialized["participants"][0]["evidence"],
            [{"speaker": "speaker_1", "start": 0.0, "end": 4.0}],
        )
        self.assertNotIn("turn_ids", materialized["participants"][0])

    def test_map_model_output_normalizes_turn_labels(self):
        value = {
            "participants": [{
                "speaker": "speaker_1",
                "summary": "摘要",
                "turn_ids": ["turn 0001", "[turn 2]", "３"],
            }],
            "topics": [], "decisions": [], "action_items": [],
            "risks": [], "open_questions": [], "warnings": [],
        }
        normalized = minutes.normalize_model_output(value)
        self.assertEqual(normalized["participants"][0]["turn_ids"], [1, 2, 3])

    def test_map_model_output_rejects_unknown_turn(self):
        window = {"window_id": 1, "start": 0.0, "end": 8.0}
        value = {
            "participants": [],
            "topics": [],
            "decisions": [{"decision": "已批准", "turn_ids": [99]}],
            "action_items": [],
            "risks": [],
            "open_questions": [],
            "warnings": [],
        }
        errors = minutes.validate_map_model_output(value, window, self.turns[:2])
        self.assertTrue(any("unknown turn" in error for error in errors))

    def test_minutes_validator_requires_null_for_unknown_owner(self):
        value = {
            "schema_version": "meeting_minutes_v0",
            "meeting_title": "安全会",
            "meeting_type": "discussion",
            "executive_summary": "讨论安全检查。",
            "participants": [],
            "topics": [],
            "decisions": [],
            "action_items": [{
                "task": "复查通道",
                "owner": "未明确",
                "due": None,
                "evidence": [{"speaker": "speaker_2", "start": 4.2, "end": 8.0}],
            }],
            "risks": [],
            "open_questions": [],
            "warnings": [],
        }
        errors = minutes.validate_minutes_output(value, self.turns)
        self.assertTrue(any("must be null" in error for error in errors))

    def test_reduce_materializes_source_ids(self):
        map_value = {
            "schema_version": "meeting_minutes_map_v0",
            "window_id": 1,
            "time_range": {"start": 0.0, "end": 4.0},
            "participants": [{
                "speaker": "speaker_1",
                "summary": "讨论安全检查",
                "evidence": [{"speaker": "speaker_1", "start": 0.0, "end": 4.0}],
            }],
            "topics": [], "decisions": [], "action_items": [],
            "risks": [], "open_questions": [], "warnings": [],
        }
        prompt_values, sources = minutes.build_reduce_sources([map_value])
        source_id = prompt_values[0]["participants"][0]["source_id"]
        model_value = {
            "meeting_title": "安全会",
            "meeting_type": "discussion",
            "executive_summary": "讨论安全检查。",
            "participants": [{
                "speaker": "speaker_1",
                "summary": "讨论安全检查",
                "source_ids": [source_id],
            }],
            "topics": [], "decisions": [], "action_items": [],
            "risks": [], "open_questions": [], "warnings": [],
        }
        self.assertEqual(
            minutes.validate_reduce_model_output(model_value, sources, self.turns), []
        )
        materialized, errors = minutes.materialize_reduce_output(model_value, sources)
        self.assertEqual(errors, [])
        self.assertEqual(
            materialized["participants"][0]["evidence"],
            [{"speaker": "speaker_1", "start": 0.0, "end": 4.0}],
        )

    def test_reduce_normalizes_previous_level_minutes(self):
        value = {
            "schema_version": "meeting_minutes_v0",
            "meeting_title": "安全会",
            "meeting_type": "discussion",
            "executive_summary": "摘要",
            "participants": [],
            "topics": [],
            "decisions": [],
            "action_items": [],
            "risks": [],
            "open_questions": [],
            "warnings": [],
        }
        normalized = minutes.normalize_reduce_inputs([value])
        self.assertEqual(normalized[0]["schema_version"], "meeting_minutes_map_v0")
        self.assertEqual(normalized[0]["time_range"], {"start": 0.0, "end": 0.0})
        self.assertNotIn("meeting_title", normalized[0])

        value["_source_time_range"] = {"start": 2.0, "end": 9.0}
        normalized = minutes.normalize_reduce_inputs([value])
        self.assertEqual(normalized[0]["time_range"], {"start": 2.0, "end": 9.0})

    def test_json_syntax_normalizes_fullwidth_values_only(self):
        raw = '{"window_id":１,"time_range":{"start":１０．７２,"end":２０．５},"text":"保留全角０"}'
        value, _ = minutes.parse_json_content(raw)
        self.assertEqual(value["window_id"], 1)
        self.assertEqual(value["time_range"]["start"], 10.72)
        self.assertEqual(value["text"], "保留全角０")

    def test_model_output_normalizes_fullwidth_schema_and_warning_objects(self):
        value = minutes.normalize_model_output({
            "schema_version": "meeting_minutes_v０",
            "warnings": [{"text": "窗口重叠"}, "低质量转写"],
        })
        self.assertEqual(value["schema_version"], "meeting_minutes_v0")
        self.assertEqual(value["warnings"], ["窗口重叠", "低质量转写"])

    def test_json_extraction(self):
        value, extracted = minutes.parse_json_content('说明文字\n{"ok": true}\n结束')
        self.assertEqual(value, {"ok": True})
        self.assertTrue(extracted)

    def test_json_extraction_strips_empty_qwen3_thinking_block(self):
        value, extracted = minutes.parse_json_content(
            '<think>\n\n</think>\n\n{"ok": true}'
        )
        self.assertEqual(value, {"ok": True})
        self.assertFalse(extracted)

    def test_prompt_budget_can_split_window(self):
        plan = minutes.build_window_plan(
            self.turns, target_chars=1000, max_turns=10, overlap_turns=0
        )
        original = plan["windows"][0]
        children = minutes.split_window(plan, original)
        self.assertFalse(original["active"])
        self.assertEqual(len(children), 2)
        covered = [turn_id for child in children for turn_id in child["turn_ids"]]
        self.assertEqual(sorted(set(covered)), [1, 2, 3])

    def test_resume_only_skips_successful_map_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "map_results.jsonl"
            path.write_text(
                json.dumps({"window_id": 1, "status": "ok", "output": {"ok": True}}) + "\n"
                + json.dumps({"window_id": 2, "status": "failed", "output": {"warning": True}}) + "\n",
                encoding="utf-8",
            )
            latest = minutes.latest_map_records(path)
        self.assertEqual(latest[1]["status"], "ok")
        self.assertEqual(latest[2]["status"], "failed")

    def test_empty_server_response_has_distinct_error(self):
        class Args:
            host = "127.0.0.1"
            port = 1
            model_name = "default"
            temperature = 0.0
            response_format_json_object = False
            request_timeout = 1

        original = minutes.urllib.request.urlopen

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b""

        minutes.urllib.request.urlopen = lambda *_args, **_kwargs: Response()
        try:
            with self.assertRaises(minutes.EmptyServerResponse):
                minutes.post_chat(Args(), "prompt", 32)
        finally:
            minutes.urllib.request.urlopen = original

    def test_preflight_prompt_budget_stops_before_http(self):
        class DummyMonitor:
            def set_context(self, **_values):
                pass

            def record_anchor(self, *_args, **_values):
                return {}

        args = type("Args", (), {
            "max_retries": 0,
            "chars_to_tokens_ratio": 1.0,
            "max_prompt_tokens": 10,
            "idle_seconds": 0.0,
        })()
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(minutes.PromptBudgetExceeded):
                minutes.call_model(
                    args,
                    "x" * 20,
                    10,
                    Path(temp_dir),
                    {"phase": "map"},
                    lambda _value: [],
                    DummyMonitor(),
                )

    def test_complete_json_at_token_limit_is_accepted(self):
        class DummyMonitor:
            def set_context(self, **_values):
                pass

            def record_anchor(self, *_args, **_values):
                return {}

        args = type("Args", (), {
            "max_retries": 0,
            "chars_to_tokens_ratio": 1.0,
            "max_prompt_tokens": 100,
            "idle_seconds": 0.0,
        })()
        original = minutes.post_chat
        minutes.post_chat = lambda *_args, **_kwargs: ({"request": True}, {
            "choices": [{
                "finish_reason": "length",
                "message": {"content": '{"ok": true}'},
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        })
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                value, metadata = minutes.call_model(
                    args,
                    "prompt",
                    2,
                    Path(temp_dir),
                    {"phase": "test"},
                    lambda result: [] if result.get("ok") is True else ["bad"],
                    DummyMonitor(),
                )
            self.assertTrue(value["ok"])
            self.assertTrue(metadata["complete_json_at_limit"])
        finally:
            minutes.post_chat = original

    def test_failed_map_placeholder_is_not_a_pass(self):
        value = minutes.placeholder_for_failed_window(
            {"window_id": 1, "start": 0.0, "end": 3.0}, "bad JSON"
        )
        self.assertTrue(minutes.is_failed_map_placeholder(value))
        value["topics"] = [{"name": "有效主题"}]
        self.assertFalse(minutes.is_failed_map_placeholder(value))

    def test_memory_leak_assessment(self):
        stable = [
            {"kind": "post_idle", "mem_available_kb": 7000000 - i * 1000,
             "cached_kb": 1000000 + i * 900, "server_rss_kb": 200000,
             "cma_free_kb": 32000}
            for i in range(6)
        ]
        self.assertFalse(minutes.assess_memory_leak(stable, 128)["memory_leak_suspected"])

        leaking = [
            {"kind": "post_idle", "mem_available_kb": 7000000 - i * 80000,
             "cached_kb": 1000000, "server_rss_kb": 200000 + i * 50000,
             "cma_free_kb": 32000 - i * 2000}
            for i in range(6)
        ]
        self.assertTrue(minutes.assess_memory_leak(leaking, 128)["memory_leak_suspected"])

    def test_schema_files_parse(self):
        root = Path(__file__).resolve().parents[3]
        for name in (
            "meeting_transcript_turns_v0.schema.json",
            "meeting_minutes_map_v0.schema.json",
            "meeting_minutes_v0.schema.json",
        ):
            data = json.loads((root / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual(data["type"], "array" if name.startswith("meeting_transcript") else "object")


if __name__ == "__main__":
    unittest.main()

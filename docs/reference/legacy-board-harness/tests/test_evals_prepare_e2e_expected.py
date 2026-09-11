from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from evals.prepare_e2e_expected import (
    build_e2e_manifest,
    build_expected_prompt,
    discover_cases,
    validate_expected,
)
from evals.textgrid import parse_textgrid

TEXTGRID = """File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 3
 tiers? <exists>
 size = 2
 item []:
    item [1]:
        class = "IntervalTier"
        name = "speaker_a"
        xmin = 0
        xmax = 3
        intervals: size = 2
        intervals [1]:
            xmin = 0
            xmax = 1
            text = "介绍需求"
        intervals [2]:
            xmin = 2
            xmax = 3
            text = "确认明天提交"
    item [2]:
        class = "IntervalTier"
        name = "speaker_b"
        xmin = 0
        xmax = 3
        intervals: size = 1
        intervals [1]:
            xmin = 1
            xmax = 2
            text = "讨论方案"
"""


class PrepareE2EExpectedTests(unittest.TestCase):
    def _dataset(self, root: pathlib.Path):
        for split in ("test", "train_L", "train_S"):
            (root / split / "wav").mkdir(parents=True)
            (root / split / "TextGrid").mkdir(parents=True)
            stem = f"meeting_{split}"
            (root / split / "wav" / f"{stem}.flac").write_bytes(b"audio")
            (root / split / "TextGrid" / f"{stem}.TextGrid").write_text(
                TEXTGRID, encoding="utf-8"
            )
            (root / split / "TextGrid" / f"{stem}.rttm").write_text(
                "SPEAKER sample 1 0 1 <NA> <NA> speaker_a <NA> <NA>\n",
                encoding="utf-8",
            )

    def test_discover_and_build_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            self._dataset(root)
            output = root / "e2e_expected"
            cases = discover_cases(root, output, ["test", "train_L", "train_S"])
            self.assertEqual(len(cases), 3)
            self.assertEqual(cases[0].case_id, "test_meeting_test")
            self.assertIsNotNone(cases[0].rttm_path)
            manifest_path = root / "e2e_manifest.json"
            manifest = build_e2e_manifest(
                cases,
                dataset_root=root,
                manifest_path=manifest_path,
                model="claude-opus-5",
            )
            self.assertEqual(manifest["dataset_root"], ".")
            self.assertEqual(len(manifest["cases"]), 3)
            self.assertEqual(
                manifest["cases"][0]["reference_timeline_file"],
                "test/TextGrid/meeting_test.TextGrid",
            )
            self.assertEqual(
                manifest["cases"][0]["expected_source"],
                "llm_assisted_from_official_textgrid",
            )

    def test_validate_four_field_expected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "sample.TextGrid"
            path.write_text(TEXTGRID, encoding="utf-8")
            segments, _ = parse_textgrid(path)
            expected = {
                "overview": {
                    "text": "会议介绍需求、讨论方案，并确认明天提交。",
                    "refs": ["seg-000001", "seg-000002", "seg-000003"],
                },
                "chapters": [
                    {
                        "title": "需求与方案",
                        "overview": "先介绍需求并讨论方案。",
                        "start_ref": "seg-000001",
                        "end_ref": "seg-000002",
                        "refs": ["seg-000001", "seg-000002"],
                    },
                    {
                        "title": "提交安排",
                        "overview": "确认明天提交。",
                        "start_ref": "seg-000003",
                        "end_ref": "seg-000003",
                        "refs": ["seg-000003"],
                    },
                ],
                "speakers": [
                    {
                        "speaker_id": "speaker_a",
                        "overview": "介绍需求并确认明天提交。",
                        "refs": ["seg-000001", "seg-000003"],
                    },
                    {
                        "speaker_id": "speaker_b",
                        "overview": "讨论方案。",
                        "refs": ["seg-000002"],
                    },
                ],
                "action_items": [
                    {
                        "task": "明天提交。",
                        "owner": None,
                        "deadline": "明天",
                        "refs": ["seg-000003"],
                    }
                ],
            }
            normalized = validate_expected(expected, segments)
            self.assertEqual(normalized, expected)

    def test_validates_explicit_core_facts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "sample.TextGrid"
            path.write_text(TEXTGRID, encoding="utf-8")
            segments, _ = parse_textgrid(path)
            expected = {
                "overview": {"text": "会议讨论需求并确认提交。", "refs": ["seg-000001"]},
                "chapters": [
                    {
                        "title": "会议内容",
                        "overview": "讨论需求、方案和提交安排。",
                        "start_ref": "seg-000001",
                        "end_ref": "seg-000003",
                        "refs": ["seg-000001", "seg-000003"],
                    }
                ],
                "speakers": [
                    {"speaker_id": "speaker_a", "overview": "介绍需求并确认提交。", "refs": ["seg-000001", "seg-000003"]},
                    {"speaker_id": "speaker_b", "overview": "讨论方案。", "refs": ["seg-000002"]},
                ],
                "action_items": [],
                "core_facts": [
                    {"text": "会议讨论了需求和方案。", "importance": "major", "refs": ["seg-000001", "seg-000002"]},
                    {"text": "会议确认明天提交。", "importance": "critical", "refs": ["seg-000003"]},
                ],
            }

            normalized = validate_expected(expected, segments, require_core_facts=True)

            self.assertEqual(normalized["core_facts"], expected["core_facts"])

    def test_rejects_invalid_or_duplicate_core_facts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "sample.TextGrid"
            path.write_text(TEXTGRID, encoding="utf-8")
            segments, _ = parse_textgrid(path)
            base = {
                "overview": {"text": "概述", "refs": ["seg-000001"]},
                "chapters": [
                    {
                        "title": "会议",
                        "overview": "会议内容。",
                        "start_ref": "seg-000001",
                        "end_ref": "seg-000003",
                        "refs": ["seg-000001"],
                    }
                ],
                "speakers": [
                    {"speaker_id": "speaker_a", "overview": "发言。", "refs": ["seg-000001"]},
                    {"speaker_id": "speaker_b", "overview": "发言。", "refs": ["seg-000002"]},
                ],
                "action_items": [],
            }
            with self.assertRaisesRegex(ValueError, "core_facts"):
                validate_expected(base, segments, require_core_facts=True)

            duplicate = {
                **base,
                "core_facts": [
                    {"text": "确认提交", "importance": "major", "refs": ["seg-000003"]},
                    {"text": "确认提交", "importance": "critical", "refs": ["seg-000003"]},
                ],
            }
            with self.assertRaisesRegex(ValueError, "duplicate core fact"):
                validate_expected(duplicate, segments, require_core_facts=True)

            invalid_importance = {
                **base,
                "core_facts": [
                    {"text": "确认提交", "importance": "minor", "refs": ["seg-000003"]}
                ],
            }
            with self.assertRaisesRegex(ValueError, "importance"):
                validate_expected(invalid_importance, segments, require_core_facts=True)

    def test_repairs_mechanical_reference_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            self._dataset(root)
            case = discover_cases(root, root / "expected", ["test"])[0]
            segments, _ = parse_textgrid(case.textgrid_path)
            prompt = build_expected_prompt(case, segments)
            self.assertIn("唯一来源", prompt)
            self.assertIn("core_facts", prompt)
            self.assertIn("原子", prompt)
            self.assertIn("test_meeting_test", prompt)
            raw = {
                "overview": {"text": "概述", "refs": ["seg-00001"]},
                "chapters": [
                    {
                        "title": "",
                        "overview": "覆盖整场会议。",
                        "start_ref": "seg-000002",
                        "end_ref": "seg-00003",
                        "refs": ["seg-000002", "seg-999999"],
                    }
                ],
                "speakers": [
                    {
                        "speaker_id": "speaker_a",
                        "overview": "介绍需求并确认提交。",
                        "refs": ["seg-000002"],
                    },
                    {
                        "speaker_id": "speaker_b",
                        "overview": "讨论方案。",
                        "refs": ["seg-00002"],
                    },
                ],
                "action_items": [
                    {
                        "task": "",
                        "owner": None,
                        "deadline": None,
                        "refs": ["seg-000003"],
                    }
                ],
            }
            normalized = validate_expected(raw, segments)
            self.assertEqual(normalized["overview"]["refs"], ["seg-000001"])
            self.assertEqual(normalized["chapters"][0]["title"], "章节 1")
            self.assertEqual(normalized["chapters"][0]["start_ref"], "seg-000001")
            self.assertEqual(normalized["chapters"][0]["end_ref"], "seg-000003")
            self.assertEqual(
                normalized["speakers"][0]["refs"],
                ["seg-000001", "seg-000003"],
            )
            self.assertEqual(normalized["action_items"], [])

    def test_manifest_is_json_serializable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            self._dataset(root)
            cases = discover_cases(root, root / "expected", ["test"])
            manifest = build_e2e_manifest(
                cases,
                dataset_root=root,
                manifest_path=root / "manifest.json",
                model="claude-opus-5",
            )
            self.assertIsInstance(json.dumps(manifest), str)


if __name__ == "__main__":
    unittest.main()

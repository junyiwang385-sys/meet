import json
import unittest

from meeting_agent.stages.product_summary import (
    MIN_BLOCK_SUMMARY_CHARS,
    _block_summary_messages,
    _build_compact_ref_map,
    _build_compact_speaker_map,
    _reduce_blocks_to_chapters,
    _validate_block_summary,
)
from meeting_agent.stages.validation import (
    SummaryValidationError,
    validate_summary_object,
)


def _seg(index, start_ms, end_ms, speaker, text):
    return {
        "segment_id": f"seg-{index:06d}",
        "index": index,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "speaker_id": speaker,
        "text": text,
    }


LONG = (
    "关于采购预算的季度拆分我们已经对齐了整体执行口径和责任划分并明确了"
    "后续跟进节奏与验收标准以及风险应对方式确保按时按质落地不出偏差同时"
    "预留了应急调整空间以应对需求变化和外部不确定因素"
)


class BlockSummaryValidationTests(unittest.TestCase):
    def setUp(self):
        self.segments = [
            _seg(0, 0, 3000, "speaker_1", "先说采购预算的季度拆分安排。"),
            _seg(1, 3100, 6000, "speaker_2", "我补充一下验收标准和风险应对。"),
        ]
        self.ref_map, _ = _build_compact_ref_map(self.segments)
        self.speaker_map, _ = _build_compact_speaker_map(
            [s["speaker_id"] for s in self.segments]
        )

    def _content(self, **overrides):
        payload = {
            "title": "采购预算季度拆分",
            "summary": LONG,
            "continues_previous": False,
            "key_refs": ["r1"],
            "action_candidates": [],
        }
        payload.update(overrides)
        return json.dumps(payload, ensure_ascii=False)

    def test_happy_path_normalizes_and_grounds_refs(self):
        result = _validate_block_summary(
            self._content(),
            "stop",
            False,
            self.segments,
            ref_map=self.ref_map,
            speaker_map=self.speaker_map,
        )
        self.assertEqual(result["title"], "采购预算季度拆分")
        self.assertGreaterEqual(len(result["summary"]), MIN_BLOCK_SUMMARY_CHARS)
        self.assertEqual(result["refs"], ["seg-000001"])
        self.assertEqual(result["start_ref"], "seg-000000")
        self.assertEqual(result["end_ref"], "seg-000001")
        self.assertFalse(result["continues_previous"])

    def test_short_summary_raises_too_short(self):
        with self.assertRaises(SummaryValidationError) as ctx:
            _validate_block_summary(
                self._content(summary="太短了"),
                "stop",
                False,
                self.segments,
                ref_map=self.ref_map,
                speaker_map=self.speaker_map,
            )
        self.assertIn("too short", str(ctx.exception))

    def test_invalid_refs_fall_back_to_block_bounds(self):
        result = _validate_block_summary(
            self._content(key_refs=["r99", "nope"]),
            "stop",
            False,
            self.segments,
            ref_map=self.ref_map,
            speaker_map=self.speaker_map,
        )
        self.assertEqual(result["refs"], ["seg-000000", "seg-000001"])

    def test_finish_reason_and_truncation_guarded(self):
        with self.assertRaises(SummaryValidationError):
            _validate_block_summary(
                self._content(), "length", False, self.segments,
                ref_map=self.ref_map, speaker_map=self.speaker_map,
            )
        with self.assertRaises(SummaryValidationError):
            _validate_block_summary(
                self._content(), "stop", True, self.segments,
                ref_map=self.ref_map, speaker_map=self.speaker_map,
            )

    def test_continues_previous_string_true(self):
        result = _validate_block_summary(
            self._content(continues_previous="yes"),
            "stop", False, self.segments,
            ref_map=self.ref_map, speaker_map=self.speaker_map,
        )
        self.assertTrue(result["continues_previous"])

    def test_action_candidates_grounded(self):
        result = _validate_block_summary(
            self._content(action_candidates=[
                {"task": "下周提交采购清单", "owner": "sp1", "deadline": None, "refs": ["r0"]},
                {"task": "无依据待办", "refs": ["r99"]},
            ]),
            "stop", False, self.segments,
            ref_map=self.ref_map, speaker_map=self.speaker_map,
        )
        self.assertEqual(len(result["action_candidates"]), 1)
        self.assertEqual(result["action_candidates"][0]["refs"], ["seg-000000"])

    def test_messages_structure(self):
        messages = _block_summary_messages(
            self.segments, {"title": "上块", "summary": "上块摘要"},
            ref_map=self.ref_map, speaker_map=self.speaker_map,
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("上一块标题", messages[1]["content"])
        self.assertIn("[r0]", messages[1]["content"])


class ReduceBlocksTests(unittest.TestCase):
    def setUp(self):
        self.segments = [
            _seg(0, 0, 3000, "speaker_1", "采购预算季度拆分。"),
            _seg(1, 3100, 6000, "speaker_1", "验收标准补充。"),
            _seg(2, 6100, 9000, "speaker_2", "换话题说散热噪音。"),
        ]
        self.segment_by_id = {s["segment_id"]: s for s in self.segments}

    def _block(self, block_id, seg_ids, continues, title, summary):
        return {
            "block_id": block_id,
            "segment_ids": seg_ids,
            "title": title,
            "summary": summary,
            "continues_previous": continues,
            "refs": [seg_ids[0], seg_ids[-1]],
            "action_candidates": [],
            "start_ref": seg_ids[0],
            "end_ref": seg_ids[-1],
        }

    def test_continues_previous_merges_into_prior_chapter(self):
        blocks = [
            self._block("blk-000001", ["seg-000000"], False, "预算", "采购预算季度拆分说明。"),
            self._block("blk-000002", ["seg-000001"], True, "预算续", "验收标准补充说明。"),
            self._block("blk-000003", ["seg-000002"], False, "散热", "散热与噪音测试安排。"),
        ]
        chapters, actions = _reduce_blocks_to_chapters(blocks, self.segment_by_id)
        self.assertEqual(len(chapters), 2)
        merged = chapters[0]
        self.assertEqual(merged["start_ref"], "seg-000000")
        self.assertEqual(merged["end_ref"], "seg-000001")
        self.assertIn("；", merged["overview"])
        self.assertEqual(merged["refs"], ["seg-000000", "seg-000001"])
        self.assertEqual(merged["speaker_ids"], ["speaker_1"])
        self.assertEqual(actions, [])

    def test_first_block_continues_flag_ignored(self):
        blocks = [self._block("blk-000001", ["seg-000000"], True, "预算", "采购预算季度拆分说明。")]
        chapters, _ = _reduce_blocks_to_chapters(blocks, self.segment_by_id)
        self.assertEqual(len(chapters), 1)

    def test_merged_chapters_pass_summary_validation(self):
        blocks = [
            self._block("blk-000001", ["seg-000000"], False, "预算", "采购预算季度拆分说明清楚。"),
            self._block("blk-000002", ["seg-000001"], True, "预算续", "验收标准补充说明清楚。"),
            self._block("blk-000003", ["seg-000002"], False, "散热", "散热与噪音测试安排说明。"),
        ]
        chapters, _ = _reduce_blocks_to_chapters(blocks, self.segment_by_id)
        summary = {
            "title": "项目例会", "overview": None, "chapters": chapters,
            "speakers": [], "key_points": [], "decisions": [],
            "action_items": [], "open_questions": [], "risks": [], "keywords": [],
        }
        validated, quality = validate_summary_object(summary, self.segments)
        self.assertEqual(len(validated["chapters"]), 2)
        self.assertEqual(quality["status"], "pass")


if __name__ == "__main__":
    unittest.main()

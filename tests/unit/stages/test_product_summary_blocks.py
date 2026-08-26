import json
import types
import unittest

from meeting_agent.stages.product_summary import (
    MAX_RETRY_ECHO_CHARS,
    MIN_BLOCK_SUMMARY_CHARS,
    _apply_think_directive,
    _block_summary_messages,
    _build_compact_ref_map,
    _build_compact_speaker_map,
    _build_retry_messages,
    _kind_output_tokens,
    _kind_uses_think,
    _overview_from_source_messages,
    _reduce_blocks_to_chapters,
    _validate_block_summary,
)
from meeting_agent.stages.transcript import render_timeline
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


class OverviewFromSourceTests(unittest.TestCase):
    def setUp(self):
        self.segments = [
            _seg(0, 0, 3000, "speaker_1", "采购预算按季度拆分执行。"),
            _seg(1, 3100, 6000, "speaker_2", "散热与风扇噪音测试安排。"),
        ]
        self.ref_map, _ = _build_compact_ref_map(self.segments)
        self.speaker_map, _ = _build_compact_speaker_map(
            [s["speaker_id"] for s in self.segments]
        )
        self.timeline = render_timeline(self.segments)
        self.chapters = [
            {
                "title": "采购预算",
                "overview": "这是章节摘要不应出现在原文档版提示词里的二次压缩内容。",
                "start_ref": "seg-000000",
                "end_ref": "seg-000000",
                "refs": ["seg-000000"],
            }
        ]

    def test_includes_source_timeline_and_skeleton_not_chapter_summary(self):
        messages = _overview_from_source_messages(
            self.timeline, self.chapters,
            ref_map=self.ref_map, speaker_map=self.speaker_map,
        )
        self.assertEqual(len(messages), 2)
        user = messages[1]["content"]
        # 原文事实在场
        self.assertIn("采购预算按季度拆分执行", user)
        self.assertIn("散热与风扇噪音测试", user)
        # 章节提纲（标题）在场
        self.assertIn("章节提纲", user)
        self.assertIn("采购预算", user)
        # 章节摘要（二次压缩）不应泄露
        self.assertNotIn("不应出现在原文档版", user)


class RetryMessagesTests(unittest.TestCase):
    def setUp(self):
        self.base = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "原始任务"},
        ]

    def test_previous_output_is_echoed_as_assistant_turn(self):
        messages, echo = _build_retry_messages(
            self.base, '{"summary":"太短"}', "请写详实些"
        )
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[2]["role"], "assistant")
        self.assertEqual(messages[2]["content"], '{"summary":"太短"}')
        self.assertEqual(messages[3]["role"], "user")
        self.assertEqual(messages[3]["content"], "请写详实些")
        self.assertEqual(echo, '{"summary":"太短"}')

    def test_long_previous_output_is_truncated(self):
        long_output = "字" * (MAX_RETRY_ECHO_CHARS + 500)
        messages, echo = _build_retry_messages(self.base, long_output, "改正")
        self.assertTrue(echo.endswith("…（后续省略）"))
        self.assertEqual(len(echo), MAX_RETRY_ECHO_CHARS + len("…（后续省略）"))
        self.assertEqual(messages[2]["content"], echo)

    def test_none_previous_output_is_safe(self):
        messages, echo = _build_retry_messages(self.base, None, "改正")
        self.assertEqual(echo, "")
        self.assertEqual(messages[2]["content"], "")

    def test_base_messages_not_mutated(self):
        _build_retry_messages(self.base, "x", "c")
        self.assertEqual(len(self.base), 2)


class ThinkAndBudgetTests(unittest.TestCase):
    def _config(self, max_tokens=3072):
        return types.SimpleNamespace(llm=types.SimpleNamespace(max_tokens=max_tokens))

    def test_extraction_kinds_no_think_judgment_kinds_think(self):
        self.assertFalse(_kind_uses_think("block-summary"))
        self.assertFalse(_kind_uses_think("full-summary"))
        self.assertFalse(_kind_uses_think("speaker-batch"))
        self.assertTrue(_kind_uses_think("action-review"))

    def test_kind_output_tokens_capped_by_global(self):
        cfg = self._config(max_tokens=3072)
        self.assertEqual(_kind_output_tokens("block-summary", cfg), 1200)
        self.assertEqual(_kind_output_tokens("action-review", cfg), 3072)
        # 未知 kind 回退到全局
        self.assertEqual(_kind_output_tokens("unknown", cfg), 3072)
        # 全局更小时不得超过全局
        self.assertEqual(_kind_output_tokens("full-summary", self._config(900)), 900)

    def test_no_think_appends_directive_to_last_user_turn(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "任务"},
        ]
        patched = _apply_think_directive(messages, think=False)
        self.assertTrue(patched[1]["content"].endswith("/no_think"))
        # 原对象不被改动
        self.assertEqual(messages[1]["content"], "任务")

    def test_think_true_is_passthrough(self):
        messages = [{"role": "user", "content": "判断题"}]
        self.assertIs(_apply_think_directive(messages, think=True), messages)

    def test_no_think_targets_last_user_not_assistant(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "任务"},
            {"role": "assistant", "content": "上次输出"},
            {"role": "user", "content": "纠正"},
        ]
        patched = _apply_think_directive(messages, think=False)
        self.assertEqual(patched[2]["content"], "上次输出")
        self.assertTrue(patched[3]["content"].endswith("/no_think"))

    def test_no_think_not_duplicated(self):
        messages = [{"role": "user", "content": "任务\n/no_think"}]
        patched = _apply_think_directive(messages, think=False)
        self.assertEqual(patched[0]["content"].count("/no_think"), 1)


if __name__ == "__main__":
    unittest.main()

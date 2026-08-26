import unittest

from meeting_agent.llm.chunking import BudgetPolicy
from meeting_agent.stages.topic_segmentation import (
    SegmentationConfig,
    segment_blocks,
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


class TopicSegmentationTests(unittest.TestCase):
    def setUp(self):
        # 宽裕预算，避免预算兜底干扰纯边界逻辑测试。
        self.policy = BudgetPolicy(ctx=8192, output_tokens=1024, safety_tokens=256)

    def test_empty_input_yields_no_blocks(self):
        result = segment_blocks([], self.policy)
        self.assertEqual(result["blocks"], [])
        self.assertTrue(result["coverage_complete"])

    def test_empty_text_segments_are_skipped(self):
        segments = [
            _seg(0, 0, 2000, "speaker_1", "我们先讨论采购预算的整体安排。"),
            _seg(1, 2000, 2500, "speaker_1", "   "),
        ]
        result = segment_blocks(segments, self.policy)
        self.assertEqual(result["nonempty_segment_count"], 1)
        covered = [sid for block in result["blocks"] for sid in block["segment_ids"]]
        self.assertEqual(covered, ["seg-000000"])

    def test_vad_gap_forces_boundary(self):
        # 同一说话人、话题相近，但中间隔了很长静音 -> 必须断开。
        segments = [
            _seg(0, 0, 3000, "speaker_1", "这个采购预算我们按季度来拆分执行。"),
            _seg(1, 60000, 63000, "speaker_1", "另外关于采购预算的季度拆分再补充一点。"),
        ]
        config = SegmentationConfig(min_block_chars=1)
        result = segment_blocks(segments, self.policy, config)
        self.assertEqual(result["block_count"], 2)
        self.assertIn("gap", result["blocks"][1]["opened_by"])

    def test_speaker_and_topic_change_opens_new_block(self):
        segments = [
            _seg(0, 0, 3000, "speaker_1", "采购预算这块我们按季度拆分执行落实。"),
            _seg(1, 3100, 6000, "speaker_2", "换个话题说说机房散热和风扇噪音测试。"),
        ]
        config = SegmentationConfig(min_block_chars=1, cohesion_min_chars=4)
        result = segment_blocks(segments, self.policy, config)
        self.assertEqual(result["block_count"], 2)
        self.assertTrue(
            {"speaker", "cohesion"} & set(result["blocks"][1]["opened_by"])
        )

    def test_speaker_change_alone_does_not_split_when_topic_continues(self):
        # 说话人变了但话题连续、无 gap -> 单信号 0.5 < 阈值，不应断开。
        shared = "关于采购预算的季度拆分我们继续对齐执行细节。"
        segments = [
            _seg(0, 0, 3000, "speaker_1", shared),
            _seg(1, 3100, 6000, "speaker_2", shared),
        ]
        result = segment_blocks(segments, self.policy, SegmentationConfig(min_block_chars=1))
        self.assertEqual(result["block_count"], 1)

    def test_coverage_is_complete_and_ordered(self):
        segments = [
            _seg(0, 0, 3000, "speaker_1", "采购预算按季度拆分执行。"),
            _seg(1, 60000, 63000, "speaker_1", "机房散热与风扇噪音测试。"),
            _seg(2, 63100, 66000, "speaker_2", "最后确认交付时间与责任人。"),
        ]
        config = SegmentationConfig(min_block_chars=1)
        result = segment_blocks(segments, self.policy, config)
        covered = [sid for block in result["blocks"] for sid in block["segment_ids"]]
        self.assertEqual(covered, ["seg-000000", "seg-000001", "seg-000002"])
        self.assertTrue(result["coverage_complete"])

    def test_over_budget_block_is_force_split(self):
        # 极小预算逼出预算兜底切分。
        policy = BudgetPolicy(ctx=200, output_tokens=40, safety_tokens=0, chars_per_token=1.0, fixed_overhead_tokens=0)
        long_text = "采购预算季度拆分执行细节对齐确认交付时间责任人风险项。" * 3
        segments = [
            _seg(i, i * 4000, i * 4000 + 3000, "speaker_1", long_text)
            for i in range(4)
        ]
        config = SegmentationConfig(min_block_chars=1, max_block_tokens=120, target_block_tokens=120)
        result = segment_blocks(segments, policy, config)
        self.assertGreater(result["block_count"], 1)
        self.assertTrue(result["coverage_complete"])
        self.assertIn("size_split", result["boundary_reason_counts"])

    def test_long_single_topic_splits_by_soft_target(self):
        # 单人、单话题、无长停顿：语义信号都不触发，但块过长应被软目标切开。
        text = "关于采购预算季度拆分执行细节风险应对验收标准的持续对齐说明。"
        segments = [
            _seg(i, i * 3000, i * 3000 + 2900, "speaker_1", text)
            for i in range(20)
        ]
        # 每段约 28 字≈35 token，20 段≈700 token；target 设 200 逼出多块。
        config = SegmentationConfig(min_block_chars=1, target_block_tokens=200)
        result = segment_blocks(segments, self.policy, config)
        self.assertGreater(result["block_count"], 1)
        self.assertTrue(result["coverage_complete"])
        self.assertIn("size_split", result["boundary_reason_counts"])

    def test_deterministic(self):
        segments = [
            _seg(0, 0, 3000, "speaker_1", "采购预算按季度拆分执行落实。"),
            _seg(1, 60000, 63000, "speaker_2", "机房散热与风扇噪音的测试安排。"),
        ]
        first = segment_blocks(segments, self.policy)
        second = segment_blocks(segments, self.policy)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

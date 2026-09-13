import unittest

from meeting_agent.stages.postprocess import (
    PostProcessConfig,
    _lcs_span,
    _rule_candidate,
    build_lexicon,
    correct_proper_nouns,
    dedup_overlaps,
    run_postprocess,
    smooth_for_display,
)


def _seg(index, text, start_ms, end_ms, speaker="speaker_1"):
    return {
        "segment_id": f"seg-{index:06d}",
        "speaker_id": speaker,
        "text": text,
        "start_ms": start_ms,
        "end_ms": end_ms,
    }


class _StubLlm:
    """可注入的 LlmCall：按预设返回，并记录调用次数。"""

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def __call__(self, messages, schema, *, max_tokens):
        self.calls += 1
        return dict(self.reply)


# ---- ① 去重 ----------------------------------------------------------------

class LcsSpanTests(unittest.TestCase):
    def test_longest_common_substring(self):
        length, end_a, end_b = _lcs_span("abcde", "cdefg")
        self.assertEqual((length, end_a, end_b), (3, 5, 3))  # "cde"

    def test_no_common(self):
        self.assertEqual(_lcs_span("abc", "xyz"), (0, 0, 0))


class DedupOverlapsTests(unittest.TestCase):
    def test_removes_boundary_repeat_on_overlap(self):
        segs = [
            _seg(0, "今天我们开会讨论预算", 0, 1000),
            _seg(1, "讨论预算的分配方案", 900, 2000),  # start<prev.end → 重叠
        ]
        stats = dedup_overlaps(segs, PostProcessConfig())
        self.assertEqual(segs[1]["text"], "的分配方案")  # 头部重复"讨论预算"被切
        self.assertEqual(stats["segments_fixed"], 1)
        self.assertEqual(stats["chars_removed"], 4)

    def test_skips_when_no_timestamp_overlap(self):
        segs = [
            _seg(0, "讨论预算问题", 0, 1000),
            _seg(1, "讨论预算问题", 1000, 2000),  # 不重叠（start>=prev.end）
        ]
        stats = dedup_overlaps(segs, PostProcessConfig())
        self.assertEqual(segs[1]["text"], "讨论预算问题")  # 原样保留
        self.assertEqual(stats["segments_fixed"], 0)

    def test_short_overlap_below_min_lcs_not_touched(self):
        # 公共子串仅"讨论"(2字) < _DEDUP_MIN_LCS(3) → 不切
        segs = [
            _seg(0, "今天我们讨论", 0, 1000),
            _seg(1, "讨论完了没有", 900, 2000),
        ]
        dedup_overlaps(segs, PostProcessConfig())
        self.assertEqual(segs[1]["text"], "讨论完了没有")


# ---- ② 专名候选规则 --------------------------------------------------------

class RuleCandidateTests(unittest.TestCase):
    def test_near_same_shengmu(self):
        # 秋衣粉 vs 蚯蚓粉：中间音 yi/yin 声母都是 y → near
        self.assertEqual(_rule_candidate("秋衣粉", "蚯蚓粉"), "near")

    def test_exact_homophone(self):
        # 杨帆 / 扬帆 完全同音 → exact
        self.assertEqual(_rule_candidate("杨帆", "扬帆"), "exact")

    def test_length_mismatch_none(self):
        self.assertIsNone(_rule_candidate("秋衣", "蚯蚓粉"))

    def test_function_char_guarded(self):
        # 含语气词"呀" → 拒绝（挡 按摩呀→按摩椅 这类假阳性）
        self.assertIsNone(_rule_candidate("按摩呀", "按摩椅"))

    def test_different_shengmu_none(self):
        # 保健产 vs 保健品：末音 chan/pin 声母 ch≠p → 非候选
        self.assertIsNone(_rule_candidate("保健产", "保健品"))


# ---- ② 专名纠错（规则圈候选 + LLM 判定） -----------------------------------

class CorrectProperNounsTests(unittest.TestCase):
    def test_replaces_when_llm_says_yes(self):
        segs = [_seg(0, "你不叫秋衣粉吗", 0, 1000)]
        llm = _StubLlm({"replace": True, "reason": "宾语位产品名"})
        stats = correct_proper_nouns(segs, PostProcessConfig(lexicon=("蚯蚓粉",)), llm)
        self.assertEqual(segs[0]["text"], "你不叫蚯蚓粉吗")
        self.assertEqual(stats["segments_corrected"], 1)
        self.assertGreaterEqual(stats["llm_calls"], 1)

    def test_keeps_when_llm_says_no(self):
        segs = [_seg(0, "你不叫秋衣粉吗", 0, 1000)]
        llm = _StubLlm({"replace": False, "reason": "不通顺"})
        stats = correct_proper_nouns(segs, PostProcessConfig(lexicon=("蚯蚓粉",)), llm)
        self.assertEqual(segs[0]["text"], "你不叫秋衣粉吗")  # 未改
        self.assertEqual(stats["segments_corrected"], 0)
        self.assertGreaterEqual(stats["llm_calls"], 1)  # 候选命中但判否

    def test_skipped_without_lexicon(self):
        segs = [_seg(0, "你不叫秋衣粉吗", 0, 1000)]
        llm = _StubLlm({"replace": True})
        stats = correct_proper_nouns(segs, PostProcessConfig(lexicon=()), llm)
        self.assertEqual(stats.get("skipped"), "no_lexicon")
        self.assertEqual(llm.calls, 0)  # 无词表根本不调 LLM
        self.assertEqual(segs[0]["text"], "你不叫秋衣粉吗")


# ---- 词表构建 --------------------------------------------------------------

class BuildLexiconTests(unittest.TestCase):
    def test_materials_source_trusted(self):
        llm = _StubLlm({"terms": ["蚯蚓粉", "护颈仪"]})
        out = build_lexicon(PostProcessConfig(), llm, materials="产品有蚯蚓粉和护颈仪")
        self.assertEqual(out["source"], "materials")
        self.assertFalse(out["needs_confirmation"])
        self.assertIn("蚯蚓粉", out["terms"])

    def test_transcript_source_needs_confirmation(self):
        llm = _StubLlm({"terms": ["秋衣粉"]})
        segs = [_seg(0, "你不叫秋衣粉吗", 0, 1000)]
        out = build_lexicon(PostProcessConfig(), llm, segments=segs)
        self.assertEqual(out["source"], "transcript_candidates")
        self.assertTrue(out["needs_confirmation"])  # 转写候选写法可能错，需确认

    def test_manual_terms_merged_deduped(self):
        llm = _StubLlm({"terms": ["蚯蚓粉"]})
        out = build_lexicon(PostProcessConfig(), llm, materials="蚯蚓粉",
                            manual_terms=("蚯蚓粉", "护颈仪"))
        self.assertEqual(out["terms"].count("蚯蚓粉"), 1)  # 去重
        self.assertIn("护颈仪", out["terms"])

    def test_no_source(self):
        llm = _StubLlm({"terms": []})
        out = build_lexicon(PostProcessConfig(), llm)
        self.assertEqual(out["source"], "none")
        self.assertEqual(out["terms"], [])


# ---- 顺滑（有损，护栏） ----------------------------------------------------

class SmoothingTests(unittest.TestCase):
    def test_writes_display_text_and_keeps_l1(self):
        segs = [_seg(0, "呃就是那个我觉得没有没有用啊", 0, 1000)]
        llm = _StubLlm({"smoothed": "我觉得没有用。"})
        smooth_for_display(segs, PostProcessConfig(), llm)
        self.assertEqual(segs[0]["display_text"], "我觉得没有用。")
        self.assertEqual(segs[0]["text"], "呃就是那个我觉得没有没有用啊")  # L1 不动

    def test_guardrail_falls_back_on_inflation(self):
        l1 = "简短原文"
        segs = [_seg(0, l1, 0, 1000)]
        llm = _StubLlm({"smoothed": "被异常膨胀的输出" * 5})  # >1.4x → 退回 L1
        smooth_for_display(segs, PostProcessConfig(), llm)
        self.assertEqual(segs[0]["display_text"], l1)


# ---- 编排 ------------------------------------------------------------------

class RunPostprocessTests(unittest.TestCase):
    def test_dedup_runs_correction_skipped_without_llm(self):
        segs = [
            _seg(0, "今天我们开会讨论预算", 0, 1000),
            _seg(1, "讨论预算的分配方案", 900, 2000),
        ]
        stats = run_postprocess(segs, PostProcessConfig(), llm_call=None)
        self.assertEqual(stats["steps"]["dedup"]["segments_fixed"], 1)
        self.assertEqual(stats["steps"]["proper_correction"], {"skipped": "no_llm"})
        # L1 定格后每段都有 display_text
        self.assertTrue(all("display_text" in s for s in segs))


if __name__ == "__main__":
    unittest.main()

import copy
import unittest

from meeting_agent.stages.validation import (
    SummaryValidationError,
    clean_text,
    empty_summary,
    normalize_refs,
    normalize_summary,
    parse_content,
    validate_llm_result,
    validate_summary_object,
)


def _seg(index, speaker, text, start_ms=None, end_ms=None):
    start_ms = index * 3000 if start_ms is None else start_ms
    end_ms = start_ms + 2900 if end_ms is None else end_ms
    return {
        "segment_id": f"seg-{index:06d}",
        "speaker_id": speaker,
        "text": text,
        "start_ms": start_ms,
        "end_ms": end_ms,
    }


class CleanTextTests(unittest.TestCase):
    def test_none_passthrough(self):
        self.assertIsNone(clean_text(None))

    def test_whitespace_collapsed(self):
        self.assertEqual(clean_text("  a\n b\t c  "), "a b c")

    def test_placeholder_becomes_none(self):
        for value in ("未明确", "无", "待确认", "NONE", "n/a"):
            self.assertIsNone(clean_text(value), value)

    def test_non_string_raises(self):
        with self.assertRaises(SummaryValidationError):
            clean_text(123)


class ParseContentTests(unittest.TestCase):
    def test_valid_object(self):
        self.assertEqual(parse_content('{"a": 1}'), {"a": 1})

    def test_non_object_raises(self):
        with self.assertRaises(SummaryValidationError):
            parse_content("[1, 2, 3]")

    def test_invalid_json_raises(self):
        with self.assertRaises(SummaryValidationError):
            parse_content("not json at all")

    def test_repairs_literal_control_char(self):
        # 字符串值里混入裸换行（LLM 常见），应被修复而非报错
        content = '{"text": "line1' + chr(10) + 'line2"}'
        self.assertEqual(parse_content(content), {"text": "line1\nline2"})


class NormalizeRefsTests(unittest.TestCase):
    def setUp(self):
        segs = [_seg(0, "speaker_1", "有内容"), _seg(1, "speaker_1", "")]
        self.by_id = {s["segment_id"]: s for s in segs}

    def test_drops_invalid_empty_and_dedups(self):
        repairs = []
        out = normalize_refs(
            ["seg-000000", "seg-000000", "seg-000001", "seg-999999"],
            self.by_id, repairs, "loc",
        )
        self.assertEqual(out, ["seg-000000"])  # 去重 + 丢空文本 + 丢无效
        types = {r["type"] for r in repairs}
        self.assertIn("drop_invalid_refs", types)   # seg-999999
        self.assertIn("drop_empty_text_ref", types)  # seg-000001

    def test_non_list_raises(self):
        with self.assertRaises(SummaryValidationError):
            normalize_refs("seg-000000", self.by_id, [], "loc")


class NormalizeSummaryTests(unittest.TestCase):
    def test_empty_summary_shape(self):
        s = empty_summary()
        self.assertIsNone(s["title"])
        self.assertIsNone(s["overview"])
        for f in ("chapters", "speakers", "decisions", "action_items", "keywords"):
            self.assertEqual(s[f], [])

    def test_unknown_top_level_field_warned(self):
        segs = [_seg(0, "speaker_1", "内容")]
        _, quality = normalize_summary({"bogus_field": 1}, segs)
        self.assertTrue(any("bogus_field" in w for w in quality["warnings"]))

    def test_placeholder_overview_dropped(self):
        segs = [_seg(0, "speaker_1", "内容")]
        raw = {"overview": {"text": "未明确", "refs": ["seg-000000"]}}
        summary, _ = normalize_summary(raw, segs)
        self.assertIsNone(summary["overview"])

    def test_chapter_kept_and_range_computed(self):
        segs = [_seg(0, "speaker_1", "开场", 0, 1000), _seg(1, "speaker_2", "讨论", 3000, 5000)]
        raw = {"chapters": [{
            "title": "第一章", "overview": "概述",
            "refs": ["seg-000000", "seg-000001"],
        }]}
        summary, _ = normalize_summary(raw, segs)
        self.assertEqual(len(summary["chapters"]), 1)
        ch = summary["chapters"][0]
        self.assertEqual(ch["start_ms"], 0)
        self.assertEqual(ch["end_ms"], 5000)
        self.assertEqual(ch["speaker_ids"], ["speaker_1", "speaker_2"])

    def test_chapter_reversed_range_dropped(self):
        segs = [_seg(0, "speaker_1", "a", 0, 1000), _seg(1, "speaker_1", "b", 3000, 5000)]
        raw = {"chapters": [{
            "title": "t", "overview": "o",
            "refs": ["seg-000000", "seg-000001"],
            "start_ref": "seg-000001", "end_ref": "seg-000000",  # 反向
        }]}
        summary, quality = normalize_summary(raw, segs)
        self.assertEqual(summary["chapters"], [])
        self.assertTrue(any(r["type"] == "drop_invalid_chapter_range" for r in quality["repairs"]))

    def test_chapter_missing_overview_dropped(self):
        segs = [_seg(0, "speaker_1", "a")]
        raw = {"chapters": [{"title": "t", "refs": ["seg-000000"]}]}  # 缺 overview
        summary, _ = normalize_summary(raw, segs)
        self.assertEqual(summary["chapters"], [])

    def test_speaker_cross_refs_dropped(self):
        segs = [_seg(0, "speaker_1", "我说的"), _seg(1, "speaker_2", "他说的")]
        raw = {"speakers": [{
            "speaker_id": "speaker_1", "overview": "发言概述",
            "refs": ["seg-000000", "seg-000001"],  # seg1 属于 speaker_2
        }]}
        summary, quality = normalize_summary(raw, segs)
        self.assertEqual(len(summary["speakers"]), 1)
        self.assertEqual(summary["speakers"][0]["refs"], ["seg-000000"])  # 跨人 ref 被剔
        self.assertTrue(any(r["type"] == "drop_cross_speaker_refs" for r in quality["repairs"]))

    def test_keyword_uses_keyword_key(self):
        segs = [_seg(0, "speaker_1", "预算相关内容")]
        raw = {"keywords": [{"keyword": "预算", "refs": ["seg-000000"]}]}
        summary, _ = normalize_summary(raw, segs)
        self.assertEqual(summary["keywords"], [{"keyword": "预算", "refs": ["seg-000000"]}])


class ActionItemEvidenceTests(unittest.TestCase):
    """行动项的‘不编造’底线：owner 必须有发言证据、deadline 必须在原文出现。"""

    def test_unsupported_owner_and_deadline_cleared(self):
        segs = [_seg(0, "speaker_1", "我们下周三上线", 0, 2000),
                _seg(1, "speaker_2", "好的", 3000, 4000)]
        raw = {"action_items": [{
            "task": "上线", "refs": ["seg-000000"],
            "owner": "speaker_2",   # 是发言人之一，但不在该 ref 的说话人 → 无据
            "deadline": "下周五",    # 原文没出现 → 无据
        }]}
        summary, quality = normalize_summary(raw, segs)
        item = summary["action_items"][0]
        self.assertIsNone(item["owner"])
        self.assertIsNone(item["deadline"])
        types = {r["type"] for r in quality["repairs"]}
        self.assertIn("clear_unsupported_owner", types)
        self.assertIn("clear_unsupported_deadline", types)

    def test_supported_owner_and_deadline_kept(self):
        segs = [_seg(0, "speaker_1", "我下周三前提交方案", 0, 2000)]
        raw = {"action_items": [{
            "task": "提交方案", "refs": ["seg-000000"],
            "owner": "speaker_1", "deadline": "下周三",
        }]}
        summary, _ = normalize_summary(raw, segs)
        item = summary["action_items"][0]
        self.assertEqual(item["owner"], "speaker_1")
        self.assertEqual(item["deadline"], "下周三")

    def test_action_without_refs_dropped(self):
        segs = [_seg(0, "speaker_1", "内容")]
        raw = {"action_items": [{"task": "做点事", "refs": []}]}
        summary, _ = normalize_summary(raw, segs)
        self.assertEqual(summary["action_items"], [])


class ValidateWrappersTests(unittest.TestCase):
    def test_validate_summary_object_nondict_raises(self):
        with self.assertRaises(SummaryValidationError):
            validate_summary_object(["not", "a", "dict"], [])

    def test_does_not_mutate_input(self):
        segs = [_seg(0, "speaker_1", "内容")]
        raw = {"chapters": [{"title": "t", "overview": "o", "refs": ["seg-000000"]}]}
        snapshot = copy.deepcopy(raw)
        validate_summary_object(raw, segs)
        self.assertEqual(raw, snapshot)  # deepcopy 保护，入参不被改

    def test_llm_result_rejects_bad_finish_reason(self):
        segs = [_seg(0, "speaker_1", "内容")]
        with self.assertRaises(SummaryValidationError):
            validate_llm_result('{"title": "t"}', "length", segs, context_truncated=False)

    def test_llm_result_rejects_truncation(self):
        segs = [_seg(0, "speaker_1", "内容")]
        with self.assertRaises(SummaryValidationError):
            validate_llm_result('{"title": "t"}', "stop", segs, context_truncated=True)

    def test_llm_result_ok_adds_checks(self):
        segs = [_seg(0, "speaker_1", "内容")]
        summary, quality = validate_llm_result('{"title": "季度会"}', "stop", segs, context_truncated=False)
        self.assertEqual(summary["title"], "季度会")
        self.assertTrue(quality["checks"]["finish_reason"])
        self.assertTrue(quality["checks"]["context_not_truncated"])


if __name__ == "__main__":
    unittest.main()

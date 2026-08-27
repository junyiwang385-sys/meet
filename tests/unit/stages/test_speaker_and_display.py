import json
import unittest

from meeting_agent.stages.product_summary import (
    SPEAKER_MIN_CHARS,
    _build_compact_ref_map,
    _build_compact_speaker_map,
    _build_speaker_documents,
    _validate_speaker_batch,
)
from meeting_agent.stages.display import (
    _carry_over_unknown_labels,
    build_frontend_result,
)


def _seg(index, speaker, text, start_ms=None, end_ms=None):
    start_ms = index * 3000 if start_ms is None else start_ms
    end_ms = start_ms + 2900 if end_ms is None else end_ms
    return {
        "segment_id": f"seg-{index:06d}", "index": index,
        "start_ms": start_ms, "end_ms": end_ms,
        "speaker_id": speaker, "text": text,
    }


class BuildSpeakerDocumentsTests(unittest.TestCase):
    def test_unknown_excluded_and_trivial_filtered(self):
        segments = [
            _seg(0, "speaker_1", "关于接口鉴权我们统一走网关校验令牌再回源，细节这样对齐" * 2),  # 实质
            _seg(1, "unknown", "嗯对啊行"),                                     # unknown → 排除
            _seg(2, "speaker_2", "对"),                                        # 琐碎 → 过滤
            _seg(3, "speaker_1", "补充一下超时和重试策略要统一配置管理" * 2),
        ]
        docs = _build_speaker_documents(segments)
        ids = {d["speaker_id"] for d in docs}
        self.assertIn("speaker_1", ids)
        self.assertNotIn("unknown", ids)
        self.assertNotIn("speaker_2", ids)  # 只说了"对"，< min_chars

    def test_min_chars_boundary(self):
        segments = [_seg(0, "speaker_1", "x" * SPEAKER_MIN_CHARS)]
        self.assertEqual(len(_build_speaker_documents(segments)), 1)
        segments = [_seg(0, "speaker_1", "x" * (SPEAKER_MIN_CHARS - 1))]
        self.assertEqual(len(_build_speaker_documents(segments)), 0)


class ValidateSpeakerBatchTests(unittest.TestCase):
    def setUp(self):
        self.documents = [
            {"speaker_id": "speaker_1", "first_index": 0, "segments": [
                _seg(0, "speaker_1", "短"), _seg(1, "speaker_1", "这是更长更实质的一段发言内容"),
            ]},
            {"speaker_id": "speaker_2", "first_index": 2, "segments": [
                _seg(2, "speaker_2", "speaker二的实质发言"),
            ]},
        ]
        self.ref_map, _ = _build_compact_ref_map(
            [s for d in self.documents for s in d["segments"]]
        )
        self.speaker_map, _ = _build_compact_speaker_map(
            [d["speaker_id"] for d in self.documents]
        )

    def _content(self, speakers):
        return json.dumps({"speakers": speakers}, ensure_ascii=False)

    def test_refs_assigned_by_code_not_model(self):
        # 模型即使乱塞 refs 也被忽略；refs 取该 speaker 自己最长的段
        content = self._content([
            {"speaker_id": "sp1", "overview": "sp1的总结", "refs": ["r999", "乱编"]},
            {"speaker_id": "sp2", "overview": "sp2的总结"},
        ])
        res = _validate_speaker_batch(content, "stop", False, self.documents,
                                      ref_map=self.ref_map, speaker_map=self.speaker_map)
        by = {r["speaker_id"]: r for r in res}
        self.assertEqual(set(by), {"speaker_1", "speaker_2"})
        # speaker_1 两段，按长度降序取前 2（最长 seg-000001 在前）
        self.assertEqual(by["speaker_1"]["refs"], ["seg-000001", "seg-000000"])
        self.assertEqual(by["speaker_2"]["refs"], ["seg-000002"])
        # 模型乱塞的 r999/乱编 未被采用
        self.assertNotIn("r999", by["speaker_1"]["refs"])

    def test_missing_speaker_is_best_effort_not_raise(self):
        # 模型只给了 sp1 → 不 raise，只返回 sp1
        content = self._content([{"speaker_id": "sp1", "overview": "只有sp1"}])
        res = _validate_speaker_batch(content, "stop", False, self.documents,
                                      ref_map=self.ref_map, speaker_map=self.speaker_map)
        self.assertEqual([r["speaker_id"] for r in res], ["speaker_1"])

    def test_transport_failure_still_raises(self):
        from meeting_agent.stages.validation import SummaryValidationError
        with self.assertRaises(SummaryValidationError):
            _validate_speaker_batch(self._content([]), "length", False, self.documents,
                                    ref_map=self.ref_map, speaker_map=self.speaker_map)


class CarryOverUnknownTests(unittest.TestCase):
    def test_forward_fill_and_backfill(self):
        segs = [
            _seg(0, "unknown", "a"), _seg(1, "speaker_1", "b"),
            _seg(2, "unknown", "c"), _seg(3, "speaker_2", "d"), _seg(4, "unknown", "e"),
        ]
        self.assertEqual(
            _carry_over_unknown_labels(segs),
            ["speaker_1", "speaker_1", "speaker_1", "speaker_2", "speaker_2"],
        )

    def test_all_unknown_stays_unknown(self):
        segs = [_seg(0, "unknown", "a"), _seg(1, "unknown", "b")]
        self.assertEqual(_carry_over_unknown_labels(segs), ["unknown", "unknown"])

    def test_frontend_transcription_merges_unknown(self):
        segments = [
            _seg(0, "speaker_1", "开场"), _seg(1, "unknown", "插话"),
        ]
        fr = build_frontend_result(
            {"meeting_id": "m", "duration_ms": 6000},
            segments,
            {"title": "T", "overview": None, "chapters": [], "speakers": [], "action_items": []},
            context_policy="test",
        )
        rows = fr["transcription"]
        self.assertEqual(rows[1]["speaker_id"], "speaker_1")   # unknown 归并
        self.assertEqual(rows[1]["raw_speaker_id"], "unknown")  # 原始保留


if __name__ == "__main__":
    unittest.main()

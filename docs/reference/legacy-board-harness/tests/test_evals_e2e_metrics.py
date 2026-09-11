from __future__ import annotations

import unittest

from evals.e2e_metrics import (
    edit_distance,
    evaluate_timelines,
    normalize_text,
    speaker_mapping,
)


def segment(index, start, end, speaker, text):
    return {
        "segment_id": f"seg-{index:06d}",
        "index": index,
        "start_ms": start,
        "end_ms": end,
        "speaker_id": speaker,
        "text": text,
        "status": "ok",
    }


class EditDistanceTests(unittest.TestCase):
    def test_known_distances(self):
        self.assertEqual(edit_distance("", "abc"), 3)
        self.assertEqual(edit_distance("kitten", "sitting"), 3)
        self.assertEqual(edit_distance("会议纪要", "会议摘要"), 1)

    def test_normalize_text(self):
        self.assertEqual(normalize_text("会议，AI-2026！"), "会议ai2026")


class TimelineMetricTests(unittest.TestCase):
    def test_identical_timeline(self):
        timeline = [
            segment(1, 0, 1000, "speaker_1", "会议开始"),
            segment(2, 1000, 2000, "speaker_2", "确认方案"),
        ]
        metrics = evaluate_timelines(timeline, timeline, sample_step_ms=100)
        self.assertEqual(metrics["text"]["cer"], 0.0)
        self.assertEqual(metrics["speech"]["recall"], 1.0)
        self.assertEqual(metrics["speech"]["precision"], 1.0)
        self.assertEqual(metrics["speaker"]["accuracy_on_overlap"], 1.0)
        self.assertEqual(metrics["speaker"]["absolute_count_error"], 0)

    def test_anonymous_speaker_mapping(self):
        reference = [
            segment(1, 0, 1000, "alice", "甲"),
            segment(2, 1000, 2000, "bob", "乙"),
        ]
        predicted = [
            segment(1, 0, 1000, "speaker_9", "甲"),
            segment(2, 1000, 2000, "speaker_3", "乙"),
        ]
        mapping, _ = speaker_mapping(predicted, reference)
        self.assertEqual(mapping, {"speaker_3": "bob", "speaker_9": "alice"})
        metrics = evaluate_timelines(predicted, reference, sample_step_ms=100)
        self.assertEqual(metrics["speaker"]["accuracy_on_overlap"], 1.0)

    def test_partial_speech_and_unknown(self):
        reference = [segment(1, 0, 2000, "speaker_a", "一二三四")]
        predicted = [segment(1, 0, 1000, "unknown", "一二")]
        metrics = evaluate_timelines(predicted, reference, sample_step_ms=100)
        self.assertEqual(metrics["speech"]["recall"], 0.5)
        self.assertEqual(metrics["speech"]["precision"], 1.0)
        self.assertEqual(metrics["timeline"]["unknown_segment_ratio"], 1.0)
        self.assertEqual(metrics["timeline"]["unknown_speech_ratio"], 1.0)
        self.assertEqual(metrics["text"]["cer"], 0.5)

    def test_activity_segments_include_empty_asr_intervals(self):
        reference = [segment(1, 0, 2000, "speaker_a", "一二")]
        predicted = [segment(1, 0, 1000, "speaker_x", "一二")]
        activity = [
            segment(1, 0, 1000, "speaker_x", "一二"),
            segment(2, 1000, 2000, "speaker_x", ""),
        ]
        metrics = evaluate_timelines(
            predicted,
            reference,
            activity_segments=activity,
            sample_step_ms=100,
        )
        self.assertEqual(metrics["speech"]["recall"], 1.0)
        self.assertEqual(metrics["timeline"]["predicted_segment_count"], 2)
        self.assertEqual(metrics["timeline"]["predicted_empty_text_count"], 1)


if __name__ == "__main__":
    unittest.main()

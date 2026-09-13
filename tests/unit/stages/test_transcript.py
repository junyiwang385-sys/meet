import unittest

from meeting_agent.stages.transcript import (
    canonicalize_rows,
    format_ms,
    normalize_speaker,
    render_timeline,
    seconds_to_ms,
)


def _row(index, start, end, text, speaker="1", status="ok"):
    return {"index": index, "start": start, "end": end, "text": text,
            "speaker": speaker, "status": status}


class NormalizeSpeakerTests(unittest.TestCase):
    def test_unknown_variants(self):
        for v in (None, "", "unknown", "UNKNOWN", "  "):
            self.assertEqual(normalize_speaker(v), "unknown", repr(v))

    def test_bare_number_prefixed(self):
        self.assertEqual(normalize_speaker("3"), "speaker_3")

    def test_already_prefixed_kept(self):
        self.assertEqual(normalize_speaker("speaker_2"), "speaker_2")


class SecondsToMsTests(unittest.TestCase):
    def test_rounds_to_ms(self):
        self.assertEqual(seconds_to_ms(1.5, "start"), 1500)
        self.assertEqual(seconds_to_ms("2.0", "start"), 2000)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            seconds_to_ms(-1, "start")

    def test_non_numeric_raises(self):
        with self.assertRaises(ValueError):
            seconds_to_ms("abc", "end")


class FormatMsTests(unittest.TestCase):
    def test_format(self):
        self.assertEqual(format_ms(1000), "0m01s")
        self.assertEqual(format_ms(65000), "1m05s")


class CanonicalizeRowsTests(unittest.TestCase):
    def test_basic_shape_and_stats(self):
        rows = [_row(0, 0.0, 1.0, "  你好  世界 "), _row(1, 1.0, 2.5, "第二段")]
        segs, stats = canonicalize_rows(rows)
        self.assertEqual(segs[0]["segment_id"], "seg-000000")
        self.assertEqual(segs[0]["text"], "你好 世界")  # 空白折叠+strip
        self.assertEqual(segs[0]["start_ms"], 0)
        self.assertEqual(segs[1]["end_ms"], 2500)
        self.assertEqual(stats["segment_count"], 2)
        self.assertEqual(stats["speaker_ids"], ["speaker_1"])

    def test_sorted_by_start(self):
        rows = [_row(1, 5.0, 6.0, "后"), _row(0, 0.0, 1.0, "先")]
        segs, _ = canonicalize_rows(rows)
        self.assertEqual([s["text"] for s in segs], ["先", "后"])

    def test_empty_list_raises(self):
        with self.assertRaises(ValueError):
            canonicalize_rows([])

    def test_row_not_dict_raises(self):
        with self.assertRaises(ValueError):
            canonicalize_rows(["not a dict"])

    def test_duplicate_index_raises(self):
        rows = [_row(0, 0.0, 1.0, "a"), _row(0, 1.0, 2.0, "b")]
        with self.assertRaises(ValueError):
            canonicalize_rows(rows)

    def test_negative_index_raises(self):
        with self.assertRaises(ValueError):
            canonicalize_rows([_row(-1, 0.0, 1.0, "a")])

    def test_end_le_start_raises(self):
        with self.assertRaises(ValueError):
            canonicalize_rows([_row(0, 2.0, 2.0, "a")])

    def test_failed_status_raises(self):
        with self.assertRaises(ValueError):
            canonicalize_rows([_row(0, 0.0, 1.0, "a", status="error")])

    def test_transcript_empty_accepted(self):
        rows = [_row(0, 0.0, 1.0, "有字"), _row(1, 1.0, 2.0, "", status="transcript_empty")]
        segs, stats = canonicalize_rows(rows)
        self.assertEqual(stats["segment_count"], 2)
        self.assertEqual(stats["nonempty_segment_count"], 1)
        self.assertEqual(stats["empty_segment_count"], 1)


class RenderTimelineTests(unittest.TestCase):
    def test_skips_empty_and_formats(self):
        rows = [_row(0, 0.0, 1.0, "开场白"), _row(1, 1.0, 2.0, "", status="transcript_empty")]
        segs, _ = canonicalize_rows(rows)
        timeline = render_timeline(segs)
        self.assertIn("[seg-000000]", timeline)
        self.assertIn("[speaker_1] 开场白", timeline)
        self.assertNotIn("seg-000001", timeline)  # 空文本段不出现


if __name__ == "__main__":
    unittest.main()

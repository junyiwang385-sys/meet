from __future__ import annotations

import pathlib
import tempfile
import unittest

from evals.run_e2e_eval import load_reference
from evals.textgrid import parse_textgrid

TEXTGRID = """File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 2
 tiers? <exists>
 size = 2
 item []:
    item [1]:
        class = "IntervalTier"
        name = "speaker_a"
        xmin = 0
        xmax = 2
        intervals: size = 2
        intervals [1]:
            xmin = 0
            xmax = 1
            text = "会议开始"
        intervals [2]:
            xmin = 1
            xmax = 2
            text = ""
    item [2]:
        class = "IntervalTier"
        name = "speaker_b"
        xmin = 0
        xmax = 2
        intervals: size = 1
        intervals [1]:
            xmin = 1
            xmax = 2
            text = "确认方案"
"""


class TextGridTests(unittest.TestCase):
    def test_parse_and_render_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "sample.TextGrid"
            path.write_text(TEXTGRID, encoding="utf-8")
            segments, speakers = parse_textgrid(path)
            self.assertEqual(speakers, ["speaker_a", "speaker_b"])
            self.assertEqual(len(segments), 2)
            self.assertEqual(segments[0]["segment_id"], "seg-000001")
            self.assertEqual(segments[1]["start_ms"], 1000)
            loaded, loaded_speakers, timeline = load_reference(path)
            self.assertEqual(loaded, segments)
            self.assertEqual(loaded_speakers, speakers)
            self.assertIn("[seg-000001][0m00s-0m01s][speaker_a] 会议开始", timeline)
            self.assertIn("[seg-000002][0m01s-0m02s][speaker_b] 确认方案", timeline)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import pathlib
import tempfile
import unittest


SCRIPT_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "board" / "board_3dspeaker_segment_prepare_absorb_unknown.py"
SPEC = importlib.util.spec_from_file_location("absorb_unknown_prepare", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def row(start, end, speaker):
    return {
        "start": float(start),
        "end": float(end),
        "speaker": speaker,
        "source": "rttm",
        "source_ids": [f"{speaker}:{start}-{end}"],
        "absorbed_gap_ids": [],
    }


class GapAbsorptionTests(unittest.TestCase):
    def build(self, rows, duration=10.0, threshold=2.0, max_known=30.0):
        return MODULE.build_segment_plan(rows, duration, 0.0, threshold, max_known, 20.0)

    def test_same_speaker_short_gap_is_absorbed(self):
        result = self.build([row(0, 3, "A"), row(4.5, 8, "A")], duration=8)
        absorbed = [item for item in result["decisions"] if item["decision"] == "absorbed"]
        self.assertEqual(len(absorbed), 1)
        self.assertEqual(absorbed[0]["assigned_speaker"], "A")
        self.assertEqual([(item["start"], item["end"], item["speaker"]) for item in result["known"]], [(0.0, 8.0, "A")])
        self.assertEqual(result["unknown"], [])

    def test_gap_at_threshold_is_absorbed(self):
        result = self.build([row(0, 3, "A"), row(5, 8, "A")], duration=8)
        self.assertEqual(result["decisions"][0]["decision"], "absorbed")

    def test_gap_over_threshold_is_unknown(self):
        result = self.build([row(0, 3, "A"), row(5.01, 8, "A")], duration=8)
        self.assertEqual(result["decisions"][0]["reason"], "over_threshold")
        self.assertEqual(len(result["unknown"]), 1)

    def test_different_speakers_keep_unknown(self):
        result = self.build([row(0, 3, "A"), row(4, 8, "B")], duration=8)
        self.assertEqual(result["decisions"][0]["reason"], "different_boundary_speakers")
        self.assertEqual(result["unknown"][0]["speaker"], "unknown")

    def test_leading_and_trailing_gaps_are_unknown(self):
        result = self.build([row(1, 9, "A")], duration=10)
        self.assertEqual([item["reason"] for item in result["decisions"]], ["leading_gap", "trailing_gap"])
        self.assertEqual(len(result["unknown"]), 2)

    def test_ambiguous_boundary_keeps_unknown(self):
        result = self.build([row(0, 3, "A"), row(0, 3, "B"), row(4, 8, "A")], duration=8)
        self.assertEqual(result["decisions"][0]["reason"], "ambiguous_left_boundary")

    def test_absorption_then_max_split(self):
        result = self.build([row(0, 20, "A"), row(21, 40, "A")], duration=40, max_known=30)
        self.assertEqual(len(result["known"]), 2)
        self.assertEqual([(item["start"], item["end"]) for item in result["known"]], [(0.0, 30.0), (30.0, 40.0)])
        self.assertEqual(result["unknown"], [])

    def test_empty_rttm_becomes_unknown(self):
        result = self.build([], duration=10)
        self.assertEqual(result["known"], [])
        self.assertEqual([(item["start"], item["end"]) for item in result["unknown"]], [(0.0, 10.0)])

    def test_threshold_zero_disables_positive_gap_absorption(self):
        result = self.build([row(0, 3, "A"), row(3.1, 8, "A")], duration=8, threshold=0.0)
        self.assertEqual(result["decisions"][0]["reason"], "over_threshold")

    def test_fresh_output_removes_stale_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            source = root / "source.wav"
            source.write_bytes(b"audio")
            speaker_dir = root / "3dspeaker"
            speaker_dir.mkdir()
            out_dir = root / "out"
            out_dir.mkdir()
            (out_dir / "stale.wav").write_bytes(b"stale")
            MODULE.prepare_fresh_out_dir(out_dir, source, speaker_dir, overwrite=True)
            self.assertEqual(list(out_dir.iterdir()), [])

    def test_cleanup_refuses_output_containing_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            out_dir = root / "out"
            out_dir.mkdir()
            source = out_dir / "source.wav"
            source.write_bytes(b"audio")
            speaker_dir = root / "3dspeaker"
            speaker_dir.mkdir()
            with self.assertRaises(ValueError):
                MODULE.prepare_fresh_out_dir(out_dir, source, speaker_dir, overwrite=True)

    def test_cleanup_refuses_output_inside_speaker_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            source = root / "source.wav"
            source.write_bytes(b"audio")
            speaker_dir = root / "3dspeaker"
            speaker_dir.mkdir()
            out_dir = speaker_dir / "output"
            with self.assertRaises(ValueError):
                MODULE.prepare_fresh_out_dir(out_dir, source, speaker_dir, overwrite=True)


if __name__ == "__main__":
    unittest.main()

import csv
import json
import pathlib
import sys
import wave


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meeting_harness.artifacts import HarnessPaths
from meeting_harness.pipeline import asr_artifacts_valid


def write_wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 160)


def test_asr_resume_requires_exact_segment_identities(tmp_path):
    paths = HarnessPaths.from_root(tmp_path / "run")
    paths.create_directories()
    wav_dir = paths.segments / "cut_audio" / "wav_segments"
    wav_name = "seg_0001_A_1.000_2.000.wav"
    write_wav(wav_dir / wav_name)
    manifest = paths.segments / "cut_audio" / "cut_segments.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["index", "speaker", "start", "end", "file_name"])
        writer.writeheader()
        writer.writerow({"index": 1, "speaker": "A", "start": 1.0, "end": 2.0, "file_name": wav_name})
    segment_summary = {
        "wav_segments_dir": str(wav_dir),
        "cut_segments_csv": str(manifest),
    }
    paths.asr.mkdir(parents=True, exist_ok=True)
    summary = {
        "segment_count": 1,
        "completed_count": 1,
        "failed_count": 0,
        "missing_result_count": 0,
        "extra_result_count": 0,
        "status_counts": {"ok": 1},
    }
    (paths.asr / "batch_asr_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    transcript = [{"index": 1, "job_id": pathlib.Path(wav_name).stem, "audio_name": wav_name, "status": "ok"}]
    transcript_path = paths.asr / "segment_transcripts.json"
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")

    assert asr_artifacts_valid(paths, segment_summary) is not None

    transcript[0]["job_id"] = "seg_9999_other"
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")
    assert asr_artifacts_valid(paths, segment_summary) is None

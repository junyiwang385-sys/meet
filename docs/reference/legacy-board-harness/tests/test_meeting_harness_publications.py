import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meeting_harness.artifacts import HarnessPaths
from meeting_harness.pipeline import collect_artifacts, rotate_previous_publications


def test_resume_rotates_all_board_summary_publications(tmp_path):
    paths = HarnessPaths.from_root(tmp_path / "run")
    paths.create_directories()
    paths.meeting_summary.write_text("summary", encoding="utf-8")
    paths.meeting_frontend.write_text("frontend", encoding="utf-8")
    paths.meeting_display.write_text("display", encoding="utf-8")

    rotate_previous_publications(paths, resume=True)

    assert not paths.meeting_summary.exists()
    assert not paths.meeting_frontend.exists()
    assert not paths.meeting_display.exists()
    assert (paths.root / "previous_meeting_summary.json").read_text(encoding="utf-8") == "summary"
    assert (paths.root / "previous_meeting_frontend.json").read_text(encoding="utf-8") == "frontend"
    assert (paths.root / "previous_meeting_display.txt").read_text(encoding="utf-8") == "display"
    artifacts = collect_artifacts(paths)
    assert "previous_meeting_summary" in artifacts
    assert "previous_meeting_frontend" in artifacts
    assert "previous_meeting_display" in artifacts

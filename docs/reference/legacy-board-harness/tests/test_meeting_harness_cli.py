import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meeting_harness.main import parse_args


def test_cli_uses_qwen3_ctx16k_thinking_budget_defaults():
    args = parse_args(["--source-audio", "meeting.wav", "--out-dir", "out"])

    assert args.ctx == 16384
    assert args.predict == 4096
    assert args.max_tokens == 4096
    assert args.input_safety_tokens == 512
    assert args.input_chars_per_token == 1.3
    assert args.chunk_overlap_segments == 1
    assert args.model_dir.endswith("qwen3-4b-v104-ctx16k")

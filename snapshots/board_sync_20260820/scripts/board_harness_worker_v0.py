#!/usr/bin/env python3
"""Run the current board Harness as a cancellable background job.

This wrapper deliberately leaves the Harness package unchanged.  It starts
``python -m harness.main`` from the package parent directory so the Harness
relative imports work, follows its stage_status.json file, and returns a small
JSON-safe result for the board Agent API.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_SCRIPTS_DIR = Path("/userdata/meeting_agent/scripts")
DEFAULT_3DSPEAKER_DIR = Path("/userdata/3D-Speaker")
DEFAULT_3DSPEAKER_PYTHON = Path("/userdata/miniforge3/envs/3dspeaker/bin/python")
DEFAULT_ASR_DIR = Path(
    "/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_batch_demo"
)
DEFAULT_ASR_MODEL_DIR = Path("/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn")
DEFAULT_MODEL_DIR = Path("/userdata/meeting_agent/models/llm/v104/qwen3-4b-v104-ctx16k")
DEFAULT_SERVER = Path("/usr/bin/rkllm3-server")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18245
DEFAULT_CTX = 16384
DEFAULT_PREDICT = 3072
DEFAULT_MAX_TOKENS = 3072
DEFAULT_INPUT_SAFETY_TOKENS = 512
DEFAULT_INPUT_CHARS_PER_TOKEN = 1.3
DEFAULT_INPUT_FIXED_OVERHEAD_TOKENS = 128
DEFAULT_CHUNK_OVERLAP_SEGMENTS = 0
DEFAULT_TEMPERATURE = 0.0
DEFAULT_SERVER_TEMP = 0.0
DEFAULT_SERVER_TOP_K = 1
DEFAULT_SERVER_TOP_P = 1.0
DEFAULT_SERVER_REPEAT_PENALTY = 1.05
DEFAULT_READY_TIMEOUT = 300
DEFAULT_REQUEST_TIMEOUT = 1200
DEFAULT_SAMPLE_INTERVAL = 0.2

HARNESS_MODEL_PROFILE = "qwen3-4b-v104-ctx16k"
STAGE_ORDER = (
    "segmentation",
    "batch_asr",
    "transcript_prepare",
    "llm_summary",
    "compat_export",
)
TERMINAL_STAGE_STATUSES = {"succeeded", "reused", "skipped"}


@dataclass(frozen=True)
class HarnessRunConfig:
    """Explicit Harness runtime configuration used by the service wrapper."""

    scripts_dir: Path = DEFAULT_SCRIPTS_DIR
    three_d_speaker_dir: Path = DEFAULT_3DSPEAKER_DIR
    three_d_speaker_python: Path = DEFAULT_3DSPEAKER_PYTHON
    asr_dir: Path = DEFAULT_ASR_DIR
    asr_model_dir: Path = DEFAULT_ASR_MODEL_DIR
    model_dir: Path = DEFAULT_MODEL_DIR
    server: Path = DEFAULT_SERVER
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    ctx: int = DEFAULT_CTX
    predict: int = DEFAULT_PREDICT
    max_tokens: int = DEFAULT_MAX_TOKENS
    input_safety_tokens: int = DEFAULT_INPUT_SAFETY_TOKENS
    input_chars_per_token: float = DEFAULT_INPUT_CHARS_PER_TOKEN
    input_fixed_overhead_tokens: int = DEFAULT_INPUT_FIXED_OVERHEAD_TOKENS
    chunk_overlap_segments: int = DEFAULT_CHUNK_OVERLAP_SEGMENTS
    temperature: float = DEFAULT_TEMPERATURE
    server_temp: float = DEFAULT_SERVER_TEMP
    server_top_k: int = DEFAULT_SERVER_TOP_K
    server_top_p: float = DEFAULT_SERVER_TOP_P
    server_repeat_penalty: float = DEFAULT_SERVER_REPEAT_PENALTY
    ready_timeout: int = DEFAULT_READY_TIMEOUT
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT
    sample_interval: float = DEFAULT_SAMPLE_INTERVAL
    resume: bool = True


StageCallback = Callable[[str, dict[str, Any]], None]


class HarnessWorkerError(RuntimeError):
    """A preflight or process-level Harness wrapper error."""


class HarnessWorkerCancelled(RuntimeError):
    """Raised internally when a service task was cancelled."""


def read_json(path: Path) -> dict[str, Any] | None:
    """Read an optional JSON object without allowing malformed status to crash polling."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def current_stage(stage_status_path: Path) -> tuple[str, dict[str, Any]]:
    """Resolve the first unfinished Harness stage from stage_status.json."""

    status = read_json(stage_status_path)
    if status is None:
        return "processing", {"status": "starting"}

    stages = status.get("stages")
    if isinstance(stages, dict):
        for name in STAGE_ORDER:
            item = stages.get(name)
            if not isinstance(item, dict):
                return name, {"status": "pending"}
            if item.get("status") not in TERMINAL_STAGE_STATUSES:
                return name, dict(item)

    if status.get("status") == "succeeded":
        return "meeting_ready", {"status": "succeeded"}
    if status.get("status") == "failed":
        return "harness_failed", dict(status.get("error") or {})
    return "processing", {"status": status.get("status", "running")}


def build_command(
    source_audio: Path,
    out_dir: Path,
    config: HarnessRunConfig,
    python_executable: str | None = None,
) -> list[str]:
    """Build a shell-free command for the current Harness CLI."""

    executable = python_executable or sys.executable
    command = [
        executable,
        "-m",
        "harness.main",
        "--source-audio",
        str(source_audio),
        "--out-dir",
        str(out_dir),
        "--board-scripts-dir",
        str(config.scripts_dir),
        "--3dspeaker-dir",
        str(config.three_d_speaker_dir),
        "--3dspeaker-python",
        str(config.three_d_speaker_python),
        "--asr-dir",
        str(config.asr_dir),
        "--asr-model-dir",
        str(config.asr_model_dir),
        "--model-dir",
        str(config.model_dir),
        "--server",
        str(config.server),
        "--host",
        config.host,
        "--port",
        str(config.port),
        "--ctx",
        str(config.ctx),
        "--predict",
        str(config.predict),
        "--max-tokens",
        str(config.max_tokens),
        "--input-safety-tokens",
        str(config.input_safety_tokens),
        "--input-chars-per-token",
        str(config.input_chars_per_token),
        "--input-fixed-overhead-tokens",
        str(config.input_fixed_overhead_tokens),
        "--chunk-overlap-segments",
        str(config.chunk_overlap_segments),
        "--temperature",
        str(config.temperature),
        "--server-temp",
        str(config.server_temp),
        "--server-top-k",
        str(config.server_top_k),
        "--server-top-p",
        str(config.server_top_p),
        "--server-repeat-penalty",
        str(config.server_repeat_penalty),
        "--ready-timeout",
        str(config.ready_timeout),
        "--request-timeout",
        str(config.request_timeout),
        "--sample-interval",
        str(config.sample_interval),
        "--resume" if config.resume else "--overwrite",
    ]
    return command


def terminate_process(process: subprocess.Popen[str], timeout: float = 15.0) -> None:
    """Stop a Harness process and escalate only if it does not exit."""

    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def result_artifacts(out_dir: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Return only Harness-reported artifact references, not arbitrary file paths."""

    artifacts = result.get("artifacts")
    if isinstance(artifacts, dict):
        return artifacts
    return {}


def run_harness_task(
    *,
    source_audio: Path,
    out_dir: Path,
    cancel_event: threading.Event | None = None,
    on_stage: StageCallback | None = None,
    config: HarnessRunConfig | None = None,
    python_executable: str | None = None,
) -> dict[str, Any]:
    """Run Harness, report stages, and return a JSON-safe result dictionary."""

    config = config or HarnessRunConfig()
    cancel_event = cancel_event or threading.Event()
    source_audio = source_audio.resolve()
    out_dir = out_dir.resolve()
    if not source_audio.is_file():
        raise HarnessWorkerError(f"source audio not found: {source_audio}")
    if not config.scripts_dir.is_dir():
        raise HarnessWorkerError(f"Harness scripts directory not found: {config.scripts_dir}")
    if not (config.scripts_dir / "harness" / "main.py").is_file():
        raise HarnessWorkerError(f"Harness entry not found: {config.scripts_dir / 'harness' / 'main.py'}")
    if cancel_event.is_set():
        raise HarnessWorkerCancelled("Harness task was cancelled before start")

    out_dir.mkdir(parents=True, exist_ok=True)
    stage_status_path = out_dir / "stage_status.json"
    worker_log_path = out_dir.parent / "worker.log"
    command = build_command(source_audio, out_dir, config, python_executable)
    command_record = {
        "command": command,
        "cwd": str(config.scripts_dir),
        "model_profile": HARNESS_MODEL_PROFILE,
        "source_audio": str(source_audio),
        "out_dir": str(out_dir),
    }
    write_json(out_dir / "worker_command.json", command_record)

    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    existing_python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(config.scripts_dir) + (
        os.pathsep + existing_python_path if existing_python_path else ""
    )

    last_stage = ""
    process: subprocess.Popen[str] | None = None
    started = time.time()
    try:
        with worker_log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            log_file.write(json.dumps(command_record, ensure_ascii=False) + "\n")
            log_file.flush()
            process = subprocess.Popen(
                command,
                cwd=str(config.scripts_dir),
                env=environment,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )

            while process.poll() is None:
                if cancel_event.is_set():
                    terminate_process(process)
                    raise HarnessWorkerCancelled("Harness task was cancelled")
                stage, details = current_stage(stage_status_path)
                if stage != last_stage:
                    last_stage = stage
                    if on_stage is not None:
                        on_stage(stage, details)
                time.sleep(0.5)

            return_code = process.returncode

        if cancel_event.is_set():
            raise HarnessWorkerCancelled("Harness task was cancelled")

        result_path = out_dir / "meeting_result.json"
        result = read_json(result_path)
        stage, stage_details = current_stage(stage_status_path)
        if return_code != 0:
            return {
                "status": "failed",
                "stage": stage if stage != "processing" else "harness",
                "return_code": return_code,
                "error": stage_details,
                "result_path": str(result_path) if result_path.is_file() else None,
                "worker_log": str(worker_log_path),
                "elapsed_seconds": round(time.time() - started, 3),
            }
        if result is None or result.get("status") != "ok":
            return {
                "status": "failed",
                "stage": "harness_result",
                "return_code": return_code,
                "error": "Harness exited successfully but meeting_result.json is missing or not ok",
                "result_path": str(result_path) if result_path.is_file() else None,
                "worker_log": str(worker_log_path),
                "elapsed_seconds": round(time.time() - started, 3),
            }

        if on_stage is not None:
            on_stage("meeting_ready", {"status": "succeeded"})
        return {
            "status": "succeeded",
            "stage": "meeting_ready",
            "return_code": return_code,
            "result_path": str(result_path),
            "artifact_refs": result_artifacts(out_dir, result),
            "worker_log": str(worker_log_path),
            "elapsed_seconds": round(time.time() - started, 3),
        }
    except HarnessWorkerCancelled:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise HarnessWorkerError(str(exc)) from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run current Meeting Harness with cancellable wrapper")
    parser.add_argument("--source-audio", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--scripts-dir", type=Path, default=DEFAULT_SCRIPTS_DIR)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--ctx", type=int, default=DEFAULT_CTX)
    parser.add_argument("--predict", type=int, default=DEFAULT_PREDICT)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = HarnessRunConfig(
        scripts_dir=args.scripts_dir,
        model_dir=args.model_dir,
        port=args.port,
        ctx=args.ctx,
        predict=args.predict,
        max_tokens=args.max_tokens,
        resume=not args.overwrite,
    )
    cancel_event = threading.Event()

    def handle_signal(_signum: int, _frame: Any) -> None:
        cancel_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    def report_stage(stage: str, details: dict[str, Any]) -> None:
        print(
            json.dumps(
                {"stage": stage, "details": details},
                ensure_ascii=False,
            ),
            flush=True,
        )

    try:
        result = run_harness_task(
            source_audio=Path(args.source_audio),
            out_dir=Path(args.out_dir),
            cancel_event=cancel_event,
            on_stage=report_stage,
            config=config,
        )
    except HarnessWorkerCancelled as exc:
        print(json.dumps({"status": "cancelled", "error": str(exc)}, ensure_ascii=False))
        return 130
    except HarnessWorkerError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())

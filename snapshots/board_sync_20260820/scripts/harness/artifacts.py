"""Output paths and durable artifact helpers for the meeting Harness."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import tempfile
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HarnessPaths:
    root: pathlib.Path
    logs: pathlib.Path
    segments: pathlib.Path
    asr: pathlib.Path
    llm: pathlib.Path
    runtime: pathlib.Path
    run_config: pathlib.Path
    run_manifest: pathlib.Path
    run_events: pathlib.Path
    run_metrics: pathlib.Path
    error_report: pathlib.Path
    stage_status: pathlib.Path
    timeline: pathlib.Path
    meeting_summary: pathlib.Path
    meeting_frontend: pathlib.Path
    meeting_display: pathlib.Path
    meeting_result: pathlib.Path
    compat_export: pathlib.Path

    @classmethod
    def from_root(cls, root: pathlib.Path) -> "HarnessPaths":
        root = root.resolve()
        return cls(
            root=root,
            logs=root / "logs",
            segments=root / "01_segments",
            asr=root / "02_batch_asr",
            llm=root / "03_llm_summary",
            runtime=root / "runtime",
            run_config=root / "run_config.json",
            run_manifest=root / "run_manifest.json",
            run_events=root / "run_events.jsonl",
            run_metrics=root / "run_metrics.json",
            error_report=root / "error_report.json",
            stage_status=root / "stage_status.json",
            timeline=root / "timeline.txt",
            meeting_summary=root / "meeting_summary.json",
            meeting_frontend=root / "meeting_frontend.json",
            meeting_display=root / "meeting_display.txt",
            meeting_result=root / "meeting_result.json",
            compat_export=root / "04_compat_export",
        )

    def create_directories(self) -> None:
        for path in (self.root, self.logs, self.llm, self.runtime, self.compat_export):
            path.mkdir(parents=True, exist_ok=True)


def is_relative_to(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def prepare_output_dir(
    out_dir: str | pathlib.Path,
    source_audio: str | pathlib.Path,
    *,
    overwrite: bool,
    resume: bool,
) -> HarnessPaths:
    if overwrite and resume:
        raise ValueError("--overwrite and --resume are mutually exclusive")

    root = pathlib.Path(out_dir).expanduser().resolve()
    source = pathlib.Path(source_audio).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source audio not found: {source}")
    if root == pathlib.Path(root.anchor):
        raise ValueError("refusing filesystem root as out-dir")
    if source == root or is_relative_to(source, root):
        raise ValueError("source audio cannot be inside out-dir")

    if resume:
        if not root.is_dir():
            raise FileNotFoundError(f"resume out-dir not found: {root}")
    elif root.exists() and any(root.iterdir()):
        if not overwrite:
            raise FileExistsError(f"out-dir is not empty: {root}; use --overwrite or --resume")
        shutil.rmtree(root)

    paths = HarnessPaths.from_root(root)
    paths.create_directories()
    return paths


def atomic_write_text(path: str | pathlib.Path, text: str) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: str | pathlib.Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_json(path: str | pathlib.Path) -> Any:
    with pathlib.Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path: str | pathlib.Path) -> str:
    digest = hashlib.sha256()
    with pathlib.Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_artifact(path: str | pathlib.Path, root: str | pathlib.Path) -> dict[str, Any]:
    path = pathlib.Path(path).resolve()
    root = pathlib.Path(root).resolve()
    result: dict[str, Any] = {"path": str(path.relative_to(root)) if is_relative_to(path, root) else str(path)}
    if path.is_file():
        result.update({"size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return result


def write_stage_status(path: str | pathlib.Path, state: dict[str, Any]) -> None:
    atomic_write_json(path, state)

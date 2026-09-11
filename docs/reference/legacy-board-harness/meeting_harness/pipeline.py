"""End-to-end orchestration for the first meeting Harness release."""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time
from typing import Any

from . import HARNESS_VERSION, RESULT_SCHEMA_VERSION
from .artifacts import (
    HarnessPaths,
    atomic_write_json,
    atomic_write_text,
    load_json,
    prepare_output_dir,
    relative_artifact,
    sha256_file,
    write_stage_status,
)
from .chunking import ChunkingError
from .display import build_frontend_result, render_meeting_display
from .llm import LlmConfig, LlmRunError, load_board_helpers
from .product_summary import ProductSummaryConfig, run_product_summary_stage
from .compat_export import write_compat_bundle
from .transcript import prepare_transcript
from .validation import SummaryValidationError, empty_summary


class PipelineStageError(RuntimeError):
    def __init__(self, stage: str, code: str, message: str, exit_code: int, artifact: str | None = None):
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.exit_code = exit_code
        self.artifact = artifact

    def as_dict(self) -> dict[str, Any]:
        result = {"stage": self.stage, "code": self.code, "message": str(self)}
        if self.artifact:
            result["artifact"] = self.artifact
        return result


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def run_process_stage(
    name: str,
    command: list[str],
    log_path: pathlib.Path,
    sampler: Any,
) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(log_path.with_suffix(".cmd.json"), command)
    sampler.set_phase(name)
    started = time.time()
    process = None
    with log_path.open("wb") as handle:
        try:
            process = subprocess.Popen(
                command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
            sampler.add_target(name, process.pid)
            return_code = process.wait()
        except BaseException:
            if process is not None and process.poll() is None:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait()
            raise
    result = {
        "status": "succeeded" if return_code == 0 else "failed",
        "return_code": return_code,
        "elapsed_seconds": round(time.time() - started, 3),
        "command": command,
        "log": str(log_path),
    }
    if return_code != 0:
        result["log_tail"] = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
    return result


def require_json_object(path: pathlib.Path, fields: tuple[str, ...]) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"missing artifact: {path}")
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    missing = [field for field in fields if field not in value]
    if missing:
        raise ValueError(f"artifact {path} is missing fields: {missing}")
    return value


def segment_artifacts_valid(paths: HarnessPaths) -> dict[str, Any] | None:
    try:
        summary = require_json_object(
            paths.segments / "board_3dspeaker_segment_summary.json",
            ("wav_segments_dir", "cut_segments_csv", "audio_duration_seconds"),
        )
        if not pathlib.Path(summary["wav_segments_dir"]).is_dir():
            return None
        if not pathlib.Path(summary["cut_segments_csv"]).is_file():
            return None
        return summary
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def expected_segment_identities(segment_summary: dict[str, Any]) -> set[tuple[int, str, str]]:
    wav_dir = pathlib.Path(str(segment_summary["wav_segments_dir"]))
    manifest_path = pathlib.Path(str(segment_summary["cut_segments_csv"]))
    identities: set[tuple[int, str, str]] = set()
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            audio_name = row.get("file_name") or pathlib.Path(row.get("file", "")).name
            if not audio_name:
                raise ValueError("cut_segments.csv row has no file name")
            index = int(row["index"])
            identities.add((index, pathlib.Path(audio_name).stem, audio_name))
    discovered = {path.name for path in wav_dir.glob("seg_*.wav")}
    expected_names = {identity[2] for identity in identities}
    if not identities or discovered != expected_names:
        raise ValueError("segment manifest and WAV directory identities do not match")
    return identities


def asr_artifacts_valid(
    paths: HarnessPaths,
    segment_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        summary = require_json_object(
            paths.asr / "batch_asr_summary.json",
            ("segment_count", "failed_count", "status_counts"),
        )
        if int(summary["failed_count"]) != 0:
            return None
        transcripts = load_json(paths.asr / "segment_transcripts.json")
        if not isinstance(transcripts, list) or not transcripts:
            return None
        if len(transcripts) != int(summary["segment_count"]):
            return None
        if int(summary.get("completed_count", 0)) != int(summary["segment_count"]):
            return None
        if int(summary.get("missing_result_count", 0)) != 0:
            return None
        if int(summary.get("extra_result_count", 0)) != 0:
            return None
        accepted = {"ok", "transcript_empty"}
        if any(not isinstance(item, dict) for item in transcripts):
            return None
        if any(str(item.get("status")) not in accepted for item in transcripts):
            return None
        transcript_identities = {
            (int(item["index"]), str(item.get("job_id") or ""), str(item.get("audio_name") or ""))
            for item in transcripts
        }
        if len(transcript_identities) != len(transcripts):
            return None
        if segment_summary is not None and transcript_identities != expected_segment_identities(segment_summary):
            return None
        return summary
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def build_meeting_result_base(args: Any, source_audio: pathlib.Path, paths: HarnessPaths) -> dict[str, Any]:
    source_sha = sha256_file(source_audio)
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "harness_version": HARNESS_VERSION,
        "status": "running",
        "run_id": f"mtg_{source_sha[:16]}",
        "meeting": {
            "meeting_id": f"mtg_{source_sha[:16]}",
            "source_audio": str(source_audio),
            "source_audio_sha256": source_sha,
            "source_audio_size_bytes": source_audio.stat().st_size,
            "duration_ms": None,
        },
        "transcript": None,
        "summary": None,
        "quality": {"status": "not_run", "checks": {}, "repairs": [], "warnings": []},
        "runtime": {
            "started_at": now_iso(),
            "finished_at": None,
            "total_elapsed_seconds": None,
            "context_policy": "pending",
            "stages": {},
            "llm": {
                "request_count": 0,
                "reused_request_count": 0,
                "ctx": args.ctx,
                "predict": args.predict,
                "max_tokens": args.max_tokens,
                "input_safety_tokens": args.input_safety_tokens,
            },
            "memory": {},
        },
        "artifacts": {},
        "errors": [],
        "output_dir": str(paths.root),
    }


def file_identity(path: str | pathlib.Path, *, hash_content: bool = False) -> dict[str, Any]:
    path = pathlib.Path(path).expanduser().resolve()
    identity: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if path.is_file():
        stat = path.stat()
        identity.update({"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
        if hash_content:
            identity["sha256"] = sha256_file(path)
    return identity


def config_identity(
    args: Any,
    source_sha256: str,
    prepare_script: pathlib.Path,
    asr_script: pathlib.Path,
) -> dict[str, Any]:
    speaker_infer = pathlib.Path(args.__dict__["3dspeaker_dir"]) / "speakerlab/bin/infer_diarization.py"
    asr_dir = pathlib.Path(args.asr_dir)
    asr_model_dir = pathlib.Path(args.asr_model_dir)
    asr_artifacts = [
        asr_dir / "rknn_qwen3_asr_batch_demo",
        *(asr_model_dir / name for name in (
            "encoder.rknn",
            "encoder.weight",
            "llm.rknn",
            "llm.weight",
            "llm.tokenizer.gguf",
            "llm.embed.bin",
        )),
    ]
    llm_model_dir = pathlib.Path(args.model_dir).resolve()
    llm_artifacts = []
    for suffix in (".rknn", ".weight", ".tokenizer.gguf", ".embed.bin"):
        matches = sorted(llm_model_dir.glob(f"*{suffix}"))
        llm_artifacts.extend(file_identity(path) for path in matches)
    return {
        "source_audio_sha256": source_sha256,
        "segmentation": {
            "3dspeaker_dir": args.__dict__["3dspeaker_dir"],
            "3dspeaker_python": file_identity(args.__dict__["3dspeaker_python"]),
            "prepare_script": file_identity(prepare_script, hash_content=True),
            "infer_script": file_identity(speaker_infer, hash_content=True),
            "pad": args.pad,
            "absorb_unknown_max": args.absorb_unknown_max,
            "max_known_segment": args.max_known_segment,
            "max_unknown_segment": args.max_unknown_segment,
            "trim_duration": args.trim_duration,
        },
        "asr": {
            "wrapper_script": file_identity(asr_script, hash_content=True),
            "artifacts": [file_identity(path) for path in asr_artifacts],
            "encoder_core": args.encoder_core,
            "asr_llm_core": args.asr_llm_core,
        },
        "llm": {
            "model_dir": str(llm_model_dir),
            "model_artifacts": llm_artifacts,
            "server": file_identity(args.server),
            "ctx": args.ctx,
            "predict": args.predict,
            "max_tokens": args.max_tokens,
            "input_safety_tokens": args.input_safety_tokens,
            "input_chars_per_token": args.input_chars_per_token,
            "input_fixed_overhead_tokens": args.input_fixed_overhead_tokens,
            "chunk_overlap_segments": args.chunk_overlap_segments,
            "temperature": args.temperature,
            "server_temp": args.server_temp,
            "server_top_k": args.server_top_k,
            "server_top_p": args.server_top_p,
            "server_repeat_penalty": args.server_repeat_penalty,
        },
    }


def rotate_previous_publications(paths: HarnessPaths, *, resume: bool) -> None:
    if not resume:
        return
    publications = (
        (paths.meeting_summary, paths.root / "previous_meeting_summary.json"),
        (paths.meeting_frontend, paths.root / "previous_meeting_frontend.json"),
        (paths.meeting_display, paths.root / "previous_meeting_display.txt"),
    )
    for current, previous in publications:
        if current.is_file():
            if previous.exists():
                previous.unlink()
            os.replace(current, previous)
    previous_validation = paths.llm / "previous_validation.json"
    current_validation = paths.llm / "validation.json"
    if current_validation.is_file():
        if previous_validation.exists():
            previous_validation.unlink()
        os.replace(current_validation, previous_validation)
    previous_compat_export = paths.root / "04_compat_export_previous"
    if (paths.compat_export / "manifest.json").is_file():
        if previous_compat_export.exists():
            shutil.rmtree(previous_compat_export)
        os.replace(paths.compat_export, previous_compat_export)
        paths.compat_export.mkdir(parents=True, exist_ok=True)
    for stale in (paths.llm / "plan.json", paths.llm / "server_status.json"):
        if stale.is_file():
            stale.unlink()


def collect_artifacts(paths: HarnessPaths) -> dict[str, Any]:
    candidates = {
        "segment_summary": paths.segments / "board_3dspeaker_segment_summary.json",
        "batch_asr_summary": paths.asr / "batch_asr_summary.json",
        "segment_transcripts": paths.asr / "segment_transcripts.json",
        "timeline": paths.timeline,
        "canonical_segments": paths.llm / "canonical_segments.json",
        "llm_plan": paths.llm / "plan.json",
        "llm_server_status": paths.llm / "server_status.json",
        "validation": paths.llm / "validation.json",
        "compat_manifest": paths.compat_export / "manifest.json",
        "compat_task_result": paths.compat_export / "task_result.json",
        "meeting_summary": paths.meeting_summary,
        "meeting_frontend": paths.meeting_frontend,
        "meeting_display": paths.meeting_display,
        "previous_meeting_summary": paths.root / "previous_meeting_summary.json",
        "previous_meeting_frontend": paths.root / "previous_meeting_frontend.json",
        "previous_meeting_display": paths.root / "previous_meeting_display.txt",
        "previous_validation": paths.llm / "previous_validation.json",
        "previous_compat_export_manifest": paths.root / "04_compat_export_previous" / "manifest.json",
    }
    return {
        name: relative_artifact(path, paths.root)
        for name, path in candidates.items()
        if path.is_file()
    }


def run_pipeline(args: Any) -> int:
    source_audio = pathlib.Path(args.source_audio).expanduser().resolve()
    paths = prepare_output_dir(
        args.out_dir,
        source_audio,
        overwrite=args.overwrite,
        resume=args.resume,
    )
    started = time.time()
    state: dict[str, Any] = {"status": "running", "stages": {}}
    result = build_meeting_result_base(args, source_audio, paths)
    rotate_previous_publications(paths, resume=args.resume)
    previous_config = None
    run_config = None
    write_stage_status(paths.stage_status, state)
    atomic_write_json(paths.meeting_result, result)

    sampler = None
    exit_code = 1
    summary_published = False
    compat_export_published = False
    try:
        board_scripts_dir = pathlib.Path(args.board_scripts_dir).resolve()
        prepare_script = board_scripts_dir / "board_3dspeaker_segment_prepare_absorb_unknown.py"
        asr_script = board_scripts_dir / "board_segment_asr_batch.py"
        for path in (prepare_script, asr_script):
            if not path.is_file():
                raise PipelineStageError("preflight", "missing_script", f"missing board script: {path}", 2)

        if args.resume and paths.run_config.is_file():
            try:
                previous_config = load_json(paths.run_config)
            except (OSError, json.JSONDecodeError) as exc:
                raise PipelineStageError(
                    "preflight", "invalid_previous_config", f"cannot read previous run_config.json: {exc}", 2, str(paths.run_config)
                ) from exc
        identity = config_identity(
            args,
            result["meeting"]["source_audio_sha256"],
            prepare_script,
            asr_script,
        )
        run_config = {**vars(args), "identity": identity}
        helpers = load_board_helpers(board_scripts_dir)
        sampler = helpers.MemorySampler(paths.runtime / "memory_samples.jsonl", args.sample_interval)
        sampler.start()
        previous_identity = previous_config.get("identity") if isinstance(previous_config, dict) else None
        reuse_segmentation = bool(
            args.resume
            and previous_identity
            and previous_identity.get("source_audio_sha256") == identity["source_audio_sha256"]
            and previous_identity.get("segmentation") == identity["segmentation"]
        )
        reuse_asr = bool(
            reuse_segmentation
            and previous_identity.get("asr") == identity["asr"]
        )
        atomic_write_json(paths.root / "run_config_attempt.json", run_config)
        segment_summary = segment_artifacts_valid(paths) if reuse_segmentation else None
        if segment_summary is None:
            if paths.asr.exists():
                shutil.rmtree(paths.asr)
            for stale_path in (paths.timeline, paths.llm / "canonical_segments.json"):
                if stale_path.exists():
                    stale_path.unlink()
            command = [
                args.__dict__["3dspeaker_python"],
                str(prepare_script),
                "--source-audio", str(source_audio),
                "--out-dir", str(paths.segments),
                "--3dspeaker-dir", args.__dict__["3dspeaker_dir"],
                "--python", args.__dict__["3dspeaker_python"],
                "--pad", str(args.pad),
                "--absorb-unknown-max", str(args.absorb_unknown_max),
                "--max-known-segment", str(args.max_known_segment),
                "--max-unknown-segment", str(args.max_unknown_segment),
                "--overwrite",
            ]
            if args.trim_duration > 0:
                command.extend(["--trim-duration", str(args.trim_duration)])
            reuse_asr = False
            stage = run_process_stage("segmentation", command, paths.logs / "01_segmentation.log", sampler)
            state["stages"]["segmentation"] = stage
            result["runtime"]["stages"]["segmentation"] = stage
            write_stage_status(paths.stage_status, state)
            if stage["return_code"] != 0:
                raise PipelineStageError("segmentation", "process_failed", "3D-Speaker segmentation failed", 3, stage["log"])
            segment_summary = segment_artifacts_valid(paths)
            if segment_summary is None:
                raise PipelineStageError("segmentation", "invalid_artifacts", "segmentation artifacts are missing or invalid", 3)
        else:
            stage = {"status": "reused"}
            state["stages"]["segmentation"] = stage
            result["runtime"]["stages"]["segmentation"] = stage

        asr_summary = asr_artifacts_valid(paths, segment_summary) if reuse_asr else None
        if asr_summary is None:
            command = [
                sys.executable,
                str(asr_script),
                "--wav-dir", str(segment_summary["wav_segments_dir"]),
                "--manifest", str(segment_summary["cut_segments_csv"]),
                "--out-dir", str(paths.asr),
                "--asr-dir", args.asr_dir,
                "--asr-model-dir", args.asr_model_dir,
                "--encoder-core", args.encoder_core,
                "--llm-core", args.asr_llm_core,
                "--overwrite",
            ]
            stage = run_process_stage("batch_asr", command, paths.logs / "02_batch_asr.log", sampler)
            state["stages"]["batch_asr"] = stage
            result["runtime"]["stages"]["batch_asr"] = stage
            write_stage_status(paths.stage_status, state)
            if stage["return_code"] != 0:
                raise PipelineStageError("batch_asr", "process_failed", "Batch ASR failed", 4, stage["log"])
            asr_summary = asr_artifacts_valid(paths, segment_summary)
            if asr_summary is None:
                raise PipelineStageError("batch_asr", "invalid_artifacts", "Batch ASR artifacts are missing or invalid", 4)
        else:
            stage = {"status": "reused"}
            state["stages"]["batch_asr"] = stage
            result["runtime"]["stages"]["batch_asr"] = stage

        sampler.set_phase("transcript_prepare")
        transcript_started = time.time()
        canonical_path = paths.llm / "canonical_segments.json"
        segments, transcript_stats, timeline = prepare_transcript(
            paths.asr / "segment_transcripts.json",
            canonical_path,
            paths.timeline,
        )
        transcript_stage = {
            "status": "succeeded",
            "elapsed_seconds": round(time.time() - transcript_started, 3),
        }
        state["stages"]["transcript_prepare"] = transcript_stage
        result["runtime"]["stages"]["transcript_prepare"] = transcript_stage
        result["meeting"]["duration_ms"] = int(round(float(segment_summary["audio_duration_seconds"]) * 1000))
        result["transcript"] = {
            "source_artifact": str((paths.asr / "segment_transcripts.json").relative_to(paths.root)),
            "timeline_artifact": str(paths.timeline.relative_to(paths.root)),
            **transcript_stats,
            "segments": segments,
        }
        write_stage_status(paths.stage_status, state)
        atomic_write_json(paths.run_config, run_config)

        if not timeline:
            summary = empty_summary()
            quality = {
                "status": "pass",
                "checks": {"no_fact_policy": True},
                "counts": {"repairs": 0, "invalid_refs": 0, "dropped_items": 0},
                "repairs": [],
                "warnings": ["all transcript segments are empty; LLM request skipped"],
            }
            llm_stage = {"status": "skipped", "reason": "empty_transcript"}
            result["runtime"]["context_policy"] = "no_fact_skip"
        else:
            llm_config = LlmConfig(
                board_scripts_dir=board_scripts_dir,
                model_dir=pathlib.Path(args.model_dir).resolve(),
                server=pathlib.Path(args.server),
                host=args.host,
                port=args.port,
                ctx=args.ctx,
                predict=args.predict,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                server_temp=args.server_temp,
                server_top_k=args.server_top_k,
                server_top_p=args.server_top_p,
                server_repeat_penalty=args.server_repeat_penalty,
                ready_timeout=args.ready_timeout,
                request_timeout=args.request_timeout,
            )
            llm_started = time.time()
            try:
                llm_run = run_product_summary_stage(
                    config=ProductSummaryConfig(
                        llm=llm_config,
                        safety_tokens=args.input_safety_tokens,
                        chars_per_token=args.input_chars_per_token,
                        fixed_overhead_tokens=args.input_fixed_overhead_tokens,
                        resume=args.resume,
                    ),
                    segments=segments,
                    speaker_ids=transcript_stats["speaker_ids"],
                    timeline=timeline,
                    out_dir=paths.llm,
                    sampler=sampler,
                )
            except SummaryValidationError as exc:
                raise PipelineStageError(
                    "llm_summary", "validation_failed", str(exc), 7, str(paths.llm / "plan.json")
                ) from exc
            except (LlmRunError, ChunkingError, OSError, TimeoutError) as exc:
                raise PipelineStageError(
                    "llm_summary",
                    "request_failed",
                    str(exc),
                    6,
                    str(paths.llm / "rkllm_server.log"),
                ) from exc
            summary = llm_run["summary"]
            quality = llm_run["quality"]
            atomic_write_json(paths.llm / "validation.json", quality)
            llm_stage = {
                "status": "succeeded",
                "elapsed_seconds": round(time.time() - llm_started, 3),
                "policy": llm_run["policy"],
                "request_count": llm_run["request_count"],
                "validated_request_count": llm_run["validated_request_count"],
                "reused_request_count": llm_run["reused_request_count"],
                "server_ready_seconds": llm_run["server_ready_seconds"],
            }
            result["runtime"]["context_policy"] = llm_run["policy"]
            result["runtime"]["llm"] = {
                **result["runtime"]["llm"],
                "request_count": llm_run["request_count"],
                "validated_request_count": llm_run["validated_request_count"],
                "reused_request_count": llm_run["reused_request_count"],
                "server_ready_seconds": llm_run["server_ready_seconds"],
                "requests": llm_run["requests"],
                "resolved_model_files": llm_run["resolved_model_files"],
                "plan": llm_run["plan"],
            }

        state["stages"]["llm_summary"] = llm_stage
        result["runtime"]["stages"]["llm_summary"] = llm_stage
        result["summary"] = summary
        result["quality"] = quality
        frontend_result = build_frontend_result(
            result["meeting"],
            segments,
            summary,
            context_policy=result["runtime"]["context_policy"],
        )
        meeting_publication_dir = paths.root / ".meeting_publication.staging"
        if meeting_publication_dir.exists():
            shutil.rmtree(meeting_publication_dir)
        meeting_publication_dir.mkdir(parents=True)
        atomic_write_json(meeting_publication_dir / paths.meeting_summary.name, summary)
        atomic_write_json(meeting_publication_dir / paths.meeting_frontend.name, frontend_result)
        atomic_write_text(
            meeting_publication_dir / paths.meeting_display.name,
            render_meeting_display(frontend_result),
        )

        export_started = time.time()
        try:
            compat_manifest = write_compat_bundle(
                paths.compat_export,
                task_id=result["meeting"]["meeting_id"],
                meeting=result["meeting"],
                segments=segments,
                summary=summary,
                source_summary_path=meeting_publication_dir / paths.meeting_summary.name,
                source_segments_path=canonical_path,
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise PipelineStageError(
                "compat_export",
                "export_failed",
                str(exc),
                8,
                str(paths.compat_export),
            ) from exc
        export_stage = {
            "status": "succeeded",
            "elapsed_seconds": round(time.time() - export_started, 3),
            "mapping_version": compat_manifest["mapping_version"],
        }
        state["stages"]["compat_export"] = export_stage
        result["runtime"]["stages"]["compat_export"] = export_stage
        compat_export_published = True
        for path in (paths.meeting_summary, paths.meeting_frontend, paths.meeting_display):
            os.replace(meeting_publication_dir / path.name, path)
        meeting_publication_dir.rmdir()
        summary_published = True
        result["status"] = "ok"
        state["status"] = "succeeded"
        atomic_write_json(paths.run_config, run_config)
        attempt_config = paths.root / "run_config_attempt.json"
        if attempt_config.exists():
            attempt_config.unlink()
        exit_code = 0
    except PipelineStageError as exc:
        result["status"] = "failed"
        result["errors"].append(exc.as_dict())
        if exc.stage != "compat_export":
            result["quality"]["status"] = "fail"
        state["status"] = "failed"
        state["error"] = exc.as_dict()
        exit_code = exc.exit_code
    except Exception as exc:
        result["status"] = "failed"
        error = {"stage": "pipeline", "code": "internal_error", "message": repr(exc)}
        result["errors"].append(error)
        result["quality"]["status"] = "fail"
        state["status"] = "failed"
        state["error"] = error
        exit_code = 1
    finally:
        if sampler is not None:
            sampler.set_phase("cleanup")
            sampler.stop()
            memory = sampler.summary()
        else:
            memory = {}
        atomic_write_json(paths.runtime / "memory_summary.json", memory)
        result["runtime"]["memory"] = memory
        server_status_path = paths.llm / "server_status.json"
        if server_status_path.is_file():
            try:
                server_status = load_json(server_status_path)
                result["runtime"]["llm"]["request_count"] = max(
                    int(result["runtime"]["llm"].get("request_count", 0)),
                    int(server_status.get("request_count", 0)),
                )
                result["runtime"]["llm"]["successful_response_count"] = int(
                    server_status.get("successful_response_count", 0)
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
        result["runtime"]["finished_at"] = now_iso()
        result["runtime"]["total_elapsed_seconds"] = round(time.time() - started, 3)
        meeting_publication_dir = paths.root / ".meeting_publication.staging"
        if meeting_publication_dir.exists():
            shutil.rmtree(meeting_publication_dir)
        artifacts = collect_artifacts(paths)
        if not summary_published:
            for name in ("meeting_summary", "meeting_frontend", "meeting_display"):
                if name in artifacts:
                    artifacts[f"previous_{name}"] = artifacts.pop(name)
        if not compat_export_published:
            for name in ("compat_manifest", "compat_task_result"):
                if name in artifacts:
                    artifacts[f"previous_{name}"] = artifacts.pop(name)
        result["artifacts"] = artifacts
        write_stage_status(paths.stage_status, state)
        atomic_write_json(paths.meeting_result, result)
    return exit_code

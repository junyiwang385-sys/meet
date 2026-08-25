"""Process and stage lifecycle helpers used by the Harness orchestrator."""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import signal
import shutil
import subprocess
import time
from typing import Any

from ..storage.artifacts import (
    HarnessPaths,
    atomic_write_json,
    relative_artifact,
    write_stage_status,
)

def now_iso() -> str:
    """Return a stable UTC timestamp for business result and stage snapshots."""

    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_process_stage(
    name: str,
    command: list[str],
    log_path: pathlib.Path,
    sampler: Any,
    run_log: RunLogContext | None = None,
) -> dict[str, Any]:
    """运行一个子进程阶段，并把进程生命周期同步到结构化日志。"""

    # 子进程的 stdout/stderr 统一落到对应 .log 文件，既保留原始文本，也方便后续定位问题。
    log_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(log_path.with_suffix(".cmd.json"), command)
    sampler.set_phase(name)
    started = time.time()
    started_at = now_iso()
    process = None
    with log_path.open("wb") as handle:
        try:
            process = subprocess.Popen(
                command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
            # 进程一拿到 PID 就立刻写事件，后续即使崩溃，日志里也能知道它是否真正启动过。
            if run_log is not None:
                run_log.emit(
                    "process_started",
                    stage=name,
                    message=f"{name} 进程已启动",
                    details={
                        "pid": process.pid,
                        "command": command,
                        "log": str(log_path),
                    },
                )
            sampler.add_target(name, process.pid)
            return_code = process.wait()
        except BaseException as exc:
            # 任何异常都先尽力回收子进程，避免残留进程继续占着板端资源。
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
            if run_log is not None:
                run_log.emit(
                    "process_failed",
                    stage=name,
                    level="error",
                    message=f"{name} 进程在运行期间被中断",
                    duration_ms=int(round((time.time() - started) * 1000)),
                    error={"stage": name, "code": "process_failed", "message": repr(exc)},
                )
            raise
    elapsed_seconds = round(time.time() - started, 3)
    result = {
        "status": "succeeded" if return_code == 0 else "failed",
        "return_code": return_code,
        "elapsed_seconds": elapsed_seconds,
        "started_at": started_at,
        "finished_at": now_iso(),
        "command": command,
        "log": str(log_path),
    }
    if return_code != 0:
        result["log_tail"] = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
    if run_log is not None:
        run_log.emit(
            "process_exited",
            stage=name,
            level="info" if return_code == 0 else "error",
            message=f"{name} 进程已退出，返回码={return_code}",
            duration_ms=int(round(elapsed_seconds * 1000)),
            metrics={"return_code": return_code},
            details={"log": str(log_path)},
        )
    return result

def collect_artifacts(paths: HarnessPaths) -> dict[str, Any]:
    candidates = {
        "run_manifest": paths.run_manifest,
        "run_events": paths.run_events,
        "run_metrics": paths.run_metrics,
        "error_report": paths.error_report,
        "stage_status": paths.stage_status,
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


def finalize_run_artifacts(
    *,
    paths: HarnessPaths,
    result: dict[str, Any],
    state: dict[str, Any],
    run_log: Any,
    memory: dict[str, Any],
    summary_published: bool,
    compat_export_published: bool,
) -> dict[str, Any]:
    """Write metrics and final artifact refs without leaving a stale self-hash."""

    def collect_final() -> dict[str, Any]:
        artifacts = collect_artifacts(paths)
        if not summary_published:
            for name in ("meeting_summary", "meeting_frontend", "meeting_display"):
                if name in artifacts:
                    artifacts[f"previous_{name}"] = artifacts.pop(name)
        if not compat_export_published:
            for name in ("compat_manifest", "compat_task_result"):
                if name in artifacts:
                    artifacts[f"previous_{name}"] = artifacts.pop(name)
        return artifacts

    # First write creates run_metrics. The second write measures the complete
    # artifact set, including run_metrics itself. The final collection then
    # records the post-write size/hash in meeting_result.json.
    for _ in range(2):
        result["artifacts"] = collect_final()
        run_log.write_metrics(result=result, state=state, memory=memory)
    result["artifacts"] = collect_final()
    return result["artifacts"]


def mark_stage_running(
    name: str,
    state: dict[str, Any],
    paths: HarnessPaths,
    run_log: RunLogContext,
    details: dict[str, Any] | None = None,
) -> float:
    """把某个 stage 标成 running，并同步 stage_status.json 与结构化日志。"""

    stage = {"status": "running", "started_at": now_iso()}
    if details:
        stage.update(details)
    state["stages"][name] = stage
    state["current_stage"] = name
    write_stage_status(paths.stage_status, state)
    run_log.stage_started(name, details=details)
    return time.time()


def mark_stage_done(
    name: str,
    stage: dict[str, Any],
    state: dict[str, Any],
    result: dict[str, Any],
    paths: HarnessPaths,
    run_log: RunLogContext,
    *,
    started: float | None = None,
    status: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """把某个 stage 标成完成态，并把结果写回状态文件和运行结果。"""

    stage = dict(stage)
    if started is not None and "elapsed_seconds" not in stage:
        stage["elapsed_seconds"] = round(time.time() - started, 3)
    stage.setdefault("finished_at", now_iso())
    if status is not None:
        stage["status"] = status
    state["stages"][name] = stage
    result["runtime"]["stages"][name] = stage
    write_stage_status(paths.stage_status, state)
    if stage.get("status") == "succeeded":
        run_log.stage_succeeded(name, stage)
    elif stage.get("status") in {"reused", "skipped"}:
        run_log.stage_skipped(name, reason or str(stage.get("reason") or stage.get("status")), str(stage.get("status")))
    return stage


def mark_stage_failed(
    name: str,
    stage: dict[str, Any] | None,
    state: dict[str, Any],
    result: dict[str, Any],
    paths: HarnessPaths,
    run_log: RunLogContext,
    *,
    error: dict[str, Any],
    started: float | None = None,
) -> dict[str, Any]:
    """把某个 stage 标成失败态，并把标准化错误写回状态文件和运行结果。"""

    failed_stage = dict(stage or {})
    failed_stage["status"] = "failed"
    failed_stage["finished_at"] = now_iso()
    if started is not None:
        failed_stage["elapsed_seconds"] = round(time.time() - started, 3)
    elif isinstance(failed_stage.get("started_at"), str):
        try:
            started_at = dt.datetime.fromisoformat(str(failed_stage["started_at"]))
            failed_stage["elapsed_seconds"] = round((dt.datetime.now(dt.timezone.utc) - started_at).total_seconds(), 3)
        except ValueError:
            pass
    failed_stage["error"] = error
    state["stages"][name] = failed_stage
    result["runtime"]["stages"][name] = failed_stage
    write_stage_status(paths.stage_status, state)
    run_log.stage_failed(name, error, failed_stage)
    return failed_stage

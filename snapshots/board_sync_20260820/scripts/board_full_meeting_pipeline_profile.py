#!/usr/bin/env python3
"""Profile the full RK1828 meeting pipeline from source audio to summary JSON."""

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import time


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from board_meeting_chain_profile import (  # noqa: E402
    MemorySampler,
    discover_llm_files,
    log,
    terminate_process,
    wait_ready,
    write_json,
)
from board_timeline_summary_profile import (  # noqa: E402
    build_server_cmd,
    build_windows,
    parse_timeline,
    run_timeline,
)


DEFAULT_SCRIPTS_DIR = "/userdata/meeting_agent/scripts"
DEFAULT_3DSPEAKER_DIR = "/userdata/3D-Speaker"
DEFAULT_3DSPEAKER_PYTHON = "/userdata/miniforge3/envs/3dspeaker/bin/python"
DEFAULT_ASR_DIR = "/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_batch_demo"
DEFAULT_ASR_MODEL_DIR = "/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn"
DEFAULT_LLM_MODEL_DIR = "/userdata/meeting_agent/models/llm/v100/qwen25-7b-ctx8k-v100"
DEFAULT_SERVER = "/usr/bin/rkllm3-server"


def is_relative_to(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def prepare_out_dir(path, source_audio, overwrite):
    out_dir = pathlib.Path(path).resolve()
    source_audio = pathlib.Path(source_audio).resolve()
    if out_dir == pathlib.Path(out_dir.anchor):
        raise ValueError("refusing filesystem root as out-dir")
    if source_audio == out_dir or is_relative_to(source_audio, out_dir):
        raise ValueError("source audio cannot be inside out-dir")
    if out_dir.exists() and any(out_dir.iterdir()):
        if not overwrite:
            raise FileExistsError(f"out-dir is not empty: {out_dir}; use --overwrite")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def run_process_stage(name, cmd, log_path, sampler, cwd=None):
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(log_path.with_suffix(".cmd.json"), cmd)
    sampler.set_phase(name)
    started = time.time()
    log(f"[{name}] start")
    log(f"[{name}] command={' '.join(str(item) for item in cmd)}")
    with log_path.open("wb") as fh:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=fh,
            stderr=subprocess.STDOUT,
        )
        sampler.add_target(name, proc.pid)
        return_code = proc.wait()
    elapsed = round(time.time() - started, 3)
    result = {
        "name": name,
        "return_code": return_code,
        "elapsed_seconds": elapsed,
        "log": str(log_path),
        "cmd": [str(item) for item in cmd],
    }
    log(f"[{name}] done rc={return_code} elapsed={elapsed}s")
    if return_code != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
        result["log_tail"] = tail
    return result


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run and profile source audio -> diarization -> batch ASR -> meeting summary."
    )
    parser.add_argument("--source-audio", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--resume-from-asr", action="store_true", help="Reuse existing 01_segments and 02_batch_asr, then rerun only LLM")
    parser.add_argument("--scripts-dir", default=DEFAULT_SCRIPTS_DIR)

    parser.add_argument("--3dspeaker-dir", default=DEFAULT_3DSPEAKER_DIR)
    parser.add_argument("--3dspeaker-python", default=DEFAULT_3DSPEAKER_PYTHON)
    parser.add_argument("--pad", type=float, default=1.0)
    parser.add_argument("--absorb-unknown-max", type=float, default=2.0)
    parser.add_argument("--max-known-segment", type=float, default=30.0)
    parser.add_argument("--max-unknown-segment", type=float, default=20.0)
    parser.add_argument("--trim-duration", type=float, default=0.0)

    parser.add_argument("--asr-dir", default=DEFAULT_ASR_DIR)
    parser.add_argument("--asr-model-dir", default=DEFAULT_ASR_MODEL_DIR)
    parser.add_argument("--encoder-core", default="0xff")
    parser.add_argument("--asr-llm-core", default="0xff")

    parser.add_argument("--model-dir", default=DEFAULT_LLM_MODEL_DIR)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18245)
    parser.add_argument("--ctx", type=int, default=8192)
    parser.add_argument("--predict", type=int, default=2048)
    parser.add_argument("--map-max-tokens", type=int, default=512)
    parser.add_argument("--reduce-max-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--server-temp", type=float, default=0.0)
    parser.add_argument("--server-top-k", type=int, default=1)
    parser.add_argument("--server-top-p", type=float, default=1.0)
    parser.add_argument("--server-repeat-penalty", type=float, default=1.05)
    parser.add_argument("--ready-timeout", type=int, default=300)
    parser.add_argument("--request-timeout", type=int, default=1200)
    parser.add_argument("--core-window-seconds", type=float, default=300.0)
    parser.add_argument("--context-margin-seconds", type=float, default=30.0)
    parser.add_argument("--sample-interval", type=float, default=0.2)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.predict < max(args.map_max_tokens, args.reduce_max_tokens):
        raise ValueError("predict must cover map/reduce max tokens")

    if args.resume_from_asr:
        out_dir = pathlib.Path(args.out_dir).resolve()
        if not out_dir.is_dir():
            raise FileNotFoundError(f"resume out-dir not found: {out_dir}")
    else:
        out_dir = prepare_out_dir(args.out_dir, args.source_audio, args.overwrite)
    logs_dir = out_dir / "logs"
    segment_out = out_dir / "01_segments"
    asr_out = out_dir / "02_batch_asr"
    llm_out = out_dir / "03_llm_summary"
    if args.resume_from_asr:
        for name in ("pipeline_summary.json", "memory_summary.json", "run_config.json"):
            source = out_dir / name
            if source.is_file():
                shutil.copy2(source, out_dir / f"{source.stem}_before_resume{source.suffix}")
        if llm_out.exists():
            shutil.rmtree(llm_out)
    scripts_dir = pathlib.Path(args.scripts_dir)
    prepare_script = scripts_dir / "board_3dspeaker_segment_prepare_absorb_unknown.py"
    asr_script = scripts_dir / "board_segment_asr_batch.py"

    for path in (prepare_script, asr_script):
        if not path.is_file():
            raise FileNotFoundError(f"missing board script: {path}")

    write_json(out_dir / "run_config.json", vars(args))
    sampler = MemorySampler(out_dir / "memory_samples.jsonl", args.sample_interval)
    sampler.start()
    pipeline = {
        "status": "unknown",
        "source_audio": args.source_audio,
        "out_dir": str(out_dir),
        "stages": {},
    }
    server_proc = None
    server_log = None
    exit_code = 1
    started_all = time.time()
    try:
        segment_summary_path = segment_out / "board_3dspeaker_segment_summary.json"
        asr_summary_path = asr_out / "batch_asr_summary.json"
        if args.resume_from_asr:
            pipeline["stages"]["diarization_prepare"] = {"status": "reused"}
            pipeline["stages"]["batch_asr"] = {"status": "reused"}
            for path in (segment_summary_path, asr_summary_path, asr_out / "llm_input_timeline.txt"):
                if not path.is_file():
                    raise FileNotFoundError(f"resume artifact missing: {path}")
        else:
            prepare_cmd = [
                args.__dict__["3dspeaker_python"],
                str(prepare_script),
                "--source-audio", args.source_audio,
                "--out-dir", str(segment_out),
                "--3dspeaker-dir", args.__dict__["3dspeaker_dir"],
                "--python", args.__dict__["3dspeaker_python"],
                "--pad", str(args.pad),
                "--absorb-unknown-max", str(args.absorb_unknown_max),
                "--max-known-segment", str(args.max_known_segment),
                "--max-unknown-segment", str(args.max_unknown_segment),
                "--overwrite",
            ]
            if args.trim_duration > 0:
                prepare_cmd.extend(["--trim-duration", str(args.trim_duration)])
            prepare_result = run_process_stage(
                "diarization_prepare",
                prepare_cmd,
                logs_dir / "01_diarization_prepare.log",
                sampler,
            )
            pipeline["stages"]["diarization_prepare"] = prepare_result
            if prepare_result["return_code"] != 0:
                pipeline["status"] = "diarization_failed"
                return 2

            segment_summary = json.loads(segment_summary_path.read_text(encoding="utf-8"))
            asr_cmd = [
                sys.executable,
                str(asr_script),
                "--wav-dir", segment_summary["wav_segments_dir"],
                "--manifest", segment_summary["cut_segments_csv"],
                "--out-dir", str(asr_out),
                "--asr-dir", args.asr_dir,
                "--asr-model-dir", args.asr_model_dir,
                "--encoder-core", args.encoder_core,
                "--llm-core", args.asr_llm_core,
                "--overwrite",
            ]
            asr_result = run_process_stage(
                "batch_asr",
                asr_cmd,
                logs_dir / "02_batch_asr.log",
                sampler,
            )
            pipeline["stages"]["batch_asr"] = asr_result
            if asr_result["return_code"] != 0:
                pipeline["status"] = "asr_failed"
                return 3

        segment_summary = json.loads(segment_summary_path.read_text(encoding="utf-8"))
        pipeline["segment_summary"] = segment_summary
        asr_summary = json.loads(asr_summary_path.read_text(encoding="utf-8"))
        pipeline["asr_summary"] = asr_summary
        timeline_path = asr_out / "llm_input_timeline.txt"
        rows, stats = parse_timeline(timeline_path)
        llm_out.mkdir(parents=True, exist_ok=True)
        write_json(llm_out / "input_stats.json", stats)
        meeting_end = stats["end_seconds"]
        windows = build_windows(
            meeting_end,
            args.core_window_seconds,
            args.context_margin_seconds,
        )
        write_json(llm_out / "windows.json", windows)

        files = discover_llm_files(args.model_dir)
        server_cmd = build_server_cmd(args, files)
        write_json(llm_out / "llm_cmd.json", server_cmd)
        llm_out.mkdir(parents=True, exist_ok=True)
        server_log = (llm_out / "rkllm_server.log").open("wb")
        sampler.set_phase("llm_server_start")
        llm_start = time.time()
        server_proc = subprocess.Popen(
            server_cmd,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        sampler.add_target("rkllm_server", server_proc.pid)
        ready = wait_ready(args.host, args.port, args.ready_timeout)
        pipeline["stages"]["llm_server_start"] = {
            "pid": server_proc.pid,
            "ready_seconds": ready,
            "elapsed_seconds": round(time.time() - llm_start, 3),
            "log": str(llm_out / "rkllm_server.log"),
        }
        if ready is None:
            pipeline["status"] = "llm_server_not_ready"
            return 4

        llm_result = run_timeline(
            "asr",
            rows,
            stats,
            windows,
            args,
            llm_out,
            sampler,
        )
        pipeline["stages"]["llm_summary"] = llm_result
        if llm_result.get("status") != "ok":
            pipeline["status"] = "llm_summary_failed"
            return 5

        pipeline["status"] = "ok"
        pipeline["outputs"] = {
            "segment_summary": str(segment_summary_path),
            "batch_asr_summary": str(asr_summary_path),
            "segment_transcripts": str(asr_out / "segment_transcripts.json"),
            "llm_input_timeline": str(timeline_path),
            "final_summary": str(llm_out / "asr" / "final_summary.json"),
            "llm_profile": str(llm_out / "asr" / "profile_summary.json"),
        }
        exit_code = 0
        return exit_code
    except Exception as exc:
        pipeline["status"] = "error"
        pipeline["error"] = repr(exc)
        log(f"[PIPELINE ERROR] {repr(exc)}")
        return 1
    finally:
        sampler.set_phase("cleanup")
        if server_proc is not None:
            terminate_process(server_proc)
        if server_log is not None:
            server_log.close()
        sampler.stop()
        pipeline["total_elapsed_seconds"] = round(time.time() - started_all, 3)
        memory = sampler.summary()
        pipeline["memory"] = memory
        write_json(out_dir / "memory_summary.json", memory)
        write_json(out_dir / "pipeline_summary.json", pipeline)
        log(
            f"[PIPELINE DONE] status={pipeline['status']} "
            f"elapsed={pipeline['total_elapsed_seconds']}s "
            f"board_peak={memory.get('board_used_peak_mb')}MB out={out_dir}"
        )


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Board-only full pipeline test with a prefix-limited LLM input.

This is not the formal Meeting Harness entry point. Diarization and Batch ASR run
on the complete source audio. Only the LLM input is limited to whole leading
segments so an 8K model can be tested without pretending to summarize the full
meeting.
"""

from __future__ import annotations

import argparse
import http.client
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .artifacts import atomic_write_json, atomic_write_text, load_json
from .llm import (
    LlmConfig,
    LlmRunError,
    SUMMARY_SHAPE,
    build_server_cmd,
    discover_model_files,
    ensure_port_available,
    load_board_helpers,
    log_reports_truncation,
    extract_summary_content,
)
from .main import (
    DEFAULT_3DSPEAKER_DIR,
    DEFAULT_3DSPEAKER_PYTHON,
    DEFAULT_ASR_DIR,
    DEFAULT_ASR_MODEL_DIR,
    DEFAULT_BOARD_SCRIPTS_DIR,
    DEFAULT_SERVER,
)
from .pipeline import run_process_stage
from .transcript import prepare_transcript, render_timeline
from .validation import validate_llm_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run full diarization/ASR and summarize only a context-safe leading prefix."
    )
    parser.add_argument("--source-audio", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--resume-from-asr", action="store_true")
    parser.add_argument("--board-scripts-dir", default=DEFAULT_BOARD_SCRIPTS_DIR)

    parser.add_argument("--3dspeaker-dir", default=DEFAULT_3DSPEAKER_DIR)
    parser.add_argument("--3dspeaker-python", default=DEFAULT_3DSPEAKER_PYTHON)
    parser.add_argument("--pad", type=float, default=1.0)
    parser.add_argument("--absorb-unknown-max", type=float, default=2.0)
    parser.add_argument("--max-known-segment", type=float, default=30.0)
    parser.add_argument("--max-unknown-segment", type=float, default=20.0)

    parser.add_argument("--asr-dir", default=DEFAULT_ASR_DIR)
    parser.add_argument("--asr-model-dir", default=DEFAULT_ASR_MODEL_DIR)
    parser.add_argument("--encoder-core", default="0xff")
    parser.add_argument("--asr-llm-core", default="0xff")

    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18245)
    parser.add_argument("--ctx", type=int, default=8192)
    parser.add_argument("--predict", type=int, default=1536)
    parser.add_argument("--max-tokens", type=int, default=1536)
    parser.add_argument("--input-safety-tokens", type=int, default=768)
    parser.add_argument(
        "--input-chars-per-token",
        type=float,
        default=1.0,
        help="Conservative estimate for this test; 1.0 means at most one input character per token budget unit",
    )
    parser.add_argument("--ready-timeout", type=int, default=300)
    parser.add_argument("--request-timeout", type=int, default=1200)
    parser.add_argument("--sample-interval", type=float, default=0.2)
    args = parser.parse_args()

    if args.predict < args.max_tokens:
        parser.error("predict must be greater than or equal to max-tokens")
    if args.ctx <= args.max_tokens + args.input_safety_tokens:
        parser.error("ctx must exceed max-tokens plus input-safety-tokens")
    if args.input_chars_per_token <= 0:
        parser.error("input-chars-per-token must be positive")
    return args


def build_partial_messages(timeline: str, speakers: list[str], selection: dict) -> list[dict[str, str]]:
    shape = json.dumps(SUMMARY_SHAPE, ensure_ascii=False, indent=2)
    notice = (
        "这是一次 Pipeline 测试。以下内容只包含完整会议转写的前缀，不是整场会议。"
        "只能总结所提供的前缀，不得声称覆盖整场会议。"
    )
    user = (
        f"{notice}\n"
        f"本次覆盖时间：{selection['coverage_start_ms']}ms 至 {selection['coverage_end_ms']}ms。\n"
        f"允许的 speaker_id：{json.dumps(speakers, ensure_ascii=False)}\n"
        "请严格按下列 JSON 结构输出：\n"
        f"{shape}\n\n会议前缀时间线：\n{timeline}"
    )
    system = """你是会议事实整理器。本次输入只是会议开头的一部分，不是整场会议。
只能依据提供的会议前缀生成局部总结，不得声称覆盖整场会议。
只输出一个合法 JSON 对象，不要输出 Markdown、解释或代码围栏。
所有重要条目必须附带输入中真实存在的 segment_id refs。
不得虚构事实、负责人、截止时间、数字、决定或风险；没有依据时使用 null 或 []。"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def choose_prefix(segments: list[dict], character_budget: int) -> tuple[list[dict], str, dict]:
    selected = []
    for segment in segments:
        if not segment["text"]:
            continue
        candidate = render_timeline(selected + [segment])
        if len(candidate) > character_budget:
            break
        selected.append(segment)
    if not selected:
        raise ValueError("no complete non-empty segment fits the calculated LLM input budget")
    timeline = render_timeline(selected)
    nonempty_count = sum(bool(item["text"]) for item in segments)
    return selected, timeline, {
        "policy": "test-prefix-only",
        "character_budget": character_budget,
        "selected_characters": len(timeline),
        "selected_segment_count": len(selected),
        "omitted_nonempty_segment_count": nonempty_count - len(selected),
        "coverage_start_ms": selected[0]["start_ms"],
        "coverage_end_ms": selected[-1]["end_ms"],
        "is_partial": len(selected) < nonempty_count,
    }


def run_partial_llm(
    config: LlmConfig,
    messages: list[dict[str, str]],
    out_dir: pathlib.Path,
    sampler,
) -> dict:
    helpers = load_board_helpers(config.board_scripts_dir)
    files = discover_model_files(config.model_dir)
    ensure_port_available(config.host, config.port)
    command = build_server_cmd(config, files)
    payload = {
        "model": "default",
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": config.max_tokens,
        "response_format": {"type": "json_object"},
    }
    atomic_write_json(out_dir / "llm_cmd.json", command)
    atomic_write_json(out_dir / "messages.json", messages)
    atomic_write_json(out_dir / "request.json", payload)

    log_path = out_dir / "rkllm_server.log"
    process = None
    log_file = None
    ready_seconds = None
    request_seconds = None
    response = None
    started = time.time()
    try:
        log_file = log_path.open("wb")
        sampler.set_phase("llm_server_start")
        process = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)
        sampler.add_target("rkllm_server", process.pid)
        ready_started = time.time()
        while time.time() - ready_started < config.ready_timeout:
            if process.poll() is not None:
                raise LlmRunError(f"rkllm3-server exited before ready; rc={process.returncode}")
            try:
                urllib.request.urlopen(
                    f"http://{config.host}:{config.port}/health", timeout=1
                ).read()
                ready_seconds = round(time.time() - ready_started, 3)
                break
            except Exception:
                time.sleep(1)
        if ready_seconds is None:
            raise LlmRunError("rkllm3-server ready timeout")

        sampler.set_phase("llm_partial_summary")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"http://{config.host}:{config.port}/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        request_started = time.time()
        try:
            raw = urllib.request.urlopen(request, timeout=config.request_timeout).read()
        except http.client.IncompleteRead as exc:
            atomic_write_text(out_dir / "response_http.txt", exc.partial.decode("utf-8", "replace"))
            raise LlmRunError("LLM HTTP response ended early") from exc
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            atomic_write_text(out_dir / "response_http.txt", body)
            raise LlmRunError(f"LLM HTTP error: {exc.code}") from exc
        request_seconds = round(time.time() - request_started, 3)
        raw_text = raw.decode("utf-8", "replace")
        atomic_write_text(out_dir / "response_http.txt", raw_text)
        response = json.loads(raw_text)
        atomic_write_json(out_dir / "response.json", response)
    finally:
        if process is not None:
            helpers.terminate_process(process)
        if log_file is not None:
            log_file.close()

    choice = response["choices"][0]
    raw_content = str(choice.get("message", {}).get("content") or "")
    atomic_write_text(out_dir / "response_content.txt", raw_content)
    content = extract_summary_content(raw_content)
    atomic_write_text(out_dir / "response_summary_content.txt", content)
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    return {
        "content": content,
        "finish_reason": choice.get("finish_reason"),
        "usage": response.get("usage"),
        "timings": response.get("timings"),
        "ready_seconds": ready_seconds,
        "request_seconds": request_seconds,
        "elapsed_seconds": round(time.time() - started, 3),
        "context_truncated": log_reports_truncation(log_text),
        "resolved_model_files": files,
    }


def main() -> int:
    args = parse_args()
    source = pathlib.Path(args.source_audio).resolve()
    out_dir = pathlib.Path(args.out_dir).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if out_dir.exists() and any(out_dir.iterdir()) and not args.overwrite and not args.resume_from_asr:
        raise FileExistsError(f"out-dir is not empty: {out_dir}")
    if args.overwrite and out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)
    segments_dir = out_dir / "01_segments"
    asr_dir = out_dir / "02_batch_asr"
    llm_dir = out_dir / "03_partial_llm_test"
    logs_dir = out_dir / "logs"
    llm_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    board_dir = pathlib.Path(args.board_scripts_dir)
    helpers = load_board_helpers(board_dir)
    sampler = helpers.MemorySampler(out_dir / "memory_samples.jsonl", args.sample_interval)
    sampler.start()
    stages = {}
    started = time.time()
    try:
        segment_summary_path = segments_dir / "board_3dspeaker_segment_summary.json"
        transcripts_path = asr_dir / "segment_transcripts.json"
        if args.resume_from_asr:
            if not segment_summary_path.is_file() or not transcripts_path.is_file():
                raise FileNotFoundError("resume requires existing segment summary and segment_transcripts.json")
            stages["segmentation"] = {"status": "reused"}
            stages["batch_asr"] = {"status": "reused"}
        else:
            prepare_cmd = [
                args.__dict__["3dspeaker_python"],
                str(board_dir / "board_3dspeaker_segment_prepare_absorb_unknown.py"),
                "--source-audio", str(source),
                "--out-dir", str(segments_dir),
                "--3dspeaker-dir", args.__dict__["3dspeaker_dir"],
                "--python", args.__dict__["3dspeaker_python"],
                "--pad", str(args.pad),
                "--absorb-unknown-max", str(args.absorb_unknown_max),
                "--max-known-segment", str(args.max_known_segment),
                "--max-unknown-segment", str(args.max_unknown_segment),
                "--overwrite",
            ]
            stages["segmentation"] = run_process_stage(
                "segmentation", prepare_cmd, logs_dir / "01_segmentation.log", sampler
            )
            if stages["segmentation"]["return_code"] != 0:
                raise RuntimeError("segmentation failed")
            segment_summary = load_json(segment_summary_path)
            asr_cmd = [
                sys.executable,
                str(board_dir / "board_segment_asr_batch.py"),
                "--wav-dir", segment_summary["wav_segments_dir"],
                "--manifest", segment_summary["cut_segments_csv"],
                "--out-dir", str(asr_dir),
                "--asr-dir", args.asr_dir,
                "--asr-model-dir", args.asr_model_dir,
                "--encoder-core", args.encoder_core,
                "--llm-core", args.asr_llm_core,
                "--overwrite",
            ]
            stages["batch_asr"] = run_process_stage(
                "batch_asr", asr_cmd, logs_dir / "02_batch_asr.log", sampler
            )
            if stages["batch_asr"]["return_code"] != 0:
                raise RuntimeError("Batch ASR failed")

        all_segments, transcript_stats, _ = prepare_transcript(
            transcripts_path,
            llm_dir / "canonical_segments.json",
            llm_dir / "full_timeline.txt",
        )
        static_messages = build_partial_messages("", transcript_stats["speaker_ids"], {
            "coverage_start_ms": 0,
            "coverage_end_ms": 0,
        })
        static_chars = sum(len(item["content"]) for item in static_messages)
        input_tokens = args.ctx - args.max_tokens - args.input_safety_tokens
        character_budget = int(input_tokens * args.input_chars_per_token) - static_chars
        selected, partial_timeline, selection = choose_prefix(all_segments, character_budget)
        atomic_write_text(llm_dir / "partial_timeline.txt", partial_timeline)
        atomic_write_json(llm_dir / "input_selection.json", selection)

        messages = build_partial_messages(
            partial_timeline,
            sorted({item["speaker_id"] for item in selected}),
            selection,
        )
        config = LlmConfig(
            board_scripts_dir=board_dir,
            model_dir=pathlib.Path(args.model_dir),
            server=pathlib.Path(args.server),
            host=args.host,
            port=args.port,
            ctx=args.ctx,
            predict=args.predict,
            max_tokens=args.max_tokens,
            temperature=0.0,
            server_temp=0.0,
            server_top_k=1,
            server_top_p=1.0,
            server_repeat_penalty=1.05,
            ready_timeout=args.ready_timeout,
            request_timeout=args.request_timeout,
        )
        llm_result = run_partial_llm(config, messages, llm_dir, sampler)
        summary, quality = validate_llm_result(
            llm_result["content"],
            llm_result["finish_reason"],
            selected,
            context_truncated=llm_result["context_truncated"],
        )
        quality["checks"]["full_meeting_coverage"] = not selection["is_partial"]
        quality["warnings"].append(
            "test-only partial summary; the LLM received only the leading transcript prefix"
        )
        atomic_write_json(out_dir / "partial_meeting_summary.json", summary)
        atomic_write_json(
            out_dir / "partial_pipeline_test_result.json",
            {
                "status": "ok",
                "test_scope": "full audio diarization and ASR; prefix-only LLM summary",
                "model_dir": args.model_dir,
                "stages": stages,
                "transcript": transcript_stats,
                "input_selection": selection,
                "summary": summary,
                "quality": quality,
                "llm": {key: value for key, value in llm_result.items() if key != "content"},
                "elapsed_seconds": round(time.time() - started, 3),
            },
        )
        return 0
    except Exception as exc:
        atomic_write_json(
            out_dir / "partial_pipeline_test_result.json",
            {
                "status": "failed",
                "test_scope": "full audio diarization and ASR; prefix-only LLM summary",
                "model_dir": args.model_dir,
                "stages": stages,
                "error": repr(exc),
                "elapsed_seconds": round(time.time() - started, 3),
            },
        )
        print(f"prefix pipeline test failed: {exc!r}", file=sys.stderr)
        return 1
    finally:
        sampler.stop()
        atomic_write_json(out_dir / "memory_summary.json", sampler.summary())


if __name__ == "__main__":
    raise SystemExit(main())

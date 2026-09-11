"""Run Meeting_Agent model-quality evaluation cases."""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# On the board the deployed Harness package is named ``harness``.  Alias it
# before importing evaluation helpers so local and board layouts share imports.
_EVALS_ROOT = pathlib.Path(__file__).resolve().parent
_DEPLOYMENT_ROOT = _EVALS_ROOT.parent
_HARNESS_ROOT_CANDIDATES = (
    _DEPLOYMENT_ROOT / "scripts",
    _DEPLOYMENT_ROOT,
)
for _harness_root in _HARNESS_ROOT_CANDIDATES:
    if (_harness_root / "harness").is_dir():
        if str(_harness_root) not in sys.path:
            sys.path.insert(0, str(_harness_root))
        import harness as _deployed_harness

        sys.modules.setdefault("meeting_harness", _deployed_harness)
        break

from .deterministic_grader import grade_summary, normalize_expected
from .llm_judge import DEFAULT_JUDGE_MODEL, JUDGE_PROMPT_VERSION, judge_summary

TIMELINE_LINE_RE = re.compile(
    r"^\[(seg-\d+)\]\[(\d+)m(\d{2})s-(\d+)m(\d{2})s\]\[([^\]]+)\]\s+(.*)$"
)


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    group: str
    category: str
    timeline_path: pathlib.Path
    expected_path: pathlib.Path
    metadata: dict[str, Any]


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def _atomic_write(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _atomic_text(path: pathlib.Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _parse_time(minutes: str, seconds: str) -> int:
    return (int(minutes) * 60 + int(seconds)) * 1000


def parse_timeline(path: pathlib.Path) -> tuple[list[dict[str, Any]], list[str], str]:
    segments = []
    speaker_ids = set()
    previous_index = -1
    lines = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        match = TIMELINE_LINE_RE.match(line)
        if not match:
            raise ValueError(f"invalid Timeline line {line_number}: {raw_line[:160]!r}")
        segment_id, start_m, start_s, end_m, end_s, speaker_id, text = match.groups()
        index = int(segment_id.rsplit("-", 1)[1])
        start_ms = _parse_time(start_m, start_s)
        end_ms = _parse_time(end_m, end_s)
        if index <= previous_index:
            raise ValueError(f"segment IDs are not increasing at line {line_number}")
        if end_ms <= start_ms:
            raise ValueError(f"segment has invalid time range at line {line_number}")
        if not text.strip():
            raise ValueError(f"segment has empty text at line {line_number}")
        segments.append({
            "segment_id": segment_id,
            "index": index,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "speaker_id": speaker_id,
            "text": text.strip(),
            "status": "ok",
        })
        speaker_ids.add(speaker_id)
        lines.append(line)
        previous_index = index
    if not segments:
        raise ValueError(f"Timeline is empty: {path}")
    return segments, sorted(speaker_ids), "\n".join(lines) + "\n"


def _manifest_cases(vcsum_root: pathlib.Path) -> list[EvalCase]:
    """Load only the five VCSum cases used for the formal evaluation."""
    cases: list[EvalCase] = []
    manifest_path = vcsum_root / "vcsum_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for group, items in manifest.get("groups", {}).items():
        for item in items:
            case_id = str(item["name"])
            cases.append(EvalCase(
                case_id=case_id,
                group="vcsum",
                category=str(item.get("category", group)),
                timeline_path=vcsum_root / item["timeline_file"],
                expected_path=vcsum_root / item["expected_file"],
                metadata=item,
            ))
    return cases


def _find_candidate_path(root: pathlib.Path, case_id: str) -> pathlib.Path | None:
    candidates = [
        root / case_id / "meeting_summary.json",
        root / case_id / "candidate_summary.json",
        root / f"{case_id}_summary" / "meeting_summary.json",
        root / f"{case_id}_summary" / "candidate_summary.json",
        root / f"{case_id}.json",
    ]
    return next((path for path in candidates if path.is_file()), None)


def _load_candidate(path: pathlib.Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"candidate summary must be a JSON object: {path}")
    return value


def _load_memory_helper(board_scripts_dir: pathlib.Path):
    helper_path = board_scripts_dir / "board_meeting_chain_profile.py"
    if not helper_path.is_file():
        raise FileNotFoundError(f"memory helper not found: {helper_path}")
    spec = importlib.util.spec_from_file_location("meeting_agent_eval_memory_helper", helper_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load memory helper: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_local_candidate(
    case: EvalCase,
    case_dir: pathlib.Path,
    segments: list[dict[str, Any]],
    speaker_ids: list[str],
    timeline: str,
    args: argparse.Namespace,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    started = time.time()
    runtime: dict[str, Any] = {"mode": "current_workflow", "status": "failed"}
    memory_sampler = None
    memory_summary: dict[str, Any] = {"status": "unavailable"}
    model_request_elapsed: list[float] = []
    original_request_method = None
    try:
        if str(_repo_root()) not in sys.path:
            sys.path.insert(0, str(_repo_root()))
        from meeting_harness import llm as llm_module
        from meeting_harness.llm import LlmConfig
        from meeting_harness.product_summary import ProductSummaryConfig, run_product_summary_stage

        original_request_method = llm_module.RkllmServerSession.request

        def timed_request(session, *request_args, **request_kwargs):
            request_started = time.perf_counter()
            try:
                return original_request_method(session, *request_args, **request_kwargs)
            finally:
                model_request_elapsed.append(round(time.perf_counter() - request_started, 3))

        # Capture only local rkllm request time; this excludes the remote Judge.
        llm_module.RkllmServerSession.request = timed_request

        try:
            memory_helper = _load_memory_helper(pathlib.Path(args.board_scripts_dir))
            memory_sampler = memory_helper.MemorySampler(
                case_dir / "runtime" / "memory_samples.jsonl",
                interval_s=args.sample_interval,
            )
            memory_sampler.start()
        except Exception as exc:
            memory_summary = {
                "status": "unavailable",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }

        config = ProductSummaryConfig(
            llm=LlmConfig(
                board_scripts_dir=pathlib.Path(args.board_scripts_dir),
                model_dir=pathlib.Path(args.model_dir),
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
            ),
            safety_tokens=args.input_safety_tokens,
            chars_per_token=args.input_chars_per_token,
            fixed_overhead_tokens=args.input_fixed_overhead_tokens,
            resume=args.resume_candidate,
        )
        run = run_product_summary_stage(
            config=config,
            segments=segments,
            speaker_ids=speaker_ids,
            timeline=timeline,
            out_dir=case_dir / "candidate_generation",
            sampler=memory_sampler,
        )
        candidate = run["summary"]
        if original_request_method is not None:
            llm_module.RkllmServerSession.request = original_request_method
            original_request_method = None
        if memory_sampler is not None:
            memory_sampler.stop()
            memory_summary = {"status": "success", **memory_sampler.summary()}
        _atomic_write(case_dir / "runtime" / "memory_summary.json", memory_summary)
        _atomic_write(case_dir / "candidate_summary.json", candidate)
        runtime.update({
            "status": "success",
            "elapsed_seconds": round(time.time() - started, 3),
            "llm_stage_elapsed_seconds": run.get("elapsed_seconds"),
            "llm_model_call_elapsed_seconds": round(sum(model_request_elapsed), 3),
            "llm_request_elapsed_seconds": model_request_elapsed,
            "policy": run.get("policy"),
            "request_count": run.get("request_count"),
            "validated_request_count": run.get("validated_request_count"),
            "context_truncated": run.get("quality", {}).get("checks", {}).get("context_not_truncated") is False,
            "memory": memory_summary,
            "summary_run": run,
        })
        return candidate, runtime
    except Exception as exc:
        if original_request_method is not None:
            llm_module.RkllmServerSession.request = original_request_method
            original_request_method = None
        if memory_sampler is not None:
            try:
                memory_sampler.stop()
                memory_summary = {"status": "success", **memory_sampler.summary()}
            except Exception as memory_exc:
                memory_summary = {
                    "status": "error",
                    "error": {"type": type(memory_exc).__name__, "message": str(memory_exc)},
                }
        _atomic_write(case_dir / "runtime" / "memory_summary.json", memory_summary)
        runtime.update({
            "elapsed_seconds": round(time.time() - started, 3),
            "llm_stage_elapsed_seconds": None,
            "llm_model_call_elapsed_seconds": round(sum(model_request_elapsed), 3),
            "llm_request_elapsed_seconds": model_request_elapsed,
            "memory": memory_summary,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        })
        _atomic_write(case_dir / "candidate_error.json", runtime)
        return None, runtime


def _mean(values: list[Any]) -> float | None:
    numeric = [
        value
        for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return round(sum(numeric) / len(numeric), 4) if numeric else None


def _aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    def collect(items: list[dict[str, Any]]) -> dict[str, Any]:
        grades = [item.get("deterministic", {}) for item in items if item.get("deterministic")]
        judges = [
            item.get("judge", {}).get("result", {}).get("result", {})
            for item in items
            if item.get("judge", {}).get("result", {}).get("status") == "success"
            and isinstance(item.get("judge", {}).get("result", {}).get("result"), dict)
        ]
        claim_counts = {"supported": 0, "partially_supported": 0, "unsupported": 0, "contradiction": 0}
        fact_counts = {"covered": 0, "partial": 0, "missing": 0}
        importance_weights = {"minor": 1.0, "major": 2.0, "critical": 3.0}
        covered_fact_weight = 0.0
        total_fact_weight = 0.0
        critical_claim_error_count = 0
        critical_error_count = 0
        for judge in judges:
            if isinstance(judge.get("critical_error_count"), (int, float)):
                critical_error_count += int(judge["critical_error_count"])
            for claim in judge.get("claim_evaluations", []):
                if not isinstance(claim, dict):
                    continue
                status = str(claim.get("status", ""))
                if status in claim_counts:
                    claim_counts[status] += 1
                if claim.get("severity") == "critical" and status in {"partially_supported", "unsupported", "contradiction"}:
                    critical_claim_error_count += 1
            for fact in judge.get("fact_coverage", []):
                if not isinstance(fact, dict):
                    continue
                status = str(fact.get("status", ""))
                if status not in fact_counts:
                    continue
                fact_counts[status] += 1
                weight = importance_weights.get(str(fact.get("importance", "major")), 2.0)
                total_fact_weight += weight
                if status == "covered":
                    covered_fact_weight += weight
                elif status == "partial":
                    covered_fact_weight += 0.5 * weight
        claim_total = sum(claim_counts.values())
        faithfulness = (
            (claim_counts["supported"] + 0.5 * claim_counts["partially_supported"]) / claim_total
            if claim_total
            else None
        )
        weighted_completeness = (
            covered_fact_weight / total_fact_weight if total_fact_weight else None
        )
        action_f1 = [grade["action_items"]["f1"] for grade in grades if grade.get("action_items", {}).get("applicable")]
        runtimes = [item.get("candidate", {}) for item in items if item.get("candidate", {}).get("status") == "success"]
        llm_times = [runtime.get("llm_stage_elapsed_seconds") for runtime in runtimes if isinstance(runtime.get("llm_stage_elapsed_seconds"), (int, float))]
        model_call_times = [runtime.get("llm_model_call_elapsed_seconds") for runtime in runtimes if isinstance(runtime.get("llm_model_call_elapsed_seconds"), (int, float))]
        memory_peaks = [runtime.get("memory", {}).get("board_used_peak_mb") for runtime in runtimes if isinstance(runtime.get("memory", {}).get("board_used_peak_mb"), (int, float))]
        request_counts = [runtime.get("request_count") for runtime in runtimes if isinstance(runtime.get("request_count"), (int, float))]
        return {
            "case_count": len(items),
            "candidate_success_count": sum(item.get("candidate", {}).get("status") == "success" for item in items),
            "pipeline_completion_rate": round(
                sum(item.get("candidate", {}).get("status") == "success" for item in items) / len(items),
                4,
            ) if items else None,
            "judge_success_count": len(judges),
            "faithfulness": round(faithfulness, 4) if faithfulness is not None else None,
            "weighted_completeness": round(weighted_completeness, 4) if weighted_completeness is not None else None,
            "claim_count": claim_total,
            "claim_status_counts": claim_counts,
            "fact_count": sum(fact_counts.values()),
            "fact_status_counts": fact_counts,
            "critical_error_count": critical_error_count,
            "critical_claim_error_count": critical_claim_error_count,
            "llm_stage_elapsed_seconds_mean": _mean(llm_times),
            "llm_stage_elapsed_seconds_max": max(llm_times) if llm_times else None,
            "llm_model_call_elapsed_seconds_mean": _mean(model_call_times),
            "llm_model_call_elapsed_seconds_max": max(model_call_times) if model_call_times else None,
            "memory_peak_mb_mean": _mean(memory_peaks),
            "memory_peak_mb_max": max(memory_peaks) if memory_peaks else None,
            "llm_request_count_mean": _mean(request_counts),
            "chapter_coverage": _mean([grade.get("coverage", {}).get("chapter_coverage", 0.0) for grade in grades]),
            "key_fact_recall": _mean([grade.get("key_facts", {}).get("recall", 0.0) for grade in grades]),
            "action_item_f1": _mean(action_f1),
            "action_item_applicable_cases": len(action_f1),
            "judge_factuality": _mean([judge.get("factuality", {}).get("score", 0) for judge in judges]),
            "judge_completeness": _mean([judge.get("completeness", {}).get("score", 0) for judge in judges]),
            "judge_structure": _mean([judge.get("structure", {}).get("score", 0) for judge in judges]),
            "judge_readability": _mean([judge.get("readability", {}).get("score", 0) for judge in judges]),
            "critical_error_case_count": sum(bool(judge.get("critical_error")) for judge in judges),
        }

    groups = {"all": collect(cases)}
    for group in sorted({item.get("group", "unknown") for item in cases}):
        groups[group] = collect([item for item in cases if item.get("group") == group])
    for category in sorted({item.get("category", "unknown") for item in cases}):
        groups[category] = collect([item for item in cases if item.get("category") == category])
    return {"groups": groups, "cases": cases}


def _markdown_report(aggregate: dict[str, Any]) -> str:
    def percent(value: Any) -> str:
        return f"{value * 100:.1f}%" if isinstance(value, (int, float)) else "N/A"

    lines = [
        "# Meeting_Agent Evaluation Report",
        "",
        "## Core quality metrics",
        "",
        "| Group | Meetings | Pipeline completion | Judge OK | Faithfulness | Weighted completeness | Critical errors |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in aggregate.get("groups", {}).items():
        lines.append(
            f"| {name} | {metrics.get('case_count', 0)} | "
            f"{percent(metrics.get('pipeline_completion_rate'))} | "
            f"{metrics.get('judge_success_count', 0)} | "
            f"{percent(metrics.get('faithfulness'))} | "
            f"{percent(metrics.get('weighted_completeness'))} | "
            f"{metrics.get('critical_error_count', 0)} |"
        )
    lines.extend(["", "## Meeting results", ""])
    for case in aggregate.get("cases", []):
        judge_record = case.get("judge", {}).get("result", {})
        judge = (judge_record.get("result") or {}) if isinstance(judge_record, dict) else {}
        lines.append(
            f"- **{case['case_id']}**: candidate={case.get('candidate', {}).get('status')}, "
            f"judge={judge_record.get('status', 'not_run') if isinstance(judge_record, dict) else 'not_run'}, "
            f"faithfulness={percent(judge.get('faithfulness', {}).get('rate'))}, "
            f"completeness={percent(judge.get('completeness', {}).get('weighted_coverage'))}, "
            f"critical-errors={judge.get('critical_error_count')}, "
            f"verdict={judge.get('verdict')}"
        )
    lines.extend(["", "## Runtime diagnostics", ""])
    all_metrics = aggregate.get("groups", {}).get("all", {})
    lines.append(f"- Mean local LLM call time: {all_metrics.get('llm_model_call_elapsed_seconds_mean')} s")
    lines.append(f"- Max memory peak: {all_metrics.get('memory_peak_mb_max')} MB")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", help="comma-separated VCSum case ids; default is all 5 cases")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output-root", default="output/evals")
    parser.add_argument(
        "--vcsum-root",
        default=str(_repo_root() / "data" / "vcsum"),
        help="directory containing vcsum_manifest.json, Timeline files and expected JSON",
    )
    parser.add_argument("--run-id")
    parser.add_argument("--candidate-summary-root")
    parser.add_argument("--candidate-summary", help="one JSON candidate summary; use with one selected case")
    parser.add_argument("--baseline-summary-root")
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--judge-max-tokens", type=int, default=8192)
    parser.add_argument("--judge-timeout", type=float, default=600.0)
    parser.add_argument("--prompt", default=str(_repo_root() / "evals" / "prompts" / "judge_v1.txt"))
    parser.add_argument("--board-scripts-dir", default="/userdata/meeting_agent/scripts")
    parser.add_argument("--model-dir", default="/userdata/meeting_agent/models/llm/v104/qwen3-4b-v104-ctx16k")
    parser.add_argument("--server", default="/usr/bin/rkllm3-server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18245)
    parser.add_argument("--ctx", type=int, default=16384)
    parser.add_argument("--predict", type=int, default=4096)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--input-safety-tokens", type=int, default=512)
    parser.add_argument("--input-chars-per-token", type=float, default=1.3)
    parser.add_argument("--input-fixed-overhead-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--server-temp", type=float, default=0.0)
    parser.add_argument("--server-top-k", type=int, default=1)
    parser.add_argument("--server-top-p", type=float, default=1.0)
    parser.add_argument("--server-repeat-penalty", type=float, default=1.05)
    parser.add_argument("--ready-timeout", type=int, default=300)
    parser.add_argument("--request-timeout", type=int, default=1200)
    parser.add_argument("--sample-interval", type=float, default=0.2)
    parser.add_argument("--resume-candidate", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    all_cases = _manifest_cases(pathlib.Path(args.vcsum_root).expanduser().resolve())
    selected_ids = {item.strip() for item in args.cases.split(",")} if args.cases else None
    cases = [case for case in all_cases if selected_ids is None or case.case_id in selected_ids]
    if selected_ids and {case.case_id for case in cases} != selected_ids:
        missing = sorted(selected_ids - {case.case_id for case in cases})
        raise SystemExit(f"unknown case id(s): {', '.join(missing)}")
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("no evaluation cases selected")
    if args.candidate_summary and len(cases) != 1:
        raise SystemExit("--candidate-summary requires exactly one selected case")
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = pathlib.Path(args.output_root).expanduser().resolve() / run_id
    if run_dir.exists() and any(run_dir.iterdir()):
        raise SystemExit(f"run directory is not empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": run_id, "judge_model": args.judge_model, "cases": [case.case_id for case in cases], "started_at": datetime.now(timezone.utc).isoformat()}
    _atomic_write(run_dir / "run_manifest.json", manifest)
    case_results: list[dict[str, Any]] = []
    prompt_path = pathlib.Path(args.prompt).expanduser().resolve()
    for case in cases:
        case_dir = run_dir / case.case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        try:
            segments, speaker_ids, timeline = parse_timeline(case.timeline_path)
            expected_raw = json.loads(case.expected_path.read_text(encoding="utf-8"))
            expected_normalized = normalize_expected(expected_raw)
            _atomic_text(case_dir / "timeline.txt", timeline)
            _atomic_write(case_dir / "expected.json", {"raw": expected_raw, "normalized": expected_normalized})
            _atomic_write(case_dir / "case_metadata.json", {"case_id": case.case_id, "group": case.group, "category": case.category, "metadata": case.metadata, "segment_count": len(segments), "speaker_ids": speaker_ids})
            candidate_path = pathlib.Path(args.candidate_summary).expanduser().resolve() if args.candidate_summary else (_find_candidate_path(pathlib.Path(args.candidate_summary_root).expanduser().resolve(), case.case_id) if args.candidate_summary_root else None)
            if candidate_path:
                candidate = _load_candidate(candidate_path)
                candidate_runtime = {"mode": "existing_candidate", "status": "success", "source": str(candidate_path)}
                _atomic_write(case_dir / "candidate_summary.json", candidate)
            elif args.candidate_summary_root:
                candidate = None
                candidate_runtime = {
                    "mode": "existing_candidate",
                    "status": "missing",
                    "source_root": str(pathlib.Path(args.candidate_summary_root).expanduser().resolve()),
                    "error": {"type": "candidate_missing", "message": f"No candidate summary found for {case.case_id}"},
                }
                _atomic_write(case_dir / "candidate_error.json", candidate_runtime)
            else:
                candidate, candidate_runtime = _run_local_candidate(case, case_dir, segments, speaker_ids, timeline, args)
            deterministic = grade_summary(candidate, segments, expected_raw, runtime=candidate_runtime)
            _atomic_write(case_dir / "deterministic_grade.json", deterministic)
            judge_bundle = {"request": None, "result": {"status": "skipped", "judge_model": args.judge_model, "prompt_version": JUDGE_PROMPT_VERSION, "error": {"type": "skipped"}}, "raw_response": None}
            if candidate is not None and not args.skip_judge:
                judge_bundle = judge_summary(timeline=timeline, expected=expected_normalized, candidate=candidate, prompt_path=prompt_path, model=args.judge_model, max_tokens=args.judge_max_tokens, timeout=args.judge_timeout)
            _atomic_write(case_dir / "judge_request.json", judge_bundle.get("request"))
            _atomic_write(case_dir / "judge_response_raw.json", judge_bundle.get("raw_response"))
            _atomic_write(case_dir / "judge_result.json", judge_bundle.get("result"))
            baseline_record = None
            if args.baseline_summary_root:
                baseline_path = _find_candidate_path(pathlib.Path(args.baseline_summary_root).expanduser().resolve(), case.case_id)
                if baseline_path:
                    baseline_candidate = _load_candidate(baseline_path)
                    baseline_runtime = {"mode": "baseline", "status": "success", "source": str(baseline_path)}
                    baseline_grade = grade_summary(baseline_candidate, segments, expected_raw, runtime=baseline_runtime)
                    _atomic_write(case_dir / "baseline_summary.json", baseline_candidate)
                    _atomic_write(case_dir / "baseline_deterministic_grade.json", baseline_grade)
                    baseline_record = {"candidate": baseline_runtime, "deterministic": baseline_grade}
                else:
                    baseline_record = {"candidate": {"mode": "baseline", "status": "missing"}, "deterministic": {}}
            case_results.append({"case_id": case.case_id, "group": case.group, "category": case.category, "candidate": candidate_runtime, "deterministic": deterministic, "judge": judge_bundle, "baseline": baseline_record})
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
            _atomic_write(case_dir / "case_error.json", error)
            case_results.append({"case_id": case.case_id, "group": case.group, "category": case.category, "candidate": {"status": "failed"}, "deterministic": {}, "judge": {"result": {"status": "not_run", "error": error}}})
    aggregate = _aggregate(case_results)
    baseline_cases = [item for item in case_results if item.get("baseline")]
    if baseline_cases:
        aggregate["baseline"] = _aggregate([{
            "case_id": item["case_id"],
            "group": item["group"],
            "category": item["category"],
            "candidate": item["baseline"].get("candidate", {}),
            "deterministic": item["baseline"].get("deterministic", {}),
            "judge": {"result": {"status": "skipped"}},
        } for item in baseline_cases])
    _atomic_write(run_dir / "aggregate.json", aggregate)
    _atomic_text(run_dir / "report.md", _markdown_report(aggregate))
    print(json.dumps({"status": "ok", "run_id": run_id, "run_dir": str(run_dir), "case_count": len(case_results)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

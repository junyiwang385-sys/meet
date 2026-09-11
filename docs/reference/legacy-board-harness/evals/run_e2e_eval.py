"""Run audio-to-summary end-to-end evaluation with a remote LLM Judge."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .deterministic_grader import grade_summary, normalize_expected
from .e2e_metrics import evaluate_timelines
from .textgrid import parse_textgrid, render_reference_timeline

JUDGE_PROMPT_VERSION = "judge_claim_fact_v2"
TIMELINE_LINE_RE = re.compile(
    r"^\[(seg-\d+)\]\[(\d+)m(\d{2})s-(\d+)m(\d{2})s\]\[([^\]]+)\]\s+(.*)$"
)


@dataclass(frozen=True)
class E2ECase:
    case_id: str
    group: str
    category: str
    audio_path: pathlib.Path
    reference_timeline_path: pathlib.Path
    expected_path: pathlib.Path
    pipeline_output_dir: pathlib.Path | None
    metadata: dict[str, Any]


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def _atomic_write(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _atomic_text(path: pathlib.Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def parse_timeline(path: pathlib.Path) -> tuple[list[dict[str, Any]], list[str], str]:
    segments = []
    speaker_ids = set()
    previous_index = -1
    lines = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        line = raw_line.strip()
        if not line:
            continue
        match = TIMELINE_LINE_RE.match(line)
        if not match:
            raise ValueError(f"invalid Timeline line {line_number}: {raw_line[:160]!r}")
        segment_id, start_m, start_s, end_m, end_s, speaker_id, text = match.groups()
        index = int(segment_id.rsplit("-", 1)[1])
        start_ms = (int(start_m) * 60 + int(start_s)) * 1000
        end_ms = (int(end_m) * 60 + int(end_s)) * 1000
        if index <= previous_index:
            raise ValueError(f"segment IDs are not increasing at line {line_number}")
        if end_ms <= start_ms:
            raise ValueError(f"segment has invalid time range at line {line_number}")
        if not text.strip():
            raise ValueError(f"segment has empty text at line {line_number}")
        segments.append(
            {
                "segment_id": segment_id,
                "index": index,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "speaker_id": speaker_id,
                "text": text.strip(),
                "status": "ok",
            }
        )
        speaker_ids.add(speaker_id)
        lines.append(line)
        previous_index = index
    if not segments:
        raise ValueError(f"Timeline is empty: {path}")
    return segments, sorted(speaker_ids), "\n".join(lines) + "\n"


def load_reference(path: pathlib.Path) -> tuple[list[dict[str, Any]], list[str], str]:
    if path.suffix.lower() == ".textgrid":
        segments, speakers = parse_textgrid(path)
        if not segments:
            raise ValueError(
                f"TextGrid contains no non-empty reference intervals: {path}"
            )
        return segments, speakers, render_reference_timeline(segments)
    return parse_timeline(path)


def _resolve(root: pathlib.Path, value: Any) -> pathlib.Path:
    path = pathlib.Path(str(value)).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def load_manifest(
    path: pathlib.Path, dataset_root: pathlib.Path | None = None
) -> list[E2ECase]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if dataset_root is not None:
        root = dataset_root.resolve()
    elif document.get("dataset_root"):
        root = _resolve(path.parent.resolve(), document["dataset_root"])
    else:
        root = path.parent.resolve()
    records: list[tuple[str, dict[str, Any]]] = []
    if isinstance(document.get("cases"), list):
        records.extend(
            ("e2e", item) for item in document["cases"] if isinstance(item, dict)
        )
    for group, items in document.get("groups", {}).items():
        if isinstance(items, list):
            records.extend(
                (str(group), item) for item in items if isinstance(item, dict)
            )
    cases = []
    for default_group, item in records:
        case_id = str(item.get("name") or item.get("case_id") or "").strip()
        if not case_id:
            raise ValueError("every manifest case requires name or case_id")
        required = ("audio_file", "reference_timeline_file", "expected_file")
        missing = [name for name in required if not item.get(name)]
        if missing:
            raise ValueError(f"{case_id}: missing manifest fields: {missing}")
        pipeline_value = item.get("pipeline_output_dir")
        cases.append(
            E2ECase(
                case_id=case_id,
                group=str(item.get("group") or default_group),
                category=str(item.get("category") or default_group),
                audio_path=_resolve(root, item["audio_file"]),
                reference_timeline_path=_resolve(root, item["reference_timeline_file"]),
                expected_path=_resolve(root, item["expected_file"]),
                pipeline_output_dir=_resolve(root, pipeline_value)
                if pipeline_value
                else None,
                metadata=item,
            )
        )
    if not cases:
        raise ValueError(f"manifest contains no cases: {path}")
    duplicate_ids = [
        name
        for name, count in Counter(case.case_id for case in cases).items()
        if count > 1
    ]
    if duplicate_ids:
        raise ValueError(f"duplicate case ids: {', '.join(sorted(duplicate_ids))}")
    return cases


def _load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _numeric(value: Any) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _mean(values: list[Any]) -> float | None:
    numbers = [_numeric(value) for value in values]
    numbers = [value for value in numbers if value is not None]
    return round(sum(numbers) / len(numbers), 4) if numbers else None


def _sum_request_elapsed(meeting_result: dict[str, Any]) -> float | None:
    requests = meeting_result.get("runtime", {}).get("llm", {}).get("requests", [])
    values = [
        _numeric(item.get("request_elapsed_seconds"))
        for item in requests
        if isinstance(item, dict)
    ]
    values = [value for value in values if value is not None]
    return round(sum(values), 3) if values else None


def _pipeline_runtime(
    meeting_result: dict[str, Any], pipeline_dir: pathlib.Path
) -> dict[str, Any]:
    runtime = (
        meeting_result.get("runtime", {}) if isinstance(meeting_result, dict) else {}
    )
    stages = (
        runtime.get("stages", {}) if isinstance(runtime.get("stages"), dict) else {}
    )
    llm = runtime.get("llm", {}) if isinstance(runtime.get("llm"), dict) else {}
    status = "success" if meeting_result.get("status") == "ok" else "failed"
    return {
        "mode": "end_to_end_pipeline",
        "status": status,
        "source": str(pipeline_dir),
        "elapsed_seconds": runtime.get("total_elapsed_seconds"),
        "llm_stage_elapsed_seconds": stages.get("llm_summary", {}).get(
            "elapsed_seconds"
        ),
        "llm_model_call_elapsed_seconds": _sum_request_elapsed(meeting_result),
        "request_count": llm.get("request_count"),
        "validated_request_count": llm.get("validated_request_count"),
        "policy": runtime.get("context_policy"),
        "context_truncated": any(
            bool(item.get("context_truncated"))
            for item in llm.get("requests", [])
            if isinstance(item, dict)
        ),
        "memory": runtime.get("memory", {}),
        "stages": stages,
        "errors": meeting_result.get("errors", []),
    }


def _pipeline_command(
    args: argparse.Namespace, case: E2ECase, pipeline_dir: pathlib.Path
) -> list[str]:
    command = [
        args.python,
        "-m",
        args.harness_module,
        "--source-audio",
        str(case.audio_path),
        "--out-dir",
        str(pipeline_dir),
        "--board-scripts-dir",
        args.board_scripts_dir,
        "--3dspeaker-dir",
        args.__dict__["3dspeaker_dir"],
        "--3dspeaker-python",
        args.__dict__["3dspeaker_python"],
        "--pad",
        str(args.pad),
        "--absorb-unknown-max",
        str(args.absorb_unknown_max),
        "--max-known-segment",
        str(args.max_known_segment),
        "--max-unknown-segment",
        str(args.max_unknown_segment),
        "--asr-dir",
        args.asr_dir,
        "--asr-model-dir",
        args.asr_model_dir,
        "--encoder-core",
        args.encoder_core,
        "--asr-llm-core",
        args.asr_llm_core,
        "--model-dir",
        args.model_dir,
        "--server",
        args.server,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--ctx",
        str(args.ctx),
        "--predict",
        str(args.predict),
        "--max-tokens",
        str(args.max_tokens),
        "--input-safety-tokens",
        str(args.input_safety_tokens),
        "--input-chars-per-token",
        str(args.input_chars_per_token),
        "--input-fixed-overhead-tokens",
        str(args.input_fixed_overhead_tokens),
        "--temperature",
        str(args.temperature),
        "--server-temp",
        str(args.server_temp),
        "--server-top-k",
        str(args.server_top_k),
        "--server-top-p",
        str(args.server_top_p),
        "--server-repeat-penalty",
        str(args.server_repeat_penalty),
        "--ready-timeout",
        str(args.ready_timeout),
        "--request-timeout",
        str(args.request_timeout),
        "--sample-interval",
        str(args.sample_interval),
        "--resume" if args.resume_pipeline else "--overwrite",
    ]
    return command


def _run_pipeline(
    args: argparse.Namespace,
    case: E2ECase,
    case_dir: pathlib.Path,
) -> tuple[pathlib.Path, dict[str, Any]]:
    if case.pipeline_output_dir is not None:
        pipeline_dir = case.pipeline_output_dir
        reused = True
    elif args.pipeline_output_root:
        pipeline_dir = (
            pathlib.Path(args.pipeline_output_root).expanduser().resolve()
            / case.case_id
        )
        reused = args.reuse_pipeline
    else:
        pipeline_dir = case_dir / "pipeline"
        reused = False

    command = None
    return_code = None
    elapsed_seconds = None
    if not reused:
        command = _pipeline_command(args, case, pipeline_dir)
        _atomic_write(case_dir / "pipeline_command.json", command)
        log_path = case_dir / "pipeline.log"
        started = time.time()
        with log_path.open("wb") as log_handle:
            completed = subprocess.run(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                check=False,
                cwd=args.board_scripts_dir,
            )
        elapsed_seconds = round(time.time() - started, 3)
        return_code = completed.returncode

    meeting_result_path = pipeline_dir / "meeting_result.json"
    if meeting_result_path.is_file():
        meeting_result = _load_json(meeting_result_path)
    else:
        meeting_result = {
            "status": "failed",
            "runtime": {
                "total_elapsed_seconds": elapsed_seconds,
                "stages": {},
                "memory": {},
            },
            "errors": [
                {
                    "stage": "pipeline",
                    "code": "missing_meeting_result",
                    "message": str(meeting_result_path),
                }
            ],
        }
    record = {
        "reused": reused,
        "pipeline_dir": str(pipeline_dir),
        "command": command,
        "return_code": return_code,
        "runner_elapsed_seconds": elapsed_seconds,
        "meeting_result": meeting_result,
    }
    _atomic_write(case_dir / "pipeline_record.json", record)
    return pipeline_dir, meeting_result


def _collect_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    judges = [
        item.get("judge", {}).get("result", {}).get("result", {})
        for item in items
        if item.get("judge", {}).get("result", {}).get("status") == "success"
        and isinstance(item.get("judge", {}).get("result", {}).get("result"), dict)
    ]
    claims = {
        "supported": 0,
        "partially_supported": 0,
        "unsupported": 0,
        "contradiction": 0,
    }
    facts = {"covered": 0, "partial": 0, "missing": 0}
    core_facts = {"covered": 0, "partial": 0, "missing": 0}
    legacy_facts = {"covered": 0, "partial": 0, "missing": 0}
    weights = {"minor": 1.0, "major": 2.0, "critical": 3.0}
    core_covered_weight = 0.0
    core_total_weight = 0.0
    legacy_covered_weight = 0.0
    legacy_total_weight = 0.0
    core_case_rates = []
    legacy_case_rates = []
    critical_error_count = 0
    critical_claim_error_count = 0
    for judge in judges:
        if isinstance(judge.get("critical_error_count"), (int, float)):
            critical_error_count += int(judge["critical_error_count"])
        for claim in judge.get("claim_evaluations", []):
            if not isinstance(claim, dict):
                continue
            status = str(claim.get("status", ""))
            if status in claims:
                claims[status] += 1
            if claim.get("severity") == "critical" and status in {
                "partially_supported",
                "unsupported",
                "contradiction",
            }:
                critical_claim_error_count += 1
        coverage_metric = judge.get("coverage_metric", {})
        if not isinstance(coverage_metric, dict):
            coverage_metric = {}
        metric_name = coverage_metric.get("name")
        is_core = metric_name == "core_content_coverage"
        case_covered_weight = 0.0
        case_total_weight = 0.0
        for fact in judge.get("fact_coverage", []):
            if not isinstance(fact, dict):
                continue
            status = str(fact.get("status", ""))
            if status not in facts:
                continue
            facts[status] += 1
            weight = weights.get(str(fact.get("importance", "major")), 2.0)
            case_total_weight += weight
            if status == "covered":
                case_covered_weight += weight
            elif status == "partial":
                case_covered_weight += 0.5 * weight
            target_facts = core_facts if is_core else legacy_facts
            target_facts[status] += 1
        if case_total_weight:
            case_rate = case_covered_weight / case_total_weight
            if is_core:
                core_covered_weight += case_covered_weight
                core_total_weight += case_total_weight
                core_case_rates.append(case_rate)
            else:
                legacy_covered_weight += case_covered_weight
                legacy_total_weight += case_total_weight
                legacy_case_rates.append(case_rate)
    claim_count = sum(claims.values())
    faithfulness = (
        (claims["supported"] + 0.5 * claims["partially_supported"]) / claim_count
        if claim_count
        else None
    )
    successful = sum(
        item.get("candidate", {}).get("status") == "success" for item in items
    )
    core_content_coverage = (
        core_covered_weight / core_total_weight if core_total_weight else None
    )
    legacy_weighted_completeness = (
        legacy_covered_weight / legacy_total_weight if legacy_total_weight else None
    )
    return {
        "case_count": len(items),
        "candidate_success_count": successful,
        "pipeline_completion_rate": round(successful / len(items), 4)
        if items
        else None,
        "judge_success_count": len(judges),
        "faithfulness": round(faithfulness, 4) if faithfulness is not None else None,
        "core_content_coverage": round(core_content_coverage, 4)
        if core_content_coverage is not None
        else None,
        "core_content_coverage_macro": round(sum(core_case_rates) / len(core_case_rates), 4)
        if core_case_rates
        else None,
        "core_content_coverage_case_count": len(core_case_rates),
        "core_content_fact_count": sum(core_facts.values()),
        "core_content_fact_status_counts": core_facts,
        "core_content_credited_weight": round(core_covered_weight, 4),
        "core_content_total_weight": round(core_total_weight, 4),
        "legacy_weighted_completeness": round(legacy_weighted_completeness, 4)
        if legacy_weighted_completeness is not None
        else None,
        "legacy_completeness_case_count": len(legacy_case_rates),
        "weighted_completeness": round(legacy_weighted_completeness, 4)
        if legacy_weighted_completeness is not None and not core_case_rates
        else None,
        "claim_count": claim_count,
        "claim_status_counts": claims,
        "fact_count": sum(facts.values()),
        "fact_status_counts": facts,
        "critical_error_count": critical_error_count,
        "critical_claim_error_count": critical_claim_error_count,
        "critical_error_case_count": sum(
            bool(judge.get("critical_error")) for judge in judges
        ),
    }


def _aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {"all": _collect_summary(cases)}
    for group in sorted({item.get("group", "unknown") for item in cases}):
        groups[group] = _collect_summary(
            [item for item in cases if item.get("group") == group]
        )
    for category in sorted({item.get("category", "unknown") for item in cases}):
        if category not in groups:
            groups[category] = _collect_summary(
                [item for item in cases if item.get("category") == category]
            )
    return {"groups": groups, "cases": cases}


def _collect_e2e(items: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [
        item for item in items if item.get("candidate", {}).get("status") == "success"
    ]
    timeline_results = [
        item["e2e"]["timeline_metrics"]
        for item in items
        if item.get("e2e", {}).get("timeline_metrics", {}).get("status") == "success"
    ]
    text_results = [item["text"] for item in timeline_results]
    total_reference_chars = sum(
        int(item.get("reference_chars", 0)) for item in text_results
    )
    total_edit_distance = sum(
        int(item.get("edit_distance", 0)) for item in text_results
    )
    stage_names = sorted(
        {
            stage_name
            for item in items
            for stage_name in item.get("candidate", {}).get("stages", {})
        }
    )
    stage_elapsed_means = {
        stage_name: _mean(
            [
                item.get("candidate", {})
                .get("stages", {})
                .get(stage_name, {})
                .get("elapsed_seconds")
                for item in items
            ]
        )
        for stage_name in stage_names
    }
    failures = Counter()
    for item in items:
        if item.get("candidate", {}).get("status") == "success":
            continue
        errors = item.get("candidate", {}).get("errors", [])
        if not errors:
            failures["unknown"] += 1
        for error in errors:
            if isinstance(error, dict):
                failures[
                    f"{error.get('stage', 'unknown')}:{error.get('code', 'unknown')}"
                ] += 1
    return {
        "pipeline_success_count": len(successful),
        "pipeline_completion_rate": round(len(successful) / len(items), 4)
        if items
        else None,
        "timeline_evaluated_count": len(timeline_results),
        "cer_corpus": round(total_edit_distance / total_reference_chars, 6)
        if total_reference_chars
        else None,
        "cer_macro": _mean([item.get("cer") for item in text_results]),
        "speech_recall_macro": _mean(
            [item["speech"].get("recall") for item in timeline_results]
        ),
        "speech_precision_macro": _mean(
            [item["speech"].get("precision") for item in timeline_results]
        ),
        "speaker_accuracy_macro": _mean(
            [item["speaker"].get("accuracy_on_overlap") for item in timeline_results]
        ),
        "speaker_count_mae": _mean(
            [item["speaker"].get("absolute_count_error") for item in timeline_results]
        ),
        "unknown_speech_ratio_macro": _mean(
            [item["timeline"].get("unknown_speech_ratio") for item in timeline_results]
        ),
        "total_elapsed_seconds_mean": _mean(
            [item.get("candidate", {}).get("elapsed_seconds") for item in items]
        ),
        "total_elapsed_seconds_max": max(
            [
                item.get("candidate", {}).get("elapsed_seconds")
                for item in items
                if _numeric(item.get("candidate", {}).get("elapsed_seconds"))
                is not None
            ],
            default=None,
        ),
        "llm_model_call_elapsed_seconds_mean": _mean(
            [
                item.get("candidate", {}).get("llm_model_call_elapsed_seconds")
                for item in items
            ]
        ),
        "memory_peak_mb_mean": _mean(
            [
                item.get("candidate", {}).get("memory", {}).get("board_used_peak_mb")
                for item in items
            ]
        ),
        "memory_peak_mb_max": max(
            [
                item.get("candidate", {}).get("memory", {}).get("board_used_peak_mb")
                for item in items
                if _numeric(
                    item.get("candidate", {})
                    .get("memory", {})
                    .get("board_used_peak_mb")
                )
                is not None
            ],
            default=None,
        ),
        "stage_elapsed_seconds_mean": stage_elapsed_means,
        "failure_counts": dict(failures),
    }


def _add_e2e_aggregates(aggregate: dict[str, Any], cases: list[dict[str, Any]]) -> None:
    for name, metrics in aggregate.get("groups", {}).items():
        if name == "all":
            selected = cases
        else:
            selected = [
                item
                for item in cases
                if item.get("group") == name or item.get("category") == name
            ]
        metrics["e2e"] = _collect_e2e(selected)


def _percent(value: Any) -> str:
    return f"{value * 100:.1f}%" if isinstance(value, (int, float)) else "N/A"


def _report(aggregate: dict[str, Any]) -> str:
    evaluation = aggregate.get("evaluation", {})
    expected_sources = evaluation.get("expected_label_sources", [])
    lines = [
        "# Meeting_Agent End-to-End Evaluation Report",
        "",
        "- Factual ground truth: official Reference Timeline / TextGrid",
        f"- Completeness label source: {', '.join(expected_sources) if expected_sources else 'unspecified'}",
        "",
        "## Final summary quality",
        "",
        "| Group | Cases | Pipeline | Judge OK | Faithfulness | Core content coverage | Core cases | Critical errors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in aggregate.get("groups", {}).items():
        lines.append(
            f"| {name} | {metrics.get('case_count', 0)} | {_percent(metrics.get('pipeline_completion_rate'))} | "
            f"{metrics.get('judge_success_count', 0)} | {_percent(metrics.get('faithfulness'))} | "
            f"{_percent(metrics.get('core_content_coverage'))} | "
            f"{metrics.get('core_content_coverage_case_count', 0)} | {metrics.get('critical_error_count', 0)} |"
        )
    lines.extend(
        [
            "",
            "Core content coverage uses explicit expected core_facts. Legacy expected labels are reported separately and are not mixed into this metric.",
            "",
            "## Upstream Timeline quality",
            "",
            "| Group | Timeline OK | CER corpus | Speech recall | Speech precision | Speaker accuracy | Speaker count MAE |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, metrics in aggregate.get("groups", {}).items():
        e2e = metrics.get("e2e", {})
        lines.append(
            f"| {name} | {e2e.get('timeline_evaluated_count', 0)} | {_percent(e2e.get('cer_corpus'))} | "
            f"{_percent(e2e.get('speech_recall_macro'))} | {_percent(e2e.get('speech_precision_macro'))} | "
            f"{_percent(e2e.get('speaker_accuracy_macro'))} | {e2e.get('speaker_count_mae')} |"
        )
    lines.extend(["", "## Case results", ""])
    for case in aggregate.get("cases", []):
        judge_record = case.get("judge", {}).get("result") or {}
        judge = judge_record.get("result") or {}
        timeline = case.get("e2e", {}).get("timeline_metrics", {})
        lines.append(
            f"- **{case['case_id']}**: pipeline={case.get('candidate', {}).get('status')}, "
            f"judge={judge_record.get('status', 'not_run')}, CER={_percent(timeline.get('text', {}).get('cer'))}, "
            f"speaker={_percent(timeline.get('speaker', {}).get('accuracy_on_overlap'))}, "
            f"faithfulness={_percent(judge.get('faithfulness', {}).get('rate'))}, "
            f"core-content-coverage={_percent(judge.get('completeness', {}).get('core_content_coverage'))}"
        )
    all_e2e = aggregate.get("groups", {}).get("all", {}).get("e2e", {})
    lines.extend(
        [
            "",
            "## Runtime diagnostics",
            "",
            f"- Mean end-to-end time: {all_e2e.get('total_elapsed_seconds_mean')} s",
            f"- Mean local LLM request time: {all_e2e.get('llm_model_call_elapsed_seconds_mean')} s",
            f"- Max board memory peak: {all_e2e.get('memory_peak_mb_max')} MB",
            f"- Mean stage times: {json.dumps(all_e2e.get('stage_elapsed_seconds_mean', {}), ensure_ascii=False)}",
            f"- Pipeline failures: {json.dumps(all_e2e.get('failure_counts', {}), ensure_ascii=False)}",
        ]
    )
    return "\n".join(lines) + "\n"


def _run_judge(**kwargs: Any) -> dict[str, Any]:
    from .llm_judge import judge_summary

    return judge_summary(**kwargs)


def _reuse_judge_response(
    source_case_dir: pathlib.Path, expected: dict[str, Any]
) -> dict[str, Any]:
    from .llm_judge import normalize_judge_response

    raw_path = source_case_dir / "judge_response_raw.json"
    if not raw_path.is_file():
        raise FileNotFoundError(f"missing saved Judge response: {raw_path}")
    raw_response = _load_json(raw_path)
    if not isinstance(raw_response, dict):
        raise TypeError(f"saved Judge response must be an object: {raw_path}")
    request_path = source_case_dir / "judge_request.json"
    request_record = _load_json(request_path) if request_path.is_file() else {}
    if not isinstance(request_record, dict):
        request_record = {}
    return normalize_judge_response(
        response_json=raw_response,
        expected=expected,
        request_record=request_record,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--dataset-root")
    parser.add_argument("--cases", help="comma-separated case ids")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--output-root", default="/userdata/meeting_agent/evals/output/e2e"
    )
    parser.add_argument("--run-id")
    parser.add_argument(
        "--pipeline-output-root",
        help="store or read Harness outputs under <root>/<case_id>",
    )
    parser.add_argument(
        "--reuse-pipeline",
        action="store_true",
        help="read existing Harness outputs without rerunning audio",
    )
    parser.add_argument(
        "--resume-pipeline",
        action="store_true",
        help="resume existing Harness stages instead of overwriting",
    )
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument(
        "--reuse-judge-run-dir",
        help=(
            "reuse <dir>/<case_id>/judge_response_raw.json and normalize it "
            "without calling the Judge API"
        ),
    )
    parser.add_argument("--judge-model", default="claude-fable-5")
    parser.add_argument("--judge-max-tokens", type=int, default=8192)
    parser.add_argument("--judge-timeout", type=float, default=600.0)
    parser.add_argument(
        "--prompt", default=str(_repo_root() / "evals" / "prompts" / "judge_e2e_v1.txt")
    )
    parser.add_argument("--timeline-sample-step-ms", type=int, default=100)

    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--harness-module", default="harness.main")
    parser.add_argument(
        "--board-scripts-dir", default="/userdata/meeting_agent/scripts"
    )
    parser.add_argument("--3dspeaker-dir", default="/userdata/3D-Speaker")
    parser.add_argument(
        "--3dspeaker-python", default="/userdata/miniforge3/envs/3dspeaker/bin/python"
    )
    parser.add_argument("--pad", type=float, default=1.0)
    parser.add_argument("--absorb-unknown-max", type=float, default=2.0)
    parser.add_argument("--max-known-segment", type=float, default=30.0)
    parser.add_argument("--max-unknown-segment", type=float, default=20.0)
    parser.add_argument(
        "--asr-dir",
        default="/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_batch_demo",
    )
    parser.add_argument(
        "--asr-model-dir",
        default="/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn",
    )
    parser.add_argument("--encoder-core", default="0xff")
    parser.add_argument("--asr-llm-core", default="0xff")
    parser.add_argument(
        "--model-dir",
        default="/userdata/meeting_agent/models/llm/v104/qwen3-4b-v104-ctx16k",
    )
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_path = pathlib.Path(args.manifest).expanduser().resolve()
    dataset_root = (
        pathlib.Path(args.dataset_root).expanduser().resolve()
        if args.dataset_root
        else None
    )
    cases = load_manifest(manifest_path, dataset_root)
    selected_ids = (
        {item.strip() for item in args.cases.split(",")} if args.cases else None
    )
    cases = [
        case for case in cases if selected_ids is None or case.case_id in selected_ids
    ]
    if selected_ids and {case.case_id for case in cases} != selected_ids:
        missing = sorted(selected_ids - {case.case_id for case in cases})
        raise SystemExit(f"unknown case id(s): {', '.join(missing)}")
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("no E2E cases selected")
    if args.timeline_sample_step_ms <= 0:
        raise SystemExit("--timeline-sample-step-ms must be positive")
    if args.reuse_pipeline and args.resume_pipeline:
        raise SystemExit(
            "--reuse-pipeline and --resume-pipeline are mutually exclusive"
        )
    if args.skip_judge and args.reuse_judge_run_dir:
        raise SystemExit("--skip-judge and --reuse-judge-run-dir are mutually exclusive")
    if (
        args.reuse_pipeline
        and not args.pipeline_output_root
        and not all(case.pipeline_output_dir is not None for case in cases)
    ):
        raise SystemExit(
            "--reuse-pipeline requires --pipeline-output-root or pipeline_output_dir for every case"
        )

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = pathlib.Path(args.output_root).expanduser().resolve() / run_id
    if run_dir.exists() and any(run_dir.iterdir()):
        raise SystemExit(f"run directory is not empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = pathlib.Path(args.prompt).expanduser().resolve()
    _atomic_write(
        run_dir / "run_manifest.json",
        {
            "run_id": run_id,
            "source_manifest": str(manifest_path),
            "judge_model": args.judge_model,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "cases": [case.case_id for case in cases],
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    results = []
    for case in cases:
        case_dir = run_dir / case.case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        candidate_runtime: dict[str, Any] = {
            "mode": "end_to_end_pipeline",
            "status": "failed",
        }
        deterministic: dict[str, Any] = {}
        timeline_metrics: dict[str, Any] = {"status": "not_run"}
        judge_bundle = {
            "request": None,
            "result": {
                "status": "skipped",
                "judge_model": args.judge_model,
                "error": {"type": "skipped"},
            },
            "raw_response": None,
        }
        try:
            for required_path in (
                case.audio_path,
                case.reference_timeline_path,
                case.expected_path,
            ):
                if not required_path.is_file():
                    raise FileNotFoundError(f"missing case input: {required_path}")
            reference_segments, reference_speakers, reference_timeline = load_reference(
                case.reference_timeline_path
            )
            expected_raw = _load_json(case.expected_path)
            expected_normalized = normalize_expected(expected_raw)
            _atomic_text(case_dir / "reference_timeline.txt", reference_timeline)
            _atomic_write(
                case_dir / "expected.json",
                {"raw": expected_raw, "normalized": expected_normalized},
            )
            _atomic_write(
                case_dir / "case_metadata.json",
                {
                    "case_id": case.case_id,
                    "group": case.group,
                    "category": case.category,
                    "audio": str(case.audio_path),
                    "reference_timeline": str(case.reference_timeline_path),
                    "expected": str(case.expected_path),
                    "reference_segment_count": len(reference_segments),
                    "reference_speakers": reference_speakers,
                    "metadata": case.metadata,
                },
            )

            pipeline_dir, meeting_result = _run_pipeline(args, case, case_dir)
            candidate_runtime = _pipeline_runtime(meeting_result, pipeline_dir)
            generated_timeline_path = pipeline_dir / "timeline.txt"
            candidate_path = pipeline_dir / "meeting_summary.json"
            candidate = (
                _load_json(candidate_path)
                if candidate_runtime["status"] == "success" and candidate_path.is_file()
                else None
            )
            if candidate_runtime["status"] == "success" and candidate is None:
                candidate_runtime["status"] = "failed"
                candidate_runtime.setdefault("errors", []).append(
                    {
                        "stage": "publication",
                        "code": "missing_meeting_summary",
                        "message": str(candidate_path),
                    }
                )
            if generated_timeline_path.is_file():
                generated_timeline = generated_timeline_path.read_text(
                    encoding="utf-8", errors="replace"
                )
                canonical_path = (
                    pipeline_dir / "03_llm_summary" / "canonical_segments.json"
                )
                if canonical_path.is_file():
                    canonical_segments = _load_json(canonical_path)
                    if not isinstance(canonical_segments, list) or any(
                        not isinstance(item, dict) for item in canonical_segments
                    ):
                        raise ValueError(f"invalid canonical segments: {canonical_path}")
                    predicted_segments = [
                        item
                        for item in canonical_segments
                        if str(item.get("text") or "").strip()
                    ]
                else:
                    predicted_segments, _, generated_timeline = parse_timeline(
                        generated_timeline_path
                    )
                    canonical_segments = predicted_segments
                timeline_metrics = evaluate_timelines(
                    predicted_segments,
                    reference_segments,
                    activity_segments=canonical_segments,
                    sample_step_ms=args.timeline_sample_step_ms,
                )
                _atomic_text(case_dir / "generated_timeline.txt", generated_timeline)
            else:
                predicted_segments = []
                generated_timeline = ""
                timeline_metrics = {
                    "status": "error",
                    "error": {
                        "type": "missing_generated_timeline",
                        "path": str(generated_timeline_path),
                    },
                }
                if candidate_runtime["status"] == "success":
                    candidate_runtime["status"] = "failed"
                    candidate_runtime.setdefault("errors", []).append(
                        {
                            "stage": "transcript_prepare",
                            "code": "missing_timeline",
                            "message": str(generated_timeline_path),
                        }
                    )
            _atomic_write(case_dir / "timeline_metrics.json", timeline_metrics)

            deterministic = grade_summary(
                candidate, predicted_segments, expected_raw, runtime=candidate_runtime
            )
            _atomic_write(case_dir / "deterministic_grade.json", deterministic)
            if candidate is not None:
                _atomic_write(case_dir / "candidate_summary.json", candidate)
            if (
                candidate_runtime["status"] == "success"
                and candidate is not None
                and generated_timeline
                and not args.skip_judge
            ):
                judge_input = (
                    "=== Reference Timeline（唯一事实真值） ===\n"
                    + reference_timeline
                    + "\n=== Generated Timeline（仅用于解析 candidate refs，不可作为事实依据） ===\n"
                    + generated_timeline
                )
                if args.reuse_judge_run_dir:
                    source_case_dir = (
                        pathlib.Path(args.reuse_judge_run_dir).expanduser().resolve()
                        / case.case_id
                    )
                    judge_bundle = _reuse_judge_response(
                        source_case_dir, expected_normalized
                    )
                else:
                    judge_bundle = _run_judge(
                        timeline=judge_input,
                        expected=expected_normalized,
                        candidate=candidate,
                        prompt_path=prompt_path,
                        model=args.judge_model,
                        max_tokens=args.judge_max_tokens,
                        timeout=args.judge_timeout,
                    )
        except Exception as exc:  # noqa: BLE001 - one bad case must not abort the batch
            error = {"type": type(exc).__name__, "message": str(exc)}
            _atomic_write(case_dir / "case_error.json", error)
            candidate_runtime = {
                **candidate_runtime,
                "status": "failed",
                "error": error,
            }
        _atomic_write(case_dir / "judge_request.json", judge_bundle.get("request"))
        _atomic_write(
            case_dir / "judge_response_raw.json", judge_bundle.get("raw_response")
        )
        _atomic_write(case_dir / "judge_result.json", judge_bundle.get("result"))
        results.append(
            {
                "case_id": case.case_id,
                "group": case.group,
                "category": case.category,
                "candidate": candidate_runtime,
                "deterministic": deterministic,
                "judge": judge_bundle,
                "e2e": {"timeline_metrics": timeline_metrics},
            }
        )

    aggregate = _aggregate(results)
    _add_e2e_aggregates(aggregate, results)
    expected_label_sources = sorted(
        {
            str(case.metadata.get("expected_source") or "unspecified")
            for case in cases
        }
    )
    aggregate["evaluation"] = {
        "type": "audio_to_summary_e2e",
        "judge_model": args.judge_model,
        "reference_timeline_is_ground_truth": True,
        "expected_label_sources": expected_label_sources,
        "expected_labels_are_human_gold": expected_label_sources == ["human"],
    }
    _atomic_write(run_dir / "aggregate.json", aggregate)
    _atomic_text(run_dir / "report.md", _report(aggregate))
    print(
        json.dumps(
            {
                "status": "ok",
                "run_id": run_id,
                "run_dir": str(run_dir),
                "case_count": len(results),
                "metrics": aggregate["groups"]["all"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

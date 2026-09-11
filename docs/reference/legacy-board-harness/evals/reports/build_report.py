"""Rebuild the readable report from an evaluation run directory."""

from __future__ import annotations

import argparse
import json
import pathlib


def render_markdown(aggregate: dict) -> str:
    def percent(value) -> str:
        return f"{value * 100:.1f}%" if isinstance(value, (int, float)) else "N/A"

    lines = [
        "# Meeting_Agent Evaluation Report",
        "",
        "## Core quality metrics",
        "",
        "| Group | Meetings | Pipeline completion | Judge OK | Faithfulness | Core content coverage | Core cases | Critical errors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in aggregate.get("groups", {}).items():
        lines.append(
            f"| {name} | {metrics.get('case_count', 0)} | "
            f"{percent(metrics.get('pipeline_completion_rate'))} | "
            f"{metrics.get('judge_success_count', 0)} | "
            f"{percent(metrics.get('faithfulness'))} | "
            f"{percent(metrics.get('core_content_coverage'))} | "
            f"{metrics.get('core_content_coverage_case_count', 0)} | "
            f"{metrics.get('critical_error_count', 0)} |"
        )
    lines.extend(["", "## Meeting results", ""])
    for case in aggregate.get("cases", []):
        judge_record = case.get("judge", {}).get("result", {})
        judge = judge_record.get("result", {}) if isinstance(judge_record, dict) else {}
        lines.append(
            f"- **{case.get('case_id')}**: candidate={case.get('candidate', {}).get('status')}, "
            f"judge={judge_record.get('status', 'not_run') if isinstance(judge_record, dict) else 'not_run'}, "
            f"faithfulness={percent(judge.get('faithfulness', {}).get('rate'))}, "
            f"core-content-coverage={percent(judge.get('completeness', {}).get('core_content_coverage'))}, "
            f"critical-errors={judge.get('critical_error_count')}, "
            f"verdict={judge.get('verdict')}"
        )
    lines.extend(["", "## Runtime diagnostics", ""])
    all_metrics = aggregate.get("groups", {}).get("all", {})
    lines.append(f"- Mean local LLM call time: {all_metrics.get('llm_model_call_elapsed_seconds_mean')} s")
    lines.append(f"- Max memory peak: {all_metrics.get('memory_peak_mb_max')} MB")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    args = parser.parse_args()
    run_dir = pathlib.Path(args.run_dir).expanduser().resolve()
    aggregate_path = run_dir / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    output = run_dir / "report.md"
    output.write_text(render_markdown(aggregate), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Merge successful Judge retries into a failed evaluation run."""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
from datetime import datetime, timezone

from .run_eval import _aggregate, _atomic_text, _atomic_write, _markdown_report


def _load_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def finalize(base_dir: pathlib.Path, retry_dir: pathlib.Path, output_root: pathlib.Path) -> pathlib.Path:
    base = _load_json(base_dir / "aggregate.json")
    retry = _load_json(retry_dir / "aggregate.json")
    retry_cases = {
        case["case_id"]: case
        for case in retry["cases"]
        if (case.get("judge", {}).get("result") or {}).get("status") == "success"
    }

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_dir = output_root / run_id
    shutil.copytree(base_dir, final_dir)

    replaced = []
    for case in base["cases"]:
        case_id = case["case_id"]
        retry_case = retry_cases.get(case_id)
        if retry_case is None:
            continue
        case["judge"] = retry_case["judge"]
        replaced.append(case_id)
        for name in ("judge_request.json", "judge_response_raw.json", "judge_result.json"):
            shutil.copy2(retry_dir / case_id / name, final_dir / case_id / name)

    aggregate = _aggregate(base["cases"])
    aggregate["mvp_final"] = {
        "judge_model": "claude-fable-5",
        "base_run": str(base_dir),
        "retry_run": str(retry_dir),
        "replaced_case_count": len(replaced),
    }
    _atomic_write(final_dir / "aggregate.json", aggregate)
    _atomic_text(final_dir / "report.md", _markdown_report(aggregate))

    metrics = aggregate["groups"]["all"]
    print(f"FINAL_DIR: {final_dir}")
    print(f"replaced_case_count: {len(replaced)}")
    for key in (
        "case_count",
        "candidate_success_count",
        "pipeline_completion_rate",
        "judge_success_count",
        "faithfulness",
        "weighted_completeness",
        "critical_error_count",
        "critical_error_case_count",
    ):
        print(f"{key}: {metrics.get(key)}")
    return final_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_dir", type=pathlib.Path)
    parser.add_argument("retry_dir", type=pathlib.Path)
    parser.add_argument("output_root", type=pathlib.Path)
    args = parser.parse_args()
    finalize(args.base_dir.resolve(), args.retry_dir.resolve(), args.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

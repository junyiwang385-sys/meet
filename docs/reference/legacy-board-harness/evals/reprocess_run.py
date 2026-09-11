"""Reparse saved Judge responses and rebuild an evaluation report without API calls."""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

from .deterministic_grader import normalize_expected
from .llm_judge import _normalize_judge_result, _text_blocks
from .run_eval import _aggregate, _atomic_text, _atomic_write, _markdown_report


def _load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def reprocess_run(run_dir: pathlib.Path) -> dict[str, Any]:
    aggregate_path = run_dir / "aggregate.json"
    if not aggregate_path.is_file():
        raise FileNotFoundError(f"aggregate.json not found: {aggregate_path}")
    previous = _load_json(aggregate_path)
    cases = previous.get("cases")
    if not isinstance(cases, list):
        raise ValueError("aggregate.json has no cases array")

    updated = 0
    errors = []
    for case in cases:
        if not isinstance(case, dict) or not case.get("case_id"):
            continue
        case_id = str(case["case_id"])
        case_dir = run_dir / case_id
        expected_path = case_dir / "expected.json"
        raw_path = case_dir / "judge_response_raw.json"
        result_path = case_dir / "judge_result.json"
        if not expected_path.is_file() or not raw_path.is_file() or not result_path.is_file():
            continue
        try:
            expected_document = _load_json(expected_path)
            raw_expected = expected_document.get("raw") if isinstance(expected_document, dict) else None
            expected = normalize_expected(raw_expected) if isinstance(raw_expected, dict) else expected_document.get("normalized", expected_document)
            raw_response = _load_json(raw_path)
            blocks = _text_blocks(raw_response)
            if not blocks:
                raise ValueError("saved Judge response has no text block")
            parsed = json.loads(blocks[0])
            if not isinstance(parsed, dict):
                raise ValueError("saved Judge text must contain a JSON object")
            normalized = _normalize_judge_result(parsed, expected)
            judge_result = _load_json(result_path)
            judge_result.update({"status": "success", "result": normalized, "error": None})
            _atomic_write(result_path, judge_result)
            judge_bundle = case.get("judge")
            if not isinstance(judge_bundle, dict):
                judge_bundle = {}
                case["judge"] = judge_bundle
            judge_bundle["result"] = judge_result
            judge_bundle["raw_response"] = raw_response
            updated += 1
        except Exception as exc:
            errors.append({"case_id": case_id, "type": type(exc).__name__, "message": str(exc)})

    rebuilt = _aggregate(cases)
    rebuilt["reprocessed"] = {
        "updated_case_count": updated,
        "errors": errors,
    }
    _atomic_write(aggregate_path, rebuilt)
    _atomic_text(run_dir / "report.md", _markdown_report(rebuilt))
    return rebuilt["reprocessed"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    args = parser.parse_args()
    run_dir = pathlib.Path(args.run_dir).expanduser().resolve()
    result = reprocess_run(run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

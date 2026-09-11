"""Merge repeated evaluation runs into one aggregate report."""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

from .run_eval import _aggregate, _atomic_text, _atomic_write, _markdown_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", help="directory containing one or more run directories")
    parser.add_argument("output_dir")
    args = parser.parse_args()
    source_root = pathlib.Path(args.source_root).expanduser().resolve()
    output_dir = pathlib.Path(args.output_dir).expanduser().resolve()
    cases: list[dict[str, Any]] = []
    source_runs = []
    for aggregate_path in sorted(source_root.rglob("aggregate.json")):
        data = json.loads(aggregate_path.read_text(encoding="utf-8"))
        items = data.get("cases")
        if not isinstance(items, list):
            continue
        cases.extend(items)
        source_runs.append(str(aggregate_path.parent))
    if not cases:
        raise SystemExit(f"no aggregate.json with cases found below {source_root}")
    aggregate = _aggregate(cases)
    aggregate["repeated_run_summary"] = {
        "source_run_count": len(source_runs),
        "case_result_count": len(cases),
        "source_runs": source_runs,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(output_dir / "aggregate.json", aggregate)
    _atomic_text(output_dir / "report.md", _markdown_report(aggregate))
    print(json.dumps(aggregate["repeated_run_summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

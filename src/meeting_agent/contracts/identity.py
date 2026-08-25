"""Identifiers shared by Harness, Board, Gateway, and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunIdentity:
    """Correlate one product request with one Harness execution."""

    trace_id: str
    meeting_id: str
    task_id: str
    run_id: str

    @classmethod
    def from_args_result(cls, args: Any, result: dict[str, Any]) -> "RunIdentity":
        meeting = result.get("meeting") if isinstance(result.get("meeting"), dict) else {}
        run_id = str(getattr(args, "run_id", None) or result.get("run_id") or "run_local")
        meeting_id = str(getattr(args, "meeting_id", None) or meeting.get("meeting_id") or run_id)
        task_id = str(getattr(args, "task_id", None) or "local")
        trace_id = str(getattr(args, "trace_id", None) or f"tr_{run_id}")
        return cls(trace_id=trace_id, meeting_id=meeting_id, task_id=task_id, run_id=run_id)

    def as_dict(self) -> dict[str, str]:
        return {
            "trace_id": self.trace_id,
            "meeting_id": self.meeting_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
        }

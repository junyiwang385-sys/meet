"""Harness stage errors with a stable external representation."""

from __future__ import annotations

from typing import Any


class PipelineStageError(RuntimeError):
    def __init__(
        self,
        stage: str,
        code: str,
        message: str,
        exit_code: int,
        artifact: str | None = None,
        *,
        cause: str | None = None,
        request: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.exit_code = exit_code
        self.artifact = artifact
        self.cause = cause
        self.request = request

    def as_dict(self) -> dict[str, Any]:
        # 对外统一使用 return_code；exit_code 只保留为异常对象内部命名。
        result: dict[str, Any] = {
            "stage": self.stage,
            "code": self.code,
            "message": str(self),
            "return_code": self.exit_code,
        }
        if self.artifact:
            result["artifact"] = self.artifact
        if self.cause:
            result["cause"] = self.cause
        if self.request:
            result.update(self.request)
        return result

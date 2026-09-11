"""Remote LLM-as-a-Judge over the Anthropic-compatible HTTP API."""

from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request
from typing import Any

JUDGE_PROMPT_VERSION = "judge_claim_core_fact_v3"
DEFAULT_JUDGE_MODEL = "claude-opus-5"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get(
    "ANTHROPIC_BASE_URL", "https://maas.xgimi.com"
)
ANTHROPIC_VERSION = "2023-06-01"

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim_evaluations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "claim": {"type": "string"},
                    "status": {"type": "string", "enum": ["supported", "partially_supported", "unsupported", "contradiction"]},
                    "severity": {"type": "string", "enum": ["none", "minor", "critical"]},
                    "refs": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["claim_id", "claim", "status", "severity", "refs", "reason"],
                "additionalProperties": False,
            },
        },
        "fact_coverage": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["covered", "partial", "missing"]},
                    "importance": {"type": "string", "enum": ["minor", "major", "critical"]},
                    "reason": {"type": "string"},
                },
                "required": ["fact_id", "status", "importance", "reason"],
                "additionalProperties": False,
            },
        },
        "factuality": {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "minimum": 1, "maximum": 5},
                "reason": {"type": "string"},
                "rate": {"type": "number", "minimum": 0, "maximum": 1},
                "supported_claim_count": {"type": "integer", "minimum": 0},
                "partial_claim_count": {"type": "integer", "minimum": 0},
                "unsupported_claim_count": {"type": "integer", "minimum": 0},
                "contradiction_count": {"type": "integer", "minimum": 0},
                "unsupported_claims": {"type": "array", "items": {"type": "string"}},
                "contradictions": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "score",
                "reason",
                "rate",
                "supported_claim_count",
                "partial_claim_count",
                "unsupported_claim_count",
                "contradiction_count",
                "unsupported_claims",
                "contradictions",
            ],
            "additionalProperties": False,
        },
        "completeness": {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "minimum": 1, "maximum": 5},
                "reason": {"type": "string"},
                "weighted_coverage": {"type": "number", "minimum": 0, "maximum": 1},
                "covered_fact_count": {"type": "integer", "minimum": 0},
                "partial_fact_count": {"type": "integer", "minimum": 0},
                "missing_fact_count": {"type": "integer", "minimum": 0},
                "missing_fact_ids": {"type": "array", "items": {"type": "string"}},
                "missing_chapter_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "score",
                "reason",
                "weighted_coverage",
                "covered_fact_count",
                "partial_fact_count",
                "missing_fact_count",
                "missing_fact_ids",
                "missing_chapter_ids",
            ],
            "additionalProperties": False,
        },
        "action_items": {
            "type": "object",
            "properties": {
                "applicable": {"type": "boolean"},
                "score": {
                    "anyOf": [
                        {"type": "integer", "minimum": 1, "maximum": 5},
                        {"type": "null"},
                    ]
                },
                "reason": {"type": "string"},
                "semantic_errors": {"type": "array", "items": {"type": "string"}},
                "missing_action_ids": {"type": "array", "items": {"type": "string"}},
                "unsupported_owner_or_deadline": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "applicable",
                "score",
                "reason",
                "semantic_errors",
                "missing_action_ids",
                "unsupported_owner_or_deadline",
            ],
            "additionalProperties": False,
        },
        "structure": {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "minimum": 1, "maximum": 5},
                "reason": {"type": "string"},
                "issues": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["score", "reason", "issues"],
            "additionalProperties": False,
        },
        "readability": {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "minimum": 1, "maximum": 5},
                "reason": {"type": "string"},
                "issues": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["score", "reason", "issues"],
            "additionalProperties": False,
        },
        "critical_error": {"type": "boolean"},
        "critical_errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "description": {"type": "string"},
                    "refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["type", "description", "refs"],
                "additionalProperties": False,
            },
        },
        "overall_score": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "verdict": {"type": "string", "enum": ["pass", "review", "fail"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "needs_human_review": {"type": "boolean"},
    },
    "required": [
        "claim_evaluations",
        "fact_coverage",
        "factuality",
        "completeness",
        "action_items",
        "structure",
        "readability",
        "critical_error",
        "critical_errors",
        "overall_score",
        "verdict",
        "confidence",
        "needs_human_review",
    ],
    "additionalProperties": False,
}


def build_judge_prompt(
    template_path: pathlib.Path,
    timeline: str,
    expected: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    template = template_path.read_text(encoding="utf-8")
    replacements = {
        "{{timeline}}": timeline,
        "{{expected_facts}}": json.dumps(expected, ensure_ascii=False, indent=2),
        "{{candidate_summary}}": json.dumps(candidate, ensure_ascii=False, indent=2),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def _text_blocks(response: dict[str, Any]) -> list[str]:
    blocks = response.get("content", [])
    if not isinstance(blocks, list):
        return []
    return [
        block["text"]
        for block in blocks
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    ]


def _error_result(
    *,
    error_type: str,
    message: str,
    request_record: dict[str, Any],
    result: dict[str, Any],
    raw_response: Any = None,
) -> dict[str, Any]:
    result["error"] = {"type": error_type, "message": message}
    return {"request": request_record, "result": result, "raw_response": raw_response}


def _normalize_judge_result(parsed: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Normalize Judge output and compute claim/fact-level core metrics."""
    source = parsed.get("scores") if isinstance(parsed.get("scores"), dict) else parsed
    faithfulness_section = (
        parsed.get("claim_level_faithfulness")
        if isinstance(parsed.get("claim_level_faithfulness"), dict)
        else {}
    )
    completeness_section = (
        parsed.get("fact_level_completeness")
        if isinstance(parsed.get("fact_level_completeness"), dict)
        else {}
    )
    dimensions = ("factuality", "completeness", "action_items", "structure", "readability")
    if (
        not any(name in source for name in dimensions)
        and not isinstance(parsed.get("claim_evaluations"), list)
        and not isinstance(parsed.get("fact_coverage"), list)
        and not faithfulness_section
        and not completeness_section
    ):
        raise ValueError("Judge JSON has no recognized claim or fact evaluations")

    def dimension(name: str) -> dict[str, Any]:
        value = source.get(name)
        if not isinstance(value, dict) and name == "factuality":
            value = faithfulness_section
        elif not isinstance(value, dict) and name == "completeness":
            value = completeness_section
        elif not isinstance(value, dict) and name == "action_items":
            value = completeness_section.get("action_items")
        value = value if isinstance(value, dict) else {}
        normalized: dict[str, Any] = {
            "score": value.get("score"),
            "reason": value.get("reason", ""),
        }
        if name == "factuality":
            normalized.update({"unsupported_claims": [], "contradictions": []})
        elif name == "completeness":
            normalized.update({"missing_fact_ids": [], "missing_chapter_ids": []})
        elif name == "action_items":
            applicable = value.get("applicable")
            normalized.update({
                "applicable": bool(applicable) if applicable is not None else False,
                "semantic_errors": [],
                "missing_action_ids": [],
                "unsupported_owner_or_deadline": [],
            })
        else:
            normalized["issues"] = []
        return normalized

    critical_errors = parsed.get("critical_errors", [])
    if not isinstance(critical_errors, list):
        critical_errors = [critical_errors]
    critical_claim_ids = set()
    explicit_critical_error_count = 0
    has_explicit_severity = False
    for error in critical_errors:
        if not isinstance(error, dict):
            continue
        severity = str(error.get("severity", "")).lower()
        if severity:
            has_explicit_severity = True
        if severity == "critical":
            explicit_critical_error_count += 1
            affected = error.get("affected_claim_ids", [])
            if isinstance(affected, list):
                critical_claim_ids.update(str(item) for item in affected)

    raw_claims = parsed.get("claim_evaluations")
    if not isinstance(raw_claims, list):
        raw_claims = faithfulness_section.get("claims", [])
    raw_claims = raw_claims if isinstance(raw_claims, list) else []
    claims = []
    claim_counts = {"supported": 0, "partially_supported": 0, "unsupported": 0, "contradiction": 0}
    critical_claim_error_count = 0
    for index, raw_claim in enumerate(raw_claims, 1):
        if not isinstance(raw_claim, dict):
            continue
        claim_id = str(raw_claim.get("claim_id") or f"claim-{index:03d}")
        status = str(raw_claim.get("status") or raw_claim.get("support_status") or "")
        if status not in claim_counts:
            continue
        severity = str(raw_claim.get("severity") or "")
        if claim_id in critical_claim_ids:
            severity = "critical"
        elif not severity:
            severity = "minor" if status == "supported" else "major"
        claim = {
            **raw_claim,
            "claim_id": claim_id,
            "status": status,
            "severity": severity,
            "refs": raw_claim.get("refs") or raw_claim.get("timeline_refs") or [],
        }
        claims.append(claim)
        claim_counts[status] += 1
        if severity == "critical" and status in {"partially_supported", "unsupported", "contradiction"}:
            critical_claim_error_count += 1
    critical_error_count = (
        explicit_critical_error_count if has_explicit_severity else len(critical_errors)
    )
    claim_total = sum(claim_counts.values())
    faithfulness_rate = (
        (claim_counts["supported"] + 0.5 * claim_counts["partially_supported"]) / claim_total
        if claim_total
        else None
    )

    returned_facts = parsed.get("fact_coverage")
    if not isinstance(returned_facts, list):
        returned_facts = []
        key_facts = completeness_section.get("key_facts", [])
        if isinstance(key_facts, list):
            returned_facts.extend(key_facts)
        action_section = completeness_section.get("action_items", {})
        if isinstance(action_section, dict):
            action_facts = action_section.get("items", [])
            if isinstance(action_facts, list):
                returned_facts.extend(action_facts)
    expected_items = expected.get("coverage_facts")
    if not isinstance(expected_items, list):
        expected_items = []
        for field in ("key_facts", "action_items"):
            value = expected.get(field, [])
            if isinstance(value, list):
                expected_items.extend(
                    item for item in value
                    if isinstance(item, dict) and item.get("id")
                )
    expected_items = [
        item for item in expected_items
        if isinstance(item, dict) and item.get("id")
    ]
    expected_by_id = {str(item["id"]): item for item in expected_items}
    returned_by_id = {
        str(item.get("fact_id")): item
        for item in returned_facts
        if isinstance(item, dict) and item.get("fact_id")
    }
    facts = []
    for fact_id, expected_item in expected_by_id.items():
        returned = returned_by_id.get(fact_id)
        if returned is None:
            facts.append({
                "fact_id": fact_id,
                "status": "missing",
                "importance": expected_item.get("importance", "major"),
                "reason": "Judge did not return an evaluation for this expected fact",
            })
            continue
        returned_coverage = returned.get("coverage")
        returned_status = returned.get("status")
        status = returned_coverage if returned_coverage in {"covered", "partial", "missing"} else returned_status
        facts.append({
            **returned,
            "fact_id": fact_id,
            "status": status or "missing",
            "importance": expected_item.get("importance", "major"),
        })
    importance_weights = {"minor": 1.0, "major": 2.0, "critical": 3.0}
    fact_total_weight = 0.0
    fact_covered_weight = 0.0
    fact_counts = {"covered": 0, "partial": 0, "missing": 0}
    for fact in facts:
        status = str(fact.get("status", ""))
        if status not in fact_counts:
            status = "missing"
            fact["status"] = status
        fact_counts[status] += 1
        weight = importance_weights.get(str(fact.get("importance", "major")), 2.0)
        fact_total_weight += weight
        if status == "covered":
            fact_covered_weight += weight
        elif status == "partial":
            fact_covered_weight += 0.5 * weight
    weighted_completeness = (
        fact_covered_weight / fact_total_weight if fact_total_weight else None
    )
    coverage_metric = expected.get("coverage_metric", {})
    if not isinstance(coverage_metric, dict):
        coverage_metric = {}
    is_core_metric = coverage_metric.get("name") == "core_content_coverage"
    core_content_coverage = weighted_completeness if is_core_metric else None
    legacy_weighted_coverage = weighted_completeness if not is_core_metric else None

    critical_error = bool(parsed.get("critical_error", critical_errors)) or critical_error_count > 0
    overall_score = parsed.get("overall_score")
    verdict = parsed.get("verdict")
    if verdict not in {"pass", "review", "fail"}:
        if critical_error:
            verdict = "fail"
        elif isinstance(overall_score, (int, float)) and overall_score >= 4:
            verdict = "pass"
        else:
            verdict = "review"

    factuality = dimension("factuality")
    factuality.update({
        "rate": faithfulness_rate,
        "supported_claim_count": claim_counts["supported"],
        "partial_claim_count": claim_counts["partially_supported"],
        "unsupported_claim_count": claim_counts["unsupported"],
        "contradiction_count": claim_counts["contradiction"],
    })
    completeness = dimension("completeness")
    completeness.update({
        "weighted_coverage": weighted_completeness,
        "core_content_coverage": core_content_coverage,
        "legacy_weighted_coverage": legacy_weighted_coverage,
        "covered_fact_count": fact_counts["covered"],
        "partial_fact_count": fact_counts["partial"],
        "missing_fact_count": fact_counts["missing"],
    })
    normalized = {
        "coverage_metric": coverage_metric,
        "claim_evaluations": claims,
        "fact_coverage": facts,
        "faithfulness": {
            "rate": faithfulness_rate,
            "claim_count": claim_total,
            "supported_claim_count": claim_counts["supported"],
            "partial_claim_count": claim_counts["partially_supported"],
            "unsupported_claim_count": claim_counts["unsupported"],
            "contradiction_count": claim_counts["contradiction"],
        },
        "factuality": factuality,
        "completeness": completeness,
        "action_items": dimension("action_items"),
        "structure": dimension("structure"),
        "readability": dimension("readability"),
        "critical_error": critical_error,
        "critical_error_count": critical_error_count,
        "critical_claim_error_count": critical_claim_error_count,
        "critical_errors": critical_errors,
        "overall_score": overall_score,
        "verdict": verdict,
        "confidence": parsed.get("confidence", "medium"),
        "needs_human_review": bool(parsed.get("needs_human_review", critical_error or verdict != "pass")),
    }
    return normalized


def normalize_judge_response(
    *,
    response_json: dict[str, Any],
    expected: dict[str, Any],
    request_record: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize a saved Messages API response without issuing another request."""
    request_record = request_record or {}
    result = dict(result or {})
    result.setdefault("judge_model", response_json.get("model"))
    result["stop_reason"] = response_json.get("stop_reason")
    result["usage"] = response_json.get("usage")
    result.setdefault("request_id", response_json.get("id"))
    coverage_metric = expected.get("coverage_metric", {})
    saved_prompt_version = request_record.get("prompt_version")
    if (
        isinstance(coverage_metric, dict)
        and coverage_metric.get("name") == "core_content_coverage"
        and saved_prompt_version
        and saved_prompt_version != JUDGE_PROMPT_VERSION
    ):
        return _error_result(
            error_type="incompatible_saved_judge_response",
            message=(
                "Saved Judge response predates the core content coverage prompt; "
                "run the Judge again with the current expected labels"
            ),
            request_record=request_record,
            result=result,
            raw_response=response_json,
        )
    if result["stop_reason"] == "refusal":
        return _error_result(
            error_type="refusal",
            message="Judge refused the request",
            request_record=request_record,
            result=result,
            raw_response=response_json,
        )
    if result["stop_reason"] == "max_tokens":
        return _error_result(
            error_type="max_tokens",
            message="Judge response reached max_tokens",
            request_record=request_record,
            result=result,
            raw_response=response_json,
        )
    blocks = _text_blocks(response_json)
    if not blocks:
        return _error_result(
            error_type="missing_text_block",
            message="No text block in Judge response",
            request_record=request_record,
            result=result,
            raw_response=response_json,
        )
    try:
        parsed = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        return _error_result(
            error_type="json_parse_error",
            message=str(exc),
            request_record=request_record,
            result={**result, "text": blocks[0]},
            raw_response=response_json,
        )
    if not isinstance(parsed, dict):
        return _error_result(
            error_type="schema_error",
            message="Judge JSON must be an object",
            request_record=request_record,
            result=result,
            raw_response=response_json,
        )
    try:
        normalized = _normalize_judge_result(parsed, expected)
    except ValueError as exc:
        return _error_result(
            error_type="schema_error",
            message=str(exc),
            request_record=request_record,
            result=result,
            raw_response=response_json,
        )
    result.update({"status": "success", "result": normalized})
    return {"request": request_record, "result": result, "raw_response": response_json}


def judge_summary(
    *,
    timeline: str,
    expected: dict[str, Any],
    candidate: dict[str, Any],
    prompt_path: pathlib.Path,
    model: str = DEFAULT_JUDGE_MODEL,
    max_tokens: int = 8192,
    timeout: float = 600.0,
) -> dict[str, Any]:
    """Call the Anthropic-compatible Messages API without an SDK dependency."""
    prompt = build_judge_prompt(prompt_path, timeline, expected, candidate)
    endpoint = ANTHROPIC_BASE_URL.rstrip("/") + "/v1/messages"
    request_record: dict[str, Any] = {
        "method": "POST",
        "endpoint": endpoint,
        "model": model,
        "prompt_version": JUDGE_PROMPT_VERSION,
        "max_tokens": max_tokens,
        "output_config": {"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
        "messages": [{"role": "user", "content": prompt}],
    }
    result: dict[str, Any] = {
        "status": "error",
        "judge_model": model,
        "prompt_version": JUDGE_PROMPT_VERSION,
        "base_url": ANTHROPIC_BASE_URL,
        "request_id": None,
        "stop_reason": None,
        "usage": None,
        "result": None,
        "error": None,
    }
    if not ANTHROPIC_API_KEY.strip():
        return _error_result(
            error_type="missing_api_key",
            message="Fill ANTHROPIC_API_KEY in evals/llm_judge.py",
            request_record=request_record,
            result=result,
        )

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": request_record["messages"],
        "output_config": request_record["output_config"],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "x-api-key": ANTHROPIC_API_KEY.strip(),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
            "accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8", "replace")
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            status_code = response.status
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", "replace")
        request_id = exc.headers.get("x-request-id") or exc.headers.get("request-id")
        result["request_id"] = request_id
        result["status_code"] = exc.code
        try:
            error_body: Any = json.loads(raw_body)
        except json.JSONDecodeError:
            error_body = raw_body
        return _error_result(
            error_type="http_error",
            message=f"Judge HTTP status {exc.code}",
            request_record=request_record,
            result={**result, "error_body": error_body},
            raw_response={
                "status_code": exc.code,
                "headers": dict(exc.headers.items()),
                "body": error_body,
            },
        )
    except urllib.error.URLError as exc:
        return _error_result(
            error_type="connection_error",
            message=str(exc),
            request_record=request_record,
            result=result,
        )
    except TimeoutError as exc:
        return _error_result(
            error_type="timeout",
            message=str(exc) or "Judge request timed out",
            request_record=request_record,
            result=result,
        )
    except OSError as exc:
        return _error_result(
            error_type="connection_error",
            message=str(exc),
            request_record=request_record,
            result=result,
        )

    result["status_code"] = status_code
    result["request_id"] = response_headers.get("x-request-id") or response_headers.get("request-id")
    try:
        response_json = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        return _error_result(
            error_type="json_parse_error",
            message=str(exc),
            request_record=request_record,
            result=result,
            raw_response={"body": raw_body, "headers": response_headers},
        )
    if not isinstance(response_json, dict):
        return _error_result(
            error_type="schema_error",
            message="Judge HTTP response must be a JSON object",
            request_record=request_record,
            result=result,
            raw_response=response_json,
        )

    return normalize_judge_response(
        response_json=response_json,
        expected=expected,
        request_record=request_record,
        result=result,
    )

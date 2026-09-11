from __future__ import annotations

import json
import pathlib
import runpy

from evals.deterministic_grader import normalize_expected

_JUDGE_MODULE = runpy.run_path(
    pathlib.Path(__file__).parents[1] / "evals" / "llm_judge_source.txt"
)
_NORMALIZE = _JUDGE_MODULE["_normalize_judge_result"]
_NORMALIZE_RESPONSE = _JUDGE_MODULE["normalize_judge_response"]


def test_normalize_expected_uses_core_facts_as_only_coverage_denominator() -> None:
    normalized = normalize_expected(
        {
            "overview": {"text": "总览", "refs": ["seg-000001"]},
            "chapters": [{"overview": "章节", "refs": ["seg-000002"]}],
            "action_items": [{"task": "执行任务", "refs": ["seg-000003"]}],
            "core_facts": [
                {"text": "核心事实", "importance": "critical", "refs": ["seg-000001"]}
            ],
        }
    )

    assert normalized["coverage_metric"]["name"] == "core_content_coverage"
    assert [item["id"] for item in normalized["coverage_facts"]] == ["core-fact-001"]
    assert [item["id"] for item in normalized["action_items"]] == ["action-001"]


def test_normalizes_fable_claim_and_fact_level_schema() -> None:
    parsed = {
        "claim_level_faithfulness": {
            "claims": [
                {
                    "claim_id": "claim-001",
                    "claim": "事实一",
                    "status": "supported",
                    "refs": ["seg-000001"],
                    "reason": "有明确原文支持",
                },
                {
                    "claim_id": "claim-002",
                    "claim": "事实二",
                    "status": "partially_supported",
                    "refs": ["seg-000002"],
                    "reason": "仅部分支持",
                },
            ],
            "faithfulness_score": 0.75,
        },
        "fact_level_completeness": {
            "key_facts": [
                {
                    "fact_id": "fact-overview",
                    "status": "covered",
                    "reason": "完整覆盖",
                }
            ],
            "action_items": {
                "applicable": True,
                "items": [
                    {
                        "fact_id": "action-001",
                        "status": "partial",
                        "reason": "缺少执行细节",
                    }
                ],
            },
        },
        "critical_errors": [],
        "structure": {"score": 0.8, "issues": []},
        "readability": {"score": 0.9, "issues": []},
    }
    expected = {
        "key_facts": [{"id": "fact-overview", "importance": "critical"}],
        "action_items": [{"id": "action-001", "importance": "critical"}],
    }

    result = _NORMALIZE(parsed, expected)

    assert result["faithfulness"]["claim_count"] == 2
    assert result["faithfulness"]["rate"] == 0.75
    assert [item["status"] for item in result["fact_coverage"]] == [
        "covered",
        "partial",
    ]
    assert result["completeness"]["weighted_coverage"] == 0.75
    assert result["action_items"]["applicable"] is True
    assert result["completeness"]["core_content_coverage"] is None
    assert result["completeness"]["legacy_weighted_coverage"] == 0.75


def test_core_content_coverage_uses_only_explicit_core_facts() -> None:
    parsed = {
        "claim_evaluations": [
            {
                "claim_id": "claim-001",
                "claim": "事实一",
                "status": "supported",
                "severity": "none",
                "refs": ["seg-000001"],
                "reason": "有依据",
            }
        ],
        "fact_coverage": [
            {"fact_id": "core-fact-001", "status": "covered", "importance": "critical", "reason": "完整覆盖"},
            {"fact_id": "core-fact-002", "status": "partial", "importance": "major", "reason": "部分覆盖"},
        ],
        "critical_errors": [],
        "structure": {"score": 5, "reason": "", "issues": []},
        "readability": {"score": 5, "reason": "", "issues": []},
    }
    expected = {
        "coverage_facts": [
            {"id": "core-fact-001", "importance": "critical"},
            {"id": "core-fact-002", "importance": "major"},
            {"id": "core-fact-003", "importance": "major"},
        ],
        "coverage_metric": {
            "name": "core_content_coverage",
            "version": "core_content_coverage_v1",
            "basis": "explicit_core_facts",
        },
        "key_facts": [{"id": "fact-overview", "importance": "critical"}],
        "action_items": [{"id": "action-001", "importance": "critical"}],
    }

    result = _NORMALIZE(parsed, expected)

    assert result["faithfulness"]["rate"] == 1.0
    assert [item["fact_id"] for item in result["fact_coverage"]] == [
        "core-fact-001",
        "core-fact-002",
        "core-fact-003",
    ]
    assert result["completeness"]["core_content_coverage"] == 4 / 7
    assert result["completeness"]["legacy_weighted_coverage"] is None
    assert result["completeness"]["missing_fact_count"] == 1


def test_rejects_old_saved_response_for_core_coverage() -> None:
    response = {
        "id": "msg_old",
        "model": "claude-fable-5",
        "stop_reason": "end_turn",
        "usage": {},
        "content": [{"type": "text", "text": "{}"}],
    }

    bundle = _NORMALIZE_RESPONSE(
        response_json=response,
        expected={
            "coverage_metric": {"name": "core_content_coverage"},
            "coverage_facts": [{"id": "core-fact-001", "importance": "major"}],
        },
        request_record={"prompt_version": "judge_claim_fact_v2"},
    )

    assert bundle["result"]["error"]["type"] == "incompatible_saved_judge_response"


def test_normalizes_saved_messages_response_without_api_call() -> None:
    parsed = {
        "claim_level_faithfulness": {
            "claims": [
                {
                    "claim_id": "claim-001",
                    "claim": "事实一",
                    "status": "supported",
                    "refs": ["seg-000001"],
                    "reason": "有明确原文支持",
                }
            ]
        },
        "fact_level_completeness": {
            "key_facts": [
                {
                    "fact_id": "fact-overview",
                    "status": "partial",
                    "reason": "部分覆盖",
                }
            ],
            "action_items": {"applicable": False, "items": []},
        },
        "critical_errors": [],
        "structure": {"score": 0.8, "issues": []},
        "readability": {"score": 0.9, "issues": []},
    }
    response = {
        "id": "msg_test",
        "model": "claude-fable-5",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 20},
        "content": [{"type": "text", "text": json.dumps(parsed)}],
    }

    bundle = _NORMALIZE_RESPONSE(
        response_json=response,
        expected={
            "key_facts": [{"id": "fact-overview", "importance": "major"}],
            "action_items": [],
        },
    )

    assert bundle["result"]["status"] == "success"
    assert bundle["result"]["request_id"] == "msg_test"
    normalized = bundle["result"]["result"]
    assert normalized["faithfulness"]["rate"] == 1.0
    assert normalized["completeness"]["weighted_coverage"] == 0.5

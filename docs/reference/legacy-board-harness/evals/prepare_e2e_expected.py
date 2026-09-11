"""Create four-field E2E expected labels from official TextGrid transcripts."""

# ruff: noqa: TRY004 - validation errors consistently use ValueError in this project

from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .textgrid import parse_textgrid, render_reference_timeline

PREPARATION_VERSION = "textgrid_expected_core_facts_v2"
DEFAULT_MODEL = "claude-opus-5"
DEFAULT_SPLITS = ("test", "train_L", "train_S")
LEGACY_TARGET_FIELDS = ("overview", "chapters", "speakers", "action_items")
TARGET_FIELDS = (*LEGACY_TARGET_FIELDS, "core_facts")

EXPECTED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "refs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["text", "refs"],
            "additionalProperties": False,
        },
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "overview": {"type": "string"},
                    "start_ref": {"type": "string"},
                    "end_ref": {"type": "string"},
                    "refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "overview", "start_ref", "end_ref", "refs"],
                "additionalProperties": False,
            },
        },
        "speakers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker_id": {"type": "string"},
                    "overview": {"type": "string"},
                    "refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["speaker_id", "overview", "refs"],
                "additionalProperties": False,
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "owner": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "deadline": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                    "refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["task", "owner", "deadline", "refs"],
                "additionalProperties": False,
            },
        },
        "core_facts": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "importance": {"type": "string", "enum": ["major", "critical"]},
                    "refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "importance", "refs"],
                "additionalProperties": False,
            },
        },
    },
    "required": list(TARGET_FIELDS),
    "additionalProperties": False,
}


@dataclass(frozen=True)
class SourceCase:
    case_id: str
    split: str
    stem: str
    audio_path: pathlib.Path
    textgrid_path: pathlib.Path
    rttm_path: pathlib.Path | None
    expected_path: pathlib.Path


def _write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _relative(path: pathlib.Path, root: pathlib.Path) -> str:
    return pathlib.Path(os.path.relpath(path, root)).as_posix()


def discover_cases(
    dataset_root: pathlib.Path,
    output_root: pathlib.Path,
    splits: list[str] | tuple[str, ...],
) -> list[SourceCase]:
    dataset_root = dataset_root.resolve()
    output_root = output_root.resolve()
    cases: list[SourceCase] = []
    for split in splits:
        split_root = dataset_root / split
        audio_dir = split_root / "wav"
        reference_dir = split_root / "TextGrid"
        if not audio_dir.is_dir():
            raise FileNotFoundError(f"audio directory not found: {audio_dir}")
        if not reference_dir.is_dir():
            raise FileNotFoundError(f"TextGrid directory not found: {reference_dir}")

        audio_by_stem: dict[str, pathlib.Path] = {}
        for path in sorted(audio_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in {".flac", ".wav"}:
                if path.stem in audio_by_stem:
                    raise ValueError(f"duplicate audio stem in {audio_dir}: {path.stem}")
                audio_by_stem[path.stem] = path.resolve()
        textgrid_by_stem = {
            path.stem: path.resolve()
            for path in sorted(reference_dir.iterdir())
            if path.is_file() and path.suffix.lower() == ".textgrid"
        }
        rttm_by_stem = {
            path.stem: path.resolve()
            for path in sorted(reference_dir.iterdir())
            if path.is_file() and path.suffix.lower() == ".rttm"
        }
        missing_textgrid = sorted(set(audio_by_stem) - set(textgrid_by_stem))
        extra_textgrid = sorted(set(textgrid_by_stem) - set(audio_by_stem))
        if missing_textgrid or extra_textgrid:
            raise ValueError(
                f"{split}: FLAC/WAV and TextGrid stems differ; "
                f"missing_textgrid={missing_textgrid[:10]}, "
                f"extra_textgrid={extra_textgrid[:10]}"
            )
        for stem in sorted(audio_by_stem):
            cases.append(
                SourceCase(
                    case_id=f"{split}_{stem}",
                    split=split,
                    stem=stem,
                    audio_path=audio_by_stem[stem],
                    textgrid_path=textgrid_by_stem[stem],
                    rttm_path=rttm_by_stem.get(stem),
                    expected_path=(
                        output_root / split / f"{stem}_expected.json"
                    ).resolve(),
                )
            )
    if not cases:
        raise ValueError(f"no audio/TextGrid cases found under {dataset_root}")
    return cases


def build_expected_prompt(
    case: SourceCase,
    segments: list[dict[str, Any]],
) -> str:
    timeline = render_reference_timeline(segments)
    speaker_ids = sorted({str(item["speaker_id"]) for item in segments})
    first_ref = segments[0]["segment_id"]
    last_ref = segments[-1]["segment_id"]
    return f"""你是会议评测参考标注整理员。请只依据官方人工标注的 Reference Timeline，为后续摘要质量评测生成 expected JSON。你是在整理参考标签，不是在评价模型输出。

case_id：{case.case_id}
有效片段数：{len(segments)}
speaker_id：{json.dumps(speaker_ids, ensure_ascii=False)}
首尾片段：{first_ref} / {last_ref}

标注规则：
1. 事实唯一来源是下方 Reference Timeline。不得补充常识、身份、姓名、原因、结论、数字、owner 或 deadline。
2. overview.text 应简洁覆盖会议目的、主要讨论、明确结论和重要限制；overview.refs 选择能直接支撑这些内容的代表性 refs。
3. chapters 按时间顺序把全部 Timeline 划分为连续且不重叠的主题区间，通常 3 至 8 章；很短会议可以 1 至 2 章。第一章 start_ref 必须是 {first_ref}，最后一章 end_ref 必须是 {last_ref}，相邻章节之间不得遗漏片段。chapter.overview 要包含该区间的重要事实、决定、分歧和限制，而不只是写主题名称。
4. 每个 chapter.refs 选择该章节区间内能支撑 overview 的代表性 refs；start_ref、end_ref 和 refs 必须使用输入中存在的 seg ID。
5. speakers 必须且只能包含这些 ID：{json.dumps(speaker_ids, ensure_ascii=False)}。每位 speaker 的 overview 只概括其本人明确说过的内容；refs 必须全部属于该 speaker。不要推测真实身份。
6. action_items 只记录会议中明确要求执行或明确承诺执行的任务。讨论、建议、愿望、假设和一般性下一步方向不算待办。owner 或 deadline 未明确时必须为 null，不能推断。没有明确待办时输出空数组。
7. core_facts 只记录这场会议最值得在摘要中保留的核心内容，建议输出 5 至 8 条，最多 10 条。内容应覆盖主要议题、重要结论或决定、明确行动、重要风险、限制或未决问题；会议内容很少时可以少于 5 条。
8. 每条 core_fact 必须是一个原子、可独立判断的事实，只表达一个重点，并使用 major 或 critical 标记重要性。不要把整章写成一条事实，不要复制 overview 或按章节重复，不要把一条事实拆成互相重叠的多条事实。
9. 每条 core_fact 必须有一个或多个直接支持它的 Reference Timeline refs。行动只有在明确要求执行或明确承诺执行时才能进入 core_facts；owner 和 deadline 不明确时不要推断。
10. 保留关键限定条件。不要把提议写成决定，不要把可能性写成事实，不要把他人观点错误归因。
11. 仅输出符合 Schema 的 JSON，不要输出 Markdown 或解释。

=== Reference Timeline ===
{timeline}"""


def _literal_constant(source: str, name: str) -> str:
    match = re.search(rf"^{name}\s*=\s*(.+)$", source, re.MULTILINE)
    if not match:
        raise RuntimeError(f"missing {name} in llm_judge configuration")
    value = ast.literal_eval(match.group(1).strip())
    if not isinstance(value, str):
        raise RuntimeError(f"{name} must be a string")
    return value


def _api_settings() -> tuple[str, str, str]:
    try:
        from .llm_judge import (  # type: ignore[import-not-found]
            ANTHROPIC_API_KEY,
            ANTHROPIC_BASE_URL,
            ANTHROPIC_VERSION,
        )

        return ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_VERSION
    except Exception:  # noqa: BLE001 - local Judge file may be binary-corrupted
        source_path = pathlib.Path(__file__).with_name("llm_judge_source.txt")
        source = source_path.read_text(encoding="utf-8", errors="strict")
        return (
            _literal_constant(source, "ANTHROPIC_API_KEY"),
            _literal_constant(source, "ANTHROPIC_BASE_URL"),
            _literal_constant(source, "ANTHROPIC_VERSION"),
        )


def _response_text(response: dict[str, Any]) -> str:
    blocks = response.get("content", [])
    if not isinstance(blocks, list):
        raise RuntimeError("expected-label API response content is not an array")
    for block in blocks:
        if (
            isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ):
            return block["text"]
    raise RuntimeError("expected-label API response has no text block")


def call_expected_api(
    prompt: str,
    *,
    model: str,
    max_tokens: int,
    timeout: float,
    retries: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    api_key, base_url, api_version = _api_settings()
    if not api_key.strip():
        raise RuntimeError("ANTHROPIC_API_KEY is empty in the Judge configuration")
    endpoint = base_url.rstrip("/") + "/v1/messages"
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {
            "format": {"type": "json_schema", "schema": EXPECTED_SCHEMA}
        },
    }
    request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    retryable_codes = {408, 409, 429, 500, 502, 503, 504}
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            endpoint,
            data=request_body,
            headers={
                "x-api-key": api_key.strip(),
                "anthropic-version": api_version,
                "content-type": "application/json",
                "accept": "application/json",
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", "replace")
                status = response.status
                headers = dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code in retryable_codes and attempt < retries:
                time.sleep(min(2**attempt, 8))
                continue
            raise RuntimeError(
                f"expected-label API HTTP {exc.code}: {body[:2000]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < retries:
                time.sleep(min(2**attempt, 8))
                continue
            raise RuntimeError(f"expected-label API connection failed: {exc}") from exc
        elapsed = time.monotonic() - started
        if status < 200 or status >= 300:
            if status in retryable_codes and attempt < retries:
                time.sleep(min(2**attempt, 8))
                continue
            raise RuntimeError(f"expected-label API HTTP {status}: {raw[:2000]}")
        response_object = json.loads(raw)
        parsed = json.loads(_response_text(response_object))
        if not isinstance(parsed, dict):
            raise RuntimeError("expected-label API result must be a JSON object")
        return parsed, {
            "model": model,
            "endpoint": endpoint,
            "request_id": headers.get("x-request-id")
            or headers.get("request-id")
            or response_object.get("id"),
            "usage": response_object.get("usage"),
            "stop_reason": response_object.get("stop_reason"),
            "elapsed_seconds": round(elapsed, 3),
            "attempts": attempt + 1,
        }
    raise AssertionError("unreachable")


def _clean_text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location} must be a non-empty string")
    return " ".join(value.split())


def _canonical_ref(value: Any, valid_refs: set[str]) -> str | None:
    ref = str(value or "").strip()
    if ref in valid_refs:
        return ref
    match = re.fullmatch(r"seg-(\d+)", ref, re.IGNORECASE)
    if not match:
        return None
    canonical = f"seg-{int(match.group(1)):06d}"
    return canonical if canonical in valid_refs else None


def _clean_refs(value: Any, *, valid_refs: set[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    refs = [
        canonical
        for item in value
        if (canonical := _canonical_ref(item, valid_refs)) is not None
    ]
    return list(dict.fromkeys(refs))


def _representative_refs(refs: list[str], limit: int = 3) -> list[str]:
    if len(refs) <= limit:
        return refs
    indexes = [round(index * (len(refs) - 1) / (limit - 1)) for index in range(limit)]
    return [refs[index] for index in dict.fromkeys(indexes)]


def _optional_text(value: Any) -> str | None:
    if value is None or not isinstance(value, str) or not value.strip():
        return None
    return " ".join(value.split())


def validate_expected(
    raw: dict[str, Any],
    segments: list[dict[str, Any]],
    *,
    require_core_facts: bool = False,
) -> dict[str, Any]:
    """Normalize expected labels and enforce reference integrity."""
    if not isinstance(raw, dict):
        raise ValueError("expected label must be a JSON object")
    has_core_facts = "core_facts" in raw
    required_fields = TARGET_FIELDS if require_core_facts or has_core_facts else LEGACY_TARGET_FIELDS
    missing = sorted(set(required_fields) - set(raw))
    extra = sorted(set(raw) - set(required_fields))
    if missing or extra:
        raise ValueError(f"expected fields mismatch; missing={missing}, extra={extra}")
    if not segments:
        raise ValueError("reference Timeline has no non-empty segments")

    by_id = {str(item["segment_id"]): item for item in segments}
    segment_ids = list(by_id)
    positions = {segment_id: index for index, segment_id in enumerate(segment_ids)}
    valid_refs = set(by_id)

    overview_raw = raw.get("overview")
    if not isinstance(overview_raw, dict):
        raise ValueError("overview must be an object")
    overview_refs = _clean_refs(overview_raw.get("refs"), valid_refs=valid_refs)
    if not overview_refs:
        overview_refs = _representative_refs(segment_ids, limit=5)
    overview = {
        "text": _clean_text(overview_raw.get("text"), "overview.text"),
        "refs": overview_refs,
    }

    chapters_raw = raw.get("chapters")
    if not isinstance(chapters_raw, list) or not chapters_raw:
        raise ValueError("chapters must be a non-empty array")
    chapters_raw = chapters_raw[: len(segment_ids)]
    chapters = []
    previous_end = -1
    for index, item in enumerate(chapters_raw):
        location = f"chapters[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{location} must be an object")
        refs = _clean_refs(item.get("refs"), valid_refs=valid_refs)
        proposed_end_ref = _canonical_ref(item.get("end_ref"), valid_refs)
        proposed_end = (
            positions[proposed_end_ref]
            if proposed_end_ref is not None
            else max((positions[ref] for ref in refs), default=previous_end + 1)
        )
        start = previous_end + 1
        remaining_chapters = len(chapters_raw) - index - 1
        maximum_end = len(segment_ids) - remaining_chapters - 1
        end = len(segment_ids) - 1 if not remaining_chapters else proposed_end
        end = max(start, min(end, maximum_end))
        start_ref = segment_ids[start]
        end_ref = segment_ids[end]
        refs = [ref for ref in refs if start <= positions[ref] <= end]
        if not refs:
            refs = _representative_refs(segment_ids[start : end + 1])
        title = _optional_text(item.get("title")) or f"章节 {index + 1}"
        chapters.append(
            {
                "title": title,
                "overview": _clean_text(
                    item.get("overview"), f"{location}.overview"
                ),
                "start_ref": start_ref,
                "end_ref": end_ref,
                "refs": refs,
            }
        )
        previous_end = end

    speakers_raw = raw.get("speakers")
    if not isinstance(speakers_raw, list):
        raise ValueError("speakers must be an array")
    expected_speaker_ids = sorted({str(item["speaker_id"]) for item in segments})
    generated_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(speakers_raw):
        if not isinstance(item, dict):
            raise ValueError(f"speakers[{index}] must be an object")
        speaker_id = str(item.get("speaker_id") or "")
        if speaker_id in generated_by_id:
            raise ValueError(f"duplicate speaker_id: {speaker_id}")
        generated_by_id[speaker_id] = item
    if sorted(generated_by_id) != expected_speaker_ids:
        raise ValueError(
            "speaker IDs mismatch; "
            f"expected={expected_speaker_ids}, actual={sorted(generated_by_id)}"
        )
    speakers = []
    for speaker_id in expected_speaker_ids:
        item = generated_by_id[speaker_id]
        refs = _clean_refs(item.get("refs"), valid_refs=valid_refs)
        refs = [
            ref for ref in refs if str(by_id[ref]["speaker_id"]) == speaker_id
        ]
        if not refs:
            own_refs = [
                ref
                for ref in segment_ids
                if str(by_id[ref]["speaker_id"]) == speaker_id
            ]
            refs = _representative_refs(own_refs)
        speakers.append(
            {
                "speaker_id": speaker_id,
                "overview": _clean_text(
                    item.get("overview"), f"speakers[{speaker_id}].overview"
                ),
                "refs": refs,
            }
        )

    actions_raw = raw.get("action_items")
    if not isinstance(actions_raw, list):
        raise ValueError("action_items must be an array")
    action_items = []
    for item in actions_raw:
        if not isinstance(item, dict):
            continue
        task = _optional_text(item.get("task"))
        refs = _clean_refs(item.get("refs"), valid_refs=valid_refs)
        if task is None or not refs:
            continue
        action_items.append(
            {
                "task": task,
                "owner": _optional_text(item.get("owner")),
                "deadline": _optional_text(item.get("deadline")),
                "refs": refs,
            }
        )

    core_facts = []
    if has_core_facts:
        core_facts_raw = raw.get("core_facts")
        if not isinstance(core_facts_raw, list):
            raise ValueError("core_facts must be an array")
        if not 1 <= len(core_facts_raw) <= 10:
            raise ValueError("core_facts must contain between 1 and 10 facts")
        seen_texts: set[str] = set()
        for index, item in enumerate(core_facts_raw):
            location = f"core_facts[{index}]"
            if not isinstance(item, dict):
                raise ValueError(f"{location} must be an object")
            text = _clean_text(item.get("text"), f"{location}.text")
            importance = item.get("importance")
            if importance not in {"major", "critical"}:
                raise ValueError(f"{location}.importance must be major or critical")
            refs = _clean_refs(item.get("refs"), valid_refs=valid_refs)
            if not refs:
                raise ValueError(f"{location}.refs must contain valid Reference refs")
            normalized_text = re.sub(r"\s+", "", text).casefold()
            if normalized_text in seen_texts:
                raise ValueError(f"duplicate core fact text at {location}")
            seen_texts.add(normalized_text)
            core_facts.append(
                {"text": text, "importance": importance, "refs": refs}
            )

    normalized = {
        "overview": overview,
        "chapters": chapters,
        "speakers": speakers,
        "action_items": action_items,
    }
    if has_core_facts:
        normalized["core_facts"] = core_facts
    return normalized


def build_e2e_manifest(
    cases: list[SourceCase],
    *,
    dataset_root: pathlib.Path,
    manifest_path: pathlib.Path,
    model: str,
) -> dict[str, Any]:
    dataset_root = dataset_root.resolve()
    manifest_path = manifest_path.resolve()
    records = []
    for case in cases:
        record: dict[str, Any] = {
            "name": case.case_id,
            "group": case.split,
            "category": "meeting",
            "audio_file": _relative(case.audio_path, dataset_root),
            "reference_timeline_file": _relative(
                case.textgrid_path, dataset_root
            ),
            "expected_file": _relative(case.expected_path, dataset_root),
            "expected_source": "llm_assisted_from_official_textgrid",
            "expected_schema_version": PREPARATION_VERSION,
        }
        if case.rttm_path is not None:
            record["rttm_file"] = _relative(case.rttm_path, dataset_root)
        records.append(record)
    return {
        "dataset_root": _relative(dataset_root, manifest_path.parent),
        "preparation": {
            "version": PREPARATION_VERSION,
            "model": model,
            "factual_ground_truth": "official_textgrid",
            "expected_label_type": "llm_assisted_reference",
        },
        "cases": records,
    }


def prepare_case(
    case: SourceCase,
    *,
    model: str,
    max_tokens: int,
    timeout: float,
    retries: int,
    validation_retries: int,
    resume: bool,
    metadata_root: pathlib.Path,
) -> dict[str, Any]:
    segments, _ = parse_textgrid(case.textgrid_path)
    if not segments:
        raise ValueError(f"TextGrid has no non-empty intervals: {case.textgrid_path}")
    if resume and case.expected_path.is_file():
        existing = json.loads(case.expected_path.read_text(encoding="utf-8"))
        try:
            validate_expected(existing, segments, require_core_facts=True)
        except (TypeError, ValueError):
            pass
        else:
            return {
                "case_id": case.case_id,
                "split": case.split,
                "status": "reused",
                "expected_file": str(case.expected_path),
                "segment_count": len(segments),
            }

    base_prompt = build_expected_prompt(case, segments)
    prompt = base_prompt
    validation_errors = []
    expected = None
    request: dict[str, Any] = {}
    for validation_attempt in range(validation_retries + 1):
        raw, request = call_expected_api(
            prompt,
            model=model,
            max_tokens=max_tokens,
            timeout=timeout,
            retries=retries,
        )
        try:
            expected = validate_expected(raw, segments, require_core_facts=True)
            break
        except (TypeError, ValueError) as exc:
            validation_errors.append(str(exc))
            if validation_attempt >= validation_retries:
                raise
            prompt = (
                base_prompt
                + "\n\n=== 上一次输出的校验错误 ===\n"
                + str(exc)
                + "\n请修正上述错误并重新输出完整四字段 JSON。"
            )
    if expected is None:
        raise AssertionError("expected-label validation produced no result")
    request["label_generation_attempts"] = len(validation_errors) + 1
    request["validation_retry_errors"] = validation_errors
    _write_json(case.expected_path, expected)
    metadata_path = metadata_root / case.split / f"{case.stem}.json"
    _write_json(
        metadata_path,
        {
            "case_id": case.case_id,
            "split": case.split,
            "preparation_version": PREPARATION_VERSION,
            "source_textgrid": str(case.textgrid_path),
            "segment_count": len(segments),
            "timeline_characters": len(render_reference_timeline(segments)),
            "request": request,
            "validation": {
                "chapter_count": len(expected["chapters"]),
                "speaker_count": len(expected["speakers"]),
                "action_item_count": len(expected["action_items"]),
                "core_fact_count": len(expected.get("core_facts", [])),
                "core_fact_importance_counts": {
                    importance: sum(
                        item.get("importance") == importance
                        for item in expected.get("core_facts", [])
                    )
                    for importance in ("major", "critical")
                },
            },
        },
    )
    return {
        "case_id": case.case_id,
        "split": case.split,
        "status": "success",
        "expected_file": str(case.expected_path),
        "segment_count": len(segments),
        "request": request,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--output-root")
    parser.add_argument("--manifest-path")
    parser.add_argument("--splits", nargs="+", default=list(DEFAULT_SPLITS))
    parser.add_argument("--cases", help="comma-separated case IDs or audio stems")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=16384)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--validation-retries",
        type=int,
        default=2,
        help="regenerate labels that fail reference-integrity validation",
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.retries < 0 or args.validation_retries < 0:
        raise SystemExit("retry counts must be non-negative")

    dataset_root = pathlib.Path(args.dataset_root).expanduser().resolve()
    output_root = (
        pathlib.Path(args.output_root).expanduser().resolve()
        if args.output_root
        else dataset_root / "e2e_expected"
    )
    manifest_path = (
        pathlib.Path(args.manifest_path).expanduser().resolve()
        if args.manifest_path
        else dataset_root / "e2e_manifest.json"
    )
    all_cases = discover_cases(dataset_root, output_root, args.splits)
    selected = (
        {item.strip() for item in args.cases.split(",") if item.strip()}
        if args.cases
        else None
    )
    cases = [
        case
        for case in all_cases
        if selected is None or case.case_id in selected or case.stem in selected
    ]
    if selected:
        matched = {
            name
            for name in selected
            if any(name in {case.case_id, case.stem} for case in all_cases)
        }
        if matched != selected:
            raise SystemExit(f"unknown cases: {sorted(selected - matched)}")
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit must be at least 1")
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("no cases selected")

    output_root.mkdir(parents=True, exist_ok=True)
    metadata_root = output_root / "_metadata"
    results = []
    for index, case in enumerate(cases, 1):
        try:
            result = prepare_case(
                case,
                model=args.model,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
                retries=args.retries,
                validation_retries=args.validation_retries,
                resume=args.resume,
                metadata_root=metadata_root,
            )
        except Exception as exc:  # noqa: BLE001 - isolate failures in a long batch
            result = {
                "case_id": case.case_id,
                "split": case.split,
                "status": "failed",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        results.append(result)
        print(
            f"[{index}/{len(cases)}] {case.case_id}: {result['status']}",
            flush=True,
        )

    manifest = build_e2e_manifest(
        cases,
        dataset_root=dataset_root,
        manifest_path=manifest_path,
        model=args.model,
    )
    _write_json(manifest_path, manifest)
    preparation = {
        "version": PREPARATION_VERSION,
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "manifest_path": str(manifest_path),
        "model": args.model,
        "case_count": len(cases),
        "success_count": sum(
            item.get("status") in {"success", "reused"} for item in results
        ),
        "failed_count": sum(item.get("status") == "failed" for item in results),
        "results": results,
    }
    _write_json(output_root / "preparation_manifest.json", preparation)
    print(
        json.dumps(
            {
                "case_count": preparation["case_count"],
                "success_count": preparation["success_count"],
                "failed_count": preparation["failed_count"],
                "output_root": str(output_root),
                "manifest_path": str(manifest_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if preparation["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

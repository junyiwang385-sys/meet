"""Prepare VCSum expected labels for Meeting_Agent's four-field output protocol."""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import urllib.error
import urllib.request
from typing import Any

from .llm_judge import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_VERSION
from .run_eval import _manifest_cases, parse_timeline

TARGET_FIELDS = ("overview", "chapters", "speakers", "action_items")
SPEAKER_PROMPT_VERSION = "speaker_reference_v1"


def _write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _speaker_prompt(
    *,
    case_id: str,
    title: str | None,
    speakers: list[dict[str, Any]],
    speaker_documents: dict[str, str],
) -> str:
    documents = []
    for item in speakers:
        speaker_id = str(item.get("speaker_id"))
        documents.append(
            "=== " + speaker_id + " ===\n"
            "代表性 refs: " + json.dumps(item.get("refs", []), ensure_ascii=False) + "\n"
            "该 speaker 的完整原文:\n" + speaker_documents.get(speaker_id, "")
        )
    return f"""你是会议参考标注整理员。请根据一场会议 Timeline 中每个 speaker 的真实原文，为评测数据生成自然、简洁、事实准确的发言人总结。

会议 case_id：{case_id}
会议标题：{title or ""}

规则：
1. 只依据对应 speaker 的原文；不要使用其他 speaker 的观点补全。
2. 每个 speaker 只输出一条 overview，概括该 speaker 的实际贡献：事实、观点、方案、案例、判断或主持工作。
3. 不要输出“发言涉及……议题”的主题列表，不要复述章节标题列表。
4. 不要推测姓名、职位、身份或未在原文中明确的责任。
5. 主持人的总结只能概括主持、提问、串联和明确表达的观点，不能把嘉宾回答归给主持人。
6. 如果 speaker 主要是简短回应，也要给出简短、客观的总结，不要虚构内容。
7. speaker_id 必须与输入完全一致；必须为每个输入 speaker 输出一项，不能增删 speaker。
8. 只返回一个 JSON 对象，不要 Markdown：{{"speakers":[{{"speaker_id":"speaker_1","overview":"……"}}]}}

""" + "\n\n".join(documents)


def _call_speaker_api(prompt: str, *, model: str, timeout: float) -> dict[str, Any]:
    if not ANTHROPIC_API_KEY.strip():
        raise RuntimeError("ANTHROPIC_API_KEY is empty in evals/llm_judge.py")
    endpoint = ANTHROPIC_BASE_URL.rstrip("/") + "/v1/messages"
    payload = {
        "model": model,
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": prompt}],
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
            raw = response.read().decode("utf-8", "replace")
            status = response.status
            headers = dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"speaker API HTTP {exc.code}: {body[:1000]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"speaker API connection failed: {exc}") from exc
    if status < 200 or status >= 300:
        raise RuntimeError(f"speaker API HTTP {status}: {raw[:1000]}")
    response = json.loads(raw)
    blocks = response.get("content", []) if isinstance(response, dict) else []
    text = next(
        (
            block.get("text")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        ),
        None,
    )
    if not text:
        raise RuntimeError("speaker API response has no text block")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"speaker API returned invalid JSON: {text[:1000]}") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("speakers"), list):
        raise RuntimeError("speaker API JSON must contain a speakers array")
    return {
        "response": parsed,
        "request_id": headers.get("x-request-id") or headers.get("request-id"),
        "usage": response.get("usage"),
        "stop_reason": response.get("stop_reason"),
    }


def _validate_speakers(
    generated: dict[str, Any],
    source_speakers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expected_ids = [str(item.get("speaker_id")) for item in source_speakers]
    generated_by_id = {
        str(item.get("speaker_id")): item
        for item in generated.get("speakers", [])
        if isinstance(item, dict) and item.get("speaker_id")
    }
    if set(generated_by_id) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(generated_by_id))
        extra = sorted(set(generated_by_id) - set(expected_ids))
        raise ValueError(f"speaker ids mismatch; missing={missing}, extra={extra}")
    result = []
    for source in source_speakers:
        speaker_id = str(source["speaker_id"])
        overview = generated_by_id[speaker_id].get("overview")
        if not isinstance(overview, str) or not overview.strip():
            raise ValueError(f"empty generated speaker overview: {speaker_id}")
        result.append({
            "speaker_id": speaker_id,
            "overview": " ".join(overview.split()),
            "refs": [str(ref) for ref in source.get("refs", [])],
        })
    return result


def prepare_case(
    case: Any,
    *,
    output_root: pathlib.Path,
    model: str,
    timeout: float,
) -> dict[str, Any]:
    raw = json.loads(case.expected_path.read_text(encoding="utf-8"))
    segments, _, _ = parse_timeline(case.timeline_path)
    by_speaker: dict[str, list[str]] = {}
    valid_refs = {segment["segment_id"] for segment in segments}
    for segment in segments:
        by_speaker.setdefault(str(segment["speaker_id"]), []).append(
            f"[{segment['segment_id']}][{segment['speaker_id']}] {segment['text']}"
        )
    source_speakers = [item for item in raw.get("speakers", []) if isinstance(item, dict)]
    speaker_documents = {speaker_id: "\n".join(lines) for speaker_id, lines in by_speaker.items()}
    prompt = _speaker_prompt(
        case_id=case.case_id,
        title=raw.get("title"),
        speakers=source_speakers,
        speaker_documents=speaker_documents,
    )
    api = _call_speaker_api(prompt, model=model, timeout=timeout)
    speakers = _validate_speakers(api["response"], source_speakers)
    invalid_refs = [
        {"speaker_id": item["speaker_id"], "ref": ref}
        for item in speakers
        for ref in item["refs"]
        if ref not in valid_refs
    ]
    if invalid_refs:
        raise ValueError(f"invalid speaker refs: {invalid_refs[:5]}")
    target = {
        "overview": raw.get("overview"),
        "chapters": raw.get("chapters", []),
        "speakers": speakers,
        "action_items": raw.get("action_items", []),
    }
    output_path = output_root / case.expected_path.name
    _write_json(output_path, target)
    return {
        "case_id": case.case_id,
        "status": "success",
        "output": str(output_path),
        "speaker_count": len(speakers),
        "removed_fields": sorted(set(raw) - set(target)),
        "request_id": api.get("request_id"),
        "usage": api.get("usage"),
        "stop_reason": api.get("stop_reason"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default="data/vcsum")
    parser.add_argument("--output-root", default="data/vcsum/eval_expected")
    parser.add_argument("--backup-root", default="data/vcsum/expected_original")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--cases")
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()
    data_root = pathlib.Path(args.data_root).expanduser().resolve()
    output_root = pathlib.Path(args.output_root).expanduser().resolve()
    backup_root = pathlib.Path(args.backup_root).expanduser().resolve()
    if args.in_place:
        output_root = data_root
        backup_root.mkdir(parents=True, exist_ok=True)
    selected = {item.strip() for item in args.cases.split(",")} if args.cases else None
    cases = _manifest_cases(data_root)
    cases = [case for case in cases if selected is None or case.case_id in selected]
    if selected and {case.case_id for case in cases} != selected:
        raise SystemExit(f"unknown case ids: {sorted(selected - {case.case_id for case in cases})}")
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_source = data_root / "vcsum_manifest.json"
    if manifest_source.is_file() and output_root != data_root:
        shutil.copy2(manifest_source, output_root / manifest_source.name)
    if output_root != data_root:
        for case in cases:
            if case.timeline_path.is_file():
                shutil.copy2(case.timeline_path, output_root / case.timeline_path.name)
    results = []
    for case in cases:
        if args.in_place:
            shutil.copy2(case.expected_path, backup_root / case.expected_path.name)
        try:
            results.append(prepare_case(case, output_root=output_root, model=args.model, timeout=args.timeout))
        except Exception as exc:
            results.append({"case_id": case.case_id, "status": "failed", "error": {"type": type(exc).__name__, "message": str(exc)}})
    manifest = {
        "version": SPEAKER_PROMPT_VERSION,
        "data_root": str(data_root),
        "output_root": str(output_root),
        "case_count": len(results),
        "success_count": sum(item.get("status") == "success" for item in results),
        "results": results,
    }
    _write_json(output_root / "prepare_manifest.json", manifest)
    print(json.dumps({"case_count": len(results), "success_count": manifest["success_count"], "output_root": str(output_root)}, ensure_ascii=False, indent=2))
    return 0 if manifest["success_count"] == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

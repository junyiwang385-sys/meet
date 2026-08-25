"""Board-oriented full-context and sliding-chapter meeting summarization."""

from __future__ import annotations

import json
import pathlib
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from .artifacts import atomic_write_json, atomic_write_text, load_json, sha256_file
from .chunking import (
    BudgetPolicy,
    ChunkingError,
    estimate_message_tokens,
    messages_fit,
    stable_hash,
)
from .llm import LlmConfig, LlmRunError, RkllmServerSession, SYSTEM_PROMPT
from .transcript import render_timeline
from .validation import (
    SummaryValidationError,
    clean_text,
    parse_content,
    validate_summary_object,
)


PRODUCT_SUMMARY_VERSION = "product-summary.v24"

CHAPTER_WINDOW_SHAPE = {
    "completed_chapters": [
        {
            "title": "章节标题",
            "summary": "章节摘要",
            "core_start_ref": "r1",
            "core_end_ref": "r10",
            "key_refs": ["r2", "r8"],
        }
    ],
    "action_candidates": [
        {
            "task": "明确提出的待办",
            "owner": None,
            "deadline": None,
            "refs": ["r8"],
        }
    ],
    "carryover_start_ref": None,
}

FULL_MEETING_SHAPE = {
    "title": None,
    "overview": {"text": "全文摘要", "refs": ["r1"]},
    "chapters": [
        {
            "title": "章节标题",
            "overview": "章节摘要",
            "core_start_ref": "r1",
            "core_end_ref": "r10",
            "refs": ["r1", "r10"],
        }
    ],
    "speakers": [
        {"speaker_id": "sp1", "overview": "发言人总结", "refs": ["r1"]}
    ],
    "action_items": [
        {
            "task": "明确待办事项",
            "owner": None,
            "deadline": None,
            "refs": ["r1"],
        }
    ],
}

FULL_SUMMARY_SHAPE = {
    "title": None,
    "overview": {"text": "全文摘要"},
}

ACTION_REVIEW_SHAPE = {
    "action_items": [
        {
            "task": "确认后的待办",
            "owner": None,
            "deadline": None,
            "refs": ["r1"],
        }
    ]
}

SPEAKER_BATCH_SHAPE = {
    "speakers": [
        {
            "speaker_id": "sp1",
            "overview": "该发言人的会议贡献总结",
            "refs": ["r1"],
        }
    ]
}


@dataclass(frozen=True)
class ProductSummaryConfig:
    llm: LlmConfig
    safety_tokens: int
    chars_per_token: float
    fixed_overhead_tokens: int
    resume: bool

    @property
    def budget(self) -> BudgetPolicy:
        return BudgetPolicy(
            ctx=self.llm.ctx,
            output_tokens=self.llm.max_tokens,
            safety_tokens=self.safety_tokens,
            chars_per_token=self.chars_per_token,
            fixed_overhead_tokens=self.fixed_overhead_tokens,
            overlap_segments=0,
        )



def _compact_ref_name(segment_id: str, fallback_index: int) -> str:
    match = re.fullmatch(r"seg-(\d+)", str(segment_id))
    if match:
        return f"r{int(match.group(1))}"
    return f"r{fallback_index}"


def _build_compact_ref_map(
    segments: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, str]]:
    forward: dict[str, str] = {}
    reverse: dict[str, str] = {}
    for index, segment in enumerate(segments, 1):
        canonical = str(segment["segment_id"])
        compact = _compact_ref_name(canonical, index)
        if compact in reverse and reverse[compact] != canonical:
            compact = f"r{index}"
        forward[canonical] = compact
        reverse[compact] = canonical
    return forward, reverse


def _build_compact_ref_map_from_ids(
    segment_ids: list[str],
) -> tuple[dict[str, str], dict[str, str]]:
    return _build_compact_ref_map(
        [{"segment_id": segment_id} for segment_id in segment_ids]
    )


def _build_compact_speaker_map(
    speaker_ids: list[str],
) -> tuple[dict[str, str], dict[str, str]]:
    forward: dict[str, str] = {}
    reverse: dict[str, str] = {}
    for index, canonical in enumerate(dict.fromkeys(str(item) for item in speaker_ids), 1):
        match = re.fullmatch(r"speaker_(\d+)", canonical)
        compact = f"sp{int(match.group(1))}" if match else f"sp{index}"
        if compact in reverse and reverse[compact] != canonical:
            compact = f"sp{index}"
        forward[canonical] = compact
        reverse[compact] = canonical
    return forward, reverse


def _compactize_payload(
    value: Any,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
    key: str | None = None,
) -> Any:
    ref_keys = {
        "segment_id",
        "start_ref",
        "end_ref",
        "core_start_ref",
        "core_end_ref",
        "carryover_start_ref",
        "refs",
    }
    speaker_keys = {"speaker_id", "owner"}
    if isinstance(value, dict):
        return {
            item_key: _compactize_payload(item_value, ref_map, speaker_map, item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_compactize_payload(item, ref_map, speaker_map, key) for item in value]
    if isinstance(value, str):
        if key in ref_keys:
            return ref_map.get(value, value)
        if key in speaker_keys:
            return speaker_map.get(value, value)
    return value


def _expand_payload(
    value: Any,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
    key: str | None = None,
) -> Any:
    ref_keys = {
        "segment_id",
        "start_ref",
        "end_ref",
        "core_start_ref",
        "core_end_ref",
        "carryover_start_ref",
        "refs",
    }
    speaker_keys = {"speaker_id", "owner"}
    if isinstance(value, dict):
        return {
            item_key: _expand_payload(item_value, ref_map, speaker_map, item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_expand_payload(item, ref_map, speaker_map, key) for item in value]
    if isinstance(value, str):
        if key in ref_keys:
            return ref_map.get(value, value)
        if key in speaker_keys:
            return speaker_map.get(value, value)
    return value


def _prompt_time(ms: int) -> str:
    total_seconds = max(0, int(ms) // 1000)
    return f"{total_seconds // 60}m{total_seconds % 60:02d}s"


def _render_compact_timeline(
    segments: list[dict[str, Any]],
    ref_map: dict[str, str] | None = None,
    speaker_map: dict[str, str] | None = None,
) -> str:
    if ref_map is None:
        ref_map, _ = _build_compact_ref_map(segments)
    if speaker_map is None:
        speaker_map, _ = _build_compact_speaker_map(
            [segment["speaker_id"] for segment in segments]
        )
    return "\n".join(
        f"[{ref_map.get(segment['segment_id'], segment['segment_id'])}]"
        f"[{_prompt_time(segment['start_ms'])}-{_prompt_time(segment['end_ms'])}]"
        f"[{speaker_map.get(segment['speaker_id'], segment['speaker_id'])}] {segment['text']}"
        for segment in segments
    )


def _full_meeting_messages(
    timeline: str,
    speaker_ids: list[str],
    *,
    ref_map: dict[str, str] | None = None,
    speaker_map: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    if ref_map is None:
        timeline_ids = re.findall(r"(?m)^\[(seg-[0-9]+)\]", timeline)
        ref_map, _ = _build_compact_ref_map_from_ids(timeline_ids)
    if speaker_map is None:
        speaker_map, _ = _build_compact_speaker_map(speaker_ids)
    compact_timeline = timeline
    for canonical, compact in ref_map.items():
        compact_timeline = compact_timeline.replace(f"[{canonical}]", f"[{compact}]")
    for canonical, compact in speaker_map.items():
        compact_timeline = compact_timeline.replace(f"[{canonical}]", f"[{compact}]")
    prompt_shape = _compactize_payload(FULL_MEETING_SHAPE, ref_map, speaker_map)
    compact_speaker_ids = [speaker_map.get(item, item) for item in speaker_ids]
    prompt = (
        "任务：\n"
        "根据下面的完整会议 Timeline，生成会议标题、全文摘要、核心章节、发言人总结和最终待办。\n"
        "所有内容都必须来自输入 Timeline；不同输出之间可以共享事实，但不要重复堆砌同一段原文。\n"
        "全文摘要：\n"
        "- overview 使用约 300～500 个中文字符，形成一段完整、连贯的会议总结。\n"
        "- 先概括会议背景、目标和整体进展，再概括主要议题及其推进关系。\n"
        "- 应覆盖最重要的事实、数据、方案、关键分歧、取舍、形成的结论，以及明确的后续行动。\n"
        "- 如果议题之间存在因果、依赖或先后关系，应说明这种关系，不要只罗列主题。\n"
        "- 对尚未解决的问题、风险或限制，只能在原文明确提及时概括；没有明确结论时保持讨论、建议或待确认的语气。\n"
        "- 不要逐章机械拼接，不要把普通发言、寒暄、重复确认或礼貌回应写进全文摘要。\n"
        "- overview.refs 应覆盖能够代表全文主要内容的原始 segment，不要只引用开场的一段。\n\n"
        "核心章节：\n"
        "- 只输出有独立问题、方案、事实、决定、风险或行动的实质章节。\n"
        "- 每个章节使用 core_start_ref/core_end_ref 标记核心讨论范围；该范围用于生成 overview 和 refs，不是完整时间轴范围。\n"
        "- 开场、寒暄、重复确认、章节间过渡和会议收尾不单独形成章节，也不需要判断其时间归属。\n"
        "- 识别一个章节后继续扫描后面的 Timeline；如果讨论对象、行业场景、问题目标或结论方向发生变化，必须新建章节。\n"
        "- 章节必须按时间顺序排列，core_start_ref/core_end_ref 的范围不得互相重叠；后一个章节必须从前一个章节结束之后开始。\n"
        "- 每个章节 overview 使用约 120～220 个中文字符、3～5 句，说明背景或问题、关键事实或方案、结论及影响；不得补充原文没有的信息。\n"
        "- 章节 overview 只总结该章节，不要把整场会议的结论重复写入每个章节。\n\n"
        "发言人总结：\n"
        "- 只为在会议中有足够实质发言的 speaker 输出一条总结；没有足够内容时不要输出。\n"
        "- overview 概括该发言人在全场会议中的主要事实、观点、方案、决定或行动，使用简洁的连续表述，不要拆成发言人要点列表。\n"
        "- speaker_id 必须来自允许的 speaker_id；refs 必须全部属于该 speaker 的原文，并且能够直接支持这条总结。\n"
        "- 不要根据发言次数、发言时长、语气或上下文推测姓名、身份、职位或职责。\n"
        "- 不要输出 speaker_key_points、发言人要点或输出结构之外的发言人字段。\n\n"
        "最终待办：\n"
        "- 只保留会议中明确要求执行、确认执行或明确分配的后续事项。\n"
        "- 普通讨论、建议、愿望、可能性和未确认方案不能作为待办。\n"
        "- 合并表达相同的任务，避免同一事项因为多处讨论而重复输出。\n"
        "- owner 只有在原文明确支持时才填写对应 speaker_id，否则使用 null。\n"
        "- deadline 只有在原文明确出现时才填写，否则使用 null。\n"
        "- 每条待办必须绑定能够直接支持该任务的 refs；没有明确待办时返回 []。\n\n"
        f"允许的 speaker_id：{json.dumps(compact_speaker_ids, ensure_ascii=False)}\n"
        "输出结构：\n"
        f"{json.dumps(prompt_shape, ensure_ascii=False, indent=2)}\n\n"
        f"输入 Timeline：\n{compact_timeline}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]


def _chapter_window_messages(
    segments: list[dict[str, Any]],
    *,
    ref_map: dict[str, str] | None = None,
    speaker_map: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    timeline = _render_compact_timeline(segments, ref_map, speaker_map)
    prompt_shape = _compactize_payload(
        CHAPTER_WINDOW_SHAPE,
        ref_map or _build_compact_ref_map(segments)[0],
        speaker_map or _build_compact_speaker_map(
            [segment["speaker_id"] for segment in segments]
        )[0],
    )
    prompt = (
        "任务：\n"
        "根据下面的 Timeline，识别当前输入中已经完成的实质核心章节，并生成章节摘要和待办候选。\n\n"
        "核心章节规则：\n"
        "- 只输出有独立问题、方案、事实、决定、风险或行动的实质章节。\n"
        "- 每个章节使用 core_start_ref/core_end_ref 标记核心讨论范围；summary 和 key_refs 只依据该核心范围。\n"
        "- 开场、寒暄、重复确认、章节间过渡和会议收尾不单独形成章节，时间归属由程序处理。\n"
        "- 识别一个章节后必须继续扫描到当前 Timeline 末尾；如果讨论对象、行业场景、问题目标或结论方向变化，必须新建章节，不能只输出第一个宽泛主题。\n"
        "- 章节必须按时间顺序排列，core_start_ref/core_end_ref 的范围不得互相重叠；后一个章节必须从前一个章节结束之后开始。\n"
        "- 每个章节 summary 使用约 120～220 个中文字符、3～5 句，说明背景或问题、关键事实或方案、结论及影响。\n"
        "- 每个章节最多输出 3 个 key_refs。\n\n"
        "待办候选：\n"
        "- 只提取当前窗口中已经明确要求执行、确认执行或明确分配的后续事项。\n"
        "- 普通讨论、建议、可能性和未确认方案不要输出为待办。\n"
        "- owner、deadline 和 refs 只能依据当前窗口原文填写；没有明确依据时使用 null。\n"
        "- 当前窗口没有明确待办时返回 []。\n\n"
        "carryover：\n"
        "- 如果窗口末尾有尚未完成的实质话题，不要把它输出为 completed_chapters。\n"
        "- carryover_start_ref 指向该话题的起点；没有未完成话题时使用 JSON null。\n"
        "- 普通建议、观点和礼貌回应不能升级为待办；未完成话题中的待办留到下一窗口。\n\n"
        "输出结构：\n"
        f"{json.dumps(prompt_shape, ensure_ascii=False, indent=2)}\n\n"
        f"输入 Timeline：\n{timeline}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]


def _full_summary_messages(
    chapters: list[dict[str, Any]],
    *,
    ref_map: dict[str, str] | None = None,
    speaker_map: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    compact = [
        {
            "id": index,
            "title": chapter["title"],
            "summary": chapter["overview"],
        }
        for index, chapter in enumerate(chapters, 1)
    ]
    prompt_shape = FULL_SUMMARY_SHAPE
    prompt = (
        "任务：\n"
        "根据下面按时间排列、已经校验的章节摘要，生成会议标题和全文摘要。\n\n"
        "全文摘要要求：\n"
        "- 使用约 300～500 个中文字符。\n"
        "- 综合主要议题、关键背景和事实数据、重要观点或方案、主要分歧与取舍、形成的结论以及明确的后续行动。\n"
        "- 体现各章节之间的逻辑关系，不要逐章机械拼接。\n"
        "- 没有明确结论时保持讨论或建议语气，不能擅自写成决定。\n"
        "- 只输出标题和摘要正文，不要输出或讨论 refs；引用由程序从已校验章节自动合并。\n\n"
        "输出结构：\n"
        f"{json.dumps(prompt_shape, ensure_ascii=False, indent=2)}\n\n"
        f"输入章节：\n{json.dumps(compact, ensure_ascii=False, indent=2)}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]


def _build_speaker_documents(
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group non-empty transcript segments by speaker in first-appearance order."""
    documents: dict[str, dict[str, Any]] = {}
    for segment in segments:
        speaker_id = str(segment["speaker_id"])
        document = documents.setdefault(
            speaker_id,
            {
                "speaker_id": speaker_id,
                "segments": [],
                "first_index": int(segment.get("index", len(documents))),
            },
        )
        document["segments"].append(segment)
    return list(documents.values())


def _speaker_batch_messages(
    documents: list[dict[str, Any]],
    *,
    ref_map: dict[str, str] | None = None,
    speaker_map: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    all_segments = [segment for document in documents for segment in document["segments"]]
    if ref_map is None:
        ref_map, _ = _build_compact_ref_map(all_segments)
    if speaker_map is None:
        speaker_map, _ = _build_compact_speaker_map(
            [document["speaker_id"] for document in documents]
        )
    speaker_ids = [speaker_map.get(document["speaker_id"], document["speaker_id"]) for document in documents]
    rendered_documents = []
    for document in documents:
        rendered_documents.append(
            f"===== {speaker_map.get(document['speaker_id'], document['speaker_id'])} =====\n"
            f"{_render_compact_timeline(document['segments'], ref_map, speaker_map)}"
        )
    prompt_shape = _compactize_payload(SPEAKER_BATCH_SHAPE, ref_map, speaker_map)
    prompt = (
        "任务：\n"
        "下面的会议发言已经按 speaker_id 分开。请分别概括每个发言人在所提供内容中的实质贡献。\n"
        "这不是章节总结，也不是全文摘要；每个 speaker 最多输出一条发言人总结。\n\n"
        "规则：\n"
        "- 只依据对应 speaker 文档中出现的原文，概括该发言人明确表达的事实、观点、方案、决定或行动。\n"
        "- overview 使用简洁的连续表述，不要拆成发言人要点列表。\n"
        "- speaker_id 必须来自本次输入；refs 必须全部属于对应 speaker，并且直接支持这条总结。\n"
        "- 不要推测姓名、身份、职位、职责或发言之外的意图。\n"
        "- 本批次输入中的每个 speaker_id 都必须输出一条 speakers 项，不能因为内容较短而省略。\n"
        "- 即使内容主要是简短回应、确认或礼貌表达，也要基于实际原文给出简短、客观的总结；不得虚构事实。\n"
        "- 本批次不为空时不得返回空的 speakers 数组。\n"
        "- 不要输出 speaker_key_points、发言人要点或输出结构之外的字段。\n\n"
        f"本次允许输出的 speaker_id：{json.dumps(speaker_ids, ensure_ascii=False)}\n"
        "输出结构：\n"
        f"{json.dumps(prompt_shape, ensure_ascii=False, indent=2)}\n\n"
        "发言人文档：\n"
        f"{chr(10).join(rendered_documents)}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]


def _truncate_speaker_document_to_budget(
    document: dict[str, Any],
    budget: BudgetPolicy,
    *,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Keep the longest chronological prefix that fits the speaker budget."""
    full_estimate = estimate_message_tokens(
        _speaker_batch_messages([document], ref_map=ref_map, speaker_map=speaker_map),
        budget,
    )
    if full_estimate <= budget.input_token_budget:
        return document, None

    original_segments = list(document["segments"])

    def estimate_segments(candidate_segments: list[dict[str, Any]]) -> int:
        candidate = {**document, "segments": candidate_segments}
        return estimate_message_tokens(
            _speaker_batch_messages([candidate], ref_map=ref_map, speaker_map=speaker_map),
            budget,
        )

    low = 0
    high = len(original_segments)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_segments(original_segments[:middle]) <= budget.input_token_budget:
            low = middle
        else:
            high = middle - 1

    retained_segments = list(original_segments[:low])
    if low < len(original_segments):
        next_segment = original_segments[low]
        original_text = str(next_segment.get("text") or "")
        text_low = 0
        text_high = len(original_text)
        best_text = ""
        while text_low <= text_high:
            middle = (text_low + text_high) // 2
            partial_segment = {**next_segment, "text": original_text[:middle]}
            candidate_segments = [*retained_segments, partial_segment]
            if estimate_segments(candidate_segments) <= budget.input_token_budget:
                best_text = original_text[:middle]
                text_low = middle + 1
            else:
                text_high = middle - 1
        if best_text:
            retained_segments.append({**next_segment, "text": best_text})

    if not retained_segments:
        raise ChunkingError(
            f"speaker_prompt_overhead_exceeds_budget: {document['speaker_id']}"
        )

    retained_document = {
        **document,
        "segments": retained_segments,
        "_truncation": {
            "original_segment_count": len(original_segments),
            "retained_segment_count": len(retained_segments),
            "original_text_chars": sum(len(str(item.get("text") or "")) for item in original_segments),
            "retained_text_chars": sum(len(str(item.get("text") or "")) for item in retained_segments),
            "original_estimated_prompt_tokens": full_estimate,
            "retained_estimated_prompt_tokens": estimate_segments(retained_segments),
        },
    }
    return retained_document, retained_document["_truncation"]


def _truncate_speaker_documents(
    documents: list[dict[str, Any]],
    budget: BudgetPolicy,
    *,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    truncated_documents = []
    truncations = []
    for document in documents:
        retained, record = _truncate_speaker_document_to_budget(
            document,
            budget,
            ref_map=ref_map,
            speaker_map=speaker_map,
        )
        truncated_documents.append(retained)
        if record is not None:
            truncations.append({"speaker_id": document["speaker_id"], **record})
    return truncated_documents, truncations


def _pack_speaker_documents(
    documents: list[dict[str, Any]],
    budget: BudgetPolicy,
    *,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
) -> list[list[dict[str, Any]]]:
    """Pack speakers into budget-fitting batches without relying on speaker order."""
    ordered = sorted(
        documents,
        key=lambda item: (-len(render_timeline(item["segments"])), item["first_index"]),
    )
    batches: list[list[dict[str, Any]]] = []
    estimates: list[int] = []
    for document in ordered:
        best_index = None
        best_remaining = None
        for index, batch in enumerate(batches):
            candidate = [*batch, document]
            estimate = estimate_message_tokens(_speaker_batch_messages(candidate, ref_map=ref_map, speaker_map=speaker_map), budget)
            if estimate > budget.input_token_budget:
                continue
            remaining = budget.input_token_budget - estimate
            if best_remaining is None or remaining < best_remaining:
                best_index = index
                best_remaining = remaining
        if best_index is None:
            estimate = estimate_message_tokens(_speaker_batch_messages([document], ref_map=ref_map, speaker_map=speaker_map), budget)
            if estimate > budget.input_token_budget:
                raise ChunkingError(
                    f"speaker_exceeds_speaker_batch_budget: {document['speaker_id']}"
                )
            batches.append([document])
            estimates.append(estimate)
        else:
            batches[best_index].append(document)
            estimates[best_index] = estimate_message_tokens(
                _speaker_batch_messages(batches[best_index]), budget
            )
    batches.sort(key=lambda batch: min(item["first_index"] for item in batch))
    return batches


def _validate_speaker_batch(
    content: str,
    finish_reason: Any,
    context_truncated: bool,
    documents: list[dict[str, Any]],
    *,
    ref_map: dict[str, str] | None = None,
    speaker_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if finish_reason != "stop":
        raise SummaryValidationError(f"speaker batch finish_reason is {finish_reason!r}")
    if context_truncated:
        raise SummaryValidationError("speaker batch input was truncated")
    raw = parse_content(content)
    batch_segments = [segment for document in documents for segment in document["segments"]]
    if ref_map is None:
        ref_map, _ = _build_compact_ref_map(batch_segments)
    if speaker_map is None:
        speaker_map, _ = _build_compact_speaker_map(
            [document["speaker_id"] for document in documents]
        )
    compact_ref_map = {compact: canonical for canonical, compact in ref_map.items()}
    compact_speaker_map = {compact: canonical for canonical, compact in speaker_map.items()}
    raw = _expand_payload(raw, compact_ref_map, compact_speaker_map)
    raw_speakers = raw.get("speakers", [])
    if not isinstance(raw_speakers, list):
        raise SummaryValidationError("speakers must be an array")
    segment_by_id = {
        segment["segment_id"]: segment
        for document in documents
        for segment in document["segments"]
    }
    allowed_speakers = {document["speaker_id"] for document in documents}
    results = []
    seen_speakers = set()
    for index, item in enumerate(raw_speakers):
        if not isinstance(item, dict):
            raise SummaryValidationError(f"speakers[{index}] must be an object")
        speaker_id = str(item.get("speaker_id") or "")
        overview = clean_text(item.get("overview"))
        refs = item.get("refs")
        if speaker_id not in allowed_speakers or overview is None or not isinstance(refs, list):
            continue
        valid_refs = []
        for ref in dict.fromkeys(str(ref) for ref in refs):
            segment = segment_by_id.get(ref)
            if segment is not None and segment["speaker_id"] == speaker_id and segment.get("text"):
                valid_refs.append(ref)
        if not valid_refs or speaker_id in seen_speakers:
            continue
        seen_speakers.add(speaker_id)
        results.append(
            {
                "speaker_id": speaker_id,
                "overview": overview,
                "refs": valid_refs,
            }
        )
    missing_speakers = sorted(allowed_speakers - seen_speakers)
    if missing_speakers:
        raise SummaryValidationError(
            "missing speaker summaries: " + ", ".join(missing_speakers)
        )
    return results


def _action_review_messages(
    candidates: list[dict[str, Any]],
    segment_by_id: dict[str, dict[str, Any]],
    *,
    ref_map: dict[str, str] | None = None,
    speaker_map: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    if ref_map is None:
        ref_map, _ = _build_compact_ref_map(list(segment_by_id.values()))
    if speaker_map is None:
        speaker_map, _ = _build_compact_speaker_map(
            [segment["speaker_id"] for segment in segment_by_id.values()]
        )
    evidence_ids = []
    seen = set()
    for candidate in candidates:
        for ref in candidate.get("refs", []):
            if ref in segment_by_id and ref not in seen:
                seen.add(ref)
                evidence_ids.append(ref)
    evidence = [
        {
            "segment_id": ref_map.get(ref, ref),
            "speaker_id": speaker_map.get(segment_by_id[ref]["speaker_id"], segment_by_id[ref]["speaker_id"]),
            "text": segment_by_id[ref]["text"],
        }
        for ref in evidence_ids
    ]
    compact_candidates = _compactize_payload(candidates, ref_map, speaker_map)
    prompt_shape = _compactize_payload(ACTION_REVIEW_SHAPE, ref_map, speaker_map)
    prompt = (
        "任务：\n"
        "复核下面各章节窗口提取的待办候选及其原文证据，输出最终待办。\n\n"
        "复核规则：\n"
        "- 只有明确要求后续执行的事项才保留。\n"
        "- 普通建议、观点、愿望和讨论必须删除。\n"
        "- 合并表达相同任务的候选，保留最明确的任务描述和证据。\n"
        "- owner 必须有原文依据；deadline 必须在原文明确出现，否则使用 null。\n\n"
        "输出结构：\n"
        f"{json.dumps(prompt_shape, ensure_ascii=False, indent=2)}\n\n"
        f"候选：\n{json.dumps(compact_candidates, ensure_ascii=False, indent=2)}\n\n"
        f"证据：\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]


def _fit_window(
    nonempty: list[dict[str, Any]],
    start: int,
    policy: BudgetPolicy,
    *,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
) -> tuple[int, list[dict[str, str]], int]:
    last_fit = None
    end = start
    while end < len(nonempty):
        candidate = nonempty[start : end + 1]
        messages = _chapter_window_messages(candidate, ref_map=ref_map, speaker_map=speaker_map)
        estimate = estimate_message_tokens(messages, policy)
        if estimate > policy.input_token_budget:
            break
        last_fit = (end + 1, messages, estimate)
        end += 1
    if last_fit is None:
        raise ChunkingError(
            f"segment_exceeds_chapter_window_budget: {nonempty[start]['segment_id']}"
        )
    return last_fit


def _normalize_overlapping_core_candidates(
    candidates: list[dict[str, Any]],
    repairs: list[dict[str, Any]],
    *,
    location_prefix: str,
) -> list[dict[str, Any]]:
    """Make model chapter intervals deterministic before range expansion."""
    ordered = sorted(
        (dict(candidate) for candidate in candidates),
        key=lambda item: (item["start_pos"], item["end_pos"], item.get("index", 0)),
    )
    normalized: list[dict[str, Any]] = []
    for current in ordered:
        start_pos = current["start_pos"]
        end_pos = current["end_pos"]
        if end_pos < start_pos:
            repairs.append(
                {
                    "type": "normalize_reversed_core_chapter_range",
                    "location": f"{location_prefix}[{current.get('index', len(normalized))}]",
                    "old_start_pos": start_pos,
                    "old_end_pos": end_pos,
                }
            )
            current["end_pos"] = start_pos
            end_pos = start_pos
        if normalized:
            previous = normalized[-1]
            previous_start = previous["start_pos"]
            previous_end = previous["end_pos"]
            if start_pos == previous_start:
                previous["end_pos"] = max(previous_end, end_pos)
                for refs_key in ("key_refs", "refs"):
                    previous_refs = previous.get(refs_key)
                    current_refs = current.get(refs_key)
                    if isinstance(previous_refs, list) and isinstance(current_refs, list):
                        previous[refs_key] = list(dict.fromkeys(previous_refs + current_refs))
                for text_key in ("title", "overview", "summary"):
                    previous_text = previous.get(text_key)
                    current_text = current.get(text_key)
                    if (
                        isinstance(previous_text, str)
                        and isinstance(current_text, str)
                        and current_text
                        and current_text != previous_text
                    ):
                        previous[text_key] = f"{previous_text}；{current_text}"
                repairs.append(
                    {
                        "type": "merge_same_start_core_chapters",
                        "location": f"{location_prefix}[{current.get('index', len(normalized))}]",
                        "start_pos": start_pos,
                    }
                )
                continue
            if start_pos <= previous_end:
                new_previous_end = start_pos - 1
                repairs.append(
                    {
                        "type": "clip_overlapping_core_chapter_boundary",
                        "location": f"{location_prefix}[{len(normalized) - 1}]",
                        "old_end_pos": previous_end,
                        "new_end_pos": new_previous_end,
                        "next_start_pos": start_pos,
                    }
                )
                previous["end_pos"] = new_previous_end
        normalized.append(current)
    return normalized


def _expand_core_chapter_ranges(
    core_chapters: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    *,
    coverage_end_ref: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not core_chapters:
        raise SummaryValidationError("LLM returned no completed core chapters")
    positions = {segment["segment_id"]: index for index, segment in enumerate(segments)}
    if coverage_end_ref not in positions:
        raise SummaryValidationError("chapter coverage end is outside current input")
    coverage_end_pos = positions[coverage_end_ref]
    repairs = []
    range_candidates = [
        {
            **chapter,
            "start_pos": positions[chapter["core_start_ref"]],
            "end_pos": positions[chapter["core_end_ref"]],
        }
        for chapter in core_chapters
    ]
    ordered = _normalize_overlapping_core_candidates(
        range_candidates,
        repairs,
        location_prefix="chapters",
    )
    expanded = []
    for index, chapter in enumerate(ordered):
        core_start_pos = chapter["start_pos"]
        core_end_pos = min(chapter["end_pos"], coverage_end_pos)
        core_start_ref = segments[core_start_pos]["segment_id"]
        core_end_ref = segments[core_end_pos]["segment_id"]
        if index + 1 < len(ordered):
            next_start_pos = ordered[index + 1]["start_pos"]
            full_end_pos = min(next_start_pos - 1, coverage_end_pos)
        else:
            full_end_pos = coverage_end_pos
        full_start_pos = 0 if index == 0 else core_start_pos
        if full_start_pos > full_end_pos:
            repairs.append(
                {
                    "type": "drop_empty_core_chapter_after_boundary_repair",
                    "location": f"chapters[{index}]",
                    "core_start_ref": core_start_ref,
                    "core_end_ref": core_end_ref,
                }
            )
            continue
        if core_end_pos < core_start_pos:
            core_end_pos = core_start_pos
            core_end_ref = segments[core_end_pos]["segment_id"]
        if core_end_pos > full_end_pos:
            core_end_pos = full_end_pos
            core_end_ref = segments[core_end_pos]["segment_id"]
            repairs.append(
                {
                    "type": "clip_core_chapter_to_continuous_boundary",
                    "location": f"chapters[{index}]",
                    "new_core_end_ref": core_end_ref,
                }
            )
        full_start_ref = segments[full_start_pos]["segment_id"]
        full_end_ref = segments[full_end_pos]["segment_id"]
        expanded_chapter = {
            key: value
            for key, value in chapter.items()
            if key not in {"start_pos", "end_pos"}
        }
        expanded_chapter.update(
            {
                "core_start_ref": core_start_ref,
                "core_end_ref": core_end_ref,
                "start_ref": full_start_ref,
                "end_ref": full_end_ref,
                "start_ms": segments[full_start_pos]["start_ms"],
                "end_ms": segments[full_end_pos]["end_ms"],
            }
        )
        expanded.append(expanded_chapter)
        if full_start_ref != core_start_ref or full_end_ref != core_end_ref:
            repairs.append(
                {
                    "type": "expand_core_chapter_to_continuous_range",
                    "location": f"chapters[{index}]",
                    "core_start_ref": core_start_ref,
                    "core_end_ref": core_end_ref,
                    "start_ref": full_start_ref,
                    "end_ref": full_end_ref,
                }
            )
    return expanded, repairs


def _validate_full_core_result(
    content: str,
    finish_reason: Any,
    context_truncated: bool,
    segments: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if finish_reason != "stop":
        raise SummaryValidationError(f"full summary finish_reason is {finish_reason!r}")
    if context_truncated:
        raise SummaryValidationError("full summary input was truncated")
    raw = parse_content(content)
    ref_map, compact_ref_map = _build_compact_ref_map(segments)
    speaker_map, compact_speaker_map = _build_compact_speaker_map(
        [segment["speaker_id"] for segment in segments]
    )
    raw = _expand_payload(raw, compact_ref_map, compact_speaker_map)
    raw_chapters = raw.get("chapters")
    if not isinstance(raw_chapters, list):
        raise SummaryValidationError("chapters must be an array")
    positions = {segment["segment_id"]: index for index, segment in enumerate(segments)}
    prepared_chapters = []
    pre_repairs = []
    for index, chapter in enumerate(raw_chapters):
        if not isinstance(chapter, dict):
            raise SummaryValidationError(f"chapters[{index}] must be an object")
        core_start_ref = str(
            chapter.get("core_start_ref") or chapter.get("start_ref") or ""
        )
        core_end_ref = str(
            chapter.get("core_end_ref") or chapter.get("end_ref") or ""
        )
        if core_start_ref not in positions or core_end_ref not in positions:
            raise SummaryValidationError(f"chapters[{index}] has invalid core range")
        start_pos = positions[core_start_ref]
        end_pos = positions[core_end_ref]
        if end_pos < start_pos:
            pre_repairs.append(
                {
                    "type": "normalize_reversed_core_chapter_range",
                    "location": f"chapters[{index}]",
                    "old_end_ref": core_end_ref,
                    "new_end_ref": core_start_ref,
                }
            )
            core_end_ref = core_start_ref
            end_pos = start_pos
        refs = chapter.get("refs")
        refs = refs if isinstance(refs, list) else []
        refs = list(dict.fromkeys(
            str(ref)
            for ref in refs
            if str(ref) in positions and start_pos <= positions[str(ref)] <= end_pos
        ))
        if not refs:
            refs = list(dict.fromkeys((core_start_ref, core_end_ref)))
        prepared_chapters.append(
            {
                **chapter,
                "start_ref": core_start_ref,
                "end_ref": core_end_ref,
                "refs": refs,
            }
        )
    prepared = {**raw, "chapters": prepared_chapters}
    summary, quality = validate_summary_object(prepared, segments)
    quality["repairs"].extend(pre_repairs)
    core_chapters = [
        {
            **chapter,
            "core_start_ref": chapter["start_ref"],
            "core_end_ref": chapter["end_ref"],
        }
        for chapter in summary["chapters"]
    ]
    expanded, repairs = _expand_core_chapter_ranges(
        core_chapters,
        segments,
        coverage_end_ref=segments[-1]["segment_id"],
    )
    summary["chapters"] = expanded
    quality["repairs"].extend(repairs)
    quality["checks"].update(
        {
            "core_chapters_identified": True,
            "continuous_ranges_assigned_by_harness": True,
        }
    )
    return summary, quality


def _validate_window(
    content: str,
    finish_reason: Any,
    context_truncated: bool,
    window_segments: list[dict[str, Any]],
    *,
    is_final: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, dict[str, Any]]:
    if finish_reason != "stop":
        raise SummaryValidationError(f"chapter window finish_reason is {finish_reason!r}")
    if context_truncated:
        raise SummaryValidationError("chapter window input was truncated")
    raw = parse_content(content)
    ref_map, compact_ref_map = _build_compact_ref_map(window_segments)
    speaker_map, compact_speaker_map = _build_compact_speaker_map(
        [segment["speaker_id"] for segment in window_segments]
    )
    raw = _expand_payload(raw, compact_ref_map, compact_speaker_map)
    raw_chapters = raw.get("completed_chapters")
    raw_actions = raw.get("action_candidates", [])
    if not isinstance(raw_chapters, list):
        raise SummaryValidationError("completed_chapters must be an array")
    if not isinstance(raw_actions, list):
        raise SummaryValidationError("action_candidates must be an array")
    by_id = {segment["segment_id"]: segment for segment in window_segments}
    positions = {segment["segment_id"]: index for index, segment in enumerate(window_segments)}
    repairs = []
    candidates = []
    for index, chapter in enumerate(raw_chapters):
        if not isinstance(chapter, dict):
            repairs.append(
                {"type": "drop_non_object_chapter", "location": f"completed_chapters[{index}]"}
            )
            continue
        title = clean_text(chapter.get("title"))
        overview = clean_text(chapter.get("summary"))
        start_ref = str(chapter.get("core_start_ref") or chapter.get("start_ref") or "")
        end_ref = str(chapter.get("core_end_ref") or chapter.get("end_ref") or "")
        if title is None or overview is None:
            repairs.append(
                {"type": "drop_empty_chapter", "location": f"completed_chapters[{index}]"}
            )
            continue
        if start_ref not in positions or end_ref not in positions:
            repairs.append(
                {"type": "drop_invalid_chapter_range", "location": f"completed_chapters[{index}]"}
            )
            continue
        start_pos = positions[start_ref]
        end_pos = positions[end_ref]
        if end_pos < start_pos:
            repairs.append(
                {"type": "drop_reversed_chapter_range", "location": f"completed_chapters[{index}]"}
            )
            continue
        candidates.append(
            {
                "index": index,
                "title": title,
                "overview": overview,
                "start_pos": start_pos,
                "end_pos": end_pos,
                "key_refs": chapter.get("key_refs", []),
            }
        )

    candidates = _normalize_overlapping_core_candidates(
        candidates,
        repairs,
        location_prefix="completed_chapters",
    )
    core_chapters = []
    last_core_end = -1
    for candidate in candidates:
        index = candidate["index"]
        start_pos = candidate["start_pos"]
        end_pos = candidate["end_pos"]
        core_start_ref = window_segments[start_pos]["segment_id"]
        core_end_ref = window_segments[end_pos]["segment_id"]
        key_refs = candidate["key_refs"]
        if not isinstance(key_refs, list):
            key_refs = []
            repairs.append(
                {"type": "replace_invalid_chapter_key_refs", "location": f"completed_chapters[{index}]"}
            )
        key_refs = list(dict.fromkeys(str(ref) for ref in key_refs))
        invalid_key_refs = [
            ref
            for ref in key_refs
            if ref not in positions or not (start_pos <= positions[ref] <= end_pos)
        ]
        if invalid_key_refs:
            repairs.append(
                {
                    "type": "drop_chapter_key_refs_outside_core_range",
                    "location": f"completed_chapters[{index}]",
                    "values": invalid_key_refs,
                }
            )
            key_refs = [ref for ref in key_refs if ref not in invalid_key_refs]
        refs = key_refs or list(dict.fromkeys((core_start_ref, core_end_ref)))
        cited = [by_id[ref] for ref in refs]
        core_chapters.append(
            {
                "title": candidate["title"],
                "overview": candidate["overview"],
                "core_start_ref": core_start_ref,
                "core_end_ref": core_end_ref,
                "start_ref": core_start_ref,
                "end_ref": core_end_ref,
                "start_ms": by_id[core_start_ref]["start_ms"],
                "end_ms": by_id[core_end_ref]["end_ms"],
                "speaker_ids": sorted({item["speaker_id"] for item in cited}),
                "refs": refs,
            }
        )
        last_core_end = end_pos

    completed_end = last_core_end
    core_ranges = [
        (positions[item["core_start_ref"]], positions[item["core_end_ref"]])
        for item in core_chapters
    ]

    carryover_raw = raw.get("carryover_start_ref")
    if carryover_raw is None:
        carryover = None
    elif isinstance(carryover_raw, str) and carryover_raw.strip().lower() in {
        "",
        "null",
        "none",
        "无",
    }:
        carryover = None
    else:
        carryover = str(carryover_raw)
    if isinstance(carryover_raw, str) and carryover_raw.strip().lower() in {
        "null",
        "none",
        "无",
    }:
        repairs.append(
            {
                "type": "normalize_string_null_carryover",
                "value": carryover_raw,
            }
        )
    if carryover is not None and carryover not in positions:
        raise SummaryValidationError("carryover_start_ref is outside current window")
    if is_final and carryover is not None:
        repairs.append(
            {
                "type": "merge_final_carryover_into_last_chapter",
                "value": carryover,
            }
        )
        carryover = None
    if carryover is not None:
        carryover_pos = positions[carryover]
        if completed_end >= 0 and carryover_pos <= completed_end:
            raise SummaryValidationError("carryover overlaps a completed core chapter")
        if carryover_pos <= 0:
            raise SummaryValidationError("carryover made no forward progress")
        coverage_end_ref = window_segments[carryover_pos - 1]["segment_id"]
    else:
        coverage_end_ref = window_segments[-1]["segment_id"]

    normalized, range_repairs = _expand_core_chapter_ranges(
        core_chapters,
        window_segments,
        coverage_end_ref=coverage_end_ref,
    )
    repairs.extend(range_repairs)
    next_offset = positions[carryover] if carryover is not None else len(window_segments)

    actions = []
    for index, item in enumerate(raw_actions):
        if not isinstance(item, dict):
            raise SummaryValidationError(f"action_candidates[{index}] must be an object")
        task = clean_text(item.get("task"))
        refs = item.get("refs")
        if task is None or not isinstance(refs, list) or not refs:
            continue
        refs = list(dict.fromkeys(str(ref) for ref in refs))
        valid_refs = [
            ref
            for ref in refs
            if ref in positions
            and any(start <= positions[ref] <= end for start, end in core_ranges)
        ]
        invalid_refs = [ref for ref in refs if ref not in valid_refs]
        if invalid_refs:
            repairs.append(
                {
                    "type": "drop_action_candidate_refs_outside_completed_chapters",
                    "location": f"action_candidates[{index}]",
                    "values": invalid_refs,
                }
            )
        if not valid_refs:
            repairs.append(
                {
                    "type": "drop_action_candidate_without_completed_evidence",
                    "location": f"action_candidates[{index}]",
                }
            )
            continue
        refs = valid_refs
        actions.append(
            {
                "task": task,
                "owner": clean_text(item.get("owner")),
                "deadline": clean_text(item.get("deadline")),
                "refs": refs,
            }
        )
    quality = {
        "status": "pass",
        "checks": {
            "finish_reason": True,
            "context_not_truncated": True,
            "core_chapter_ranges_ordered": True,
            "continuous_ranges_assigned_by_harness": True,
            "carryover_valid": True,
            "action_refs_inside_core_ranges": True,
        },
        "carryover_start_ref": carryover,
        "repairs": repairs,
    }
    return normalized, actions, next_offset, quality


def _validate_overview(
    content: str,
    finish_reason: Any,
    context_truncated: bool,
    segment_by_id: dict[str, dict[str, Any]],
    overview_refs: list[str],
) -> tuple[str | None, dict[str, Any]]:
    if finish_reason != "stop" or context_truncated:
        raise SummaryValidationError("full summary request did not finish cleanly")
    raw = parse_content(content)
    title = clean_text(raw.get("title"))
    overview = raw.get("overview")
    if not isinstance(overview, dict):
        raise SummaryValidationError("overview must be an object")
    text = clean_text(overview.get("text"))
    if text is None:
        raise SummaryValidationError("overview text is required")
    refs = list(dict.fromkeys(
        str(ref)
        for ref in overview_refs
        if str(ref) in segment_by_id and segment_by_id[str(ref)].get("text")
    ))
    if not refs:
        raise SummaryValidationError("validated chapters contain no overview refs")
    return title, {"text": text, "refs": refs}


def _empty_long_summary() -> dict[str, Any]:
    return {
        "title": None,
        "overview": None,
        "chapters": [],
        "speakers": [],
        "key_points": [],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
        "risks": [],
        "keywords": [],
    }


def _validate_actions(
    content: str,
    finish_reason: Any,
    context_truncated: bool,
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if finish_reason != "stop":
        raise SummaryValidationError(f"action review finish_reason is {finish_reason!r}")
    if context_truncated:
        raise SummaryValidationError("action review input was truncated")
    raw = parse_content(content)
    ref_map, compact_ref_map = _build_compact_ref_map(segments)
    speaker_map, compact_speaker_map = _build_compact_speaker_map(
        [segment["speaker_id"] for segment in segments]
    )
    raw = _expand_payload(raw, compact_ref_map, compact_speaker_map)
    summary, _ = validate_summary_object(
        {**_empty_long_summary(), "action_items": raw.get("action_items", [])},
        segments,
    )
    return summary["action_items"]


def _request_record(result: dict[str, Any], estimate: int) -> dict[str, Any]:
    return {
        "request_id": result.get("request_id"),
        "estimated_prompt_tokens": estimate,
        "usage": result.get("usage"),
        "timings": result.get("timings"),
        "thinking_characters": len(result.get("thinking") or ""),
        "context_truncated": result.get("context_truncated"),
        "finish_reason": result.get("finish_reason"),
        "request_elapsed_seconds": result.get("request_elapsed_seconds"),
    }


def _emit_run_log(
    run_log: Any | None,
    event: str,
    *,
    stage: str,
    level: str = "info",
    message: str | None = None,
    request: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Write bounded business events without making logging part of control flow."""

    if run_log is None:
        return
    try:
        run_log.emit(
            event,
            stage=stage,
            level=level,
            message=message,
            request=request,
            error=error,
            details=details,
            source="product_summary",
        )
    except (OSError, TypeError, ValueError):
        return


def _model_identity(files: dict[str, Any]) -> dict[str, Any]:
    identity = {}
    for name, value in sorted(files.items()):
        path = pathlib.Path(str(value))
        item: dict[str, Any] = {"path": str(path)}
        if path.is_file():
            item.update({"size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
        identity[name] = item
    return identity


def _request_fingerprint(
    *,
    request_kind: str,
    messages: list[dict[str, str]],
    config: ProductSummaryConfig,
    model_identity: dict[str, Any],
) -> str:
    return stable_hash(
        {
            "version": PRODUCT_SUMMARY_VERSION,
            "request_kind": request_kind,
            "messages": messages,
            "ctx": config.llm.ctx,
            "predict": config.llm.predict,
            "max_tokens": config.llm.max_tokens,
            "temperature": config.llm.temperature,
            "model_identity": model_identity,
        }
    )


def _load_reusable_request(
    request_dir: pathlib.Path,
    fingerprint: str,
    validator: Callable[[str, Any, bool], Any],
) -> Any | None:
    identity_path = request_dir / "request_identity.json"
    status_path = request_dir / "status.json"
    final_path = request_dir / "final_json.txt"
    validated_path = request_dir / "validated_result.json"
    validation_path = request_dir / "validation.json"
    paths = {
        "final_json": final_path,
        "validated_result": validated_path,
        "validation": validation_path,
        "status": status_path,
    }
    if not identity_path.is_file() or any(not path.is_file() for path in paths.values()):
        return None
    try:
        identity = load_json(identity_path)
        status = load_json(status_path)
        validated = load_json(validated_path)
        quality = load_json(validation_path)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if identity.get("fingerprint") != fingerprint:
        return None
    expected_hashes = identity.get("artifact_sha256")
    if not isinstance(expected_hashes, dict):
        return None
    if any(expected_hashes.get(name) != sha256_file(path) for name, path in paths.items()):
        return None
    if status.get("finish_reason") != "stop" or status.get("context_truncated"):
        return None
    if not isinstance(quality, dict) or quality.get("status") != "pass":
        return None
    try:
        current = validator(final_path.read_text(encoding="utf-8"), "stop", False)
    except (OSError, SummaryValidationError, KeyError, TypeError, ValueError):
        return None
    if current != validated:
        return None
    return current


def _save_reusable_request(
    request_dir: pathlib.Path,
    *,
    fingerprint: str,
    request_kind: str,
    validated: Any,
    quality: dict[str, Any],
) -> None:
    validated_path = request_dir / "validated_result.json"
    validation_path = request_dir / "validation.json"
    atomic_write_json(validated_path, validated)
    atomic_write_json(validation_path, quality)
    paths = {
        "final_json": request_dir / "final_json.txt",
        "validated_result": validated_path,
        "validation": validation_path,
        "status": request_dir / "status.json",
    }
    atomic_write_json(
        request_dir / "request_identity.json",
        {
            "fingerprint": fingerprint,
            "request_kind": request_kind,
            "artifact_sha256": {name: sha256_file(path) for name, path in paths.items()},
        },
    )


def run_product_summary_stage(
    *,
    config: ProductSummaryConfig,
    segments: list[dict[str, Any]],
    speaker_ids: list[str],
    timeline: str,
    out_dir: pathlib.Path,
    sampler: Any | None,
    run_log: Any | None = None,
) -> dict[str, Any]:
    started = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    budget = config.budget
    ref_map, compact_ref_map = _build_compact_ref_map(segments)
    speaker_map, compact_speaker_map = _build_compact_speaker_map(
        [segment["speaker_id"] for segment in segments] or speaker_ids
    )
    nonempty = [segment for segment in segments if segment.get("text")]
    full_messages = _full_meeting_messages(
        timeline,
        speaker_ids,
        ref_map=ref_map,
        speaker_map=speaker_map,
    )
    full_estimate = estimate_message_tokens(full_messages, budget)
    plan: dict[str, Any] = {
        "version": PRODUCT_SUMMARY_VERSION,
        "input_token_budget": budget.input_token_budget,
        "full_estimated_prompt_tokens": full_estimate,
        "full_request_fits": messages_fit(full_messages, budget),
    }
    request_records: list[dict[str, Any]] = []
    # 保留每次传输和业务校验尝试；request_records 继续只表示最终通过校验的请求，
    # 以兼容现有 meeting_result.runtime.llm 契约。
    request_attempts: list[dict[str, Any]] = []
    reused_count = 0
    session: RkllmServerSession | None = None
    cached_files: dict[str, Any] | None = None

    def build_session() -> RkllmServerSession:
        nonlocal session, cached_files
        if session is None:
            session = RkllmServerSession(config.llm, out_dir, sampler)
            cached_files = session.files
        return session

    def model_identity() -> dict[str, Any]:
        return _model_identity(build_session().files)

    def ensure_session() -> RkllmServerSession:
        current = build_session()
        current.start()
        return current

    def run_request(
        *,
        messages: list[dict[str, str]],
        request_dir: pathlib.Path,
        request_id: str,
        request_kind: str,
        phase: str,
        estimate: int,
        validator: Callable[[str, Any, bool], Any],
        quality_builder: Callable[[Any], dict[str, Any]] | None = None,
    ) -> Any:
        nonlocal reused_count
        fingerprint = _request_fingerprint(
            request_kind=request_kind,
            messages=messages,
            config=config,
            model_identity=model_identity(),
        )
        if config.resume:
            reused = _load_reusable_request(request_dir, fingerprint, validator)
            if reused is not None:
                reused_count += 1
                _emit_run_log(
                    run_log,
                    "request_reused",
                    stage=phase,
                    message="复用已校验的 LLM 请求产物",
                    request={
                        "request_id": request_id,
                        "request_kind": request_kind,
                        "attempt": 0,
                        "estimated_prompt_tokens": estimate,
                    },
                    details={"request_dir": request_dir.name},
                )
                return reused
        request_messages = messages
        result = None
        validated = None
        for attempt in range(2):
            attempt_dir = request_dir if attempt == 0 else request_dir / f"attempt-{attempt + 1}"
            attempt_request_id = request_id if attempt == 0 else f"{request_id}-attempt-{attempt + 1}"
            try:
                result = ensure_session().request(
                    request_messages,
                    attempt_dir,
                    phase=phase,
                    request_id=attempt_request_id,
                    request_kind=request_kind,
                    attempt=attempt + 1,
                    estimated_prompt_tokens=estimate,
                    run_log=run_log,
                )
            except LlmRunError as exc:
                request_attempts.append({
                    "request_id": attempt_request_id,
                    "request_kind": request_kind,
                    "attempt": attempt + 1,
                    "estimated_prompt_tokens": estimate,
                    "status": "request_failed",
                    "error_code": "request_failed",
                    "error_message": str(exc)[:600],
                })
                raise
            attempt_record = {
                **_request_record(result, estimate),
                "request_kind": request_kind,
                "attempt": attempt + 1,
                "status": "response_received",
            }
            request_attempts.append(attempt_record)
            try:
                validated = validator(
                    result["content"],
                    result["finish_reason"],
                    bool(result["context_truncated"]),
                )
                attempt_record["status"] = "validated"
                _emit_run_log(
                    run_log,
                    "validation_succeeded",
                    stage=phase,
                    message="LLM 业务校验通过",
                    request={
                        **_request_record(result, estimate),
                        "request_kind": request_kind,
                        "attempt": attempt + 1,
                    },
                )
                break
            except SummaryValidationError as exc:
                message = str(exc)
                failure_cause = (
                    "finish_reason_length"
                    if "finish_reason" in message and "length" in message
                    else "context_truncated"
                    if "input was truncated" in message
                    else "invalid_json"
                    if "not valid JSON" in message
                    else "missing_speaker_summaries"
                    if "missing speaker summaries" in message
                    else "validation_failed"
                )
                attempt_record["status"] = "validation_failed"
                attempt_record["error_code"] = "validation_failed"
                attempt_record["cause"] = failure_cause
                _emit_run_log(
                    run_log,
                    "validation_failed",
                    stage=phase,
                    level="error",
                    message="LLM 业务校验失败",
                    request={
                        **_request_record(result, estimate),
                        "request_kind": request_kind,
                        "attempt": attempt + 1,
                    },
                    error={
                        "stage": phase,
                        "code": "validation_failed",
                        "message": message,
                        "cause": failure_cause,
                        "request_id": attempt_request_id,
                        "request_kind": request_kind,
                        "attempt": attempt + 1,
                        "finish_reason": result.get("finish_reason"),
                        "context_truncated": result.get("context_truncated"),
                        "usage": result.get("usage"),
                        "request_elapsed_seconds": result.get("request_elapsed_seconds"),
                    },
                )
                retry_json = "LLM content is not valid JSON" in message
                retry_missing_speakers = "missing speaker summaries" in message
                retry_output_length = (
                    request_kind == "speaker-batch"
                    and "finish_reason" in message
                    and "length" in message
                )
                retry_context_truncated = "input was truncated" in message
                if attempt != 0 or not (
                    retry_json
                    or retry_missing_speakers
                    or retry_output_length
                    or retry_context_truncated
                ):
                    raise
                if retry_output_length:
                    correction = (
                        "上一条响应达到输出长度上限。请重新完整输出 JSON，严格只保留 speakers 字段；"
                        "每个 speaker 只输出一条 overview，overview 控制在 40 个汉字以内，"
                        "refs 每条最多 3 个，只使用输入中对应 speaker 的 refs；"
                        "不要解释、不要输出额外字段、不要输出 markdown，必须在本次响应内闭合 JSON。"
                    )
                elif retry_context_truncated:
                    correction = (
                        "上一条请求的输入上下文被截断。请只根据本次完整输入输出 JSON，"
                        "每个 speaker 一条简短 overview，refs 每条最多 3 个，不要解释或额外字段。"
                    )
                elif retry_missing_speakers:
                    correction = (
                        "上一条输出遗漏了一个或多个 speaker 的总结。请重新完整输出当前请求的 JSON，"
                        "本批次输入中的每个 speaker_id 都必须各输出一条 speakers 项，"
                        "即使内容是简短回应或确认，也要给出基于原文的简短客观总结，"
                        "并为每条总结提供属于该 speaker 的 refs；不要省略任何 speaker。"
                    )
                else:
                    correction = (
                        "上一条输出不是可解析的 JSON。请重新完整输出当前请求的 JSON，"
                        "不要输出解释，不要截断，不要在字符串中放入未转义的换行或制表符；"
                        "每个章节最多输出 3 个 key_refs。"
                    )
                _emit_run_log(
                    run_log,
                    "retry_requested",
                    stage=phase,
                    message="LLM 请求将进行受控重试",
                    request={
                        "request_id": attempt_request_id,
                        "request_kind": request_kind,
                        "attempt": attempt + 1,
                        "finish_reason": result.get("finish_reason"),
                        "context_truncated": result.get("context_truncated"),
                    },
                    details={"cause": failure_cause},
                )
                request_messages = [
                    *messages,
                    {"role": "user", "content": correction},
                ]
        assert result is not None
        assert validated is not None
        quality = quality_builder(validated) if quality_builder is not None else {"status": "pass"}
        _save_reusable_request(
            request_dir,
            fingerprint=fingerprint,
            request_kind=request_kind,
            validated=validated,
            quality=quality,
        )
        request_records.append(_request_record(result, estimate))
        return validated

    def result_payload(
        summary: dict[str, Any],
        quality: dict[str, Any],
        policy: str,
    ) -> dict[str, Any]:
        return {
            "summary": summary,
            "quality": quality,
            "policy": policy,
            "request_count": session.request_count if session is not None else 0,
            "validated_request_count": len(request_records),
            "reused_request_count": reused_count,
            "requests": request_records,
            "request_attempts": request_attempts,
            "server_ready_seconds": session.ready_seconds if session is not None else None,
            "resolved_model_files": cached_files,
            "elapsed_seconds": round(time.time() - started, 3),
            "plan": plan,
        }

    try:
        if plan["full_request_fits"]:
            def validate_full(content: str, finish_reason: Any, truncated: bool) -> dict[str, Any]:
                summary, _ = _validate_full_core_result(
                    content,
                    finish_reason,
                    truncated,
                    segments,
                )
                return summary

            summary = run_request(
                messages=full_messages,
                request_dir=out_dir / "requests" / "full",
                request_id="full",
                request_kind="full",
                phase="llm_summary_full",
                estimate=full_estimate,
                validator=validate_full,
                quality_builder=lambda value: validate_summary_object(value, segments)[1],
            )
            summary, quality = validate_summary_object(summary, segments)
            quality["checks"].update({"finish_reason": True, "context_not_truncated": True})
            if reused_count:
                quality["warnings"].append("reused validated LLM artifact")
            plan["policy"] = "single_request_all_features"
            atomic_write_json(out_dir / "plan.json", plan)
            return result_payload(summary, quality, plan["policy"])

        segment_by_id = {segment["segment_id"]: segment for segment in nonempty}
        nonempty_positions = {
            segment["segment_id"]: index for index, segment in enumerate(nonempty)
        }
        chapters = []
        action_candidates = []
        window_records = []
        cursor = 0
        window_number = 1
        while cursor < len(nonempty):
            window_end, _, estimate = _fit_window(nonempty, cursor, budget, ref_map=ref_map, speaker_map=speaker_map)
            window_segments = nonempty[cursor:window_end]
            is_final = window_end == len(nonempty)
            window_id = f"window-{window_number:06d}"
            messages = _chapter_window_messages(window_segments, ref_map=ref_map, speaker_map=speaker_map)
            estimate = estimate_message_tokens(messages, budget)
            request_dir = out_dir / "chapter_windows" / window_id
            atomic_write_text(request_dir / "timeline.txt", render_timeline(window_segments))

            def validate_window_request(
                content: str,
                finish_reason: Any,
                truncated: bool,
                current_segments: list[dict[str, Any]] = window_segments,
                final: bool = is_final,
            ) -> dict[str, Any]:
                new_chapters, new_actions, next_offset, quality = _validate_window(
                    content,
                    finish_reason,
                    truncated,
                    current_segments,
                    is_final=final,
                )
                return {
                    "chapters": new_chapters,
                    "action_candidates": new_actions,
                    "next_offset": next_offset,
                    "quality": quality,
                }

            window_result = run_request(
                messages=messages,
                request_dir=request_dir,
                request_id=window_id,
                request_kind="chapter-window",
                phase="llm_chapter_window",
                estimate=estimate,
                validator=validate_window_request,
                quality_builder=lambda value: value["quality"],
            )
            new_chapters = window_result["chapters"]
            new_actions = window_result["action_candidates"]
            next_offset = int(window_result["next_offset"])
            quality = window_result["quality"]
            if next_offset <= 0:
                raise SummaryValidationError("chapter window made no forward progress")
            chapters.extend(new_chapters)
            action_candidates.extend(new_actions)
            next_cursor = cursor + next_offset
            completed_end_ref = new_chapters[-1]["end_ref"] if new_chapters else None
            carryover_start_ref = quality.get("carryover_start_ref")
            chapter_covered_segment_count = sum(
                nonempty_positions[chapter["end_ref"]]
                - nonempty_positions[chapter["start_ref"]]
                + 1
                for chapter in new_chapters
            )
            window_record = {
                "window_id": window_id,
                "input_start_ref": window_segments[0]["segment_id"],
                "input_end_ref": window_segments[-1]["segment_id"],
                "completed_end_ref": completed_end_ref,
                "carryover_start_ref": carryover_start_ref,
                "start_ref": window_segments[0]["segment_id"],
                "end_ref": window_segments[-1]["segment_id"],
                "next_start_ref": carryover_start_ref,
                "input_segment_count": len(window_segments),
                "chapter_covered_segment_count": chapter_covered_segment_count,
                "cursor_advance_segment_count": next_offset,
                "carryover_context_segment_count": len(window_segments) - next_offset,
                "completed_segment_count": chapter_covered_segment_count,
                "carryover_segment_count": len(window_segments) - next_offset,
                "completed_chapter_count": len(new_chapters),
                "completed_chapters": new_chapters,
                "action_candidates": new_actions,
                "action_candidate_count": len(new_actions),
                "estimated_prompt_tokens": estimate,
                "quality": quality,
            }
            atomic_write_json(request_dir / "validated_window.json", window_record)
            window_records.append(window_record)
            cursor = next_cursor
            window_number += 1

        atomic_write_json(out_dir / "chapters.json", chapters)
        atomic_write_json(out_dir / "action_candidates.json", action_candidates)

        overview_refs = list(dict.fromkeys(
            str(ref)
            for chapter in chapters
            for ref in chapter.get("refs", [])
            if str(ref) in segment_by_id
        ))
        summary_messages = _full_summary_messages(chapters, ref_map=ref_map, speaker_map=speaker_map)
        summary_estimate = estimate_message_tokens(summary_messages, budget)
        if summary_estimate > budget.input_token_budget:
            raise ChunkingError("validated chapters exceed full-summary input budget")

        def validate_overview_request(
            content: str,
            finish_reason: Any,
            truncated: bool,
        ) -> dict[str, Any]:
            title, overview = _validate_overview(
                content,
                finish_reason,
                truncated,
                segment_by_id,
                overview_refs,
            )
            return {"title": title, "overview": overview}

        overview_result = run_request(
            messages=summary_messages,
            request_dir=out_dir / "requests" / "full_summary",
            request_id="full-summary",
            request_kind="full-summary",
            phase="llm_full_summary",
            estimate=summary_estimate,
            validator=validate_overview_request,
        )
        title = overview_result["title"]
        overview = overview_result["overview"]

        action_items = []
        if action_candidates:
            action_messages = _action_review_messages(action_candidates, segment_by_id, ref_map=ref_map, speaker_map=speaker_map)
            action_estimate = estimate_message_tokens(action_messages, budget)
            if action_estimate > budget.input_token_budget:
                raise ChunkingError("action candidates exceed action-review input budget")
            action_items = run_request(
                messages=action_messages,
                request_dir=out_dir / "requests" / "action_review",
                request_id="action-review",
                request_kind="action-review",
                phase="llm_action_review",
                estimate=action_estimate,
                validator=lambda content, finish_reason, truncated: _validate_actions(
                    content,
                    finish_reason,
                    truncated,
                    segments,
                ),
            )

        speaker_documents = _build_speaker_documents(nonempty)
        speaker_documents, speaker_truncations = _truncate_speaker_documents(
            speaker_documents,
            budget,
            ref_map=ref_map,
            speaker_map=speaker_map,
        )
        speaker_batches = _pack_speaker_documents(speaker_documents, budget, ref_map=ref_map, speaker_map=speaker_map)
        speaker_summaries = []
        speaker_batch_records = []
        speaker_order = {
            document["speaker_id"]: document["first_index"]
            for document in speaker_documents
        }
        def run_speaker_batch(
            batch: list[dict[str, Any]],
            request_id: str,
            request_dir: pathlib.Path,
            split_depth: int = 0,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            """Retry a truncated batch, then split it while keeping IDs stable."""

            speaker_messages = _speaker_batch_messages(
                batch,
                ref_map=ref_map,
                speaker_map=speaker_map,
            )
            speaker_estimate = estimate_message_tokens(speaker_messages, budget)
            try:
                batch_result = run_request(
                    messages=speaker_messages,
                    request_dir=request_dir,
                    request_id=request_id,
                    request_kind="speaker-batch",
                    phase="llm_speaker_batch",
                    estimate=speaker_estimate,
                    validator=lambda content, finish_reason, truncated, current_batch=batch: _validate_speaker_batch(
                        content,
                        finish_reason,
                        truncated,
                        current_batch,
                        ref_map=ref_map,
                        speaker_map=speaker_map,
                    ),
                )
                return batch_result, [{
                    "request_id": request_id,
                    "speaker_ids": [document["speaker_id"] for document in batch],
                    "segment_count": sum(len(document["segments"]) for document in batch),
                    "estimated_prompt_tokens": speaker_estimate,
                    "split_depth": split_depth,
                    "truncated_speaker_ids": [
                        document["speaker_id"]
                        for document in batch
                        if document.get("_truncation") is not None
                    ],
                }]
            except SummaryValidationError as exc:
                message = str(exc)
                can_split = (
                    "finish_reason" in message
                    and "length" in message
                    and len(batch) > 1
                    and split_depth < 3
                )
                if not can_split:
                    raise
                midpoint = max(1, len(batch) // 2)
                child_results: list[dict[str, Any]] = []
                child_records: list[dict[str, Any]] = []
                child_request_ids = [
                    f"{request_id}-split-1",
                    f"{request_id}-split-2",
                ]
                _emit_run_log(
                    run_log,
                    "batch_split",
                    stage="llm_speaker_batch",
                    message="speaker batch 将拆分后重试",
                    request={
                        "request_id": request_id,
                        "request_kind": "speaker-batch",
                        "split_depth": split_depth,
                        "finish_reason": "length",
                    },
                    details={
                        "parent_request_id": request_id,
                        "child_request_ids": child_request_ids,
                        "parent_batch_size": len(batch),
                        "child_batch_sizes": [len(batch[:midpoint]), len(batch[midpoint:])],
                    },
                )
                for child_index, child_batch in enumerate((batch[:midpoint], batch[midpoint:]), 1):
                    child_result, child_record = run_speaker_batch(
                        child_batch,
                        f"{request_id}-split-{child_index}",
                        request_dir.parent / f"{request_dir.name}-split-{child_index}",
                        split_depth + 1,
                    )
                    child_results.extend(child_result)
                    child_records.extend(child_record)
                return child_results, child_records

        for batch_index, batch in enumerate(speaker_batches, 1):
            batch_result, batch_records = run_speaker_batch(
                batch,
                f"speaker-batch-{batch_index:06d}",
                out_dir / "requests" / "speaker_batches" / f"speaker-batch-{batch_index:06d}",
            )
            speaker_summaries.extend(batch_result)
            speaker_batch_records.extend(batch_records)
        speaker_summaries.sort(
            key=lambda item: speaker_order.get(item["speaker_id"], len(speaker_order))
        )
        atomic_write_json(
            out_dir / "speaker_documents.json",
            [
                {
                    "speaker_id": document["speaker_id"],
                    "segment_ids": [segment["segment_id"] for segment in document["segments"]],
                    "segment_count": len(document["segments"]),
                    **(
                        {"truncation": document["_truncation"]}
                        if document.get("_truncation") is not None
                        else {}
                    ),
                }
                for document in speaker_documents
            ],
        )
        atomic_write_json(out_dir / "speaker_batches.json", speaker_batch_records)

        summary = _empty_long_summary()
        summary.update(
            {
                "title": title,
                "overview": overview,
                "chapters": chapters,
                "speakers": speaker_summaries,
                "action_items": action_items,
            }
        )
        summary, quality = validate_summary_object(summary, segments)
        quality["checks"].update(
            {
                "full_meeting_coverage": cursor == len(nonempty),
                "sliding_chapter_windows": True,
                "speaker_batches_processed": True,
            }
        )
        if reused_count:
            quality["warnings"].append("reused validated LLM artifacts")
        plan.update(
            {
                "policy": "sliding_chapter_windows",
                "window_count": len(window_records),
                "windows": window_records,
                "action_candidate_count": len(action_candidates),
                "speaker_count": len(speaker_documents),
                "speaker_batch_count": len(speaker_batch_records),
                "speaker_batches": speaker_batch_records,
                "speaker_truncations": speaker_truncations,
            }
        )
        atomic_write_json(out_dir / "plan.json", plan)
        atomic_write_json(out_dir / "chapters.json", chapters)
        atomic_write_json(out_dir / "full_summary.json", {"title": title, "overview": overview})
        atomic_write_json(out_dir / "action_items.json", action_items)
        return result_payload(summary, quality, plan["policy"])
    finally:
        if session is not None:
            session.close()

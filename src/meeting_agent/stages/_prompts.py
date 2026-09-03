"""摘要各环节的 prompt 构造 + 输出 schema 形状（SHAPE）。从 product_summary.py 拆出。

只负责"把输入拼成 messages"与"目标 JSON 形状"，不含请求发送/校验。依赖 _refmap 做紧凑化。
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..llm.llm import SYSTEM_PROMPT
from .summary_profiles import DomainProfile, GENERIC_PROFILE
from ._refmap import (
    _build_compact_ref_map,
    _build_compact_ref_map_from_ids,
    _build_compact_speaker_map,
    _compactize_payload,
)


MAX_RETRY_ECHO_CHARS = 600
BLOCK_SUMMARY_SHAPE = {
    "title": "本块小标题",
    "key_points": ["先抽取：本块最重要的结论/决定/方案（含被“总结/第一二三/所以/结论是”标记的内容）"],
    "anchors": ["具体例子/数字/专有名词（如：微波炉、300万、某模块名）"],
    "summary": "再据上面 key_points 与 anchors 写成的连续摘要",
    "continues_previous": False,
    "key_refs": ["r1", "r3"],
    "action_candidates": [
        {"task": "明确待办", "owner": None, "deadline": None, "refs": ["r1"]}
    ],
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
        }
    ]
}
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
def _overview_from_source_messages(
    timeline: str,
    chapters: list[dict[str, Any]],
    *,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
) -> list[dict[str, str]]:
    """自适应 overview 的"原文档"版：给完整原文 Timeline + 章节提纲，只产标题和全文摘要。

    章节提纲只给标题和核心区间当结构线索，不给章节摘要，避免二次压缩；事实必须来自原文，
    从而让 overview 直接接地，不依赖章节摘要质量。
    """
    compact_timeline = timeline
    for canonical, compact in ref_map.items():
        compact_timeline = compact_timeline.replace(f"[{canonical}]", f"[{compact}]")
    for canonical, compact in speaker_map.items():
        compact_timeline = compact_timeline.replace(f"[{canonical}]", f"[{compact}]")
    skeleton = [
        {
            "id": index,
            "title": chapter.get("title"),
            "start_ref": chapter.get("start_ref"),
            "end_ref": chapter.get("end_ref"),
        }
        for index, chapter in enumerate(chapters, 1)
    ]
    skeleton = _compactize_payload(skeleton, ref_map, speaker_map)
    prompt = (
        "任务：\n"
        "根据下面的完整会议 Timeline 和章节提纲，生成会议标题和全文摘要。\n\n"
        "全文摘要要求：\n"
        "- 使用约 300～500 个中文字符。\n"
        "- 事实、数据、方案、分歧和结论必须来自 Timeline 原文；章节提纲只用于把握结构和先后顺序。\n"
        "- 综合主要议题、关键背景与数据、重要观点或方案、主要分歧与取舍、形成的结论以及明确的后续行动。\n"
        "- 体现议题之间的逻辑关系，不要逐章机械拼接；没有明确结论时保持讨论或建议语气。\n"
        "- 只输出标题和摘要正文，不要输出或讨论 refs；引用由程序从已校验章节自动合并。\n\n"
        "输出结构：\n"
        f"{json.dumps(FULL_SUMMARY_SHAPE, ensure_ascii=False, indent=2)}\n\n"
        f"章节提纲：\n{json.dumps(skeleton, ensure_ascii=False, indent=2)}\n\n"
        f"完整 Timeline：\n{compact_timeline}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
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
        "下面的会议发言已经按 speaker_id 分开。请为每个发言人概括其在所提供内容中的实质贡献。\n"
        "这不是章节总结，也不是全文摘要；每个 speaker 最多一条 overview。\n\n"
        "规则：\n"
        "- 只依据对应 speaker 文档中出现的原文，概括该发言人明确表达的事实、观点、方案、决定或行动。\n"
        "- overview 使用简洁的连续表述，不要拆成要点列表。\n"
        "- speaker_id 必须来自本次输入；不要推测姓名、身份、职位或发言之外的意图。\n"
        "- 只输出 speaker_id 和 overview 两个字段，不要输出 refs 或其它字段（引用由程序指派）。\n"
        "- 若某 speaker 实质内容确实很少，可省略该条，不必勉强凑写。\n\n"
        f"本次允许输出的 speaker_id：{json.dumps(speaker_ids, ensure_ascii=False)}\n"
        "输出结构：\n"
        f"{json.dumps(prompt_shape, ensure_ascii=False, indent=2)}\n\n"
        "发言人文档：\n"
        f"{chr(10).join(rendered_documents)}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
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
def _block_summary_messages(
    block_segments: list[dict[str, Any]],
    prev_context: dict[str, str] | None,
    *,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
    profile: DomainProfile = GENERIC_PROFILE,
) -> list[dict[str, str]]:
    """B 层逐块摘要提示词：只处理一块，并判定是否延续上一块话题。抽取维度由 profile 决定。"""
    timeline = _render_compact_timeline(block_segments, ref_map, speaker_map)
    prompt_shape = _compactize_payload(BLOCK_SUMMARY_SHAPE, ref_map, speaker_map)
    markers = "/".join(profile.discourse_markers)
    if prev_context is not None:
        prev_text = (
            f"上一块标题：{prev_context.get('title', '')}\n"
            f"上一块摘要：{prev_context.get('summary', '')}\n\n"
        )
    else:
        prev_text = "（这是第一块，没有上一块。）\n\n"
    prompt = (
        "任务：\n"
        "先从下面这一小段会议 Timeline 抽取要点与锚点，再据此写摘要，并判断是否延续上一块话题。\n"
        "务必按 key_points → anchors → summary 的顺序：先想清楚重点，再成文。\n\n"
        "抽取要求（先做）：\n"
        f"- key_points：{profile.aspects}，最多 {profile.key_points_max} 条，按重要性排序。\n"
        f"  特别注意被“{markers}”等标记的内容，这些通常就是重点。\n"
        "  只收明确表达的实质内容，不收寒暄、过渡、重复确认；宁缺毋滥，不要把普通讨论都算进来。\n"
        f"- anchors：{profile.anchor_guidance}，最多 {profile.anchors_max} 条，原样保留不要改写。\n"
        "成文要求（后做）：\n"
        f"- summary 约 {profile.summary_target_min}～{profile.summary_target_max} 个中文字符，"
        "必须涵盖上面的 key_points，并把 anchors 自然嵌入其中。\n"
        "- 结论前置：先说本块最重要的结论，再补背景与展开；不要写成“会议讨论了X、强调了Y”的流水账。\n"
        "- 只依据本块 Timeline，不得引入块外信息，不得改写 anchors 的原意。\n"
        "其它字段：\n"
        "- continues_previous：本块是否在延续上一块的同一话题（同一问题、对象或结论方向）。没有上一块时填 false。\n"
        "- key_refs 最多 3 个，必须来自本块，用于代表本块核心内容。\n"
        "- action_candidates 只提取本块中明确要求执行、确认执行或明确分配的待办；没有则返回 []。\n"
        "- owner 只有原文明确支持时才填对应 speaker_id，否则 null；deadline 只有原文明确出现才填，否则 null。\n\n"
        f"{prev_text}"
        "输出结构：\n"
        f"{json.dumps(prompt_shape, ensure_ascii=False, indent=2)}\n\n"
        f"本块 Timeline：\n{timeline}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
def _build_retry_messages(
    base_messages: list[dict[str, str]],
    previous_output: str | None,
    correction: str,
    *,
    echo_limit: int = MAX_RETRY_ECHO_CHARS,
) -> tuple[list[dict[str, str]], str]:
    """把上次(坏)输出作为有界 assistant 轮回显，再接一条纠正 user 轮。

    贪心解码下，只有真正改变输入才可能得到不同输出；让模型看到自己上一条输出，
    纠正指令里的"上一条"才有指代对象。回显做长度上限保护，避免撑爆上下文。
    """
    previous_output = previous_output or ""
    if len(previous_output) > echo_limit:
        echo = previous_output[:echo_limit] + "…（后续省略）"
    else:
        echo = previous_output
    messages = [
        *base_messages,
        {"role": "assistant", "content": echo},
        {"role": "user", "content": correction},
    ]
    return messages, echo

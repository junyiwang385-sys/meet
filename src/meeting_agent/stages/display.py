"""Frontend view model and human-readable meeting display."""

from __future__ import annotations

from typing import Any

from .transcript import format_ms


def display_speaker_label(speaker_id: str | None) -> str:
    if not speaker_id:
        return "未指定"
    if speaker_id.startswith("speaker_"):
        suffix = speaker_id[len("speaker_") :]
        if suffix.isdigit():
            return f"发言人{int(suffix)}"
    return speaker_id


def _carry_over_unknown_labels(segments: list[dict[str, Any]]) -> list[str]:
    """展示用：unknown 段顺延归并到相邻已知说话人（先向前顺延，开头的再向后回填）。

    只影响前端/展示的 speaker 标签，不改动 canonical 段落与 refs。
    """
    labels = [str(seg.get("speaker_id") or "unknown") for seg in segments]
    last_known: str | None = None
    for i, label in enumerate(labels):
        if label != "unknown":
            last_known = label
        elif last_known is not None:
            labels[i] = last_known
    next_known: str | None = None
    for i in range(len(labels) - 1, -1, -1):
        if labels[i] != "unknown":
            next_known = labels[i]
        elif next_known is not None:
            labels[i] = next_known
    return labels


def _range_from_refs(
    refs: list[str], segment_by_id: dict[str, dict[str, Any]]
) -> tuple[int, int]:
    cited = [segment_by_id[ref] for ref in refs if ref in segment_by_id]
    if not cited:
        return 0, 0
    return (
        min(item["start_ms"] for item in cited),
        max(item["end_ms"] for item in cited),
    )


def build_frontend_result(
    meeting: dict[str, Any],
    segments: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    context_policy: str,
) -> dict[str, Any]:
    by_id = {segment["segment_id"]: segment for segment in segments}
    overview = summary.get("overview")
    chapters = [
        {
            "id": index,
            "start_ms": chapter["start_ms"],
            "end_ms": chapter["end_ms"],
            "title": chapter["title"],
            "summary": chapter["overview"],
            "start_ref": chapter.get("start_ref"),
            "end_ref": chapter.get("end_ref"),
            "refs": chapter["refs"],
        }
        for index, chapter in enumerate(summary.get("chapters", []), 1)
    ]
    speaker_summaries = [
        {
            "speaker_id": item["speaker_id"],
            "summary": item["overview"],
            "refs": item["refs"],
        }
        for item in summary.get("speakers", [])
    ]
    action_items = []
    for index, item in enumerate(summary.get("action_items", []), 1):
        start_ms, end_ms = _range_from_refs(item["refs"], by_id)
        action_items.append(
            {
                "id": index,
                "task": item["task"],
                "owner": item["owner"],
                "deadline": item["deadline"],
                "start_ms": start_ms,
                "end_ms": end_ms,
                "refs": item["refs"],
            }
        )
    nonempty_segments = [segment for segment in segments if segment.get("text")]
    carried_labels = _carry_over_unknown_labels(nonempty_segments)
    transcription = [
        {
            "segment_id": segment["segment_id"],
            "start_ms": segment["start_ms"],
            "end_ms": segment["end_ms"],
            "speaker_id": carried,
            "raw_speaker_id": segment["speaker_id"],
            "text": segment["text"],
        }
        for segment, carried in zip(nonempty_segments, carried_labels)
    ]
    return {
        "meeting_id": meeting["meeting_id"],
        "title": summary.get("title"),
        "duration_ms": meeting.get("duration_ms"),
        "context_policy": context_policy,
        "full_summary": overview["text"] if isinstance(overview, dict) else None,
        "chapters": chapters,
        "speaker_summaries": speaker_summaries,
        "action_items": action_items,
        "transcription": transcription,
    }


def render_meeting_display(frontend: dict[str, Any]) -> str:
    lines = []
    title = frontend.get("title") or "未命名会议"
    lines.extend(
        [
            f"会议标题：{title}",
            f"处理策略：{frontend.get('context_policy')}",
            "",
            "========== 全文摘要 ==========",
            frontend.get("full_summary") or "无",
            "",
            "========== 章节速览 ==========",
        ]
    )
    chapters = frontend.get("chapters", [])
    if chapters:
        for chapter in chapters:
            lines.extend(
                [
                    f"[{format_ms(chapter['start_ms'])}-{format_ms(chapter['end_ms'])}] {chapter['title']}",
                    chapter["summary"],
                    "",
                ]
            )
    else:
        lines.extend(["无", ""])

    lines.append("========== 发言人总结 ==========")
    speaker_summaries = frontend.get("speaker_summaries", [])
    if speaker_summaries:
        for item in speaker_summaries:
            lines.extend([f"{display_speaker_label(item['speaker_id'])}：{item['summary']}", ""])
    else:
        lines.extend(["当前处理路径未生成发言人总结", ""])

    lines.append("========== 待办事项 ==========")
    actions = frontend.get("action_items", [])
    if actions:
        for item in actions:
            owner = display_speaker_label(item.get("owner")) if item.get("owner") else "未指定"
            deadline = item.get("deadline") or "未指定"
            lines.append(
                f"[{format_ms(item['start_ms'])}] {item['task']}｜负责人：{owner}｜截止时间：{deadline}"
            )
        lines.append("")
    else:
        lines.extend(["无", ""])

    lines.append("========== 完整转写 ==========")
    for item in frontend.get("transcription", []):
        lines.append(
            f"[{item['segment_id']}]"
            f"[{format_ms(item['start_ms'])}-{format_ms(item['end_ms'])}]"
            f"[{display_speaker_label(item['speaker_id'])}] {item['text']}"
        )
    return "\n".join(lines).rstrip() + "\n"

"""从用户编辑后的 draft 渲染正式版会议纪要（HTML / TXT / JSON）。

纯函数，不做 IO：输入 draft content（见 build_draft_content 的结构），输出各格式文本 +
manifest，供 gateway finalize 处理器写盘与 exports 下载。方案 A：以编辑后的 draft 为准。
"""

from __future__ import annotations

import html
import json
from typing import Any


FORMAL_JSON_SCHEMA = "formal-minutes.v1"
FORMAL_MANIFEST_SCHEMA = "formal-manifest.v1"

# 与 gateway_storage._EXPORT_NAMES 保持一致
FORMAT_FILES: dict[str, tuple[str, str]] = {
    "html": ("formal_minutes.html", "text/html; charset=utf-8"),
    "txt": ("formal_minutes.txt", "text/plain; charset=utf-8"),
    "json": ("formal_result.json", "application/json; charset=utf-8"),
}


def _format_ms(value: Any) -> str:
    try:
        total_seconds = max(0, int(value) // 1000)
    except (TypeError, ValueError):
        return "--:--"
    return f"{total_seconds // 60}m{total_seconds % 60:02d}s"


def _speaker_label(speaker_id: Any, speaker_names: dict[str, Any]) -> str:
    if not speaker_id:
        return "未指定"
    label = speaker_names.get(str(speaker_id))
    if label:
        return str(label)
    text = str(speaker_id)
    if text.startswith("speaker_") and text[len("speaker_"):].isdigit():
        return f"发言人{int(text[len('speaker_'):])}"
    return text


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalized_sections(content: dict[str, Any]) -> dict[str, Any]:
    """把 draft content 归一成渲染友好的结构，各格式共用。"""
    speaker_names = content.get("speaker_names") if isinstance(content.get("speaker_names"), dict) else {}
    minutes = content.get("minutes") if isinstance(content.get("minutes"), dict) else None
    overview = _clean(minutes.get("overview")) if minutes else ""
    chapters = [
        {
            "title": _clean(item.get("title")) or "未命名章节",
            "summary": _clean(item.get("summary")),
            "start_ms": item.get("start_ms"),
            "end_ms": item.get("end_ms"),
        }
        for item in content.get("chapters", [])
        if isinstance(item, dict)
    ]
    decisions = [
        _clean(item.get("text"))
        for item in content.get("decisions", [])
        if isinstance(item, dict) and _clean(item.get("text"))
    ]
    action_items = [
        {
            "text": _clean(item.get("text")),
            "owner": _speaker_label(item.get("owner"), speaker_names) if item.get("owner") else "未指定",
            "due_date": _clean(item.get("due_date")) or "未指定",
        }
        for item in content.get("action_items", [])
        if isinstance(item, dict) and _clean(item.get("text"))
    ]
    return {
        "title": _clean(content.get("title")) or "未命名会议",
        "overview": overview,
        "chapters": chapters,
        "decisions": decisions,
        "action_items": action_items,
        "speaker_names": {str(k): str(v) for k, v in speaker_names.items()},
    }


def render_formal_txt(content: dict[str, Any]) -> str:
    s = _normalized_sections(content)
    lines = [f"会议纪要：{s['title']}", ""]
    lines += ["========== 全文摘要 ==========", s["overview"] or "无", ""]
    lines.append("========== 章节 ==========")
    if s["chapters"]:
        for chapter in s["chapters"]:
            lines.append(f"[{_format_ms(chapter['start_ms'])}-{_format_ms(chapter['end_ms'])}] {chapter['title']}")
            if chapter["summary"]:
                lines.append(chapter["summary"])
            lines.append("")
    else:
        lines += ["无", ""]
    lines.append("========== 决策 ==========")
    lines += [f"- {text}" for text in s["decisions"]] if s["decisions"] else ["无"]
    lines.append("")
    lines.append("========== 待办事项 ==========")
    if s["action_items"]:
        for action in s["action_items"]:
            lines.append(f"- {action['text']}｜负责人：{action['owner']}｜截止：{action['due_date']}")
    else:
        lines.append("无")
    return "\n".join(lines).rstrip() + "\n"


def render_formal_json(
    content: dict[str, Any], *, meeting_id: str, revision: int, finalized_at: str
) -> dict[str, Any]:
    s = _normalized_sections(content)
    return {
        "schema_version": FORMAL_JSON_SCHEMA,
        "meeting_id": meeting_id,
        "revision": revision,
        "finalized_at": finalized_at,
        "title": s["title"],
        "overview": s["overview"],
        "chapters": s["chapters"],
        "decisions": s["decisions"],
        "action_items": s["action_items"],
        "speaker_names": s["speaker_names"],
    }


def render_formal_html(content: dict[str, Any], *, meeting_id: str, finalized_at: str) -> str:
    s = _normalized_sections(content)
    esc = html.escape

    def section(title: str, body: str) -> str:
        return f"<section><h2>{esc(title)}</h2>{body}</section>"

    chapters_html = "".join(
        f"<article><h3>[{esc(_format_ms(c['start_ms']))}-{esc(_format_ms(c['end_ms']))}] {esc(c['title'])}</h3>"
        f"<p>{esc(c['summary'])}</p></article>"
        for c in s["chapters"]
    ) or "<p>无</p>"
    decisions_html = (
        "<ul>" + "".join(f"<li>{esc(text)}</li>" for text in s["decisions"]) + "</ul>"
        if s["decisions"] else "<p>无</p>"
    )
    actions_html = (
        "<ul>" + "".join(
            f"<li>{esc(a['text'])}<span class=\"meta\">负责人：{esc(a['owner'])}｜截止：{esc(a['due_date'])}</span></li>"
            for a in s["action_items"]
        ) + "</ul>"
        if s["action_items"] else "<p>无</p>"
    )
    return (
        "<!doctype html>\n"
        "<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        f"<title>{esc(s['title'])}</title>"
        "<style>body{font-family:system-ui,'Microsoft YaHei',sans-serif;max-width:760px;margin:40px auto;"
        "padding:0 20px;color:#1a1a1a;line-height:1.7}h1{font-size:1.6rem}h2{margin-top:2rem;border-bottom:1px solid #eee;"
        "padding-bottom:.3rem}article{margin:.8rem 0}.meta{display:block;color:#666;font-size:.85rem;margin-top:.2rem}"
        "footer{margin-top:3rem;color:#999;font-size:.8rem}</style></head><body>"
        f"<h1>{esc(s['title'])}</h1>"
        + section("全文摘要", f"<p>{esc(s['overview']) or '无'}</p>")
        + section("章节", chapters_html)
        + section("决策", decisions_html)
        + section("待办事项", actions_html)
        + f"<footer>会议 ID：{esc(meeting_id)}｜生成时间：{esc(finalized_at)}</footer>"
        "</body></html>\n"
    )


def build_formal_exports(
    content: dict[str, Any],
    *,
    meeting_id: str,
    revision: int,
    finalized_at: str,
    formats: list[str],
) -> dict[str, Any]:
    """渲染指定格式的正式版 + manifest；返回 {name -> {format, media_type, text}} 与 manifest。"""
    selected = [fmt for fmt in ("html", "txt", "json") if fmt in formats]
    if not selected:
        selected = ["html", "txt", "json"]
    files: dict[str, dict[str, Any]] = {}
    for fmt in selected:
        name, media_type = FORMAT_FILES[fmt]
        if fmt == "txt":
            text = render_formal_txt(content)
        elif fmt == "json":
            text = json.dumps(
                render_formal_json(content, meeting_id=meeting_id, revision=revision, finalized_at=finalized_at),
                ensure_ascii=False,
                indent=2,
            ) + "\n"
        else:
            text = render_formal_html(content, meeting_id=meeting_id, finalized_at=finalized_at)
        files[name] = {"format": fmt, "media_type": media_type, "text": text}
    manifest = {
        "schema_version": FORMAL_MANIFEST_SCHEMA,
        "meeting_id": meeting_id,
        "revision": revision,
        "finalized_at": finalized_at,
        "formats": selected,
        "files": [
            {"format": info["format"], "name": name, "media_type": info["media_type"]}
            for name, info in files.items()
        ],
    }
    files["manifest.json"] = {
        "format": "manifest",
        "media_type": "application/json; charset=utf-8",
        "text": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    }
    return {"files": files, "manifest": manifest, "formats": selected}

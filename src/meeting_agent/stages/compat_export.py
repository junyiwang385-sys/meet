"""Deterministic compatibility projections of validated meeting artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
from typing import Any

from ..storage.artifacts import atomic_write_json, relative_artifact


COMPAT_MAPPING_VERSION = "meeting-compat.v1"


def _content_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def build_sentence_index(segments: list[dict[str, Any]]) -> dict[str, int]:
    return {
        segment["segment_id"]: sentence_id
        for sentence_id, segment in enumerate(
            (item for item in segments if item.get("text")), start=1
        )
    }


def build_transcription_export(
    task_id: str,
    meeting: dict[str, Any],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    sentence_index = build_sentence_index(segments)
    paragraphs = []
    for segment in segments:
        if not segment.get("text"):
            continue
        sentence_id = sentence_index[segment["segment_id"]]
        paragraphs.append(
            {
                "ParagraphId": segment["segment_id"],
                "SpeakerId": segment["speaker_id"],
                "Words": [
                    {
                        "Id": sentence_id,
                        "SentenceId": sentence_id,
                        "Start": segment["start_ms"],
                        "End": segment["end_ms"],
                        "Text": segment["text"],
                    }
                ],
            }
        )
    return {
        "TaskId": task_id,
        "Transcription": {
            "AudioInfo": {
                "Duration": meeting.get("duration_ms"),
                "SourceAudio": meeting.get("source_audio"),
            },
            "Paragraphs": paragraphs,
        },
    }


def build_auto_chapters_export(task_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    chapters = [
        {
            "Id": index,
            "Start": chapter["start_ms"],
            "End": chapter["end_ms"],
            "Headline": chapter["title"],
            "Summary": chapter["overview"],
        }
        for index, chapter in enumerate(summary.get("chapters", []), start=1)
    ]
    return {"TaskId": task_id, "AutoChapters": chapters}


def build_summarization_export(task_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    overview = summary.get("overview")
    conversational = [
        {
            "SpeakerId": speaker["speaker_id"],
            "SpeakerName": speaker["speaker_id"],
            "Summary": speaker["overview"],
        }
        for speaker in summary.get("speakers", [])
    ]
    return {
        "TaskId": task_id,
        "Summarization": {
            "ParagraphSummary": overview["text"] if isinstance(overview, dict) else "",
            "ConversationalSummary": conversational,
        },
    }


def _evidence_range(
    refs: list[str],
    segment_by_id: dict[str, dict[str, Any]],
    sentence_index: dict[str, int],
) -> tuple[int, int, int]:
    cited = [segment_by_id[ref] for ref in refs]
    first = min(cited, key=lambda item: (item["start_ms"], item["index"]))
    return (
        sentence_index[first["segment_id"]],
        min(item["start_ms"] for item in cited),
        max(item["end_ms"] for item in cited),
    )


def build_meeting_assistance_export(
    task_id: str,
    summary: dict[str, Any],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    segment_by_id = {segment["segment_id"]: segment for segment in segments}
    sentence_index = build_sentence_index(segments)
    key_sentences = []
    key_point_items = summary.get("speaker_key_points", []) or summary.get("key_points", [])
    for index, item in enumerate(key_point_items, start=1):
        sentence_id, start, end = _evidence_range(item["refs"], segment_by_id, sentence_index)
        key_sentences.append(
            {
                "Id": index,
                "SentenceId": sentence_id,
                "Start": start,
                "End": end,
                "Text": item["text"],
            }
        )
    actions = []
    for index, item in enumerate(summary.get("action_items", []), start=1):
        sentence_id, start, end = _evidence_range(item["refs"], segment_by_id, sentence_index)
        actions.append(
            {
                "Id": index,
                "SentenceId": sentence_id,
                "Start": start,
                "End": end,
                "Text": item["task"],
            }
        )
    return {
        "TaskId": task_id,
        "MeetingAssistance": {
            "Keywords": [item["keyword"] for item in summary.get("keywords", [])],
            "KeySentences": key_sentences,
            "Actions": actions,
        },
    }


def build_compat_bundle(
    task_id: str,
    meeting: dict[str, Any],
    segments: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        "transcription.json": build_transcription_export(task_id, meeting, segments),
        "auto_chapters.json": build_auto_chapters_export(task_id, summary),
        "summarization.json": build_summarization_export(task_id, summary),
        "meeting_assistance.json": build_meeting_assistance_export(task_id, summary, segments),
    }


def validate_compat_bundle(bundle: dict[str, dict[str, Any]]) -> None:
    expected = {
        "transcription.json",
        "auto_chapters.json",
        "summarization.json",
        "meeting_assistance.json",
    }
    if set(bundle) != expected:
        raise ValueError(f"unexpected compatibility bundle files: {sorted(bundle)}")
    task_ids = {value.get("TaskId") for value in bundle.values()}
    if len(task_ids) != 1 or None in task_ids:
        raise ValueError("compatibility bundle TaskId values are missing or inconsistent")
    transcription = bundle["transcription.json"].get("Transcription")
    if not isinstance(transcription, dict) or not isinstance(transcription.get("Paragraphs"), list):
        raise ValueError("invalid compatibility transcription export")
    if not isinstance(bundle["auto_chapters.json"].get("AutoChapters"), list):
        raise ValueError("invalid compatibility auto chapters export")
    if not isinstance(bundle["summarization.json"].get("Summarization"), dict):
        raise ValueError("invalid compatibility summarization export")
    if not isinstance(bundle["meeting_assistance.json"].get("MeetingAssistance"), dict):
        raise ValueError("invalid compatibility meeting assistance export")


def write_compat_bundle(
    out_dir: pathlib.Path,
    *,
    task_id: str,
    meeting: dict[str, Any],
    segments: list[dict[str, Any]],
    summary: dict[str, Any],
    source_summary_path: pathlib.Path,
    source_segments_path: pathlib.Path,
) -> dict[str, Any]:
    bundle = build_compat_bundle(task_id, meeting, segments, summary)
    validate_compat_bundle(bundle)
    staging_dir = out_dir.with_name(f".{out_dir.name}.staging")
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    for name, value in bundle.items():
        atomic_write_json(staging_dir / name, value)
    task_result = {
        "Code": "0",
        "Data": {
            "TaskId": task_id,
            "TaskStatus": "COMPLETED",
            "Result": {
                "Transcription": "transcription.json",
                "AutoChapters": "auto_chapters.json",
                "Summarization": "summarization.json",
                "MeetingAssistance": "meeting_assistance.json",
            },
        },
        "Message": "success",
        "RequestId": task_id,
    }
    atomic_write_json(staging_dir / "task_result.json", task_result)
    manifest = {
        "mapping_version": COMPAT_MAPPING_VERSION,
        "task_id": task_id,
        "source_summary": relative_artifact(source_summary_path, out_dir.parent),
        "source_segments": relative_artifact(source_segments_path, out_dir.parent),
        "source_summary_content_hash": _content_hash(summary),
        "files": {
            name: relative_artifact(staging_dir / name, staging_dir)
            for name in (*bundle.keys(), "task_result.json")
        },
        "limitations": [
            "Paragraphs use one canonical ASR segment per Words entry; word-level timestamps are unavailable.",
            "SpeakerName falls back to the anonymous SpeakerId.",
            "The internal evidence-linked meeting_summary.json remains the source of truth.",
        ],
    }
    atomic_write_json(staging_dir / "manifest.json", manifest)
    backup_dir = out_dir.with_name(f".{out_dir.name}.backup")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    try:
        if out_dir.exists():
            os.replace(out_dir, backup_dir)
        os.replace(staging_dir, out_dir)
    except BaseException:
        if out_dir.exists():
            shutil.rmtree(out_dir)
        if backup_dir.exists():
            os.replace(backup_dir, out_dir)
        raise
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    return manifest

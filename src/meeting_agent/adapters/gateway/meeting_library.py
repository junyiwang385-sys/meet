"""Durable local meeting metadata for the Windows Gateway.

The library keeps product-facing meeting state in SQLite and stores one
metadata snapshot under each meeting directory. Audio and result files are
owned by the same directory, while Board Agent task identifiers remain an
internal Gateway concern.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FILE_HEALTH_KEYS = (
    "metadata",
    "source_audio",
    "result",
    "draft",
    "formal_html",
    "formal_txt",
    "formal_json",
)

MEETING_STATES = {
    "created",
    "recording",
    "uploading",
    "processing",
    "review_ready",
    "finalizing",
    "finalized",
    "failed",
    "cancelled",
}

SOURCE_TYPES = {"local_upload", "pc_record", "board_record"}


class MeetingLibraryError(Exception):
    """An expected local meeting-library error."""


class MeetingLibrary:
    """SQLite-backed meeting metadata and per-meeting directories."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.meetings_root = self.root / "meetings"
        self.database_path = self.root / "meetings.sqlite3"
        self._write_lock = threading.RLock()
        self.meetings_root.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS meetings (
                    meeting_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_meetings_updated_at ON meetings(updated_at DESC)"
            )
            connection.commit()

    @staticmethod
    def _clone(value: Any) -> Any:
        return copy.deepcopy(value)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _metadata_path(self, record: dict[str, Any]) -> Path:
        return self.root / record["directory"] / "metadata.json"

    def _write_metadata_snapshot(self, record: dict[str, Any]) -> None:
        path = self._metadata_path(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "meeting_id": record["detail"]["meeting_id"],
            "meeting": record["detail"],
            "board_task_id": record.get("board_task_id"),
            "board_task_kind": record.get("board_task_kind"),
        }
        temporary = path.with_name("metadata.json.tmp")
        temporary.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _save_record(self, record: dict[str, Any]) -> dict[str, Any]:
        detail = record["detail"]
        if detail["state"] not in MEETING_STATES:
            raise MeetingLibraryError(f"unsupported meeting state: {detail['state']}")
        detail["updated_at"] = self._now()
        detail["seq"] = max(1, int(detail.get("seq", 0)) + 1)
        metadata_json = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE meetings
                   SET title = ?, state = ?, updated_at = ?, metadata_json = ?
                 WHERE meeting_id = ?
                """,
                (
                    detail["title"],
                    detail["state"],
                    detail["updated_at"],
                    metadata_json,
                    detail["meeting_id"],
                ),
            )
            if connection.total_changes != 1:
                raise MeetingLibraryError("meeting record was not found")
            connection.commit()
            self._write_metadata_snapshot(record)
        return self._clone(record)

    def _row_to_record(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise MeetingLibraryError("meeting was not found")
        try:
            record = json.loads(row["metadata_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise MeetingLibraryError("meeting metadata is invalid") from exc
        if not isinstance(record, dict) or not isinstance(record.get("detail"), dict):
            raise MeetingLibraryError("meeting metadata has an invalid shape")
        return record

    def create(
        self,
        *,
        meeting_id: str,
        title: str,
        source_type: str,
        language: str,
        source_file: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if source_type not in SOURCE_TYPES:
            raise MeetingLibraryError(f"unsupported source type: {source_type}")
        now = self._now()
        source_name = None
        source_extension = None
        source_mime_type = None
        source_size_bytes = None
        if source_file is not None:
            source_name = source_file.get("name")
            source_extension = Path(str(source_name)).suffix.lower().lstrip(".") or None
            source_mime_type = source_file.get("mime_type")
            source_size_bytes = source_file.get("size_bytes")

        detail = {
            "meeting_id": meeting_id,
            "title": title,
            "source_type": source_type,
            "source_label": {
                "local_upload": "本地音频",
                "pc_record": "PC 录音",
                "board_record": "板端录音",
            }[source_type],
            "state": "created",
            "phase": "awaiting_source",
            "progress": {
                "percent": 0,
                "estimated": True,
                "elapsed_seconds": 0,
                "estimated_total_seconds": 300,
                "estimated_remaining_seconds": 300,
            },
            "availability": {
                "transcript": False,
                "speakers": False,
                "minutes": False,
                "chapters": False,
                "decisions": False,
                "action_items": False,
                "evidence": False,
                "formal_version": False,
            },
            "review": {
                "pending_count": 0,
                "reviewed_count": 0,
                "dirty": False,
                "draft_revision": 0,
            },
            "audio": {
                "state": "pending",
                "duration_ms": None,
                "size_bytes": source_size_bytes,
                "playable": False,
                "deleted_at": None,
            },
            "meeting_date": now,
            "created_at": now,
            "updated_at": now,
            "language": language or "zh-CN",
            "source": {
                "type": source_type,
                "original_name": source_name,
                "original_extension": source_extension,
                "mime_type": source_mime_type,
                "size_bytes": source_size_bytes,
                "sha256": None,
                "requires_conversion": source_extension not in {None, "wav"},
            },
            "raw_stage": "awaiting_audio",
            "seq": 1,
            "capabilities": {
                "can_cancel": True,
                "can_retry_all": False,
                "can_retry_summary": False,
                "can_edit": False,
                "can_save_draft": False,
                "can_finalize": False,
                "can_play_audio": False,
                "can_delete_audio": False,
                "can_reveal_files": True,
                "can_remove_index": True,
            },
            "file_health": {
                "metadata": "available",
                "source_audio": "not_created",
                "result": "not_created",
                "draft": "not_created",
                "formal_html": "not_created",
                "formal_txt": "not_created",
                "formal_json": "not_created",
            },
            "error": None,
        }
        record = {
            "detail": detail,
            "directory": str(Path("meetings") / meeting_id),
            "board_task_id": None,
            "board_task_kind": None,
            "board_task": None,
        }
        metadata_json = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        directory = self.root / record["directory"]
        with self._write_lock, self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM meetings WHERE meeting_id = ?", (meeting_id,)
            ).fetchone() is not None:
                raise MeetingLibraryError("meeting already exists")
            directory.mkdir(parents=True, exist_ok=False)
            connection.execute(
                "INSERT INTO meetings(meeting_id, title, state, updated_at, metadata_json) VALUES (?, ?, ?, ?, ?)",
                (meeting_id, title, "created", now, metadata_json),
            )
            connection.commit()
            self._write_metadata_snapshot(record)
        return self._clone(record)

    def get(self, meeting_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM meetings WHERE meeting_id = ?", (meeting_id,)
            ).fetchone()
        return self._clone(self._row_to_record(row))

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._save_record(self._clone(record))

    def list(
        self,
        *,
        query: str = "",
        status: str = "all",
        sort: str = "updated_desc",
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT metadata_json FROM meetings"
            ).fetchall()
        records = [self._row_to_record(row) for row in rows]
        query_lower = query.strip().casefold()
        filtered = []
        for record in records:
            detail = record["detail"]
            if query_lower and query_lower not in detail["title"].casefold():
                continue
            if status != "all" and meeting_filter(detail) != status:
                continue
            filtered.append(record)
        if sort == "title_asc":
            filtered.sort(key=lambda item: item["detail"]["title"].casefold())
        elif sort == "created_desc":
            filtered.sort(key=lambda item: item["detail"]["created_at"], reverse=True)
        else:
            filtered.sort(key=lambda item: item["detail"]["updated_at"], reverse=True)
        return self._clone(filtered)

    def facets(self) -> dict[str, int]:
        result = {"all": 0, "processing": 0, "failed": 0, "review": 0, "confirmed": 0, "deleted": 0}
        for record in self.list():
            result["all"] += 1
            category = meeting_filter(record["detail"])
            if category != "all":
                result[category] += 1
        return result

    def remove_index(self, meeting_id: str) -> None:
        with self._write_lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM meetings WHERE meeting_id = ?", (meeting_id,))
            if cursor.rowcount != 1:
                raise MeetingLibraryError("meeting was not found")
            connection.commit()

    def directory_for(self, record: dict[str, Any]) -> Path:
        return self.root / record["directory"]


def meeting_filter(detail: dict[str, Any]) -> str:
    state = detail.get("state")
    audio_state = detail.get("audio", {}).get("state")
    if state == "failed":
        return "failed"
    if state in {"created", "recording", "uploading", "processing", "finalizing"}:
        return "processing"
    if state == "review_ready":
        return "review"
    if state == "finalized" and audio_state == "deleted":
        return "deleted"
    if state == "finalized":
        return "confirmed"
    return "all"


def detail_to_list_item(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(detail[key])
        for key in (
            "meeting_id",
            "title",
            "source_type",
            "source_label",
            "state",
            "phase",
            "progress",
            "availability",
            "review",
            "audio",
            "meeting_date",
            "created_at",
            "updated_at",
        )
    }

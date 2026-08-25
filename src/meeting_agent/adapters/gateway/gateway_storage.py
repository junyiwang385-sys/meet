"""Storage accounting and narrowly-scoped temporary-file cleanup."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Iterable


WARNING_FREE_BYTES = 10 * 1024 * 1024 * 1024
MINIMUM_FREE_BYTES = 3 * 1024 * 1024 * 1024
SAFE_TEMP_AGE_SECONDS = 10 * 60
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg"}
_RESULT_NAMES = {"result.json", "board_result.json", "diagnostics.json", "error_report.json"}
_EXPORT_NAMES = {"formal_minutes.html", "formal_minutes.txt", "formal_result.json", "manifest.json"}
_TEMP_SUFFIXES = {".part", ".tmp", ".staging"}


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _iter_files(root: Path) -> Iterable[Path]:
    """Walk only real files below root; never follow a symlink outside it."""

    if not root.exists():
        return
    for directory, dir_names, file_names in os.walk(root, followlinks=False):
        dir_path = Path(directory)
        dir_names[:] = [name for name in dir_names if not (dir_path / name).is_symlink()]
        for name in file_names:
            path = dir_path / name
            if path.is_symlink():
                continue
            yield path


def _category(path: Path, root: Path) -> str:
    name = path.name.lower()
    relative_parts = {part.lower() for part in path.relative_to(root).parts}
    if "exports" in relative_parts or name in _EXPORT_NAMES:
        return "exports_bytes"
    if name in _RESULT_NAMES:
        return "results_bytes"
    if name.endswith(".part") or name.endswith(".staging") or name.endswith(".tmp"):
        return "temp_bytes"
    if path.suffix.lower() in _AUDIO_EXTENSIONS and (
        name.startswith("source.") or name == "processing.wav"
    ):
        return "audio_bytes"
    return "other_bytes"


def storage_status(free_bytes: int, *, warning_free_bytes: int = WARNING_FREE_BYTES,
                   minimum_free_bytes: int = MINIMUM_FREE_BYTES) -> str:
    if free_bytes < minimum_free_bytes:
        return "insufficient"
    if free_bytes < warning_free_bytes:
        return "warning"
    return "ok"


def summarize_storage(
    root: Path,
    *,
    warning_free_bytes: int = WARNING_FREE_BYTES,
    minimum_free_bytes: int = MINIMUM_FREE_BYTES,
) -> dict[str, Any]:
    """Return the product storage contract for one meeting-library root."""

    root = Path(root).expanduser().resolve()
    categories = {
        "audio_bytes": 0,
        "results_bytes": 0,
        "exports_bytes": 0,
        "temp_bytes": 0,
        "other_bytes": 0,
    }
    used_bytes = 0
    for path in _iter_files(root):
        size = _safe_size(path)
        used_bytes += size
        categories[_category(path, root)] += size
    try:
        usage = shutil.disk_usage(root if root.exists() else root.parent)
        total_bytes = usage.total
        free_bytes = usage.free
        writable = os.access(root, os.W_OK) if root.exists() else os.access(root.parent, os.W_OK)
    except OSError:
        total_bytes = 0
        free_bytes = 0
        writable = False
    return {
        "path": str(root),
        "writable": writable,
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "free_bytes": free_bytes,
        "status": "unavailable" if not writable or total_bytes == 0 else storage_status(
            free_bytes,
            warning_free_bytes=warning_free_bytes,
            minimum_free_bytes=minimum_free_bytes,
        ),
        "categories": categories,
        "thresholds": {
            "warning_free_bytes": warning_free_bytes,
            "minimum_free_bytes": minimum_free_bytes,
        },
    }


def storage_meetings(
    records: list[dict[str, Any]],
    root: Path,
    *,
    active_meeting_ids: set[str] | None = None,
    sort: str = "audio_size_desc",
    page: int = 1,
    page_size: int = 30,
) -> dict[str, Any]:
    """Build the per-meeting audio inventory used by StorageManagementPage."""

    active_meeting_ids = active_meeting_ids or set()
    items: list[dict[str, Any]] = []
    root = Path(root)
    for record in records:
        detail = record["detail"]
        meeting_id = str(detail["meeting_id"])
        directory = root / record["directory"]
        audio_path = None
        for candidate in sorted(directory.glob("source.*")):
            if candidate.is_file() and candidate.suffix.lower() in _AUDIO_EXTENSIONS:
                audio_path = candidate
                break
        audio_state = detail.get("audio", {}).get("state", "pending")
        if audio_path is not None:
            audio_state = "available"
        if detail.get("audio", {}).get("state") == "deleted":
            audio_state = "deleted"
        size = _safe_size(audio_path) if audio_path else detail.get("audio", {}).get("size_bytes")
        items.append({
            "meeting_id": meeting_id,
            "title": detail.get("title", meeting_id),
            "meeting_state": detail.get("state", "created"),
            "audio_state": audio_state,
            "audio_size_bytes": size,
            "meeting_date": detail.get("meeting_date") or detail.get("created_at"),
            "can_delete_audio": bool(
                detail.get("state") == "finalized"
                and audio_state == "available"
                and meeting_id not in active_meeting_ids
            ),
        })
    if sort == "title_asc":
        items.sort(key=lambda item: str(item["title"]).casefold())
    elif sort == "meeting_date_desc":
        items.sort(key=lambda item: str(item["meeting_date"] or ""), reverse=True)
    else:
        items.sort(key=lambda item: item["audio_size_bytes"] or 0, reverse=True)
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    return {
        "items": page_items,
        "page": page,
        "page_size": page_size,
        "total": len(items),
        "has_more": start + page_size < len(items),
    }


def cleanup_temporary_files(
    root: Path,
    *,
    active_meeting_ids: set[str] | None = None,
    older_than_seconds: int = SAFE_TEMP_AGE_SECONDS,
) -> dict[str, int]:
    """Delete only old, rebuildable temporary files under meeting directories."""

    active_meeting_ids = active_meeting_ids or set()
    now = time.time()
    freed_bytes = 0
    deleted_file_count = 0
    skipped_active_file_count = 0
    root = Path(root)
    for path in list(_iter_files(root)):
        if path.suffix.lower() not in _TEMP_SUFFIXES:
            continue
        try:
            age = now - path.stat().st_mtime
            relative = path.relative_to(root)
            meeting_id = relative.parts[1] if len(relative.parts) > 1 and relative.parts[0] == "meetings" else None
            if meeting_id in active_meeting_ids:
                skipped_active_file_count += 1
                continue
            if age < older_than_seconds:
                continue
            size = path.stat().st_size
            path.unlink()
            freed_bytes += size
            deleted_file_count += 1
        except (OSError, ValueError):
            continue
    return {
        "freed_bytes": freed_bytes,
        "deleted_file_count": deleted_file_count,
        "skipped_active_file_count": skipped_active_file_count,
    }

#!/usr/bin/env python3
"""Windows-side local Gateway for the Meeting Agent MVP.

The Gateway exposes a localhost HTTP API for the future browser client and
proxies the current board Agent API over the LAN.  This version only covers the
validated communication and WAV-upload probe; it does not run ASR, diarization,
NPU inference, SSE, or meeting-minutes generation.

Local API:

    GET  /api/info
    GET  /api/board/health
    POST /api/meetings
    GET  /api/meetings/{meeting_id}
    PUT  /api/meetings/{meeting_id}/audio
    POST /api/meetings/{meeting_id}/cancel

The audio endpoint accepts the same raw WAV request format as the board API:
Content-Length, Content-Type, and an optional X-File-SHA256 header.  The body
is forwarded in fixed-size chunks and is never accumulated in memory.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import http.client
import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .gateway_settings import (
    DEFAULT_MODEL_PROFILE,
    DEFAULT_SETTINGS_PATH,
    SettingsStore,
    SettingsValidationError,
    build_board_url,
    normalize_settings,
    public_settings,
    storage_path_check,
    validate_board_address,
    validate_port,
)
from .meeting_library import MeetingLibrary, MeetingLibraryError, detail_to_list_item, meeting_filter
from .gateway_storage import cleanup_temporary_files, storage_meetings, summarize_storage
from .meeting_result_adapter import (
    build_draft_content,
    draft_review_summary,
    normalize_harness_result,
)


# ---------------------------------------------------------------------------
# Gateway configuration
# ---------------------------------------------------------------------------

SERVICE_NAME = "meeting-agent-gateway-v0"
GATEWAY_VERSION = "0.2.0"
API_CONTRACT_VERSION = "meeting-agent.api.v1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_BOARD_URL = "http://10.10.22.36:18080"
DEFAULT_MEETING_LIBRARY_PATH = Path(__file__).resolve().parents[2] / "runtime" / "meeting_library"
DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)
GATEWAY_CAPABILITIES = {
    "meeting_library": True,
    "local_upload": True,
    "pc_record": False,
    "board_record": False,
    "partial_result": True,
    "draft": True,
    "finalize": False,
    "audio_delete": False,
    "settings": True,
    "storage_management": True,
    "diagnostics": True,
}
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_JSON_BODY_BYTES = 64 * 1024
MAX_BOARD_RESPONSE_BYTES = 8 * 1024 * 1024
UI_FILE = Path(__file__).with_name("meeting_agent_gateway_ui_v0.html")

SUPPORTED_TASK_KINDS = {
    "audio_upload_probe",
    "transport_probe",
    "harness_meeting_v0",
}
TERMINAL_STATES = {"completed", "cancelled", "failed"}
AUDIO_CONTENT_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "application/octet-stream",
}
MEETING_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


class GatewayError(Exception):
    """An expected Gateway or upstream request error."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        phase: str | None = None,
        retryable: bool = False,
        retry_scope: str | None = None,
        preserved: dict[str, bool] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.phase = phase
        self.retryable = retryable
        self.retry_scope = retry_scope
        self.preserved = preserved
        self.details = details


@dataclass(frozen=True)
class GatewayConfig:
    """Runtime settings shared by the HTTP server and the board client."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    board_url: str = DEFAULT_BOARD_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    meeting_library_path: Path = DEFAULT_MEETING_LIBRARY_PATH
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS
    settings_path: Path = DEFAULT_SETTINGS_PATH
    device_name: str = "会议室 RK1828"
    model_profile: str = DEFAULT_MODEL_PROFILE
    keep_audio_until_finalized: bool = True
    default_export_formats: tuple[str, ...] = ("html", "txt", "json")
    default_language: str = "zh-CN"


# The board probe currently supports one task at a time.  Keep one corresponding
# Gateway mapping so a browser never receives a task ID that the board can no
# longer query after the board-side in-memory task has been replaced.
_current_meeting: dict[str, Any] | None = None
_meeting_lock = threading.Lock()
_create_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Common response and validation helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp for local task metadata and logs."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def allowed_cors_origin(handler: BaseHTTPRequestHandler) -> str | None:
    """Return the request origin only when it is explicitly allowed."""

    origin = handler.headers.get("Origin")
    if origin is None:
        return None
    config = getattr(handler.server, "gateway_config", None)
    if config is None or origin not in config.allowed_origins:
        return None
    return origin


def send_cors_headers(handler: BaseHTTPRequestHandler) -> None:
    """Attach CORS headers for the configured local browser origins."""

    origin = allowed_cors_origin(handler)
    if origin is None:
        return
    handler.send_header("Access-Control-Allow-Origin", origin)
    handler.send_header("Vary", "Origin")


def request_id_for(handler: BaseHTTPRequestHandler) -> str:
    """Return one bounded request identifier for the current HTTP request."""

    request_id = getattr(handler, "_gateway_request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    supplied = handler.headers.get("X-Request-ID", "")
    if re.fullmatch(r"[A-Za-z0-9._-]{1,96}", supplied):
        request_id = supplied
    else:
        request_id = "req-" + uuid.uuid4().hex[:12]
    setattr(handler, "_gateway_request_id", request_id)
    return request_id


def send_json(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: dict[str, Any],
) -> None:
    """Send a compact JSON response and close the client connection."""

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Request-ID", request_id_for(handler))
    send_cors_headers(handler)
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.close_connection = True

    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        # A browser can navigate away while an upstream request is finishing.
        # That must terminate only this request, not the Gateway process.
        pass


def send_bytes(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: bytes,
    content_type: str,
) -> None:
    """Send a fixed byte response such as the local HTML UI."""

    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Request-ID", request_id_for(handler))
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.close_connection = True

    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass


def send_error_json(
    handler: BaseHTTPRequestHandler,
    status: int,
    code: str,
    message: str,
    *,
    phase: str | None = None,
    retryable: bool = False,
    retry_scope: str | None = None,
    preserved: dict[str, bool] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Return errors in the product API error-envelope shape."""

    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if phase is not None:
        error["phase"] = phase
    if retry_scope is not None:
        error["retry_scope"] = retry_scope
    if preserved is not None:
        error["preserved"] = preserved
    if details is not None:
        error["details"] = details
    send_json(handler, status, {"error": error, "request_id": request_id_for(handler)})


def safe_send_gateway_error(
    handler: BaseHTTPRequestHandler,
    error: GatewayError,
) -> None:
    """Send an expected error without masking a disconnected client."""

    try:
        send_error_json(
            handler,
            error.status,
            error.code,
            error.message,
            phase=error.phase,
            retryable=error.retryable,
            retry_scope=error.retry_scope,
            preserved=error.preserved,
            details=error.details,
        )
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    """Read a small JSON control request; audio never uses this helper."""

    raw_length = handler.headers.get("Content-Length", "0")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise GatewayError(400, "invalid_content_length", "Content-Length must be an integer") from exc

    if length < 0:
        raise GatewayError(400, "invalid_content_length", "Content-Length must not be negative")
    if length > MAX_JSON_BODY_BYTES:
        raise GatewayError(413, "request_too_large", "JSON request body is too large")

    raw_body = handler.rfile.read(length)
    if len(raw_body) != length:
        raise GatewayError(400, "request_body_incomplete", "request body ended before Content-Length bytes were received")
    if not raw_body:
        return {}

    try:
        value = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GatewayError(400, "invalid_json", str(exc)) from exc

    if not isinstance(value, dict):
        raise GatewayError(400, "invalid_json", "request body must be a JSON object")
    return value


def validate_meeting_id(value: Any) -> str:
    """Validate an ID before using it in a URL lookup or local mapping."""

    if not isinstance(value, str) or MEETING_ID_RE.fullmatch(value) is None:
        raise GatewayError(
            400,
            "invalid_meeting_id",
            "meeting_id must be 1-128 characters using letters, digits, '.', '_' or '-'",
        )
    return value


def parse_audio_headers(
    handler: BaseHTTPRequestHandler,
    max_upload_bytes: int,
) -> tuple[int, str, str | None]:
    """Validate the raw audio request headers used by the board API."""

    raw_length = handler.headers.get("Content-Length")
    if raw_length is None:
        raise GatewayError(
            411,
            "content_length_required",
            "Content-Length is required for the upload probe",
        )

    try:
        expected_size = int(raw_length)
    except ValueError as exc:
        raise GatewayError(400, "invalid_content_length", "Content-Length must be an integer") from exc

    if expected_size <= 0:
        raise GatewayError(400, "invalid_content_length", "Content-Length must be positive")
    if expected_size > max_upload_bytes:
        raise GatewayError(
            413,
            "upload_too_large",
            f"upload exceeds {max_upload_bytes} bytes",
        )

    content_type = (handler.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if content_type not in AUDIO_CONTENT_TYPES:
        raise GatewayError(
            415,
            "unsupported_content_type",
            "supported content types are audio/wav, audio/x-wav and application/octet-stream",
        )

    supplied_sha256 = handler.headers.get("X-File-SHA256")
    if supplied_sha256 is not None:
        supplied_sha256 = supplied_sha256.strip().lower()
        if SHA256_RE.fullmatch(supplied_sha256) is None:
            raise GatewayError(
                400,
                "invalid_sha256",
                "X-File-SHA256 must be a 64-character hexadecimal digest",
            )

    return expected_size, content_type, supplied_sha256


def make_meeting_id() -> str:
    """Create a URL-safe local meeting ID."""

    return "meeting-" + uuid.uuid4().hex[:12]


def current_meeting_snapshot() -> dict[str, Any] | None:
    """Copy the current local mapping without exposing mutable global state."""

    with _meeting_lock:
        if _current_meeting is None:
            return None
        snapshot = dict(_current_meeting)
        snapshot["board_task"] = dict(_current_meeting["board_task"])
        return snapshot


def get_meeting(meeting_id: str) -> dict[str, Any]:
    """Return the current mapping or a stable not-found error."""

    with _meeting_lock:
        if _current_meeting is None or _current_meeting["meeting_id"] != meeting_id:
            raise GatewayError(404, "meeting_not_found", "meeting was not found")
        snapshot = dict(_current_meeting)
        snapshot["board_task"] = dict(_current_meeting["board_task"])
        return snapshot


def update_meeting(board_task: dict[str, Any]) -> None:
    """Update the cached board snapshot after a successful proxy call."""

    global _current_meeting

    with _meeting_lock:
        if _current_meeting is None:
            return
        if _current_meeting["board_task_id"] != board_task.get("task_id"):
            return
        _current_meeting["board_task"] = dict(board_task)
        _current_meeting["updated_at"] = utc_now()


def meeting_response(
    record: dict[str, Any],
    board_task: dict[str, Any],
) -> dict[str, Any]:
    """Wrap a board task with the Gateway meeting mapping."""

    return {
        "meeting_id": record["meeting_id"],
        "board_task_id": record["board_task_id"],
        "board_task": board_task,
        "gateway": {
            "service": SERVICE_NAME,
            "version": GATEWAY_VERSION,
            "local_only": True,
        },
    }


def gateway_info(config: GatewayConfig) -> dict[str, Any]:
    """Return the v1 discovery document used by the React client."""

    advertised_host = config.host
    if advertised_host == "0.0.0.0":
        advertised_host = "127.0.0.1"
    elif advertised_host == "::":
        advertised_host = "::1"
    if ":" in advertised_host and not advertised_host.startswith("["):
        advertised_host = f"[{advertised_host}]"

    return {
        "service": SERVICE_NAME,
        "version": GATEWAY_VERSION,
        "api_contract_version": API_CONTRACT_VERSION,
        "status": "ready",
        "local_only": config.host in {"127.0.0.1", "localhost", "::1"},
        "base_url": f"http://{advertised_host}:{config.port}",
        "board_url": config.board_url,
        "capabilities": dict(GATEWAY_CAPABILITIES),
        "api": [
            "GET /",
            "GET /app",
            "GET /api/info",
            "GET /api/system/status",
            "GET /api/settings",
            "PUT /api/settings",
            "POST /api/settings/board/check",
            "POST /api/settings/storage/check",
            "GET /api/storage",
            "GET /api/storage/meetings",
            "POST /api/storage/cleanup-temp",
            "POST /api/system/reveal",
            "GET /api/board/health",
            "GET /api/meetings",
            "POST /api/meetings",
            "GET /api/meetings/{meeting_id}",
            "GET /api/meetings/{meeting_id}/result",
            "GET /api/meetings/{meeting_id}/draft",
            "PUT /api/meetings/{meeting_id}/draft",
            "PUT /api/meetings/{meeting_id}/audio",
            "POST /api/meetings/{meeting_id}/cancel",
            "POST /api/meetings/{meeting_id}/retry",
            "POST /api/meetings/{meeting_id}/rescan",
            "DELETE /api/meetings/{meeting_id}?mode=index_only",
        ],
    }


def parse_create_meeting_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a product-level meeting creation request."""

    title = payload.get("title")
    source_type = payload.get("source_type")
    language = payload.get("language", "zh-CN")
    if not isinstance(title, str) or not title.strip():
        raise GatewayError(400, "invalid_title", "title is required")
    if len(title.strip()) > 200:
        raise GatewayError(400, "invalid_title", "title must be at most 200 characters")
    if source_type not in {"local_upload", "pc_record", "board_record"}:
        raise GatewayError(400, "invalid_source_type", "source_type is invalid")
    if not isinstance(language, str) or not language.strip():
        raise GatewayError(400, "invalid_language", "language must be a non-empty string")

    source_file = payload.get("source_file")
    if source_file is not None:
        if not isinstance(source_file, dict):
            raise GatewayError(400, "invalid_source_file", "source_file must be an object")
        name = source_file.get("name")
        size_bytes = source_file.get("size_bytes")
        mime_type = source_file.get("mime_type")
        if not isinstance(name, str) or not name.strip():
            raise GatewayError(400, "invalid_source_file", "source_file.name is required")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            raise GatewayError(400, "invalid_source_file", "source_file.size_bytes must be non-negative")
        if not isinstance(mime_type, str):
            raise GatewayError(400, "invalid_source_file", "source_file.mime_type must be a string")
        source_file = {
            "name": name.strip(),
            "size_bytes": size_bytes,
            "mime_type": mime_type,
            "last_modified_at": source_file.get("last_modified_at"),
        }

    requested_id = payload.get("meeting_id")
    if requested_id is not None:
        requested_id = validate_meeting_id(requested_id)
    return {
        "meeting_id": requested_id or make_meeting_id(),
        "title": title.strip(),
        "source_type": source_type,
        "language": language.strip(),
        "source_file": source_file,
    }


def product_created_response(detail: dict[str, Any]) -> dict[str, Any]:
    """Return the response expected after creating a product meeting."""

    return {
        "meeting_id": detail["meeting_id"],
        "title": detail["title"],
        "state": detail["state"],
        "phase": detail["phase"],
        "source_type": detail["source_type"],
        "created_at": detail["created_at"],
    }


def read_local_json(path: Path) -> dict[str, Any] | None:
    """Read a local JSON object when it exists and is valid."""

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise GatewayError(500, "file_unreadable", str(exc)) from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GatewayError(422, "result_invalid", str(exc)) from exc
    if not isinstance(value, dict):
        raise GatewayError(422, "result_invalid", "result file must contain a JSON object")
    return value


def save_upload_to_path(
    handler: BaseHTTPRequestHandler,
    target: Path,
    expected_size: int,
    supplied_sha256: str | None,
) -> str:
    """Save a complete request body locally before contacting the board."""

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    received = 0
    committed = False
    try:
        with partial.open("wb") as destination:
            while received < expected_size:
                remaining = expected_size - received
                try:
                    chunk = handler.rfile.read(min(UPLOAD_CHUNK_BYTES, remaining))
                except (ConnectionError, OSError) as exc:
                    raise GatewayError(
                        400,
                        "UPLOAD_INTERRUPTED",
                        "音频传输中断",
                        phase="uploading",
                        retryable=True,
                        retry_scope="upload",
                        preserved={
                            "audio": False,
                            "transcript": False,
                            "speakers": False,
                            "summary": False,
                            "formal_version": False,
                        },
                        details={"reason": str(exc)},
                    ) from exc
                if not chunk:
                    raise GatewayError(
                        400,
                        "UPLOAD_INTERRUPTED",
                        "音频传输中断",
                        phase="uploading",
                        retryable=True,
                        retry_scope="upload",
                        preserved={
                            "audio": False,
                            "transcript": False,
                            "speakers": False,
                            "summary": False,
                            "formal_version": False,
                        },
                    )
                destination.write(chunk)
                digest.update(chunk)
                received += len(chunk)

        if received != expected_size:
            raise GatewayError(
                400,
                "UPLOAD_INTERRUPTED",
                "音频传输中断",
                phase="uploading",
                retryable=True,
                retry_scope="upload",
            )

        actual_sha256 = digest.hexdigest()
        if supplied_sha256 is not None and actual_sha256 != supplied_sha256:
            raise GatewayError(
                422,
                "input_sha256_mismatch",
                "uploaded file SHA-256 does not match X-File-SHA256",
                phase="uploading",
                retryable=True,
                retry_scope="upload",
            )

        partial.replace(target)
        committed = True
        return actual_sha256
    except GatewayError:
        raise
    except OSError as exc:
        raise GatewayError(
            507,
            "STORAGE_INSUFFICIENT",
            "本地空间不足",
            phase="uploading",
            retryable=True,
            retry_scope="upload",
            details={"path": str(target), "reason": str(exc)},
        ) from exc
    finally:
        if not committed:
            try:
                partial.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def product_upload_error(
    record: dict[str, Any],
    *,
    status: int,
    code: str,
    message: str,
    phase: str = "uploading",
    retryable: bool = True,
    retry_scope: str = "all",
    preserved_audio: bool,
) -> GatewayError:
    """Persist a failed product upload while retaining any complete local audio."""

    detail = record["detail"]
    detail["state"] = "failed"
    detail["phase"] = phase
    detail["raw_stage"] = phase
    detail["error"] = {
        "code": code,
        "message": message,
        "phase": phase,
        "retryable": retryable,
        "retry_scope": retry_scope,
        "preserved": {
            "audio": preserved_audio,
            "transcript": False,
            "speakers": False,
            "summary": False,
            "formal_version": False,
        },
    }
    detail["capabilities"]["can_cancel"] = False
    detail["capabilities"]["can_retry_all"] = preserved_audio
    if preserved_audio:
        detail["audio"]["state"] = "available"
        detail["file_health"]["source_audio"] = "available"
    return GatewayError(
        status,
        code,
        message,
        phase=phase,
        retryable=retryable,
        retry_scope=retry_scope,
        preserved=detail["error"]["preserved"],
    )


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """Write one JSON object without exposing a partially written result."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def product_phase_for_board_stage(stage: str) -> str:
    """Map board Harness stages to the smaller product phase vocabulary."""

    if stage in {"awaiting_audio", "audio_upload"}:
        return "uploading"
    if stage in {"segmentation", "batch_asr", "transcript_prepare", "processing"}:
        return "transcribing"
    if stage in {"llm_summary", "compat_export", "meeting_ready"}:
        return "synthesizing"
    return "transcribing"


def product_progress_for_board_stage(stage: str) -> int:
    """Return a deliberately estimated progress value for each board stage."""

    return {
        "awaiting_audio": 5,
        "audio_upload": 8,
        "segmentation": 12,
        "batch_asr": 35,
        "transcript_prepare": 58,
        "llm_summary": 68,
        "compat_export": 92,
        "meeting_ready": 100,
    }.get(stage, 10)


def product_board_error_code(value: Any, fallback: str) -> str:
    """Convert board-internal error identifiers to stable product codes."""

    if not isinstance(value, str) or not value.strip():
        return fallback
    return value.strip().upper()


def serve_ui(handler: BaseHTTPRequestHandler) -> None:
    """Serve the fixed same-origin browser UI without exposing arbitrary files."""

    try:
        body = UI_FILE.read_bytes()
    except OSError as exc:
        raise GatewayError(500, "ui_unavailable", str(exc)) from exc
    send_bytes(handler, 200, body, "text/html; charset=utf-8")


# ---------------------------------------------------------------------------
# Board HTTP client
# ---------------------------------------------------------------------------


class BoardClient:
    """Small dependency-free HTTP client for the board Agent API."""

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("board URL must be an HTTP or HTTPS URL with a hostname")
        if parsed.query or parsed.fragment:
            raise ValueError("board URL must not contain a query or fragment")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("board URL contains an invalid port") from exc

        self.base_url = base_url.rstrip("/")
        self.scheme = parsed.scheme
        self.host = parsed.hostname
        self.port = port or (443 if parsed.scheme == "https" else 80)
        self.base_path = parsed.path.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _connection(self) -> http.client.HTTPConnection:
        if self.scheme == "https":
            return http.client.HTTPSConnection(
                self.host,
                self.port,
                timeout=self.timeout_seconds,
            )
        return http.client.HTTPConnection(
            self.host,
            self.port,
            timeout=self.timeout_seconds,
        )

    def _target(self, endpoint: str) -> str:
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        return self.base_path + endpoint

    @staticmethod
    def _decode_response(response: http.client.HTTPResponse) -> tuple[int, dict[str, Any]]:
        body = response.read(MAX_BOARD_RESPONSE_BYTES + 1)
        if len(body) > MAX_BOARD_RESPONSE_BYTES:
            raise GatewayError(502, "board_response_too_large", "board response exceeds Gateway limit")
        if not body:
            return response.status, {}

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GatewayError(502, "invalid_board_response", str(exc)) from exc
        if not isinstance(payload, dict):
            raise GatewayError(502, "invalid_board_response", "board response must be a JSON object")
        return response.status, payload

    def request_json(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """Perform a short JSON request and preserve the board HTTP status."""

        body: bytes | None = None
        headers = {
            "Accept": "application/json",
            "Connection": "close",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
            headers["Content-Length"] = str(len(body))

        connection = self._connection()
        try:
            connection.request(method, self._target(endpoint), body=body, headers=headers)
            return self._decode_response(connection.getresponse())
        except GatewayError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise GatewayError(502, "board_unreachable", str(exc)) from exc
        finally:
            connection.close()

    def stream_audio(
        self,
        task_id: str,
        handler: BaseHTTPRequestHandler,
        expected_size: int,
        content_type: str,
        supplied_sha256: str | None,
    ) -> tuple[int, dict[str, Any], str]:
        """Forward exactly one request body to the board in fixed-size chunks."""

        connection = self._connection()
        sent = 0
        digest = hashlib.sha256()

        try:
            connection.putrequest(
                "PUT",
                self._target(f"/v1/tasks/{task_id}/audio"),
                skip_accept_encoding=True,
            )
            connection.putheader("Content-Type", content_type)
            connection.putheader("Content-Length", str(expected_size))
            connection.putheader("Connection", "close")
            if supplied_sha256 is not None:
                connection.putheader("X-File-SHA256", supplied_sha256)
            connection.endheaders()

            while sent < expected_size:
                remaining = expected_size - sent
                try:
                    chunk = handler.rfile.read(min(UPLOAD_CHUNK_BYTES, remaining))
                except (ConnectionError, OSError) as exc:
                    raise GatewayError(
                        400,
                        "client_body_incomplete",
                        f"failed to read upload body: {exc}",
                    ) from exc

                if not chunk:
                    raise GatewayError(
                        400,
                        "client_body_incomplete",
                        "request body ended before Content-Length bytes were received",
                    )

                try:
                    connection.send(chunk)
                except (OSError, http.client.HTTPException) as exc:
                    raise GatewayError(502, "board_unreachable", str(exc)) from exc
                digest.update(chunk)
                sent += len(chunk)

            status, payload = self._decode_response(connection.getresponse())
            return status, payload, digest.hexdigest()
        except GatewayError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise GatewayError(502, "board_unreachable", str(exc)) from exc
        finally:
            connection.close()

    def stream_file_audio(
        self,
        task_id: str,
        source_path: Path,
        expected_size: int,
        content_type: str,
        supplied_sha256: str | None,
    ) -> tuple[int, dict[str, Any], str]:
        """Forward a complete local audio file to the board in fixed-size chunks."""

        connection = self._connection()
        sent = 0
        digest = hashlib.sha256()
        try:
            connection.putrequest(
                "PUT",
                self._target(f"/v1/tasks/{task_id}/audio"),
                skip_accept_encoding=True,
            )
            connection.putheader("Content-Type", content_type)
            connection.putheader("Content-Length", str(expected_size))
            connection.putheader("Connection", "close")
            if supplied_sha256 is not None:
                connection.putheader("X-File-SHA256", supplied_sha256)
            connection.endheaders()

            with source_path.open("rb") as source:
                while sent < expected_size:
                    chunk = source.read(min(UPLOAD_CHUNK_BYTES, expected_size - sent))
                    if not chunk:
                        raise GatewayError(
                            500,
                            "local_audio_incomplete",
                            "本地音频文件长度与元数据不一致",
                        )
                    try:
                        connection.send(chunk)
                    except (OSError, http.client.HTTPException) as exc:
                        raise GatewayError(502, "board_unreachable", str(exc)) from exc
                    digest.update(chunk)
                    sent += len(chunk)

            status, payload = self._decode_response(connection.getresponse())
            return status, payload, digest.hexdigest()
        except GatewayError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise GatewayError(502, "board_unreachable", str(exc)) from exc
        finally:
            connection.close()


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------


class GatewayRequestHandler(BaseHTTPRequestHandler):
    """Handle the local Gateway API and proxy calls to the board."""

    protocol_version = "HTTP/1.0"
    server_version = "MeetingAgentGateway/0.1"

    @property
    def gateway_config(self) -> GatewayConfig:
        return self.server.gateway_config  # type: ignore[attr-defined]

    @property
    def board_client(self) -> BoardClient:
        return self.server.board_client  # type: ignore[attr-defined]

    @property
    def meeting_library(self) -> MeetingLibrary:
        return self.server.meeting_library  # type: ignore[attr-defined]

    @property
    def gateway_settings(self) -> dict[str, Any]:
        return self.server.gateway_settings  # type: ignore[attr-defined]

    @property
    def settings_store(self) -> SettingsStore:
        return self.server.settings_store  # type: ignore[attr-defined]

    def active_meeting_ids(self) -> set[str]:
        """Return product meetings whose Board work is not terminal."""

        active_states = {"recording", "uploading", "processing", "finalizing"}
        return {
            str(record["detail"]["meeting_id"])
            for record in self.meeting_library.list()
            if record["detail"].get("state") in active_states
        }

    def product_record(self, meeting_id: str) -> dict[str, Any]:
        """Load a durable product meeting or return a contract error."""

        try:
            return self.meeting_library.get(meeting_id)
        except MeetingLibraryError as exc:
            raise GatewayError(404, "meeting_not_found", str(exc)) from exc

    def _cache_completed_result(
        self,
        record: dict[str, Any],
        task_id: str,
    ) -> tuple[dict[str, Any], bool]:
        """Fetch one completed Harness result and publish the product cache."""

        meeting_directory = self.meeting_library.directory_for(record)
        product_path = meeting_directory / "result.json"
        existing = read_local_json(product_path)
        if existing is not None and existing.get("schema_version") == "meeting-result.v1":
            return record, True

        status, board_result = self.board_client.request_json(
            "GET",
            f"/v1/tasks/{task_id}/result",
        )
        if status >= 300:
            board_error = board_result.get("error")
            board_error = board_error if isinstance(board_error, dict) else {}
            code = product_board_error_code(board_error.get("code"), "RESULT_UNAVAILABLE")
            if code == "RESULT_NOT_READY":
                return record, False
            raise GatewayError(
                status,
                code,
                str(board_error.get("message") or "会议结果读取失败"),
                phase="synthesizing",
                retryable=True,
                retry_scope="all",
            )

        try:
            product_result = normalize_harness_result(
                record["detail"]["meeting_id"],
                record["detail"].get("language") or "zh-CN",
                board_result,
            )
            atomic_write_json(meeting_directory / "board_result.json", board_result)
            atomic_write_json(product_path, product_result)
        except (OSError, ValueError, TypeError) as exc:
            raise GatewayError(
                500,
                "RESULT_INVALID",
                f"会议结果无法转换或保存：{exc}",
                phase="synthesizing",
                retryable=True,
                retry_scope="all",
            ) from exc

        detail = record["detail"]
        detail["state"] = "review_ready"
        detail["phase"] = "ready"
        detail["raw_stage"] = "meeting_ready"
        detail["progress"]["percent"] = 100
        detail["progress"]["estimated_remaining_seconds"] = 0
        detail["availability"] = dict(product_result["availability"])
        detail["audio"]["duration_ms"] = product_result.get("duration_ms")
        detail["file_health"]["result"] = "available"
        detail["error"] = None
        detail["capabilities"].update(
            {
                "can_cancel": False,
                "can_retry_all": True,
                "can_retry_summary": True,
                "can_edit": True,
                "can_save_draft": True,
                "can_finalize": True,
            }
        )
        return record, True

    @staticmethod
    def _safe_diagnostic_error(value: Any) -> dict[str, Any]:
        """Keep stable error fields and drop prompt/raw-output content."""

        if not isinstance(value, dict):
            return {}
        allowed = (
            "stage",
            "code",
            "category",
            "message",
            "cause",
            "technical_retryable",
            "product_retryable",
            "retryable",
            "return_code",
            "request_id",
            "request_kind",
            "attempt",
            "split_depth",
            "finish_reason",
            "context_truncated",
            "request_elapsed_seconds",
            "retry_scope",
        )
        projection = {
            key: copy.deepcopy(value[key])
            for key in allowed
            if key in value
        }
        usage = value.get("usage")
        if isinstance(usage, dict):
            projection["usage"] = {
                key: usage[key]
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if isinstance(usage.get(key), (int, float))
            }
        return projection

    @classmethod
    def _safe_diagnostic_stage_details(cls, value: Any) -> dict[str, Any] | None:
        """Keep status metadata without forwarding log paths or raw details."""

        if not isinstance(value, dict):
            return None
        projection = {
            key: copy.deepcopy(value[key])
            for key in ("status", "return_code", "elapsed_seconds")
            if key in value
        }
        error = cls._safe_diagnostic_error(value.get("error"))
        if error:
            projection["error"] = error
        return projection or None

    @staticmethod
    def _safe_diagnostic_ref(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        raw_reference = value.strip()
        reference = raw_reference.replace("\\", "/")
        if reference.startswith("/") or re.match(r"^[A-Za-z]:/", reference):
            reference = Path(reference).name
        reference = reference.lstrip("/")
        if "../" in reference or reference == "..":
            return None
        return reference[:240]

    def _failed_diagnostics(
        self,
        record: dict[str, Any],
        board_task: dict[str, Any],
        board_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Project bounded, non-content diagnostics from Board failure data."""

        source = board_result or {}
        wrapped = source.get("result")
        if isinstance(wrapped, dict):
            source = wrapped
        task_error = board_task.get("error")
        task_error = task_error if isinstance(task_error, dict) else {}
        canonical_diagnostics = (
            board_task.get("harness_diagnostics")
            or task_error.get("diagnostics")
            or source.get("diagnostics")
        )
        canonical_diagnostics = (
            canonical_diagnostics
            if isinstance(canonical_diagnostics, dict)
            else None
        )
        canonical_error = (
            canonical_diagnostics.get("error")
            if canonical_diagnostics and isinstance(canonical_diagnostics.get("error"), dict)
            else {}
        )
        canonical_stage_details = (
            canonical_diagnostics.get("stage_details")
            if canonical_diagnostics and isinstance(canonical_diagnostics.get("stage_details"), dict)
            else {}
        )
        source_errors = source.get("errors")
        if isinstance(source_errors, list):
            source_error = next((item for item in source_errors if isinstance(item, dict)), {})
        elif isinstance(source_errors, dict):
            source_error = source_errors
        else:
            source_error = {}
        nested_error = task_error.get("error")
        nested_error = nested_error if isinstance(nested_error, dict) else {}
        error = self._safe_diagnostic_error(
            {
                **task_error,
                **nested_error,
                **source_error,
                **canonical_error,
            }
        )
        canonical_stage = (
            canonical_diagnostics.get("stage")
            if canonical_diagnostics
            else None
        )
        stage = str(
            error.get("stage")
            or canonical_stage
            or board_task.get("stage")
            or source.get("stage")
            or "harness"
        )
        if stage == "harness":
            stage = str(error.get("failure_stage") or "harness")
        raw_code = str(error.get("code") or "HARNESS_FAILED")[:96]
        raw_message = str(error.get("message") or "RK1828 会议处理失败")[:600]
        diagnostic_source = (
            "harness_error_report"
            if canonical_diagnostics is not None
            else "legacy_task_snapshot"
        )
        runtime = source.get("runtime")
        runtime = runtime if isinstance(runtime, dict) else {}
        previous_diagnostics = record.get("diagnostics")
        previous_diagnostics = previous_diagnostics if isinstance(previous_diagnostics, dict) else {}
        canonical_identity = (
            canonical_diagnostics.get("identity")
            if canonical_diagnostics and isinstance(canonical_diagnostics.get("identity"), dict)
            else {}
        )
        run_id = (
            source.get("run_id")
            or runtime.get("run_id")
            or canonical_identity.get("run_id")
            or previous_diagnostics.get("run_id")
        )
        cause = (
            canonical_error.get("cause")
            if canonical_error.get("cause") is not None
            else None
        )
        lowered = raw_message.casefold()
        if cause is None and "finish_reason" in lowered and "length" in lowered:
            cause = "finish_reason_length"
        elif cause is None and ("context_truncated" in lowered or "input was truncated" in lowered):
            cause = "context_truncated"
        artifact_refs: dict[str, str] = {}
        raw_refs = (
            error.get("artifact_refs")
            or board_task.get("artifact_refs")
            or (board_result or {}).get("artifact_refs")
            or source.get("artifacts")
        )
        if isinstance(raw_refs, dict):
            for key, value in raw_refs.items():
                metadata = value if isinstance(value, dict) else None
                raw_value = metadata.get("path") if metadata else value
                safe_value = self._safe_diagnostic_ref(raw_value)
                if safe_value:
                    artifact_refs[str(key)[:80]] = safe_value
        stage_details = board_task.get("harness_stage_details")
        if not isinstance(stage_details, dict) and canonical_stage_details:
            stage_details = canonical_stage_details
        stage_details = self._safe_diagnostic_stage_details(stage_details)
        if not stage_details or stage_details.get("status") in {None, "pending"}:
            stage_details = {
                "status": "failed",
                "return_code": board_task.get("return_code") or task_error.get("return_code") or previous_diagnostics.get("return_code"),
                "elapsed_seconds": runtime.get("total_elapsed_seconds") or previous_diagnostics.get("elapsed_seconds"),
                "log": None,
                "error": {"code": raw_code, "message": raw_message, "stage": stage},
            }
        return {
            "schema_version": "meeting-diagnostics.v1",
            "meeting_id": record["detail"]["meeting_id"],
            "board_task_id": record.get("board_task_id"),
            "task_kind": record.get("board_task_kind"),
            "stage": stage,
            "product_phase": product_phase_for_board_stage(stage),
            "code": raw_code,
            "message": raw_message,
            "return_code": (
                board_task.get("return_code")
                or task_error.get("return_code")
                or canonical_error.get("return_code")
                or previous_diagnostics.get("return_code")
            ),
            "elapsed_seconds": (
                board_task.get("harness_elapsed_seconds")
                or task_error.get("elapsed_seconds")
                or canonical_error.get("request_elapsed_seconds")
                or runtime.get("total_elapsed_seconds")
                or previous_diagnostics.get("elapsed_seconds")
            ),
            "run_id": str(run_id)[:160] if run_id is not None else None,
            "diagnostic_source": diagnostic_source,
            "cause": cause,
            "finish_reason": canonical_error.get("finish_reason"),
            "context_truncated": canonical_error.get("context_truncated"),
            "request_id": canonical_error.get("request_id"),
            "stage_details": stage_details,
            "artifact_refs": artifact_refs,
            "worker_log_ref": (
                Path(str(
                    task_error.get("worker_log")
                    or board_task.get("worker_log")
                    or previous_diagnostics.get("worker_log_ref")
                )).name
                if task_error.get("worker_log")
                or board_task.get("worker_log")
                or previous_diagnostics.get("worker_log_ref")
                else None
            ),
            "truncated": False,
        }

    def _save_failed_board_result(
        self,
        record: dict[str, Any],
        board_task: dict[str, Any],
        board_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Persist a failed Board snapshot and update product-level failure state."""

        detail = record["detail"]
        diagnostics = self._failed_diagnostics(record, board_task, board_result)
        partial_result: dict[str, Any] | None = None
        if board_result is not None:
            meeting_directory = self.meeting_library.directory_for(record)
            atomic_write_json(meeting_directory / "board_result.json", board_result)
            try:
                partial_result = normalize_harness_result(
                    record["detail"]["meeting_id"],
                    record["detail"].get("language") or "zh-CN",
                    board_result,
                )
                if partial_result.get("availability", {}).get("transcript"):
                    atomic_write_json(meeting_directory / "result.json", partial_result)
            except (OSError, TypeError, ValueError):
                partial_result = None
        atomic_write_json(
            self.meeting_library.directory_for(record) / "diagnostics.json",
            diagnostics,
        )
        atomic_write_json(
            self.meeting_library.directory_for(record) / "error_report.json",
            {
                "schema_version": "meeting-error-report.v1",
                "meeting_id": detail["meeting_id"],
                "generated_at": utc_now(),
                "diagnostics": diagnostics,
            },
        )
        record["diagnostics"] = diagnostics

        source = board_result or {}
        wrapped = source.get("result")
        if isinstance(wrapped, dict):
            source = wrapped
        transcript = source.get("transcript")
        transcript = transcript if isinstance(transcript, dict) else {}
        segments = transcript.get("segments")
        segments = [item for item in segments if isinstance(item, dict)] if isinstance(segments, list) else []
        speaker_ids = {
            str(item.get("speaker_id"))
            for item in segments
            if item.get("speaker_id") is not None
        }
        preserved_audio = detail["file_health"].get("source_audio") == "available"
        preserved_transcript = bool(segments)
        preserved_speakers = bool(speaker_ids)
        if preserved_transcript and partial_result is not None:
            detail["file_health"]["result"] = "partial"
        stage = diagnostics["stage"]
        product_code = "SUMMARY_GENERATION_FAILED" if stage == "llm_summary" else product_board_error_code(
            diagnostics["code"],
            "BOARD_TASK_FAILED",
        )
        product_message = "纪要生成未完成" if stage == "llm_summary" else "RK1828 会议处理失败"
        detail["state"] = "failed"
        detail["phase"] = product_phase_for_board_stage(stage)
        detail["raw_stage"] = stage
        detail["progress"]["percent"] = product_progress_for_board_stage(stage)
        detail["progress"]["estimated_remaining_seconds"] = None
        detail["availability"]["transcript"] = preserved_transcript
        detail["availability"]["speakers"] = preserved_speakers
        detail["availability"]["evidence"] = False
        detail["availability"]["minutes"] = False
        detail["availability"]["chapters"] = False
        detail["availability"]["decisions"] = False
        detail["availability"]["action_items"] = False
        detail["availability"]["formal_version"] = False
        detail["error"] = {
            "code": product_code,
            "message": product_message,
            "phase": detail["phase"],
            "retryable": preserved_audio,
            "retry_scope": "all" if preserved_audio else None,
            "preserved": {
                "audio": preserved_audio,
                "transcript": preserved_transcript,
                "speakers": preserved_speakers,
                "summary": False,
                "formal_version": False,
            },
        }
        detail["capabilities"].update(
            {
                "can_cancel": False,
                "can_retry_all": preserved_audio,
                "can_retry_summary": False,
                "can_edit": False,
                "can_save_draft": False,
                "can_finalize": False,
            }
        )
        return record

    def _fetch_failed_board_result(
        self,
        record: dict[str, Any],
        board_task: dict[str, Any],
    ) -> dict[str, Any]:
        board_result: dict[str, Any] | None = None
        task_id = record.get("board_task_id")
        if isinstance(task_id, str) and task_id:
            try:
                status, payload = self.board_client.request_json(
                    "GET",
                    f"/v1/tasks/{task_id}/result",
                )
                if status < 300:
                    board_result = payload
            except GatewayError:
                board_result = None
        return self._save_failed_board_result(record, board_task, board_result)

    def diagnostics_detail(self, record: dict[str, Any]) -> dict[str, Any]:
        """Return a bounded diagnostic projection only when explicitly requested."""

        detail = copy.deepcopy(record["detail"])
        diagnostics = record.get("diagnostics")
        if isinstance(diagnostics, dict):
            detail["diagnostics"] = copy.deepcopy(diagnostics)
        return detail

    def refresh_product_record(
        self,
        record: dict[str, Any],
        *,
        force_diagnostics: bool = False,
    ) -> dict[str, Any]:
        """Synchronize one product meeting with its Board task on demand."""

        detail = record["detail"]
        result_path = self.meeting_library.directory_for(record) / "result.json"
        if detail["state"] in {"review_ready", "finalized"} and result_path.is_file():
            return record
        if detail["state"] in {"failed", "cancelled", "finalizing", "finalized"} and not force_diagnostics:
            return record

        task_id = record.get("board_task_id")
        if not isinstance(task_id, str) or not task_id:
            return record

        try:
            status, board_task = self.board_client.request_json(
                "GET",
                f"/v1/tasks/{task_id}",
            )
        except GatewayError as exc:
            if exc.code == "board_unreachable":
                raise GatewayError(
                    502,
                    "BOARD_UNREACHABLE",
                    "RK1828 未连接",
                    phase=detail.get("phase"),
                    retryable=True,
                    retry_scope="all",
                    preserved={
                        "audio": detail["file_health"].get("source_audio") == "available",
                        "transcript": detail["availability"].get("transcript", False),
                        "speakers": detail["availability"].get("speakers", False),
                        "summary": detail["availability"].get("minutes", False),
                        "formal_version": detail["availability"].get("formal_version", False),
                    },
                ) from exc
            raise

        original = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if status >= 300:
            # A previously captured failure report is more informative than a
            # later in-memory Board task eviction. Rebuild the product view from
            # the local Board snapshot instead of degrading it to task_missing.
            if status == 404 and isinstance(record.get("diagnostics"), dict):
                local_board_result = read_local_json(
                    self.meeting_library.directory_for(record) / "board_result.json"
                )
                if local_board_result is not None:
                    record = self._save_failed_board_result(record, board_task, local_board_result)
                    try:
                        return self.meeting_library.save(record)
                    except MeetingLibraryError as exc:
                        raise GatewayError(500, "meeting_library_error", str(exc)) from exc
                return record
            board_error = board_task.get("error")
            board_error = board_error if isinstance(board_error, dict) else {}
            code = product_board_error_code(board_error.get("code"), "BOARD_TASK_UNAVAILABLE")
            if status == 404:
                code = "BOARD_TASK_MISSING"
            detail["state"] = "failed"
            detail["phase"] = product_phase_for_board_stage(str(detail.get("raw_stage") or "processing"))
            detail["error"] = {
                "code": code,
                "message": str(board_error.get("message") or "RK1828 任务已不可用"),
                "phase": detail["phase"],
                "retryable": True,
                "retry_scope": "all",
                "preserved": {
                    "audio": detail["file_health"].get("source_audio") == "available",
                    "transcript": False,
                    "speakers": False,
                    "summary": False,
                    "formal_version": False,
                },
            }
            detail["capabilities"]["can_cancel"] = False
            detail["capabilities"]["can_retry_all"] = detail["file_health"].get("source_audio") == "available"
        else:
            record["board_task"] = dict(board_task)
            board_state = str(board_task.get("state") or "processing")
            stage = str(board_task.get("stage") or "processing")
            detail["raw_stage"] = stage
            percent = product_progress_for_board_stage(stage)
            detail["progress"]["percent"] = percent
            total_seconds = detail["progress"].get("estimated_total_seconds")
            if isinstance(total_seconds, int) and total_seconds > 0:
                detail["progress"]["estimated_remaining_seconds"] = max(
                    0,
                    round(total_seconds * (100 - percent) / 100),
                )
            elapsed = board_task.get("harness_elapsed_seconds")
            if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool):
                detail["progress"]["elapsed_seconds"] = max(0, round(float(elapsed)))

            if board_state == "completed" and stage == "meeting_ready":
                record, cached = self._cache_completed_result(record, task_id)
                if not cached:
                    detail["state"] = "processing"
                    detail["phase"] = "synthesizing"
                    detail["progress"]["percent"] = 98
                    detail["progress"]["estimated_remaining_seconds"] = None
            elif board_state == "failed":
                record = self._fetch_failed_board_result(record, board_task)
            elif board_state == "cancelled":
                detail["state"] = "cancelled"
                detail["phase"] = "cancelled"
                detail["progress"]["estimated_remaining_seconds"] = None
                detail["capabilities"]["can_cancel"] = False
            elif board_state in {"created", "uploading"}:
                detail["state"] = "uploading"
                detail["phase"] = "uploading"
                detail["error"] = None
                detail["capabilities"]["can_cancel"] = True
            else:
                detail["state"] = "processing"
                detail["phase"] = product_phase_for_board_stage(stage)
                detail["error"] = None
                detail["capabilities"]["can_cancel"] = True

        updated = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if updated != original:
            try:
                return self.meeting_library.save(record)
            except MeetingLibraryError as exc:
                raise GatewayError(500, "meeting_library_error", str(exc)) from exc
        return record

    def load_product_draft(self, record: dict[str, Any]) -> dict[str, Any]:
        """Read a saved draft or build revision zero from the cached result."""

        directory = self.meeting_library.directory_for(record)
        draft_path = directory / "draft.json"
        saved = read_local_json(draft_path)
        if saved is not None:
            return saved

        result = read_local_json(directory / "result.json")
        if result is None:
            raise GatewayError(
                409,
                "RESULT_NOT_READY",
                "会议结果尚未生成",
                phase=record["detail"].get("phase"),
                retryable=record["detail"]["file_health"].get("source_audio") == "available",
                retry_scope="all",
            )
        raw_revision = result.get("result_revision", 1)
        result_revision = raw_revision if isinstance(raw_revision, int) and not isinstance(raw_revision, bool) else 1
        finalized = record["detail"].get("state") == "finalized"
        return {
            "schema_version": "meeting-draft.v1",
            "meeting_id": record["detail"]["meeting_id"],
            "revision": 0,
            "base_result_revision": result_revision,
            "updated_at": None,
            "dirty": False,
            "content": build_draft_content(
                result,
                record["detail"]["title"],
                finalized=finalized,
            ),
        }

    @staticmethod
    def validate_draft_content(content: Any) -> dict[str, Any]:
        """Validate the stable top-level shape while preserving user edits."""

        if not isinstance(content, dict):
            raise GatewayError(400, "INVALID_DRAFT", "content must be an object")
        expected_types = {
            "title": str,
            "speaker_names": dict,
            "transcript_edits": list,
            "chapters": list,
            "decisions": list,
            "action_items": list,
            "review_marks": dict,
        }
        for key, expected_type in expected_types.items():
            if key not in content or not isinstance(content[key], expected_type):
                raise GatewayError(400, "INVALID_DRAFT", f"content.{key} has an invalid type")
        if content.get("minutes") is not None and not isinstance(content["minutes"], dict):
            raise GatewayError(400, "INVALID_DRAFT", "content.minutes has an invalid type")
        return dict(content)

    def save_product_draft(self, meeting_id: str) -> None:
        """Persist a revisioned product draft and update meeting review metadata."""

        payload = read_json_body(self)
        expected_revision = payload.get("expected_revision")
        base_result_revision = payload.get("base_result_revision")
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise GatewayError(400, "INVALID_DRAFT", "expected_revision must be a non-negative integer")
        if (
            not isinstance(base_result_revision, int)
            or isinstance(base_result_revision, bool)
            or base_result_revision < 1
        ):
            raise GatewayError(400, "INVALID_DRAFT", "base_result_revision must be a positive integer")

        record = self.product_record(meeting_id)
        record = self.refresh_product_record(record)
        detail = record["detail"]
        if detail["state"] != "review_ready" or not detail["capabilities"].get("can_save_draft"):
            raise GatewayError(
                409,
                "INVALID_MEETING_STATE",
                "当前会议不可保存草稿",
                phase=detail.get("phase"),
            )

        current = self.load_product_draft(record)
        current_revision = current.get("revision", 0)
        current_base_revision = current.get("base_result_revision", 1)
        if expected_revision != current_revision:
            raise GatewayError(
                409,
                "DRAFT_REVISION_CONFLICT",
                "草稿已被较新的修改更新",
                details={
                    "expected_revision": expected_revision,
                    "current_revision": current_revision,
                },
            )
        if base_result_revision != current_base_revision:
            raise GatewayError(
                409,
                "DRAFT_RESULT_CONFLICT",
                "会议结果已更新，请重新载入后保存",
                details={
                    "expected_base_result_revision": base_result_revision,
                    "current_base_result_revision": current_base_revision,
                },
            )

        content = self.validate_draft_content(payload.get("content"))
        next_revision = current_revision + 1
        draft = {
            "schema_version": "meeting-draft.v1",
            "meeting_id": meeting_id,
            "revision": next_revision,
            "base_result_revision": current_base_revision,
            "updated_at": utc_now(),
            "dirty": False,
            "content": content,
        }
        atomic_write_json(self.meeting_library.directory_for(record) / "draft.json", draft)

        title = content["title"].strip()
        if title:
            detail["title"] = title[:200]
        review = draft_review_summary(content)
        detail["review"].update(
            {
                "pending_count": review["pending_count"],
                "reviewed_count": review["reviewed_count"],
                "dirty": False,
                "draft_revision": next_revision,
            }
        )
        detail["file_health"]["draft"] = "available"
        saved = self.meeting_library.save(record)
        draft["updated_at"] = saved["detail"]["updated_at"]
        atomic_write_json(self.meeting_library.directory_for(record) / "draft.json", draft)

        send_json(
            self,
            200,
            {
                "meeting_id": meeting_id,
                "revision": next_revision,
                "base_result_revision": current_base_revision,
                "saved_at": draft["updated_at"],
                "review": {
                    **saved["detail"]["review"],
                    "dirty": False,
                },
            },
        )

    def settings_response(self) -> dict[str, Any]:
        return public_settings(self.gateway_settings)

    def save_gateway_settings(self) -> None:
        """Validate and atomically apply the complete product settings payload."""

        payload = read_json_body(self)
        current = self.gateway_settings
        try:
            candidate = normalize_settings(
                payload,
                current=current,
                model_profile=self.gateway_config.model_profile,
            )
        except SettingsValidationError as exc:
            details = {"field": exc.field} if exc.field else None
            raise GatewayError(400, "INVALID_SETTINGS", str(exc), details=details) from exc

        current_path = Path(current["meeting_library_path"]).expanduser().resolve()
        candidate_path = Path(candidate["meeting_library_path"]).expanduser().resolve()
        active_ids = self.active_meeting_ids()
        board_changed = candidate["board"] != current["board"]
        path_changed = candidate_path != current_path
        if active_ids and (board_changed or path_changed):
            raise GatewayError(
                409,
                "SETTINGS_ACTIVE_TASK_CONFLICT",
                "活动会议处理期间不能切换板端或会议库路径",
                details={"active_meeting_ids": sorted(active_ids)},
            )

        storage_check = storage_path_check(str(candidate_path))
        if not storage_check["compatible"]:
            raise GatewayError(
                507,
                "STORAGE_INSUFFICIENT",
                "会议库路径不可写或不可用",
                details={
                    "path": str(candidate_path),
                    "free_bytes": storage_check["free_bytes"],
                    "total_bytes": storage_check["total_bytes"],
                },
            )

        if path_changed:
            current_records = self.meeting_library.list()
            if current_records:
                raise GatewayError(
                    409,
                    "MEETING_LIBRARY_MIGRATION_REQUIRED",
                    "当前会议库包含会议，切换路径前需要先完成迁移",
                    details={
                        "old_path": str(current_path),
                        "new_path": str(candidate_path),
                        "meeting_count": len(current_records),
                    },
                )
            try:
                candidate_library = MeetingLibrary(candidate_path)
            except (OSError, MeetingLibraryError) as exc:
                raise GatewayError(400, "INVALID_STORAGE_PATH", str(exc)) from exc
        else:
            candidate_library = self.meeting_library

        try:
            candidate_client = BoardClient(
                build_board_url(candidate["board"]["address"], candidate["board"]["port"]),
                self.gateway_config.timeout_seconds,
            )
            self.settings_store.save(candidate)
        except (ValueError, OSError, SettingsValidationError) as exc:
            raise GatewayError(400, "SETTINGS_SAVE_FAILED", str(exc)) from exc

        new_config = replace(
            self.gateway_config,
            board_url=build_board_url(candidate["board"]["address"], candidate["board"]["port"]),
            meeting_library_path=candidate_path,
            device_name=candidate["device_name"],
            model_profile=candidate["model_profile"],
            keep_audio_until_finalized=candidate["keep_audio_until_finalized"],
            default_export_formats=tuple(candidate["default_export_formats"]),
            default_language=candidate["default_language"],
        )
        self.server.gateway_config = new_config  # type: ignore[attr-defined]
        self.server.board_client = candidate_client  # type: ignore[attr-defined]
        self.server.meeting_library = candidate_library  # type: ignore[attr-defined]
        self.server.gateway_settings = candidate  # type: ignore[attr-defined]
        send_json(self, 200, public_settings(candidate))

    def retry_product_meeting(self, meeting_id: str) -> None:
        """Restart a failed meeting from its preserved local source audio."""

        payload = read_json_body(self)
        scope = payload.get("scope", "all")
        if scope != "all":
            raise GatewayError(
                409,
                "SUMMARY_RETRY_UNAVAILABLE",
                "当前仅支持从原始音频重新处理",
                phase="synthesizing",
                retryable=True,
                retry_scope="all",
            )
        record = self.product_record(meeting_id)
        detail = record["detail"]
        if detail.get("state") not in {"failed", "cancelled"}:
            raise GatewayError(409, "RETRY_STATE_CONFLICT", "当前会议不允许重新处理", phase=detail.get("phase"))
        source_path = self.meeting_library.directory_for(record) / "source.wav"
        if not source_path.is_file():
            raise GatewayError(
                409,
                "SOURCE_AUDIO_UNAVAILABLE",
                "原始音频不存在，无法重新处理",
                phase="uploading",
                retryable=False,
            )
        expected_size = source_path.stat().st_size
        if expected_size <= 0:
            raise GatewayError(409, "SOURCE_AUDIO_UNAVAILABLE", "原始音频为空，无法重新处理")
        digest = hashlib.sha256()
        with source_path.open("rb") as source:
            while chunk := source.read(UPLOAD_CHUNK_BYTES):
                digest.update(chunk)
        source_sha256 = digest.hexdigest()
        meeting_directory = self.meeting_library.directory_for(record)
        history_directory = meeting_directory / "history"
        history_directory.mkdir(parents=True, exist_ok=True)
        history_stamp = utc_now().replace(":", "").replace("-", "")
        for file_name in ("result.json", "board_result.json", "diagnostics.json", "error_report.json"):
            old_path = meeting_directory / file_name
            if old_path.is_file():
                old_path.replace(history_directory / f"{history_stamp}_{file_name}")
        detail["state"] = "uploading"
        detail["phase"] = "uploading"
        detail["raw_stage"] = "awaiting_audio"
        detail["error"] = None
        detail["availability"] = {
            "transcript": False,
            "speakers": False,
            "minutes": False,
            "chapters": False,
            "decisions": False,
            "action_items": False,
            "evidence": False,
            "formal_version": False,
        }
        detail["file_health"]["result"] = "not_created"
        detail["file_health"]["draft"] = "not_created"
        detail["capabilities"].update(
            {
                "can_cancel": True,
                "can_retry_all": True,
                "can_retry_summary": False,
                "can_edit": False,
                "can_save_draft": False,
                "can_finalize": False,
            }
        )
        with _create_lock:
            status, board_payload = self.board_client.request_json(
                "POST",
                "/v1/tasks",
                {"meeting_id": meeting_id, "task_kind": "harness_meeting_v0"},
            )
            if status >= 300:
                raise GatewayError(
                    status,
                    "BOARD_TASK_CREATE_FAILED",
                    "RK1828 无法创建重试任务",
                    phase="uploading",
                    retryable=True,
                    retry_scope="all",
                    preserved={"audio": True, "transcript": False, "speakers": False, "summary": False, "formal_version": False},
                )
            board_task_id = board_payload.get("task_id")
            if not isinstance(board_task_id, str) or not board_task_id:
                raise GatewayError(502, "INVALID_BOARD_RESPONSE", "重试任务响应缺少 task_id")
            record["board_task_id"] = board_task_id
            record["board_task_kind"] = "harness_meeting_v0"
            record["board_task"] = dict(board_payload)
            record = self.meeting_library.save(record)
            status, uploaded_payload, board_sha256 = self.board_client.stream_file_audio(
                board_task_id,
                source_path,
                expected_size,
                "audio/wav",
                source_sha256,
            )
            if board_sha256 != source_sha256:
                raise GatewayError(502, "INPUT_SHA256_MISMATCH", "重试音频 SHA-256 校验不一致")
            if status >= 300:
                raise GatewayError(502, "BOARD_UPLOAD_FAILED", "RK1828 重试音频上传失败")
            record["board_task"] = dict(uploaded_payload)
        detail = record["detail"]
        detail["state"] = "processing"
        detail["phase"] = "transcribing"
        detail["raw_stage"] = str(record["board_task"].get("stage") or "segmentation")
        detail["progress"]["percent"] = 5
        detail["progress"]["estimated_remaining_seconds"] = detail["progress"].get("estimated_total_seconds")
        saved = self.meeting_library.save(record)
        send_json(
            self,
            202,
            {
                "meeting_id": meeting_id,
                "state": saved["detail"]["state"],
                "phase": saved["detail"]["phase"],
                "retry_scope": "all",
                "result_revision": 1,
                "availability": saved["detail"]["availability"],
            },
        )

    def check_board_connection(self) -> None:
        payload = read_json_body(self)
        try:
            address = validate_board_address(payload.get("address"))
            port = validate_port(payload.get("port"))
            candidate = BoardClient(
                build_board_url(address, port),
                self.gateway_config.timeout_seconds,
            )
        except (SettingsValidationError, ValueError) as exc:
            raise GatewayError(400, "INVALID_BOARD_ADDRESS", str(exc)) from exc

        started = time.monotonic()
        status = "offline"
        board_payload: dict[str, Any] = {}
        try:
            http_status, board_payload = candidate.request_json("GET", "/v1/health")
            if 200 <= http_status < 300 and board_payload.get("status") == "ready":
                status = "online"
        except GatewayError:
            status = "offline"
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        send_json(
            self,
            200,
            {
                "status": status,
                "board_id": board_payload.get("board_id"),
                "protocol_version": board_payload.get("protocol_version"),
                "agent_version": board_payload.get("agent_version"),
                "model_profile": board_payload.get("model_profile"),
                "compatible": status == "online",
                "latency_ms": latency_ms if status == "online" else None,
            },
        )

    def check_storage_connection(self) -> None:
        payload = read_json_body(self)
        try:
            result = storage_path_check(payload.get("path"))
        except SettingsValidationError as exc:
            raise GatewayError(400, "INVALID_STORAGE_PATH", str(exc)) from exc
        send_json(self, 200, result)

    def reveal_system_target(self) -> None:
        payload = read_json_body(self)
        target = payload.get("target")
        target_paths = {
            "meeting_library": self.meeting_library.root,
            "gateway_scripts": Path(__file__).resolve().parent,
        }
        if target not in target_paths:
            raise GatewayError(400, "INVALID_REVEAL_TARGET", "target is not allowed")
        target_path = target_paths[target]
        try:
            target_path.mkdir(parents=True, exist_ok=True)
            if hasattr(os, "startfile"):
                os.startfile(str(target_path))  # type: ignore[attr-defined]
                opened = True
            else:
                opened = False
        except OSError as exc:
            raise GatewayError(500, "REVEAL_FAILED", str(exc)) from exc
        send_json(self, 200, {"opened": opened, "target": target})

    def log_message(self, format_string: str, *args: object) -> None:
        """Write compact UTC access logs without exposing request bodies."""

        print(
            "[%s] %s %s"
            % (
                utc_now(),
                self.address_string(),
                format_string % args,
            ),
            flush=True,
        )

    def _handle_expected_error(self, error: GatewayError) -> None:
        safe_send_gateway_error(self, error)

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight for explicitly allowed local UI origins."""

        self.send_response(204)
        send_cors_headers(self)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Idempotency-Key, X-File-Name, X-File-SHA256, X-Request-ID",
        )
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def do_GET(self) -> None:
        try:
            self._do_get()
        except GatewayError as exc:
            self._handle_expected_error(exc)
        except Exception as exc:
            print("[%s] unexpected GET error: %r" % (utc_now(), exc), flush=True)
            self._handle_expected_error(GatewayError(500, "gateway_internal_error", str(exc)))

    def _do_get(self) -> None:
        path = urlsplit(self.path).path

        if path in {"/", "/app"}:
            serve_ui(self)
            return

        if path == "/api/info":
            send_json(self, 200, gateway_info(self.gateway_config))
            return

        if path == "/api/settings":
            send_json(self, 200, self.settings_response())
            return

        if path == "/api/storage":
            summary = summarize_storage(self.meeting_library.root)
            summary["updated_at"] = utc_now()
            send_json(self, 200, summary)
            return

        if path == "/api/storage/meetings":
            params = parse_qs(urlsplit(self.path).query)
            sort = params.get("sort", ["audio_size_desc"])[0]
            if sort not in {"audio_size_desc", "title_asc", "meeting_date_desc"}:
                raise GatewayError(400, "INVALID_STORAGE_SORT", "storage sort is invalid")
            try:
                page = int(params.get("page", ["1"])[0])
                page_size = int(params.get("page_size", ["30"])[0])
            except ValueError as exc:
                raise GatewayError(400, "INVALID_STORAGE_PAGE", "page and page_size must be integers") from exc
            records = self.meeting_library.list()
            send_json(
                self,
                200,
                storage_meetings(
                    records,
                    self.meeting_library.root,
                    active_meeting_ids=self.active_meeting_ids(),
                    sort=sort,
                    page=page,
                    page_size=page_size,
                ),
            )
            return

        if path == "/api/system/status":
            usage = shutil.disk_usage(self.meeting_library.root)
            library_writable = os.access(self.meeting_library.root, os.W_OK)
            board_status = "offline"
            board_payload: dict[str, Any] = {}
            try:
                board_http_status, board_payload = self.board_client.request_json("GET", "/v1/health")
                if 200 <= board_http_status < 300 and board_payload.get("status") == "ready":
                    board_status = "online"
            except GatewayError:
                board_status = "offline"
            board_url = urlsplit(self.gateway_config.board_url)
            board_port = board_url.port or (443 if board_url.scheme == "https" else 80)
            active_task_id = board_payload.get("active_task_id")
            active_meeting_id = None
            if isinstance(active_task_id, str) and active_task_id:
                for record in self.meeting_library.list():
                    if record.get("board_task_id") == active_task_id:
                        active_meeting_id = record["detail"].get("meeting_id")
                        break
            send_json(
                self,
                200,
                {
                    "gateway": {"status": "ready", "version": GATEWAY_VERSION},
                    "meeting_library": {
                        "status": "available" if library_writable else "unavailable",
                        "path": str(self.meeting_library.root),
                        "writable": library_writable,
                    },
                    "storage": {
                        "status": "ok" if library_writable else "unavailable",
                        "free_bytes": usage.free,
                        "required_bytes_for_new_meeting": 0,
                    },
                    "board": {
                        "status": board_status,
                        "board_id": board_payload.get("board_id"),
                        "address": board_url.hostname,
                        "port": board_port,
                        "busy": bool(board_payload.get("busy", False)),
                        "active_meeting_id": active_meeting_id,
                        "model_profile": board_payload.get("model_profile"),
                    },
                    "capabilities": {
                        "can_create_meeting": library_writable,
                        "can_process_audio": board_status == "online" and GATEWAY_CAPABILITIES["local_upload"],
                        "can_start_board_recording": False,
                        "can_view_library": True,
                    },
                    "timestamp": utc_now(),
                },
            )
            return

        if path == "/api/board/health":
            status, board_payload = self.board_client.request_json("GET", "/v1/health")
            if status >= 200 and status < 300:
                response = dict(board_payload)
                response["gateway"] = {
                    "service": SERVICE_NAME,
                    "version": GATEWAY_VERSION,
                    "local_only": True,
                }
                send_json(self, status, response)
            else:
                send_json(self, status, board_payload)
            return

        if path == "/api/meetings":
            params = parse_qs(urlsplit(self.path).query)
            query = params.get("q", [""])[0]
            status_filter = params.get("status", ["all"])[0]
            sort = params.get("sort", ["updated_desc"])[0]
            if status_filter not in {"all", "processing", "failed", "review", "confirmed", "deleted"}:
                raise GatewayError(400, "invalid_status", "status filter is invalid")
            if sort not in {"updated_desc", "created_desc", "title_asc"}:
                raise GatewayError(400, "invalid_sort", "sort is invalid")
            records = self.meeting_library.list(query=query, status=status_filter, sort=sort)
            items = [detail_to_list_item(record["detail"]) for record in records]
            send_json(
                self,
                200,
                {
                    "items": items,
                    "page": 1,
                    "page_size": 30,
                    "total": len(items),
                    "has_more": False,
                    "facets": self.meeting_library.facets(),
                },
            )
            return

        draft_match = re.fullmatch(r"/api/meetings/([^/]+)/draft", path)
        if draft_match is not None:
            meeting_id = validate_meeting_id(unquote(draft_match.group(1)))
            record = self.product_record(meeting_id)
            record = self.refresh_product_record(record)
            send_json(self, 200, self.load_product_draft(record))
            return

        result_match = re.fullmatch(r"/api/meetings/([^/]+)/result", path)
        if result_match is not None:
            params = parse_qs(urlsplit(self.path).query)
            include_diagnostics = params.get("include", [None])[0] == "diagnostics"
            meeting_id = validate_meeting_id(unquote(result_match.group(1)))
            try:
                record = self.meeting_library.get(meeting_id)
            except MeetingLibraryError:
                record = None
            if record is not None:
                result_path = self.meeting_library.directory_for(record) / "result.json"
                local_result = read_local_json(result_path)
                if local_result is not None:
                    local_result = dict(local_result)
                    if include_diagnostics:
                        diagnostic_snapshot = read_local_json(
                            self.meeting_library.directory_for(record) / "diagnostics.json"
                        )
                        if diagnostic_snapshot is not None:
                            local_result["diagnostics"] = diagnostic_snapshot
                    else:
                        local_result["diagnostics"] = None
                    send_json(self, 200, local_result)
                    return

                record = self.refresh_product_record(
                    record,
                    force_diagnostics=include_diagnostics,
                )
                local_result = read_local_json(result_path)
                if local_result is not None:
                    local_result = dict(local_result)
                    if include_diagnostics:
                        diagnostic_snapshot = read_local_json(
                            self.meeting_library.directory_for(record) / "diagnostics.json"
                        )
                        if diagnostic_snapshot is not None:
                            local_result["diagnostics"] = diagnostic_snapshot
                    else:
                        local_result["diagnostics"] = None
                    send_json(self, 200, local_result)
                    return

                detail = record["detail"]
                code = "RESULT_NOT_READY" if detail["state"] in {"created", "uploading", "processing"} else "RESULT_MISSING"
                status = 409 if code == "RESULT_NOT_READY" else 404
                send_error_json(
                    self,
                    status,
                    code,
                    "会议结果尚未生成" if code == "RESULT_NOT_READY" else "会议结果不存在",
                    phase=detail.get("phase"),
                    retryable=detail["file_health"]["source_audio"] == "available",
                    retry_scope="all",
                    preserved=detail.get("error", {}).get("preserved") if isinstance(detail.get("error"), dict) else None,
                    details=record.get("diagnostics") if include_diagnostics else None,
                )
                return

            legacy_record = get_meeting(meeting_id)
            status, result_payload = self.board_client.request_json(
                "GET",
                f"/v1/tasks/{legacy_record['board_task_id']}/result",
            )
            send_json(self, status, result_payload)
            return

        meeting_match = re.fullmatch(r"/api/meetings/([^/]+)", path)
        if meeting_match is not None:
            params = parse_qs(urlsplit(self.path).query)
            include_diagnostics = params.get("include", [None])[0] == "diagnostics"
            meeting_id = validate_meeting_id(unquote(meeting_match.group(1)))
            try:
                record = self.meeting_library.get(meeting_id)
            except MeetingLibraryError:
                record = None
            if record is not None:
                record = self.refresh_product_record(
                    record,
                    force_diagnostics=include_diagnostics,
                )
                send_json(
                    self,
                    200,
                    self.diagnostics_detail(record) if include_diagnostics else record["detail"],
                )
                return

            legacy_record = get_meeting(meeting_id)
            status, board_payload = self.board_client.request_json(
                "GET",
                f"/v1/tasks/{legacy_record['board_task_id']}",
            )
            if 200 <= status < 300:
                update_meeting(board_payload)
                legacy_record = get_meeting(meeting_id)
                send_json(self, status, meeting_response(legacy_record, board_payload))
            else:
                send_json(self, status, board_payload)
            return

        send_error_json(self, 404, "not_found", "endpoint was not found")

    def do_POST(self) -> None:
        try:
            self._do_post()
        except GatewayError as exc:
            self._handle_expected_error(exc)
        except Exception as exc:
            print("[%s] unexpected POST error: %r" % (utc_now(), exc), flush=True)
            self._handle_expected_error(GatewayError(500, "gateway_internal_error", str(exc)))

    def _do_post(self) -> None:
        global _current_meeting

        path = urlsplit(self.path).path

        if path == "/api/settings/board/check":
            self.check_board_connection()
            return
        if path == "/api/settings/storage/check":
            self.check_storage_connection()
            return
        if path == "/api/storage/cleanup-temp":
            payload = read_json_body(self)
            categories = payload.get("categories", ["temp"])
            if categories != ["temp"]:
                raise GatewayError(400, "INVALID_CLEANUP_CATEGORY", "only the temp category can be cleaned")
            cleaned = cleanup_temporary_files(
                self.meeting_library.root,
                active_meeting_ids=self.active_meeting_ids(),
            )
            summary = summarize_storage(self.meeting_library.root)
            send_json(
                self,
                200,
                {
                    **cleaned,
                    "storage": {
                        "free_bytes": summary["free_bytes"],
                        "status": summary["status"],
                    },
                },
            )
            return
        if path == "/api/system/reveal":
            self.reveal_system_target()
            return

        retry_match = re.fullmatch(r"/api/meetings/([^/]+)/retry", path)
        if retry_match is not None:
            meeting_id = validate_meeting_id(unquote(retry_match.group(1)))
            self.retry_product_meeting(meeting_id)
            return

        rescan_match = re.fullmatch(r"/api/meetings/([^/]+)/rescan", path)
        if rescan_match is not None:
            meeting_id = validate_meeting_id(unquote(rescan_match.group(1)))
            record = self.product_record(meeting_id)
            record = self.refresh_product_record(record, force_diagnostics=True)
            send_json(
                self,
                200,
                {
                    "meeting_id": meeting_id,
                    "file_health": record["detail"]["file_health"],
                    "capabilities": record["detail"]["capabilities"],
                    "scanned_at": utc_now(),
                },
            )
            return

        cancel_match = re.fullmatch(r"/api/meetings/([^/]+)/cancel", path)
        if cancel_match is not None:
            meeting_id = validate_meeting_id(unquote(cancel_match.group(1)))
            try:
                record = self.meeting_library.get(meeting_id)
            except MeetingLibraryError:
                record = None
            if record is not None:
                detail = record["detail"]
                task_id = record.get("board_task_id")
                if isinstance(task_id, str) and task_id:
                    status, board_payload = self.board_client.request_json(
                        "POST",
                        f"/v1/tasks/{task_id}/cancel",
                        {},
                    )
                    if status >= 300:
                        send_json(self, status, board_payload)
                        return
                    record["board_task"] = board_payload
                detail["state"] = "cancelled"
                detail["phase"] = "cancelled"
                detail["raw_stage"] = "cancelled"
                detail["capabilities"]["can_cancel"] = False
                detail["progress"]["estimated_remaining_seconds"] = None
                saved = self.meeting_library.save(record)
                send_json(self, 200, saved["detail"])
                return

            legacy_record = get_meeting(meeting_id)
            status, board_payload = self.board_client.request_json(
                "POST",
                f"/v1/tasks/{legacy_record['board_task_id']}/cancel",
                {},
            )
            if 200 <= status < 300:
                update_meeting(board_payload)
                legacy_record = get_meeting(meeting_id)
                send_json(self, status, meeting_response(legacy_record, board_payload))
            else:
                send_json(self, status, board_payload)
            return

        if path != "/api/meetings":
            send_error_json(self, 404, "not_found", "endpoint was not found")
            return

        payload = read_json_body(self)
        if "source_type" in payload or "title" in payload:
            request = parse_create_meeting_payload(payload)
            try:
                record = self.meeting_library.create(**request)
            except MeetingLibraryError as exc:
                status = 409 if "already exists" in str(exc) else 500
                code = "meeting_already_exists" if status == 409 else "meeting_library_error"
                raise GatewayError(status, code, str(exc)) from exc
            send_json(self, 201, product_created_response(record["detail"]))
            return

        task_kind = payload.get("task_kind", "audio_upload_probe")
        if not isinstance(task_kind, str) or task_kind not in SUPPORTED_TASK_KINDS:
            raise GatewayError(
                400,
                "unsupported_task_kind",
                "supported task kinds are audio_upload_probe, transport_probe and harness_meeting_v0",
            )

        requested_meeting_id = payload.get("meeting_id")
        meeting_id = make_meeting_id() if requested_meeting_id is None else validate_meeting_id(requested_meeting_id)

        # Serialize create requests because the board itself has one in-memory
        # task slot.  A completed prior mapping can be replaced by a new one.
        with _create_lock:
            current = current_meeting_snapshot()
            if current is not None:
                current_state = current["board_task"].get("state")
                if current_state not in TERMINAL_STATES:
                    raise GatewayError(
                        409,
                        "meeting_already_active",
                        "only one active meeting is supported",
                    )

            status, board_payload = self.board_client.request_json(
                "POST",
                "/v1/tasks",
                {
                    "meeting_id": meeting_id,
                    "task_kind": task_kind,
                },
            )
            if status >= 300:
                send_json(self, status, board_payload)
                return

            board_task_id = board_payload.get("task_id")
            if not isinstance(board_task_id, str) or not board_task_id:
                raise GatewayError(
                    502,
                    "invalid_board_response",
                    "board task creation response did not contain task_id",
                )

            now = utc_now()
            with _meeting_lock:
                _current_meeting = {
                    "meeting_id": meeting_id,
                    "board_task_id": board_task_id,
                    "task_kind": task_kind,
                    "created_at": now,
                    "updated_at": now,
                    "board_task": dict(board_payload),
                }
                record = dict(_current_meeting)
                record["board_task"] = dict(board_payload)

        send_json(self, status, meeting_response(record, board_payload))

    def do_DELETE(self) -> None:
        try:
            path_parts = urlsplit(self.path)
            match = re.fullmatch(r"/api/meetings/([^/]+)", path_parts.path)
            if match is None:
                send_error_json(self, 404, "not_found", "endpoint was not found")
                return
            params = parse_qs(path_parts.query)
            if params.get("mode", [None])[0] != "index_only":
                send_error_json(self, 400, "invalid_delete_mode", "only mode=index_only is supported")
                return
            meeting_id = validate_meeting_id(unquote(match.group(1)))
            try:
                self.meeting_library.remove_index(meeting_id)
            except MeetingLibraryError as exc:
                raise GatewayError(404, "meeting_not_found", str(exc)) from exc
            send_json(
                self,
                200,
                {
                    "meeting_id": meeting_id,
                    "removed_from_library": True,
                    "files_deleted": False,
                    "files_retained": True,
                },
            )
        except GatewayError as exc:
            self._handle_expected_error(exc)
        except Exception as exc:
            print("[%s] unexpected DELETE error: %r" % (utc_now(), exc), flush=True)
            self._handle_expected_error(GatewayError(500, "gateway_internal_error", str(exc)))

    def do_PUT(self) -> None:
        try:
            self._do_put()
        except GatewayError as exc:
            self._handle_expected_error(exc)
        except Exception as exc:
            print("[%s] unexpected PUT error: %r" % (utc_now(), exc), flush=True)
            self._handle_expected_error(GatewayError(500, "gateway_internal_error", str(exc)))

    def _do_product_put(self, meeting_id: str, record: dict[str, Any]) -> None:
        """Persist a product upload locally, then send the local file to RK1828."""

        expected_size, content_type, supplied_sha256 = parse_audio_headers(
            self,
            self.gateway_config.max_upload_bytes,
        )
        detail = record["detail"]
        if detail["state"] in {
            "recording",
            "uploading",
            "processing",
            "review_ready",
            "finalizing",
            "finalized",
        }:
            raise GatewayError(
                409,
                "meeting_upload_conflict",
                "会议当前不允许重新上传音频",
                phase=detail.get("phase"),
            )

        source_path = self.meeting_library.directory_for(record) / "source.wav"
        detail["state"] = "uploading"
        detail["phase"] = "uploading"
        detail["raw_stage"] = "uploading"
        detail["error"] = None
        detail["audio"]["state"] = "uploading"
        detail["audio"]["size_bytes"] = expected_size
        detail["file_health"]["source_audio"] = "partial"
        detail["source"]["size_bytes"] = expected_size
        detail["source"]["mime_type"] = content_type
        detail["source"]["requires_conversion"] = False
        header_name = self.headers.get("X-File-Name")
        if header_name:
            detail["source"]["original_name"] = unquote(header_name)
            detail["source"]["original_extension"] = Path(
                detail["source"]["original_name"]
            ).suffix.lower().lstrip(".") or "wav"
        record = self.meeting_library.save(record)

        self.close_connection = True
        try:
            actual_sha256 = save_upload_to_path(
                self,
                source_path,
                expected_size,
                supplied_sha256,
            )
        except GatewayError as exc:
            preserved_audio = source_path.is_file()
            failure = product_upload_error(
                record,
                status=exc.status,
                code=exc.code,
                message=exc.message,
                phase=exc.phase or "uploading",
                retryable=exc.retryable,
                retry_scope=exc.retry_scope or "upload",
                preserved_audio=preserved_audio,
            )
            if preserved_audio:
                record["detail"]["audio"]["size_bytes"] = source_path.stat().st_size
            try:
                self.meeting_library.save(record)
            except MeetingLibraryError:
                pass
            raise failure

        detail = record["detail"]
        detail["source"]["sha256"] = actual_sha256
        detail["audio"]["state"] = "available"
        detail["audio"]["size_bytes"] = expected_size
        detail["file_health"]["source_audio"] = "available"
        record = self.meeting_library.save(record)

        try:
            with _create_lock:
                status, board_payload = self.board_client.request_json(
                    "POST",
                    "/v1/tasks",
                    {
                        "meeting_id": meeting_id,
                        "task_kind": "harness_meeting_v0",
                    },
                )
                if status >= 300:
                    board_error = board_payload.get("error", {})
                    code = str(board_error.get("code") or "BOARD_TASK_CREATE_FAILED")
                    if code.islower():
                        code = "BOARD_" + code.upper()
                    message = str(board_error.get("message") or "RK1828 无法创建处理任务")
                    raise product_upload_error(
                        record,
                        status=status,
                        code=code,
                        message=message,
                        preserved_audio=True,
                    )

                board_task_id = board_payload.get("task_id")
                if not isinstance(board_task_id, str) or not board_task_id:
                    raise product_upload_error(
                        record,
                        status=502,
                        code="invalid_board_response",
                        message="board task creation response did not contain task_id",
                        retry_scope="all",
                        preserved_audio=True,
                    )

                record["board_task_id"] = board_task_id
                record["board_task_kind"] = "harness_meeting_v0"
                record["board_task"] = dict(board_payload)
                detail = record["detail"]
                detail["raw_stage"] = "awaiting_audio"
                record = self.meeting_library.save(record)

                status, board_payload, board_sha256 = self.board_client.stream_file_audio(
                    board_task_id,
                    source_path,
                    expected_size,
                    content_type,
                    actual_sha256,
                )
                if board_sha256 != actual_sha256:
                    raise product_upload_error(
                        record,
                        status=502,
                        code="input_sha256_mismatch",
                        message="本地音频 SHA-256 校验不一致",
                        preserved_audio=True,
                    )
                if status >= 300:
                    board_error = board_payload.get("error", {})
                    code = str(board_error.get("code") or "BOARD_UPLOAD_FAILED")
                    if code.islower():
                        code = "BOARD_" + code.upper()
                    message = str(board_error.get("message") or "RK1828 音频上传失败")
                    raise product_upload_error(
                        record,
                        status=status,
                        code=code,
                        message=message,
                        preserved_audio=True,
                    )
        except GatewayError as exc:
            if exc.code == "board_unreachable":
                failure = product_upload_error(
                    record,
                    status=502,
                    code="BOARD_UNREACHABLE",
                    message="RK1828 未连接",
                    phase="uploading",
                    retryable=True,
                    retry_scope="all",
                    preserved_audio=True,
                )
            elif exc.code in {"BOARD_UNREACHABLE", "BOARD_UPLOAD_FAILED", "BOARD_TASK_CREATE_FAILED"}:
                failure = exc
            else:
                failure = product_upload_error(
                    record,
                    status=exc.status,
                    code=exc.code,
                    message=exc.message,
                    phase=exc.phase or "uploading",
                    retryable=exc.retryable,
                    retry_scope=exc.retry_scope or "all",
                    preserved_audio=True,
                )
            try:
                self.meeting_library.save(record)
            except MeetingLibraryError:
                pass
            raise failure

        detail = record["detail"]
        detail["state"] = "processing"
        detail["phase"] = "transcribing"
        detail["raw_stage"] = str(board_payload.get("stage") or "segmentation")
        detail["progress"]["percent"] = 5
        detail["progress"]["estimated"] = True
        detail["error"] = None
        detail["capabilities"]["can_cancel"] = True
        detail["capabilities"]["can_retry_all"] = True
        record["board_task"] = dict(board_payload)
        record = self.meeting_library.save(record)
        send_json(self, 202, record["detail"])

    def _do_put(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/settings":
            self.save_gateway_settings()
            return

        draft_match = re.fullmatch(r"/api/meetings/([^/]+)/draft", path)
        if draft_match is not None:
            meeting_id = validate_meeting_id(unquote(draft_match.group(1)))
            self.save_product_draft(meeting_id)
            return

        audio_match = re.fullmatch(r"/api/meetings/([^/]+)/audio", path)
        if audio_match is None:
            send_error_json(self, 404, "not_found", "endpoint was not found")
            return

        meeting_id = validate_meeting_id(unquote(audio_match.group(1)))
        try:
            product_record = self.meeting_library.get(meeting_id)
        except MeetingLibraryError:
            product_record = None
        if product_record is not None:
            self._do_product_put(meeting_id, product_record)
            return

        # Preserve the previously validated probe endpoint for callers that
        # create a board task directly instead of using the product meeting API.
        record = get_meeting(meeting_id)
        expected_size, content_type, supplied_sha256 = parse_audio_headers(
            self,
            self.gateway_config.max_upload_bytes,
        )
        self.close_connection = True
        status, board_payload, actual_sha256 = self.board_client.stream_audio(
            record["board_task_id"],
            self,
            expected_size,
            content_type,
            supplied_sha256,
        )
        if supplied_sha256 is not None and actual_sha256 != supplied_sha256:
            if 200 <= status < 300:
                raise GatewayError(
                    422,
                    "input_sha256_mismatch",
                    "uploaded file SHA-256 does not match X-File-SHA256",
                )

        if 200 <= status < 300:
            update_meeting(board_payload)
            record = get_meeting(meeting_id)
            send_json(self, status, meeting_response(record, board_payload))
        else:
            send_json(self, status, board_payload)


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    """Allow quick development restarts and isolate requests in threads."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        gateway_config: GatewayConfig,
        board_client: BoardClient,
        meeting_library: MeetingLibrary,
        settings_store: SettingsStore,
        gateway_settings: dict[str, Any],
    ) -> None:
        super().__init__(server_address, handler_class)
        self.gateway_config = gateway_config
        self.board_client = board_client
        self.meeting_library = meeting_library
        self.settings_store = settings_store
        self.gateway_settings = gateway_settings


# ---------------------------------------------------------------------------
# Command-line entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local PC Gateway for the Meeting Agent board API",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Local bind host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Local bind port")
    parser.add_argument("--board-url", default=DEFAULT_BOARD_URL, help="Board Agent base URL")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        dest="timeout_seconds",
        help="Board request timeout in seconds",
    )
    parser.add_argument(
        "--max-upload-bytes",
        type=int,
        default=DEFAULT_MAX_UPLOAD_BYTES,
        help="Maximum Gateway upload size",
    )
    parser.add_argument(
        "--meeting-library-path",
        type=Path,
        default=DEFAULT_MEETING_LIBRARY_PATH,
        help="Local meeting library directory",
    )
    parser.add_argument(
        "--allowed-origin",
        action="append",
        dest="allowed_origins",
        help="Allowed browser origin; repeat for multiple origins",
    )
    parser.add_argument(
        "--settings-path",
        type=Path,
        default=DEFAULT_SETTINGS_PATH,
        help="Persistent Gateway settings file",
    )
    return parser.parse_args(argv)


def validate_config(args: argparse.Namespace) -> GatewayConfig:
    if args.port < 1 or args.port > 65535:
        raise ValueError("port must be between 1 and 65535")
    if args.timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    if args.max_upload_bytes <= 0:
        raise ValueError("max-upload-bytes must be positive")
    if not isinstance(args.meeting_library_path, Path):
        raise ValueError("meeting-library-path must be a filesystem path")

    allowed_origins = tuple(args.allowed_origins or DEFAULT_ALLOWED_ORIGINS)
    for origin in allowed_origins:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"invalid allowed browser origin: {origin}")

    return GatewayConfig(
        host=args.host,
        port=args.port,
        board_url=args.board_url,
        timeout_seconds=args.timeout_seconds,
        max_upload_bytes=args.max_upload_bytes,
        meeting_library_path=args.meeting_library_path,
        allowed_origins=allowed_origins,
        settings_path=args.settings_path,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = validate_config(args)
        settings_store = SettingsStore(config.settings_path, config.meeting_library_path)
        gateway_settings, warning = settings_store.load()
        if warning:
            print(warning, flush=True)
        settings_path = Path(gateway_settings["meeting_library_path"]).expanduser().resolve()
        board_url = build_board_url(
            gateway_settings["board"]["address"],
            gateway_settings["board"]["port"],
        )
        config = replace(
            config,
            board_url=board_url,
            meeting_library_path=settings_path,
            device_name=gateway_settings["device_name"],
            model_profile=gateway_settings["model_profile"],
            keep_audio_until_finalized=gateway_settings["keep_audio_until_finalized"],
            default_export_formats=tuple(gateway_settings["default_export_formats"]),
            default_language=gateway_settings["default_language"],
        )
        board_client = BoardClient(config.board_url, config.timeout_seconds)
        meeting_library = MeetingLibrary(config.meeting_library_path)
    except (ValueError, OSError, MeetingLibraryError, SettingsValidationError) as exc:
        print(f"configuration error: {exc}")
        return 2

    server = ReusableThreadingHTTPServer(
        (config.host, config.port),
        GatewayRequestHandler,
        config,
        board_client,
        meeting_library,
        settings_store,
        gateway_settings,
    )
    print(
        "%s listening on %s:%s board=%s version=%s"
        % (
            SERVICE_NAME,
            config.host,
            config.port,
            config.board_url,
            GATEWAY_VERSION,
        ),
        flush=True,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("meeting-agent-gateway stopping", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

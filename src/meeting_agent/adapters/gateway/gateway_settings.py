"""Persistent product settings and safe local-path validation for the Gateway."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import time
from pathlib import Path
from typing import Any


SETTINGS_SCHEMA_VERSION = "gateway-settings.v1"
DEFAULT_DEVICE_NAME = "会议室 RK1828"
DEFAULT_MODEL_PROFILE = "qwen3-4b-v104-ctx16k"
DEFAULT_EXPORT_FORMATS = ("html", "txt", "json")
DEFAULT_LANGUAGE = "zh-CN"
_PACKAGE_ROOT = Path(__file__).resolve()
# src/meeting_agent/adapters/gateway/<file> -> repository root is parents[4].
# Keep a safe cwd fallback for wheel/zip deployments where the source tree is absent.
_PROJECT_ROOT = _PACKAGE_ROOT.parents[4] if len(_PACKAGE_ROOT.parents) > 4 else Path.cwd()
DEFAULT_MEETING_LIBRARY_PATH = _PROJECT_ROOT / "runtime" / "meeting_library"
DEFAULT_SETTINGS_PATH = _PROJECT_ROOT / "runtime" / "gateway_settings.json"
SUPPORTED_EXPORT_FORMATS = set(DEFAULT_EXPORT_FORMATS)
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")


class SettingsValidationError(ValueError):
    """A user-provided setting failed validation."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def default_settings(meeting_library_path: Path) -> dict[str, Any]:
    """Return the v1 defaults without reading or creating any files."""

    path = Path(meeting_library_path).expanduser().resolve()
    return {
        "device_name": DEFAULT_DEVICE_NAME,
        "board": {
            "address": "10.10.22.36",
            "port": 18080,
        },
        "model_profile": DEFAULT_MODEL_PROFILE,
        "meeting_library_path": str(path),
        "keep_audio_until_finalized": True,
        "default_export_formats": list(DEFAULT_EXPORT_FORMATS),
        "default_language": DEFAULT_LANGUAGE,
    }


def build_board_url(address: str, port: int) -> str:
    """Build an HTTP Board Agent URL, including IPv6 bracket notation."""

    host = address.strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}"


def validate_board_address(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SettingsValidationError("board.address must be a non-empty string", field="board.address")
    address = value.strip()
    if len(address) > 253 or any(character.isspace() for character in address):
        raise SettingsValidationError("board.address is invalid", field="board.address")
    try:
        ipaddress.ip_address(address.strip("[]"))
        return address.strip("[]")
    except ValueError:
        pass
    if address.lower() == "localhost" or HOST_RE.fullmatch(address) is not None:
        return address
    raise SettingsValidationError("board.address is invalid", field="board.address")


def validate_port(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise SettingsValidationError("board.port must be between 1 and 65535", field="board.port")
    return value


def validate_storage_path(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise SettingsValidationError(
            "meeting_library_path must be a non-empty string",
            field="meeting_library_path",
        )
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise SettingsValidationError(
            "meeting_library_path must be an absolute path",
            field="meeting_library_path",
        )
    return path.resolve()


def _validate_export_formats(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise SettingsValidationError(
            "default_export_formats must contain at least one format",
            field="default_export_formats",
        )
    formats: list[str] = []
    for item in value:
        if not isinstance(item, str) or item not in SUPPORTED_EXPORT_FORMATS:
            raise SettingsValidationError(
                "default_export_formats contains an unsupported format",
                field="default_export_formats",
            )
        if item not in formats:
            formats.append(item)
    return formats


def normalize_settings(
    payload: dict[str, Any],
    *,
    current: dict[str, Any],
    model_profile: str = DEFAULT_MODEL_PROFILE,
) -> dict[str, Any]:
    """Validate a complete PUT payload and return its canonical JSON shape."""

    if not isinstance(payload, dict):
        raise SettingsValidationError("settings body must be an object")
    board = payload.get("board")
    if not isinstance(board, dict):
        raise SettingsValidationError("board must be an object", field="board")

    device_name = payload.get("device_name")
    if not isinstance(device_name, str) or not device_name.strip():
        raise SettingsValidationError("device_name must be a non-empty string", field="device_name")
    if len(device_name.strip()) > 120:
        raise SettingsValidationError("device_name must be at most 120 characters", field="device_name")

    address = validate_board_address(board.get("address"))
    port = validate_port(board.get("port"))
    meeting_library_path = validate_storage_path(payload.get("meeting_library_path"))

    keep_audio = payload.get("keep_audio_until_finalized")
    if not isinstance(keep_audio, bool):
        raise SettingsValidationError(
            "keep_audio_until_finalized must be a boolean",
            field="keep_audio_until_finalized",
        )

    export_formats = _validate_export_formats(payload.get("default_export_formats"))
    language = payload.get("default_language")
    if not isinstance(language, str) or not language.strip() or len(language.strip()) > 32:
        raise SettingsValidationError(
            "default_language must be a non-empty string of at most 32 characters",
            field="default_language",
        )

    # model_profile is a derived/read-only setting in v1.  Never accept a client
    # supplied value that could silently select a different Board model.
    effective_model_profile = str(current.get("model_profile") or model_profile)
    return {
        "device_name": device_name.strip(),
        "board": {"address": address, "port": port},
        "model_profile": effective_model_profile,
        "meeting_library_path": str(meeting_library_path),
        "keep_audio_until_finalized": keep_audio,
        "default_export_formats": export_formats,
        "default_language": language.strip(),
    }


def public_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Return the frontend contract with the derived Board base URL."""

    board = settings["board"]
    return {
        **settings,
        "board": {
            "address": board["address"],
            "port": board["port"],
            "base_url": build_board_url(board["address"], board["port"]),
        },
        "default_export_formats": list(settings["default_export_formats"]),
    }


def _nearest_existing_parent(path: Path) -> Path | None:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate if candidate.exists() else None


def storage_path_check(path_value: Any) -> dict[str, Any]:
    """Check a candidate directory without requiring it to exist already."""

    path = validate_storage_path(path_value)
    exists = path.exists()
    if exists and not path.is_dir():
        return {
            "exists": True,
            "writable": False,
            "total_bytes": 0,
            "free_bytes": 0,
            "compatible": False,
        }

    parent = path if exists else _nearest_existing_parent(path)
    if parent is None:
        return {
            "exists": False,
            "writable": False,
            "total_bytes": 0,
            "free_bytes": 0,
            "compatible": False,
        }
    try:
        usage = shutil.disk_usage(parent)
    except OSError:
        usage = None
    writable = os.access(parent, os.W_OK)
    if exists:
        writable = writable and os.access(path, os.W_OK)
    return {
        "exists": exists,
        "writable": writable,
        "total_bytes": usage.total if usage else 0,
        "free_bytes": usage.free if usage else 0,
        "compatible": bool(writable and usage),
    }


class SettingsStore:
    """Versioned, atomic JSON persistence for Gateway product settings."""

    def __init__(self, path: Path, default_library_path: Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.default_library_path = Path(default_library_path).expanduser().resolve()

    def load(self) -> tuple[dict[str, Any], str | None]:
        """Load settings, falling back to defaults for absent/corrupt files."""

        defaults = default_settings(self.default_library_path)
        if not self.path.is_file():
            return defaults, None
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(envelope, dict):
                raise ValueError("settings file must be an object")
            saved = envelope.get("settings")
            if not isinstance(saved, dict):
                raise ValueError("settings file is missing settings")
            normalized = normalize_settings(
                saved,
                current=defaults,
                model_profile=DEFAULT_MODEL_PROFILE,
            )
            return normalized, None
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return defaults, f"settings file ignored: {exc}"

    def save(self, settings: dict[str, Any]) -> None:
        """Atomically replace the settings file after validating its shape."""

        normalized = normalize_settings(
            settings,
            current=settings,
            model_profile=str(settings.get("model_profile") or DEFAULT_MODEL_PROFILE),
        )
        envelope = {
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "updated_at": utc_now(),
            "settings": normalized,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        raw = (json.dumps(envelope, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
        temporary.replace(self.path)


def resolve_hostname(address: str) -> str | None:
    """Resolve a Board hostname for a lightweight compatibility check."""

    try:
        return socket.gethostbyname(address)
    except (OSError, socket.gaierror):
        return None

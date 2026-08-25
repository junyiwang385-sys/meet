#!/usr/bin/env python3
"""PC-side FunASR ASR server for Meeting Agent prototyping.

This server is intentionally separate from the RK1828 board path. It borrows
FunASR's offline VAD + punctuation + CAM++ diarization pipeline to prototype a
one-shot upload API that returns timestamps, anonymous speaker labels, and a
Meeting-Agent-friendly transcript.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SERVICE_NAME = "meeting-agent-funasr-pc-asr"
SUPPORTED_EXTENSIONS = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg"}
SUPPORTED_RESPONSE_FORMATS = {"json", "verbose_json"}
DEFAULT_WORK_DIR = Path(tempfile.gettempdir()) / "meeting_agent_funasr_uploads"


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8008
    device: str = "cpu"
    model: str = "paraformer-zh"
    vad_model: str = "fsmn-vad"
    punc_model: str = "ct-punc"
    spk_model: str = "cam++"
    vad_max_single_segment_time: int = 60000
    batch_size_s: int = 300
    max_upload_mb: int = 500
    max_concurrency: int = 1
    work_dir: Path = DEFAULT_WORK_DIR
    keep_uploads: bool = False
    disable_update: bool = True


@dataclass(frozen=True)
class RequestOptions:
    model: str
    language: str
    response_format: str
    enable_spk: bool
    include_raw: bool
    merge_turns: bool


class ApiError(Exception):
    def __init__(self, status_code: int, error_type: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.message = message


class ModelLoadError(RuntimeError):
    pass


class InferenceError(RuntimeError):
    pass


def error_payload(error_type: str, message: str) -> Dict[str, Dict[str, str]]:
    return {"error": {"type": error_type, "message": message}}


def str_to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def safe_round(value: Optional[float], ndigits: int = 3) -> Optional[float]:
    if value is None:
        return None
    if not math.isfinite(value):
        return None
    return round(value, ndigits)


def ms_to_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return safe_round(numeric / 1000.0)


def first_present(mapping: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def extract_sentence_text(item: Dict[str, Any]) -> str:
    value = first_present(item, ("text", "sentence", "raw_text", "transcript"))
    if value is None:
        return ""
    return str(value).strip()


def extract_sentence_start_end(item: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    start_raw = first_present(item, ("start", "begin", "start_time", "start_ms"))
    end_raw = first_present(item, ("end", "stop", "end_time", "end_ms"))
    return ms_to_seconds(start_raw), ms_to_seconds(end_raw)


def extract_source_speaker(item: Dict[str, Any]) -> Optional[str]:
    value = first_present(item, ("spk", "speaker", "speaker_id", "source_speaker"))
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def normalize_timestamp_pairs(value: Any) -> Optional[List[List[Optional[float]]]]:
    if not isinstance(value, list):
        return None

    normalized: List[List[Optional[float]]] = []
    for entry in value:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        start = ms_to_seconds(entry[0])
        end = ms_to_seconds(entry[1])
        normalized.append([start, end])
    return normalized or None


def normalize_speaker_token(source_speaker: str, speaker_map: Dict[str, str]) -> str:
    if source_speaker not in speaker_map:
        speaker_map[source_speaker] = f"speaker_{len(speaker_map) + 1}"
    return speaker_map[source_speaker]


def build_speaker_summaries(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_speaker: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    for segment in segments:
        speaker = segment.get("speaker") or "speaker_1"
        if speaker not in by_speaker:
            by_speaker[speaker] = {
                "id": speaker,
                "source_speaker": segment.get("source_speaker"),
                "segment_count": 0,
                "total_duration": 0.0,
            }
            order.append(speaker)

        summary = by_speaker[speaker]
        summary["segment_count"] += 1
        if summary.get("source_speaker") is None and segment.get("source_speaker") is not None:
            summary["source_speaker"] = segment.get("source_speaker")

        start = segment.get("start")
        end = segment.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
            summary["total_duration"] += end - start

    speakers = []
    for speaker in order:
        item = dict(by_speaker[speaker])
        item["total_duration"] = safe_round(float(item["total_duration"])) or 0.0
        speakers.append(item)
    return speakers


def normalize_segments(raw: Dict[str, Any], enable_spk: bool, warnings: List[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    sentence_info = raw.get("sentence_info")
    segments: List[Dict[str, Any]] = []
    speaker_map: Dict[str, str] = {}
    missing_timestamps = False
    missing_speaker = False

    if isinstance(sentence_info, list) and sentence_info:
        for item in sentence_info:
            if not isinstance(item, dict):
                continue
            text = extract_sentence_text(item)
            if not text:
                continue
            start, end = extract_sentence_start_end(item)
            if start is None or end is None:
                missing_timestamps = True

            source_speaker = extract_source_speaker(item)
            if source_speaker is None:
                missing_speaker = True
                source_speaker = "__speaker_fallback__"
            speaker = normalize_speaker_token(source_speaker, speaker_map)

            segment: Dict[str, Any] = {
                "id": len(segments) + 1,
                "start": start,
                "end": end,
                "text": text,
                "speaker": speaker,
                "source_speaker": None if source_speaker == "__speaker_fallback__" else source_speaker,
            }

            item_timestamps = normalize_timestamp_pairs(item.get("timestamp") or item.get("timestamps"))
            if item_timestamps is not None:
                segment["timestamps"] = item_timestamps

            segments.append(segment)
    else:
        text = str(raw.get("text") or "").strip()
        if text:
            missing_timestamps = True
            if enable_spk:
                missing_speaker = True
            segments.append(
                {
                    "id": 1,
                    "start": None,
                    "end": None,
                    "text": text,
                    "speaker": "speaker_1",
                    "source_speaker": None,
                }
            )
        warnings.append("missing_sentence_info")

    if missing_timestamps:
        warnings.append("missing_or_partial_sentence_timestamps")
    if missing_speaker:
        warnings.append("speaker_fallback")

    speakers = build_speaker_summaries(segments)
    return segments, speakers


def can_merge_turn(previous: Dict[str, Any], current: Dict[str, Any], max_gap_s: float) -> bool:
    if previous.get("speaker") != current.get("speaker"):
        return False
    prev_end = previous.get("end")
    cur_start = current.get("start")
    if prev_end is None or cur_start is None:
        return True
    if not isinstance(prev_end, (int, float)) or not isinstance(cur_start, (int, float)):
        return True
    return cur_start - prev_end <= max_gap_s


def build_turns(segments: List[Dict[str, Any]], max_gap_s: float = 1.0) -> List[Dict[str, Any]]:
    turns: List[Dict[str, Any]] = []
    for segment in segments:
        if not segment.get("text"):
            continue
        if turns and can_merge_turn(turns[-1], segment, max_gap_s):
            turns[-1]["text"] = (turns[-1]["text"].rstrip() + segment["text"].lstrip()).strip()
            if segment.get("end") is not None:
                turns[-1]["end"] = segment.get("end")
            continue
        turns.append(
            {
                "id": len(turns) + 1,
                "start": segment.get("start"),
                "end": segment.get("end"),
                "speaker": segment.get("speaker") or "speaker_1",
                "text": segment.get("text") or "",
            }
        )
    return turns


def format_time(seconds: Optional[float]) -> str:
    if seconds is None:
        return "??:??:??"
    if not isinstance(seconds, (int, float)) or not math.isfinite(float(seconds)):
        return "??:??:??"
    total = max(0, int(round(float(seconds))))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_meeting_transcript(turns: List[Dict[str, Any]]) -> str:
    lines = []
    for turn in turns:
        start = format_time(turn.get("start"))
        end = format_time(turn.get("end"))
        lines.append(f"[{start}-{end}] {turn.get('speaker') or 'speaker_1'}: {turn.get('text') or ''}".rstrip())
    return "\n".join(lines)


def get_audio_duration_seconds(audio_path: Path) -> Optional[float]:
    try:
        import soundfile as sf  # type: ignore

        info = sf.info(str(audio_path))
        if info.samplerate <= 0:
            return None
        return safe_round(float(info.frames) / float(info.samplerate))
    except Exception:
        return None


def sanitize_for_json(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(key): sanitize_for_json(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_for_json(item, depth + 1) for item in value]
    if hasattr(value, "tolist"):
        try:
            return sanitize_for_json(value.tolist(), depth + 1)
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return sanitize_for_json(value.item(), depth + 1)
        except Exception:
            pass
    return str(value)


def normalize_funasr_result(
    raw: Dict[str, Any],
    request: RequestOptions,
    duration: Optional[float],
    processing_time: float,
) -> Dict[str, Any]:
    warnings: List[str] = []
    text = str(raw.get("text") or "").strip()
    segments, speakers = normalize_segments(raw, request.enable_spk, warnings)
    if not text and segments:
        text = "".join(segment["text"] for segment in segments).strip()

    timestamps = normalize_timestamp_pairs(raw.get("timestamp") or raw.get("timestamps"))
    if timestamps is None and not any("timestamps" in segment for segment in segments):
        warnings.append("missing_word_or_char_timestamps")

    turns = build_turns(segments) if request.merge_turns else []
    meeting_transcript = format_meeting_transcript(turns if turns else segments)
    rtf = safe_round(processing_time / duration) if duration and duration > 0 else None

    response: Dict[str, Any] = {
        "task": "transcribe",
        "language": request.language,
        "duration": duration,
        "text": text,
        "segments": segments,
        "speakers": speakers,
        "turns": turns,
        "meeting_transcript": meeting_transcript,
        "processing_time": safe_round(processing_time),
        "rtf": rtf,
        "warnings": sorted(set(warnings)),
    }
    if timestamps is not None:
        response["timestamps"] = timestamps
    return response


class FunASRMeetingService:
    def __init__(self, config: ServerConfig):
        self.config = config
        self._models: Dict[Tuple[str, bool], Any] = {}
        self._model_lock = threading.Lock()
        self._semaphore = asyncio.Semaphore(max(1, config.max_concurrency))

    def model_loaded(self) -> bool:
        return bool(self._models)

    def get_model(self, model_name: str, enable_spk: bool) -> Any:
        key = (model_name, enable_spk)
        with self._model_lock:
            if key in self._models:
                return self._models[key]
            try:
                from funasr import AutoModel  # type: ignore
            except Exception as exc:
                raise ModelLoadError(
                    "funasr is not available. Install dependencies from scripts/requirements-funasr-pc.txt"
                ) from exc

            kwargs: Dict[str, Any] = {
                "model": model_name,
                "vad_model": self.config.vad_model,
                "vad_kwargs": {"max_single_segment_time": self.config.vad_max_single_segment_time},
                "punc_model": self.config.punc_model,
                "device": self.config.device,
                "disable_update": self.config.disable_update,
            }
            if enable_spk:
                kwargs["spk_model"] = self.config.spk_model

            try:
                model = AutoModel(**kwargs)
            except Exception as exc:
                raise ModelLoadError(f"failed to load FunASR model {model_name!r}: {exc}") from exc

            self._models[key] = model
            return model

    async def transcribe(self, audio_path: Path, request: RequestOptions) -> Tuple[Dict[str, Any], float]:
        async with self._semaphore:
            return await asyncio.to_thread(self._transcribe_sync, audio_path, request)

    def _transcribe_sync(self, audio_path: Path, request: RequestOptions) -> Tuple[Dict[str, Any], float]:
        model = self.get_model(request.model, request.enable_spk)
        started = time.perf_counter()
        try:
            result = model.generate(
                input=str(audio_path),
                batch_size_s=self.config.batch_size_s,
                sentence_timestamp=True,
                language=request.language,
            )
        except Exception as exc:
            raise InferenceError(f"FunASR inference failed: {exc}") from exc
        elapsed = time.perf_counter() - started

        if isinstance(result, list) and result:
            raw = result[0]
        elif isinstance(result, dict):
            raw = result
        else:
            raise InferenceError(f"FunASR returned unsupported result type: {type(result).__name__}")
        if not isinstance(raw, dict):
            raise InferenceError(f"FunASR result item is not an object: {type(raw).__name__}")
        return raw, elapsed


async def save_upload_to_temp(upload: Any, config: ServerConfig) -> Path:
    original_name = upload.filename or "audio"
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ApiError(400, "invalid_request_error", f"Unsupported audio extension: {suffix or '<none>'}. Supported: {supported}")

    config.work_dir.mkdir(parents=True, exist_ok=True)
    temp_path = config.work_dir / f"{uuid.uuid4().hex}{suffix}"
    max_bytes = config.max_upload_mb * 1024 * 1024
    total = 0

    try:
        with temp_path.open("wb") as out_file:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ApiError(413, "request_too_large", f"Uploaded file exceeds {config.max_upload_mb} MB")
                out_file.write(chunk)
    except ApiError:
        try:
            temp_path.unlink(missing_ok=True)
        except TypeError:
            if temp_path.exists():
                temp_path.unlink()
        raise
    except Exception as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except TypeError:
            if temp_path.exists():
                temp_path.unlink()
        raise ApiError(500, "upload_error", f"Failed to save upload: {exc}") from exc
    finally:
        await upload.close()

    if total == 0:
        try:
            temp_path.unlink(missing_ok=True)
        except TypeError:
            if temp_path.exists():
                temp_path.unlink()
        raise ApiError(400, "invalid_request_error", "Uploaded file is empty")
    return temp_path


def remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except TypeError:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def create_app(config: ServerConfig) -> Any:
    try:
        from fastapi import FastAPI, File, Form, UploadFile  # type: ignore
        from fastapi.responses import JSONResponse  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "fastapi/python-multipart are not available. Install dependencies from scripts/requirements-funasr-pc.txt"
        ) from exc

    app = FastAPI(title="Meeting Agent FunASR PC ASR Server", version="0.1.0")
    service = FunASRMeetingService(config)

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Any, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=error_payload(exc.error_type, exc.message))

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "device": config.device,
            "model": config.model,
            "vad_model": config.vad_model,
            "punc_model": config.punc_model,
            "spk_model": config.spk_model,
            "model_loaded": service.model_loaded(),
            "max_concurrency": config.max_concurrency,
        }

    @app.post("/v1/audio/transcriptions")
    async def transcribe_endpoint(
        file: UploadFile = File(...),
        model: str = Form(default=""),
        language: str = Form(default="zh"),
        response_format: str = Form(default="verbose_json"),
        spk: bool = Form(default=True),
        include_raw: bool = Form(default=False),
        merge_turns: bool = Form(default=True),
    ) -> JSONResponse:
        response_format = (response_format or "verbose_json").strip().lower()
        if response_format not in SUPPORTED_RESPONSE_FORMATS:
            supported = ", ".join(sorted(SUPPORTED_RESPONSE_FORMATS))
            raise ApiError(400, "invalid_request_error", f"Unsupported response_format: {response_format!r}. Supported: {supported}")

        request = RequestOptions(
            model=(model or config.model).strip() or config.model,
            language=(language or "zh").strip() or "zh",
            response_format=response_format,
            enable_spk=bool(spk),
            include_raw=bool(include_raw),
            merge_turns=bool(merge_turns),
        )

        audio_path = await save_upload_to_temp(file, config)
        try:
            duration = get_audio_duration_seconds(audio_path)
            raw, processing_time = await service.transcribe(audio_path, request)
            normalized = normalize_funasr_result(raw, request, duration, processing_time)
            if request.response_format == "json":
                return JSONResponse(content={"text": normalized["text"]})
            if request.include_raw:
                normalized["raw"] = sanitize_for_json(raw)
            return JSONResponse(content=sanitize_for_json(normalized))
        except ModelLoadError as exc:
            raise ApiError(503, "model_load_error", str(exc)) from exc
        except InferenceError as exc:
            raise ApiError(500, "inference_error", str(exc)) from exc
        finally:
            if not config.keep_uploads:
                remove_file(audio_path)

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PC-side FunASR server for one-shot meeting ASR with timestamps and speaker labels.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=8008, help="Port to bind")
    parser.add_argument("--device", default="cpu", help="FunASR device, for example cpu or cuda:0")
    parser.add_argument("--model", default="paraformer-zh", help="FunASR ASR model name or local path")
    parser.add_argument("--vad-model", default="fsmn-vad", help="FunASR VAD model name or local path")
    parser.add_argument("--punc-model", default="ct-punc", help="FunASR punctuation model name or local path")
    parser.add_argument("--spk-model", default="cam++", help="FunASR speaker model name or local path")
    parser.add_argument("--vad-max-single-segment-time", type=int, default=60000, help="Max VAD segment length in ms")
    parser.add_argument("--batch-size-s", type=int, default=300, help="FunASR batch_size_s value")
    parser.add_argument("--max-upload-mb", type=int, default=500, help="Maximum upload size in MB")
    parser.add_argument("--max-concurrency", type=int, default=1, help="Maximum concurrent FunASR inference calls")
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR, help="Temporary upload directory")
    parser.add_argument("--keep-uploads", action="store_true", help="Keep uploaded temp files for debugging")
    parser.add_argument("--allow-update", action="store_true", help="Allow FunASR/model hub update checks")
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> ServerConfig:
    return ServerConfig(
        host=args.host,
        port=args.port,
        device=args.device,
        model=args.model,
        vad_model=args.vad_model,
        punc_model=args.punc_model,
        spk_model=args.spk_model,
        vad_max_single_segment_time=args.vad_max_single_segment_time,
        batch_size_s=args.batch_size_s,
        max_upload_mb=args.max_upload_mb,
        max_concurrency=args.max_concurrency,
        work_dir=args.work_dir,
        keep_uploads=args.keep_uploads,
        disable_update=not args.allow_update,
    )


def main() -> int:
    args = parse_args()
    config = config_from_args(args)
    try:
        import uvicorn  # type: ignore
    except Exception as exc:
        print("uvicorn is not available. Install dependencies from scripts/requirements-funasr-pc.txt")
        print(str(exc))
        return 2

    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

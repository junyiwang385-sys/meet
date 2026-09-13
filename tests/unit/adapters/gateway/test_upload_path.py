import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from meeting_agent.adapters.gateway.meeting_agent_gateway_v0 import (
    DEFAULT_MAX_UPLOAD_BYTES,
    GatewayError,
    parse_audio_headers,
    save_upload_to_path,
)


class _Handler:
    """最小 handler 替身：只提供 parse_audio_headers / save_upload_to_path 用到的
    headers（dict.get）与 rfile（可读流）。"""

    def __init__(self, headers, body=b""):
        self.headers = dict(headers)
        self.rfile = io.BytesIO(body)
        self.close_connection = False


class ParseAudioHeadersTests(unittest.TestCase):
    def _err(self, headers):
        with self.assertRaises(GatewayError) as ctx:
            parse_audio_headers(_Handler(headers), DEFAULT_MAX_UPLOAD_BYTES)
        return ctx.exception

    def test_missing_content_length_411(self):
        self.assertEqual(self._err({}).status, 411)

    def test_invalid_content_length_400(self):
        self.assertEqual(self._err({"Content-Length": "abc"}).status, 400)

    def test_nonpositive_content_length_400(self):
        self.assertEqual(self._err({"Content-Length": "0"}).status, 400)

    def test_too_large_413(self):
        e = self._err({"Content-Length": str(DEFAULT_MAX_UPLOAD_BYTES + 1),
                       "Content-Type": "audio/wav"})
        self.assertEqual(e.status, 413)

    def test_unsupported_content_type_415(self):
        e = self._err({"Content-Length": "100", "Content-Type": "video/mp4"})
        self.assertEqual(e.status, 415)

    def test_audio_wave_rejected_415_regression(self):
        # Windows 常把 .wav 报成 audio/wave（非 audio/wav）→ 服务端 415。
        # 这是那个"415→前端误报本地服务未链接"的根因；前端已改发 audio/wav 绕开，
        # 此用例把服务端接受集钉死：audio/wave 仍被拒（改接受集时会红，提醒同步）。
        e = self._err({"Content-Length": "100", "Content-Type": "audio/wave"})
        self.assertEqual(e.status, 415)
        self.assertEqual(e.code, "unsupported_content_type")

    def test_accepted_types(self):
        for ct in ("audio/wav", "audio/x-wav", "application/octet-stream"):
            size, content_type, sha = parse_audio_headers(
                _Handler({"Content-Length": "100", "Content-Type": ct}),
                DEFAULT_MAX_UPLOAD_BYTES,
            )
            self.assertEqual((size, content_type, sha), (100, ct, None))

    def test_content_type_with_charset_param(self):
        size, ct, _ = parse_audio_headers(
            _Handler({"Content-Length": "10", "Content-Type": "audio/wav; charset=utf-8"}),
            DEFAULT_MAX_UPLOAD_BYTES,
        )
        self.assertEqual(ct, "audio/wav")

    def test_valid_sha256_returned(self):
        digest = "a" * 64
        _, _, sha = parse_audio_headers(
            _Handler({"Content-Length": "10", "Content-Type": "audio/wav", "X-File-SHA256": digest}),
            DEFAULT_MAX_UPLOAD_BYTES,
        )
        self.assertEqual(sha, digest)

    def test_invalid_sha256_400(self):
        e = self._err({"Content-Length": "10", "Content-Type": "audio/wav", "X-File-SHA256": "xyz"})
        self.assertEqual(e.status, 400)


class SaveUploadToPathTests(unittest.TestCase):
    def test_writes_file_and_returns_sha(self):
        body = "会议音频占位".encode("utf-8")
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "sub" / "source.wav"
            sha = save_upload_to_path(_Handler({}, body), target, len(body), None)
            self.assertEqual(sha, hashlib.sha256(body).hexdigest())
            self.assertEqual(target.read_bytes(), body)  # 目录自动创建 + 内容一致

    def test_sha_mismatch_422(self):
        body = b"hello world"
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "source.wav"
            with self.assertRaises(GatewayError) as ctx:
                save_upload_to_path(_Handler({}, body), target, len(body), "0" * 64)
            self.assertEqual(ctx.exception.status, 422)
            self.assertEqual(ctx.exception.code, "input_sha256_mismatch")

    def test_short_body_interrupted(self):
        body = b"abc"
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "source.wav"
            with self.assertRaises(GatewayError) as ctx:
                save_upload_to_path(_Handler({}, body), target, 100, None)  # 声称 100，实到 3
            self.assertEqual(ctx.exception.code, "UPLOAD_INTERRUPTED")


if __name__ == "__main__":
    unittest.main()

"""PC 上的 LLM 后端适配层：用本地 Ollama 顶替板端 rkllm3-server。

板端 `RkllmServerSession` 会启动 rkllm 二进制并 POST 到 /v1/chat/completions。
PC 上没有该二进制，但 rkllm-server 与 Ollama 都实现了 **OpenAI 兼容**的
`/v1/chat/completions`，所以本适配层只需：
    - 不启动子进程（假定 Ollama 已在跑）；
    - 把请求指向 Ollama 的 OpenAI 兼容端点，payload 里带上具体模型名。

它与 `RkllmServerSession` **鸭子类型对齐**：同样的 `request(messages, request_dir, ...)`
签名与返回 dict、同样写出 messages/request/response/final_json 等产物文件、同样暴露
files/request_count 等属性，因此 `product_summary` 无需改动即可换用本后端。

用途：在 PC 上用真 stage 代码（segment_blocks + minutes/overview map-reduce）复现
板端摘要流程，模型换成 qwen3:4b（GGUF），验证逻辑而非板端复现。
"""

from __future__ import annotations

import json
import pathlib
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..storage.artifacts import atomic_write_json, atomic_write_text
from .llm import LlmRunError, split_assistant_output


@dataclass
class OllamaConfig:
    model: str = "qwen3:4b"
    host: str = "127.0.0.1"
    port: int = 11434
    temperature: float = 0.0
    max_tokens: int = 1024
    request_timeout: float = 180.0
    # Ollama OpenAI 兼容端点对 response_format 支持有限；默认走 json_object 软约束，
    # 具体 JSON 形状由 prompt 指定（与板端一致）。
    use_json_object: bool = True


class OllamaSession:
    """与 RkllmServerSession 接口对齐的 PC 后端（Ollama /v1/chat/completions）。"""

    def __init__(self, config: OllamaConfig, out_dir: pathlib.Path, sampler: Any = None) -> None:
        self.config = config
        self.out_dir = pathlib.Path(out_dir)
        self.sampler = sampler
        # 与板端对齐的属性（product_summary 会读取）。
        self.files: dict[str, str] = {"model": config.model}
        self.request_count = 0
        self.transport_request_count = 0
        self.http_response_count = 0
        self.response_parse_success_count = 0
        self.successful_response_count = 0
        self.ready_seconds = 0.0
        # product_summary 结束时会读取这几个计数器写进报告；与板端对齐置 0。
        self.retry_count = 0
        self.split_count = 0
        self.validation_failed_count = 0
        self._started = False
        self.process = None  # 无子进程，占位以兼容读取

    def start(self) -> None:
        """幂等"就绪"：无服务器要拉起，ping 一下 Ollama 确认在跑（对齐 RkllmServerSession.start）。"""
        if self._started:
            return
        try:
            urllib.request.urlopen(
                f"http://{self.config.host}:{self.config.port}/api/tags", timeout=5
            ).close()
        except Exception as exc:  # noqa: BLE001
            raise LlmRunError(
                f"Ollama 未就绪（{self.config.host}:{self.config.port}）：先启动 `ollama serve`"
            ) from exc
        self._started = True

    # 上下文管理：委托给 start()。
    def __enter__(self) -> "OllamaSession":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def request(
        self,
        messages: list[dict[str, str]],
        request_dir: pathlib.Path,
        *,
        max_tokens: int | None = None,
        phase: str = "llm_summary",
        request_id: str = "request",
        request_kind: str = "unknown",
        attempt: int = 1,
        estimated_prompt_tokens: int | None = None,
        run_log: Any | None = None,
    ) -> dict[str, Any]:
        request_dir = pathlib.Path(request_dir)
        request_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
        }
        if self.config.use_json_object:
            payload["response_format"] = {"type": "json_object"}
        atomic_write_json(request_dir / "messages.json", messages)
        atomic_write_json(request_dir / "request.json", payload)
        if self.sampler is not None:
            self.sampler.set_phase(phase)

        # 走 Ollama 原生 /api/chat：可用 think=false 关掉 qwen3 思考（OpenAI /v1 端点关不掉，
        # qwen3 会只吐 <think> 无正文）。payload 转成原生格式。
        native = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": max_tokens or self.config.max_tokens,
            },
        }
        if self.config.use_json_object:
            native["format"] = "json"
        started = time.time()
        data = json.dumps(native, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"http://{self.config.host}:{self.config.port}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        self.request_count += 1
        self.transport_request_count += 1
        try:
            with urllib.request.urlopen(req, timeout=self.config.request_timeout) as handle:
                self.http_response_count += 1
                raw_http = handle.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raw_http = exc.read().decode("utf-8", "replace")
            atomic_write_text(request_dir / "response_http.txt", raw_http)
            raise LlmRunError(f"Ollama HTTP error: {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LlmRunError(f"Ollama HTTP request failed: {exc}") from exc

        elapsed = round(time.time() - started, 3)
        atomic_write_text(request_dir / "response_http.txt", raw_http)
        try:
            response = json.loads(raw_http)
        except json.JSONDecodeError as exc:
            raise LlmRunError(f"Ollama body is not valid JSON: {exc}") from exc
        if not isinstance(response, dict):
            raise LlmRunError("Ollama response must be a JSON object")
        atomic_write_json(request_dir / "response.json", response)

        # 原生 /api/chat 返回 {"message":{"role","content",...}, ...}（无 choices 包裹）。
        message = response.get("message")
        if not isinstance(message, dict):
            raise LlmRunError("Ollama response has no message object")
        # done_reason 有时缺失；非流式响应 done=true 即正常收尾，兜底成 "stop"
        # （对齐板端 OpenAI 风格 finish_reason，校验器要求非空）。
        done_reason = response.get("done_reason")
        if not done_reason:
            done_reason = "stop" if response.get("done") else "length"
        choice = {"finish_reason": done_reason}

        split = split_assistant_output(message)
        self.response_parse_success_count += 1
        atomic_write_text(request_dir / "raw_content.txt", split["raw_content"])
        atomic_write_text(request_dir / "response_content.txt", split["raw_content"])
        atomic_write_text(request_dir / "thinking.txt", split["thinking"])
        atomic_write_text(request_dir / "final_json.txt", split["final_content"])
        atomic_write_text(request_dir / "response_summary_content.txt", split["final_content"])
        self.successful_response_count += 1

        result = {
            "status": "ok",
            "request_id": request_id,
            "content": split["final_content"],
            "thinking": split["thinking"],
            "thinking_source": split["thinking_source"],
            "finish_reason": choice.get("finish_reason"),
            "usage": response.get("usage"),
            "timings": response.get("timings"),
            "request_elapsed_seconds": elapsed,
            "server_ready_seconds": self.ready_seconds,
            "resolved_model_files": self.files,
            "server_pid": None,
            "context_truncated": False,
        }
        atomic_write_json(
            request_dir / "status.json",
            {k: v for k, v in result.items() if k not in {"content", "thinking"}},
        )
        return result

    def close(self) -> None:
        return None

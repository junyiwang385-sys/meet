"""本地 Ollama 裁判(接入 DeepEval)—— 无 key、不出网。

Ollama 提供 OpenAI 兼容端点(http://localhost:11434/v1),同一个 openai SDK 指过去即可,
api_key 传占位串。封装成 DeepEval 的 DeepEvalBaseLLM,供 GEval 等 LLM-as-judge 指标当裁判。

设计意图(对齐 eval/评测线规划.md §0):裁判**全流程本地、不出网**,和项目隐私叙事一致;
默认裁判 = 本地 Ollama(L2 趋势 / CI),无需任何 key。云千问(qwen_judge)降为可选。

裁判模型 JUDGE_MODEL 环境变量可配,默认 qwen3:8b(比被评的 4B 强,缓解"4B 裁 4B");
本机 4060 8G 可全进显存。模型需先 `ollama pull qwen3:8b`。
"""
from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

from deepeval.models.base_model import DeepEvalBaseLLM

DEFAULT_BASE = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "qwen3:8b"


class OllamaJudge(DeepEvalBaseLLM):
    def __init__(self, model: str | None = None, base_url: str = DEFAULT_BASE) -> None:
        self.model = model or os.environ.get("JUDGE_MODEL", DEFAULT_MODEL)
        # Ollama 的 OpenAI 兼容端点不校验 key,传占位串即可(无 key、不出网)。
        self._client = OpenAI(api_key="ollama", base_url=base_url, timeout=600.0)

    def load_model(self) -> "OllamaJudge":
        return self

    def _chat(self, prompt: str, json_mode: bool) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        r = self._client.chat.completions.create(**kwargs)
        return r.choices[0].message.content or ""

    def generate(self, prompt: str, schema: Any = None, **_: Any) -> Any:
        """有 schema(pydantic 类)→ JSON 模式取回并校验;否则返回纯文本。
        兜底:截第一个平衡 JSON 再校验(与 qwen_judge 一致)。"""
        if schema is not None:
            text = self._chat(prompt, json_mode=True)
            try:
                return schema.model_validate_json(text)
            except Exception:
                import json as _j
                s = text.find("{")
                if s >= 0:
                    depth = 0
                    for i in range(s, len(text)):
                        if text[i] == "{":
                            depth += 1
                        elif text[i] == "}":
                            depth -= 1
                            if depth == 0:
                                return schema.model_validate(_j.loads(text[s : i + 1]))
                raise
        return self._chat(prompt, json_mode=False)

    async def a_generate(self, prompt: str, schema: Any = None, **_: Any) -> Any:
        return self.generate(prompt, schema)

    def get_model_name(self) -> str:
        return f"ollama/{self.model}"

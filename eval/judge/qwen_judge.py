"""通义千问裁判(接入 DeepEval)。

千问走 DashScope 的 OpenAI 兼容端点,用 openai SDK 指过去即可。
封装成 DeepEval 的 DeepEvalBaseLLM,供 GEval 等 LLM-as-judge 指标当裁判。

Key 从环境变量 DASHSCOPE_API_KEY 读,**不硬编码进代码**(避免泄漏/提交)。
运行前:  set DASHSCOPE_API_KEY=sk-...   (PowerShell: $env:DASHSCOPE_API_KEY="sk-...")

裁判用云端强模型(qwen3.8-max),比被评的端侧 4B 大 → 判定可靠(解决 4B 裁 4B 的问题)。
评测跑在 PC/CI,不上板端,联网当裁判不影响端侧离线部署。
"""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

from deepeval.models.base_model import DeepEvalBaseLLM

DEFAULT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.8-max"


class QwenJudge(DeepEvalBaseLLM):
    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE) -> None:
        key = os.environ.get("DASHSCOPE_API_KEY")
        if not key:
            raise RuntimeError("缺 DASHSCOPE_API_KEY 环境变量(千问裁判需要)")
        self.model = model
        self._client = OpenAI(api_key=key, base_url=base_url, timeout=300.0)

    def load_model(self) -> "QwenJudge":
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
        """DeepEval 会在需要结构化输出时传 schema(pydantic 类)。
        有 schema → JSON 模式取回并校验成该 schema 实例;否则返回纯文本。"""
        if schema is not None:
            text = self._chat(prompt, json_mode=True)
            try:
                return schema.model_validate_json(text)
            except Exception:
                # 兜底:截第一个平衡 JSON 再校验
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
        return self.model

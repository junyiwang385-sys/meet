"""评测裁判层。QwenJudge 把通义千问(DashScope OpenAI 兼容端点)接入 DeepEval。"""
from .qwen_judge import QwenJudge

__all__ = ["QwenJudge"]

"""G-Eval 质量指标(LLM-as-judge,裁判=千问 qwen3.8-max)。

借鉴业界 G-Eval 方法(用自然语言写评判标准 + 裁判带思维链打分),
针对"会议纪要"场景定制标准。裁判须比被评的端侧 4B 大 → 判定可靠。
"""

from __future__ import annotations

from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams as P


def faithfulness(judge, threshold: float = 0.8) -> GEval:
    """忠实度:纪要里的结论/数字/事项能否在原文找到依据,有没有编造。"""
    return GEval(
        name="忠实度",
        criteria=(
            "判断【实际纪要 Actual Output】是否忠实于【会议原文 Input】："
            "纪要中的结论、数字、人名、事项都应能在原文中找到依据；"
            "凡原文没有、被夸大或篡改的内容都算不忠实。数字与专名尤其要对得上。"
        ),
        evaluation_params=[P.INPUT, P.ACTUAL_OUTPUT],
        model=judge,
        threshold=threshold,
    )


def completeness(judge, threshold: float = 0.8) -> GEval:
    """完整度:纪要是否覆盖了原文讨论的主要议题与关键结论,有没有漏掉重要信息。"""
    return GEval(
        name="完整度",
        criteria=(
            "判断【实际纪要 Actual Output】是否完整覆盖了【会议原文 Input】中讨论的"
            "主要议题和关键结论；重要决定、关键数字、明确待办等是否有遗漏。"
            "覆盖越全分越高；遗漏关键信息要扣分。"
        ),
        evaluation_params=[P.INPUT, P.ACTUAL_OUTPUT],
        model=judge,
        threshold=threshold,
    )

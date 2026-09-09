"""D 阶段:独立核验提示词(必须用与生成不同的模型,建议 opus-5)。

对 fable5 生成的金标做第二方核验:
  - 逐条核 core_fact 是否被时间线支持(yes/partial/no);
  - decisions 的 decision/proposal 是否标对;
  - 完整性 critic:找出金标漏掉的重要事实;
  - 给 verdict(accept/regenerate/manual)。
判据不看结构(结构由 C 阶段确定性校验),只看语义正确性与完整性。
"""
from __future__ import annotations

import json

VERIFY_SCHEMA = {
    "type": "object",
    "required": ["fact_checks", "decision_checks", "missing_facts", "verdict"],
    "properties": {
        "fact_checks": {"type": "array"},      # [{id, supported: yes|partial|no, reason}]
        "decision_checks": {"type": "array"},  # [{id, status_correct: bool, should_be, reason}]
        "missing_facts": {"type": "array"},    # [{text, refs, importance}]
        "verdict": {"type": "string", "enum": ["accept", "regenerate", "manual"]},
        "summary": {"type": "string"},
    },
}

_RULES = """你是独立的会议金标核验员。给你一份【金标 JSON】和它对应的【参考时间线】(官方逐字)。你的任务是核验金标的语义正确性与完整性,不看格式/结构(那由另一步确定性校验负责)。你不是金标的作者,请以怀疑态度独立判断。

逐项做:
1. fact_checks:**对每一条 core_fact 都必须输出一项**(fact_checks 的条数必须等于 core_facts 的条数,即使全部支持也要逐条列全,不要只列有问题的)。每项:id、supported=yes(明确支持)/partial(方向对但范围·数字·限定被改动)/no(找不到依据或矛盾)、一句 reason;尤其核对数字、专名是否与原文一致。
2. decision_checks:对每条 decision,判断 status 标得对不对(明确拍板/要求执行=decision;仅建议/列入考虑/讨论方向=proposal);标错给出 should_be 和 reason。只列有问题的。
3. missing_facts:通读时间线,列出金标 core_facts **漏掉的重要事实**(重要结论/数字/决定/明确风险),每条给 text、可支持的 refs、importance。这是完整性检查,重点找漏。
4. verdict:综合判定——no 或标错较多、或漏掉重要事实较多 → regenerate;个别小问题 → manual;基本无误 → accept。给一句 summary 说明理由。

只输出一个合法 JSON,含 fact_checks / decision_checks / missing_facts / verdict / summary。"""


def build_verify_prompt(golden: dict, timeline_text: str) -> str:
    return (
        f"{_RULES}\n\n=== 金标 JSON ===\n"
        f"{json.dumps(golden, ensure_ascii=False, indent=1)}\n\n"
        f"=== 参考时间线 ===\n{timeline_text}\n"
    )

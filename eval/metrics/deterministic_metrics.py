"""确定性纪要质量指标(DeepEval BaseMetric,不花裁判 token,可复现)。

补齐体检发现的缺口:
  - AnchorSupportMetric  证据可回溯率(refs 是否真指向存在的原文段)——项目"证据链"卖点
  - KeywordPurityMetric  关键词纯净度(是不是纯议题词,不含人名/部门)——量化 P1 关键词去噪
  - DecisionOwnerMetric  决策 owner 归属率(多少决策标了负责人)——量化 P1 决策改造 + 对标飞书

全部从 test_case.additional_metadata 取数({minutes, valid_seg_ids}),不依赖裁判、不依赖 src。
"""

from __future__ import annotations

from typing import Any

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

# 中文机构/职务构词后缀(通用,跨域;与 src 侧同规则,自包含复制,遵守原则9不枚举词表)
_ROLE_SUFFIX = ("部", "科", "处", "室", "局", "办", "中心", "组",
                "长", "员", "主任", "经理", "总监", "主席", "主管", "干事", "主持人")


def _is_role_or_dept(w: str) -> bool:
    w = (w or "").strip()
    return bool(w) and len(w) <= 5 and w.endswith(_ROLE_SUFFIX)


class _Base(BaseMetric):
    def __init__(self, threshold: float = 0.8) -> None:
        self.threshold = threshold
        self.async_mode = False
        self.evaluation_cost = 0.0
        self.skipped = False

    async def a_measure(self, tc: LLMTestCase, *a: Any, **k: Any) -> float:
        return self.measure(tc)

    def is_successful(self) -> bool | None:
        return self.success


class AnchorSupportMetric(_Base):
    """证据可回溯率 = 能落到真实非空原文段的 refs 占全部 refs 的比例。
    取 summary.chapters[].refs + enrichment.quotes[].ref;decisions.turn_ids 是行号不是段id,不计。"""

    def measure(self, tc: LLMTestCase, *a: Any, **k: Any) -> float:
        meta = tc.additional_metadata or {}
        minutes = meta.get("minutes") or {}
        valid = set(meta.get("valid_seg_ids") or [])
        refs: list[str] = []
        for ch in (minutes.get("summary") or {}).get("chapters") or []:
            refs += [str(r) for r in (ch.get("refs") or [])]
        for q in (minutes.get("enrichment") or {}).get("quotes") or []:
            if q.get("ref"):
                refs.append(str(q["ref"]))
        if not refs:
            self.skipped, self.score, self.success = True, None, None
            self.reason = "无 refs"
            return 0.0
        hit = sum(1 for r in refs if r in valid)
        self.score = round(hit / len(refs), 3)
        self.success = self.score >= self.threshold
        self.reason = f"证据可回溯 {hit}/{len(refs)}"
        return self.score

    @property
    def __name__(self) -> str:
        return "锚点支持率"


class KeywordPurityMetric(_Base):
    """关键词纯净度 = 议题词占比(1 - 人名/部门/职务占比)。量化 P1 关键词去噪。"""

    def measure(self, tc: LLMTestCase, *a: Any, **k: Any) -> float:
        meta = tc.additional_metadata or {}
        kws = [str(w) for w in ((meta.get("minutes") or {}).get("enrichment") or {}).get("keywords") or []]
        if not kws:
            self.skipped, self.score, self.success = True, None, None
            self.reason = "无关键词"
            return 0.0
        bad = [w for w in kws if _is_role_or_dept(w)]
        self.score = round(1 - len(bad) / len(kws), 3)
        self.success = self.score >= self.threshold
        self.reason = f"纯净 {len(kws)-len(bad)}/{len(kws)}；混入称谓：{bad}"
        return self.score

    @property
    def __name__(self) -> str:
        return "关键词纯净度"


class DecisionOwnerMetric(_Base):
    """决策 owner 归属率 = 标了负责人的决策占比。量化 P1 决策改造 + 对标飞书说话人归属。"""

    def __init__(self, threshold: float = 0.3) -> None:  # owner 归属天然不会 100%,阈值放低
        super().__init__(threshold)

    def measure(self, tc: LLMTestCase, *a: Any, **k: Any) -> float:
        decs = ((tc.additional_metadata or {}).get("minutes") or {}).get("enrichment", {}).get("decisions") or []
        decs = [d for d in decs if isinstance(d, dict)]
        if not decs:
            self.skipped, self.score, self.success = True, None, None
            self.reason = "无决策"
            return 0.0
        owned = sum(1 for d in decs if str(d.get("owner") or "").strip())
        self.score = round(owned / len(decs), 3)
        self.success = self.score >= self.threshold
        self.reason = f"带owner {owned}/{len(decs)}"
        return self.score

    @property
    def __name__(self) -> str:
        return "决策owner归属率"

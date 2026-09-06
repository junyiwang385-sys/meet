"""关键点召回(确定性指标,对人工金标)——包成 DeepEval 自定义 metric。

复用已有 eval/summary/keypoint_recall.py 的打分逻辑,不重造。
golden 与结构化纪要 minutes 通过 test_case.additional_metadata 传入
(评测器在每个 test case 里带上该会自己的金标)。

low_freq_only=True 时只算【精确低频点】子类召回——即 anchor 含数字/中文数字的关键点。
这是对标飞书/阿里发现的最大短板(净利润80万/每层3灭火器/三起案件等只说一次的精确信息),
按 anchor 类型自动判定(不逐会手标,遵守 CLAUDE.md 原则9)。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # eval/
from summary.keypoint_recall import score as kp_score  # noqa: E402

# 低频精确点:anchor 含阿拉伯数字或中文数字 → "只说一次的精确信息"子类
_DIGIT = re.compile(r"[0-9零一二三四五六七八九十百千万]")


def _is_lowfreq(kp: dict) -> bool:
    return any(_DIGIT.search(str(a)) for a in kp.get("anchors", []))


class KeypointRecallMetric(BaseMetric):
    def __init__(self, threshold: float = 0.8, low_freq_only: bool = False) -> None:
        self.threshold = threshold
        self.low_freq_only = low_freq_only
        self.async_mode = False       # 确定性,无需异步
        self.evaluation_cost = 0.0     # 不花裁判 token
        self.skipped = False

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        meta = test_case.additional_metadata or {}
        golden = dict(meta.get("golden") or {})
        minutes = meta.get("minutes") or {}
        kps = golden.get("key_points", [])
        if self.low_freq_only:
            kps = [kp for kp in kps if _is_lowfreq(kp)]
            golden = {**golden, "key_points": kps}
        if not kps:
            self.skipped = True
            self.score, self.success = None, None
            self.reason = "该会无低频精确点"
            return 0.0
        r = kp_score(minutes, golden)
        self.score = r["recall"]
        self.success = self.score >= self.threshold
        self.reason = (f"{'低频' if self.low_freq_only else '全部'}召回 "
                       f"{r['recalled']}/{r['total_keypoints']}；漏：{r['missed_ids']}")
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool | None:
        return self.success

    @property
    def __name__(self) -> str:
        return "低频精确召回" if self.low_freq_only else "关键点召回"

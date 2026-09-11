# -*- coding: utf-8 -*-
"""转写评测·文本归一化约定 v1(CER/WER 前必须统一,否则数字不可比)。

规则(ref 与 hyp 同策略):
  1) 去掉 <...> 标记(TextGrid 的 <sil>/<unk> 等);
  2) 去掉所有标点 + 空白(CJK + ASCII);
  3) 全角数字/字母/空格 → 半角;
  4) 【不做 ITN】中文数字保持原样(Qwen3-ASR 语音场景本就输出中文数字,ref TextGrid 亦然);
  5) 【不做繁简转换】。
业界对标:等价于 AISHELL/WenetSpeech 报 CER 前的"去标点、无空格"口径;
偏离处(不 ITN/不繁简)已在此显式声明,保证跨报告可比。
"""
from __future__ import annotations
import re

_TAG = re.compile(r"<[^>]*>")
_PUNC = re.compile(r"[\s，。、！？：；,.!?:;\"'“”‘’（）()【】\[\]<>《》…—―·~～`|/\\*#@\-—]+")
# 全角 → 半角(FF01-FF5E → 21-7E,以及全角空格 3000)
_FW = {0x3000: 0x20}
_FW.update({c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)})


def normalize_zh(s: str) -> str:
    s = _TAG.sub("", s or "")
    s = s.translate(_FW)
    s = _PUNC.sub("", s)
    return s.strip()

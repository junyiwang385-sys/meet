# -*- coding: utf-8 -*-
"""转写评测·标准评分器(点3 ASR 隔离)。

- CER:字级编辑距离(jiwer.process_characters),累计 S/D/I 与 ref 字数做微平均。
- B-WER / U-WER:上下文偏置的行业标准指标(Le et al., contextualized ASR)——
  把偏置词(热词)当作【原子 token】、其余按【单字】切,跑词级对齐,按 ref token 是否偏置词
  分别累计错误:
    B-WER = (偏置词的 S+D + 偏置词的插入) / ref 中偏置词数
    U-WER = (非偏置词的 S+D+I) / ref 中非偏置词数
  偏置词插入(hyp 冒出 ref 没有的热词)= echo/幻觉信号,单列 b_ins。
"""
from __future__ import annotations
import jiwer
from normalize import normalize_zh


def cer_counts(ref: str, hyp: str) -> dict:
    r, h = normalize_zh(ref), normalize_zh(hyp)
    o = jiwer.process_characters(r, h)
    return {"s": o.substitutions, "d": o.deletions, "i": o.insertions, "n": len(r)}


def _tok(text: str, terms: list[str]):
    """贪心最长匹配:偏置词切成原子 token,其余单字。返回 (tokens, is_bias[0/1])。"""
    terms = sorted({t for t in terms if t}, key=len, reverse=True)
    toks, isb, i = [], [], 0
    while i < len(text):
        hit = next((t for t in terms if text.startswith(t, i)), None)
        if hit:
            toks.append(hit); isb.append(1); i += len(hit)
        else:
            toks.append(text[i]); isb.append(0); i += 1
    return toks, isb


def bwer_counts(ref: str, hyp: str, terms: list[str]) -> dict:
    rt, rb = _tok(normalize_zh(ref), terms)
    ht, hb = _tok(normalize_zh(hyp), terms)
    B = {"ref": sum(rb), "s": 0, "d": 0, "i": 0}
    U = {"ref": sum(1 - x for x in rb), "s": 0, "d": 0, "i": 0}
    if not rt and not ht:
        return {"B": B, "U": U}
    o = jiwer.process_words(" ".join(rt) or " ", " ".join(ht) or " ")
    for c in o.alignments[0]:
        if c.type == "equal":
            continue
        if c.type in ("substitute", "delete"):
            key = "s" if c.type == "substitute" else "d"
            for k in range(c.ref_start_idx, c.ref_end_idx):
                (B if rb[k] else U)[key] += 1
        elif c.type == "insert":
            for k in range(c.hyp_start_idx, c.hyp_end_idx):
                (B if hb[k] else U)["i"] += 1
    return {"B": B, "U": U}


def rate(s, d, i, n):
    return round((s + d + i) / n, 4) if n else None

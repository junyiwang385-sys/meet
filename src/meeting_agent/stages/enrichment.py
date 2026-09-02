"""纪要内容丰富（对标飞书/阿里的产出模块）。

在 product_summary 之外、解耦地补三类内容，避免动 2100 行主 stage：
- keywords   关键词：全文主题标签（4B 抽取，顺滑/书面化）。
- qa         问答回顾：把会议里的"提问→回答"对提出来（顺滑成书面）。
- quotes     金句时刻：挑有代表性的原话 + 点评意义。**原话保真**——4B 选句后
             snap 回转写里的真实原句（逐字），点评可书面化。

设计原则（见分层：归纳顺滑、证据保真）：
- keywords/qa 的文字是归纳产物 → 书面化 OK。
- quotes 的 quote 字段是"引用凭证" → 必须逐字保真（snap 到真实 turn 文本），
  只有 comment（点评）是生成的。

LLM 由调用方注入（LlmCall，与 postprocess 一致），不绑定后端。
"""

from __future__ import annotations

from typing import Any, Protocol


class LlmCall(Protocol):
    def __call__(
        self, messages: list[dict[str, str]], schema: dict[str, Any], *, max_tokens: int
    ) -> dict[str, Any]: ...


def _text(segments: list[dict[str, Any]]) -> str:
    return "".join(str(s.get("text") or "") for s in segments)


def _dedup(items: list[str]) -> list[str]:
    seen: list[str] = []
    for it in items:
        w = str(it).strip()
        if w and w not in seen:
            seen.append(w)
    return seen


# ---- 关键词 -----------------------------------------------------------------

_KEYWORDS_SCHEMA = {
    "type": "object",
    "properties": {"keywords": {"type": "array", "items": {"type": "string"}}},
    "required": ["keywords"],
}


def extract_keywords(
    segments: list[dict[str, Any]], llm_call: LlmCall, *, top_k: int = 18, block_chars: int = 6000
) -> list[str]:
    """全文关键词/主题标签。文本长则分块抽取再按出现频次并集排序。"""
    text = _text(segments)
    if not text.strip():
        return []
    sys = (
        "你是会议关键词提炼器。从会议内容中提炼最能代表主题的关键词（名词/名词短语），"
        "覆盖讨论到的主要方面。只输出词，不要解释。以JSON输出 {\"keywords\":[...]}。"
    )
    freq: dict[str, int] = {}
    for i in range(0, len(text), block_chars):
        chunk = text[i : i + block_chars]
        res = llm_call(
            [{"role": "system", "content": sys}, {"role": "user", "content": "会议内容：\n" + chunk}],
            _KEYWORDS_SCHEMA,
            max_tokens=300,
        )
        for kw in res.get("keywords") or []:
            w = str(kw).strip()
            if w:
                freq[w] = freq.get(w, 0) + 1
    # 频次高优先，其次先出现的
    ordered = sorted(freq, key=lambda w: (-freq[w]))
    return ordered[:top_k]


# ---- 问答回顾 ---------------------------------------------------------------

_QA_SCHEMA = {
    "type": "object",
    "properties": {
        "qa": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "turn_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["question", "answer"],
            },
        }
    },
    "required": ["qa"],
}


def _numbered_timeline(segments: list[dict[str, Any]], start: int) -> tuple[str, list[int]]:
    lines = []
    ids = []
    for idx, s in enumerate(segments, start):
        lines.append(f"[{idx}] {s.get('text') or ''}")
        ids.append(idx)
    return "\n".join(lines), ids


def extract_qa(
    segments: list[dict[str, Any]], llm_call: LlmCall, *, block_segs: int = 40
) -> list[dict[str, Any]]:
    """提取"提问→回答"对（书面化）。分块抽取后合并；turn_ids 便于锚回原文。

    只保留真正的疑问（有人提出问题、另一方回答），过滤开场白/陈述被误当问题；
    问题句改写成凝练的书面问句（以"？"结尾）。
    """
    sys = (
        "你是会议问答提炼器。从会议转写中找出真正的\"提问—回答\"对：必须是有人"
        "明确提出了一个问题、另一方作了回答。把问题改写成一句凝练的书面问句（以问号结尾），"
        "把回答整理成一句通顺的书面话。\n"
        "严格要求：\n"
        "- 只提取真实发生的问答，不臆造；\n"
        "- 开场白、致辞、纯陈述、过渡语不是问题，不要当作问答；\n"
        "- 问题要是一个具体、可回答的问句，不是半句话或口头禅。\n"
        "turn_ids 填该问答涉及的行号（整数）。以JSON输出 "
        '{"qa":[{"question":"具体问句？","answer":"","turn_ids":[]}]}。'
    )
    # 不用 few-shot：弱 4B 会直接 echo 示例答案（实测污染）。只靠强化 system 约束 +
    # 下面的疑问词过滤把控质量。
    out: list[dict[str, Any]] = []
    for i in range(0, len(segments), block_segs):
        blk = segments[i : i + block_segs]
        tl, _ = _numbered_timeline(blk, i + 1)
        res = llm_call(
            [{"role": "system", "content": sys},
             {"role": "user", "content": "转写：\n" + tl}],
            _QA_SCHEMA,
            max_tokens=800,
        )
        for pair in res.get("qa") or []:
            q = str(pair.get("question") or "").strip()
            a = str(pair.get("answer") or "").strip()
            # 过滤：问题必须像个问句（含疑问标记），否则多半是开场白/陈述误判
            if q and a and (("？" in q) or ("?" in q) or any(w in q for w in ("吗", "怎么", "如何", "什么", "是否", "有没有", "为什么", "哪"))):
                out.append({"question": q, "answer": a, "turn_ids": pair.get("turn_ids") or []})
    return out


# ---- 金句时刻（原话保真 + 点评） --------------------------------------------

_QUOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "quotes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"quote": {"type": "string"}, "comment": {"type": "string"}},
                "required": ["quote", "comment"],
            },
        }
    },
    "required": ["quotes"],
}


def _snap_to_transcript(quote: str, segments: list[dict[str, Any]]) -> tuple[str, str | None]:
    """把 4B 给的金句 snap 到转写里最匹配的真实 turn，保证逐字保真。

    返回 (真实原句, 该句的 segment_id)；找不到足够重合则返回 (原样, None)。
    """
    q = quote.strip()
    if not q:
        return quote, None
    best_seg = None
    best_overlap = 0
    for s in segments:
        t = str(s.get("text") or "")
        if not t:
            continue
        # 字符集重合近似（快速、无依赖）
        overlap = len(set(q) & set(t))
        # 若 quote 是 turn 的子串，直接命中
        if q in t:
            return t.strip(), str(s.get("segment_id") or s.get("id") or "")
        if overlap > best_overlap:
            best_overlap = overlap
            best_seg = s
    if best_seg is not None and best_overlap >= max(4, len(q) // 3):
        return str(best_seg.get("text") or "").strip(), str(best_seg.get("segment_id") or best_seg.get("id") or "")
    return quote, None


def extract_quotes(
    segments: list[dict[str, Any]], llm_call: LlmCall, *, max_quotes: int = 3, block_chars: int = 6000
) -> list[dict[str, Any]]:
    """挑代表性金句 + 点评。quote 经 snap 回真实原句（保真），comment 为生成点评。"""
    text = _text(segments)
    if not text.strip():
        return []
    sys = (
        "你是会议金句提炼器。从会议内容中挑出最有代表性、最能点明核心观点的原话"
        "（1-3句），并为每句写一句点评说明它为什么重要。quote 要尽量接近原文表述。"
        '以JSON输出 {"quotes":[{"quote":"原话","comment":"点评"}]}。'
    )
    cands: list[dict[str, Any]] = []
    for i in range(0, len(text), block_chars):
        chunk = text[i : i + block_chars]
        res = llm_call(
            [{"role": "system", "content": sys}, {"role": "user", "content": "会议内容：\n" + chunk}],
            _QUOTES_SCHEMA,
            max_tokens=400,
        )
        for q in res.get("quotes") or []:
            quote = str(q.get("quote") or "").strip()
            comment = str(q.get("comment") or "").strip()
            if quote and comment:
                real, seg_id = _snap_to_transcript(quote, segments)
                cands.append({"quote": real, "comment": comment, "ref": seg_id, "verbatim": seg_id is not None})
    return cands[:max_quotes]


# ---- 编排 -------------------------------------------------------------------


def enrich(
    segments: list[dict[str, Any]], llm_call: LlmCall
) -> dict[str, Any]:
    """一次性产出三类丰富内容，供并入最终纪要。"""
    return {
        "keywords": extract_keywords(segments, llm_call),
        "qa": extract_qa(segments, llm_call),
        "quotes": extract_quotes(segments, llm_call),
    }

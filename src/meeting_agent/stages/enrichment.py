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

import re
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
        "你是会议关键词提炼器。从会议内容中提炼最能代表【讨论议题/主题】的关键词（名词/名词短语），"
        "覆盖讨论到的主要方面。\n"
        "只要“讨论的事项”，不要“谁在讨论”——即：**不要人名、职务称谓、部门/机构名称、说话人标签**"
        "（例如 “某某主任 / 某科长 / XX部 / XX办” 这类称谓一律不要，只保留他们讨论的事项）。\n"
        "只输出词，不要解释。以JSON输出 {\"keywords\":[...]}。"
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
    # 后处理去噪：滤掉人名/部门/职务类词（提示词可能仍漏网），只留议题词
    ordered = [w for w in sorted(freq, key=lambda w: (-freq[w])) if not _is_role_or_dept(w)]
    return ordered[:top_k]


# 通用规则：靠中文【机构/职务的构词后缀】识别"称谓类"词，不枚举任何具体会议的词表。
# 这套后缀对 医院/政府/企业/学校 等各类组织通用（如 X部/X科/X处/X室/X局/X办/X中心、
# X长/X员/X主任/X经理/X总监/X主席）。个例词表不写死——那样只对某场会有效，不规范。
_ROLE_DEPT_SUFFIX = (
    "部", "科", "处", "室", "局", "办", "中心", "组",  # 机构/部门
    "长", "员", "主任", "经理", "总监", "主席", "主管", "干事", "主持人",  # 职务/称谓
)


def _is_role_or_dept(w: str) -> bool:
    """按中文机构/职务构词判断是否为'称谓类'词（通用，不依赖具体会议词表）。"""
    w = w.strip()
    if not w:
        return True
    # 短词且以机构/职务后缀结尾（如 招生办/保卫科/教务主任/产品经理/技术总监）→ 称谓类。
    # 限长≤5 避免误伤含这些字的议题词（如 "部署方案" 不会被误判，因为它不是短称谓）。
    return len(w) <= 5 and w.endswith(_ROLE_DEPT_SUFFIX)


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


_QA_MARKS = ("吗", "怎么", "如何", "什么", "是否", "有没有", "为什么", "哪", "呢", "?", "？")
_QA_FILLER = set("嗯呃啊哦额那这就是的了吧呗吧呀啦哈")
# 纯口头语气/停顿字：句中出现连串或高密度 → ASR 把口语噪声当内容识别，答案不可信
_DISFLUENCY = set("呃嗯额哦啊呀啦呗哈")
_DISFLUENCY_RUN = re.compile(r"[呃嗯额哦啊]{2,}")  # 连续≥2个语气字（如"呃嗯"）


def _is_question(q: str) -> bool:
    return bool(q) and any(w in q for w in _QA_MARKS)


def _valid_answer(a: str) -> bool:
    """答案质量门：过滤过短、纯语气词开头、结巴/ASR 噪声（连串/高密度语气字）、以疑问收尾。"""
    if len(a) < 6:
        return False
    if a.rstrip("。.！!").endswith(("？", "?")):
        return False  # 以问号结尾 → 是半句/反问，不是回答
    if _DISFLUENCY_RUN.search(a):
        return False  # 句中出现"呃嗯"这类连续语气字 → ASR 噪声混入（如"反对党的呃嗯被动会"）
    core = a.strip("，。、,. ")
    if core and sum(1 for c in core if c in _DISFLUENCY) / len(core) > 0.15:
        return False  # 语气字密度过高 → 口语噪声，非有效回答
    j = 0
    while j < len(core) and core[j] in _QA_FILLER:
        j += 1
    if len(core) - j < 5:  # 去掉开头语气词后实质内容太少
        return False
    for k in range(len(core) - 1):  # 同一 2 字片段重复≥3 次 → 结巴/识别噪声
        gram = core[k : k + 2]
        if gram.strip() and core.count(gram) >= 3:
            return False
    return True


def _norm_q(q: str) -> str:
    return "".join(ch for ch in q if ch.isalnum())[:20]


def extract_qa(
    segments: list[dict[str, Any]], llm_call: LlmCall, *, block_segs: int = 40, max_qa: int = 15
) -> list[dict[str, Any]]:
    """提取"提问→回答"对（书面化）。分块抽取→质量门过滤→按问题去重→全局限量。

    只保留真正的疑问（有人提出、另一方直接回答），过滤开场白/陈述/半句/噪声/答非所问。
    """
    sys = (
        "你是会议问答提炼器。从会议转写里找出真实发生的\"提问→回答\"对。\n"
        "严格要求：\n"
        "- 必须是有人明确提出一个具体问题，且另一方随后作出直接回应；\n"
        "- answer 必须是对该问题的直接回答（取回答者的话，整理成一句通顺书面话）；"
        "找不到清晰且对得上的回答，就不要输出这一条；\n"
        "- 问题与答案必须语义相关，答非所问的一律不要；\n"
        "- 不要输出开场白/致辞/纯陈述/过渡语，不要输出未说完的半句、口头禅或识别噪声。\n"
        "turn_ids 填该问答涉及的行号（整数）。以JSON输出 "
        '{"qa":[{"question":"具体问句？","answer":"","turn_ids":[]}]}。'
    )
    # 不用 few-shot：弱 4B 会 echo 示例。靠强 system 约束 + 下面的质量门/去重/限量把控。
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
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
            if not _is_question(q) or not _valid_answer(a):
                continue
            key = _norm_q(q)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append({"question": q, "answer": a, "turn_ids": pair.get("turn_ids") or []})
            if len(out) >= max_qa:
                return out
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


# ---- 关键决策（结构化：问题→方案[谁提]→依据） -----------------------------

_DECISIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string"},
                    "problem": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                    "owner": {"type": "string"},
                    "turn_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["decision"],
            },
        }
    },
    "required": ["decisions"],
}


def extract_decisions(
    segments: list[dict[str, Any]], llm_call: LlmCall, *, block_segs: int = 50
) -> list[dict[str, Any]]:
    """结构化关键决策：不只一句结论，还带 问题背景 / 讨论方案 / 决策依据（对标飞书）。

    只提取会上真正作出的决定；普通建议/讨论不升级为决定。分块抽取后合并。
    """
    sys = (
        "你是会议决策整理器。从会议转写中找出真正作出的关键决策，每条给出：\n"
        "- decision: 最终决定（一句话）；\n"
        "- problem: 该决策针对的问题/背景；\n"
        "- options: 讨论过的方案/选项（数组，可为空）；\n"
        "- rationale: 决策依据/理由；\n"
        "- owner: 提出或负责该决策的人/部门，**只在转写里明确出现时填**（如某部门、某职务），否则留空，不要猜。\n"
        "严格：只提取明确作出的决定，普通建议、设想、还在讨论没定的，不算决策，不要臆造。"
        "turn_ids 填涉及行号。以JSON输出 "
        '{"decisions":[{"decision":"","problem":"","options":[],"rationale":"","owner":"","turn_ids":[]}]}。'
    )
    out: list[dict[str, Any]] = []
    for i in range(0, len(segments), block_segs):
        blk = segments[i : i + block_segs]
        tl, _ = _numbered_timeline(blk, i + 1)
        res = llm_call(
            [{"role": "system", "content": sys}, {"role": "user", "content": "转写：\n" + tl}],
            _DECISIONS_SCHEMA,
            max_tokens=900,
        )
        for d in res.get("decisions") or []:
            dec = str(d.get("decision") or "").strip()
            if dec:
                out.append({
                    "decision": dec,
                    "problem": str(d.get("problem") or "").strip(),
                    "options": _dedup([str(o) for o in (d.get("options") or [])]),
                    "rationale": str(d.get("rationale") or "").strip(),
                    "owner": str(d.get("owner") or "").strip(),
                    "turn_ids": d.get("turn_ids") or [],
                })
    # 跨块去重：按决策文本归一化合并，避免同一决定被多块各报一遍（旧版 30 条偏多）
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in out:
        key = "".join(ch for ch in d["decision"] if ch.isalnum())[:24]
        if key and key in seen:
            continue
        seen.add(key)
        deduped.append(d)
    return deduped


# ---- 层级化全文摘要（分组大纲，对标飞书三层缩进） ---------------------------

_OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "purpose": {"type": "string"},
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string"},
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "points": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["heading", "points"],
                        },
                    },
                },
                "required": ["theme", "sections"],
            },
        },
    },
    "required": ["purpose", "groups"],
}


def build_outline_summary(
    chapter_summaries: list[str], llm_call: LlmCall
) -> dict[str, Any]:
    """把各章节摘要归并成【两层层级大纲】：会议目的 + 大类(theme) → 分组(heading+要点)。

    对标飞书的"三层缩进总结"（如 复盘/规划/统一要求 → 部门/议题 → 条目）：
    先把章节聚合成 2-4 个大类主线，大类下再分组，避免"一章一组"的平铺。
    归纳去重，不等比缝合。输入是已压缩的章节摘要（reduce 侧，短），不喂原始转写。
    """
    if not chapter_summaries:
        return {"purpose": "", "groups": []}
    joined = "\n".join(f"- {s}" for s in chapter_summaries if s.strip())
    sys = (
        "你是会议纪要归纳器。给你各章节摘要，归并成一份两层层级大纲：\n"
        "- purpose: 必填，一句话点明会议整体目的（不能为空）。\n"
        "- groups: 先把内容聚合成 2-4 个高层大类(theme)——例如按 上月复盘/下月规划/统一要求，"
        "或按 业务经营/法务合规/市场营销 等主线归类；每个大类下再分若干 section(heading+要点points)。\n"
        "要做真正的归纳聚合：合并同类章节、跨章去重，不要把每个章节各自当成一个分组平铺。"
        "只依据输入内容，不臆造。以JSON输出 "
        '{"purpose":"","groups":[{"theme":"大类","sections":[{"heading":"","points":[""]}]}]}。'
    )
    res = llm_call(
        [{"role": "system", "content": sys}, {"role": "user", "content": "各章节摘要：\n" + joined}],
        _OUTLINE_SCHEMA,
        max_tokens=1900,  # 嵌套大纲JSON最长,给足输出预算,否则截断→解析空(实测1300会截)
    )
    groups = []
    for g in res.get("groups") or []:
        theme = str(g.get("theme") or "").strip()
        if not theme:
            continue
        secs = [
            {"heading": str(s.get("heading") or "").strip(),
             "points": _dedup([str(p) for p in (s.get("points") or [])])}
            for s in (g.get("sections") or [])
            if str(s.get("heading") or "").strip()
        ]
        groups.append({"theme": theme, "sections": secs})
    return {"purpose": str(res.get("purpose") or "").strip(), "groups": groups}


# ---- 编排 -------------------------------------------------------------------


def enrich(
    segments: list[dict[str, Any]],
    llm_call: LlmCall,
    *,
    chapter_summaries: list[str] | None = None,
) -> dict[str, Any]:
    """一次性产出丰富内容，供并入最终纪要。

    chapter_summaries 提供时额外产出层级化大纲摘要（否则跳过，避免重复喂原文）。
    """
    result = {
        "keywords": extract_keywords(segments, llm_call),
        "qa": extract_qa(segments, llm_call),
        "quotes": extract_quotes(segments, llm_call),
        "decisions": extract_decisions(segments, llm_call),
    }
    if chapter_summaries:
        result["outline_summary"] = build_outline_summary(chapter_summaries, llm_call)
    return result


# ---- Stage 封装（复用摘要 stage 的活着 session，不另起 server） ---------------

import json as _json
import pathlib as _pathlib
import time as _time


def _loads_tolerant(text: str) -> dict[str, Any]:
    """把 4B/板端输出的 JSON 文本尽量解析成 dict；失败返回 {}（下游按空处理）。"""
    s = (text or "").strip()
    if not s:
        return {}
    try:
        value = _json.loads(s)
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001
        # 兜底：截取第一个平衡的 {...}
        start = s.find("{")
        if start < 0:
            return {}
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = _json.loads(s[start : i + 1])
                        return value if isinstance(value, dict) else {}
                    except Exception:  # noqa: BLE001
                        return {}
        return {}


def _no_think(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """给最后一条 user 追加 Qwen3 的 /no_think 软开关（enrichment 全是抽取，不需思考、省输出预算）。"""
    patched = [dict(m) for m in messages]
    for m in reversed(patched):
        if m.get("role") == "user":
            content = str(m.get("content") or "")
            if "/no_think" not in content:
                m["content"] = content + "\n/no_think"
            break
    return patched


def make_session_llm_call(
    session: Any,
    out_dir: "_pathlib.Path",
    run_log: Any | None = None,
    *,
    max_predict: int = 2000,
) -> tuple[LlmCall, dict[str, int]]:
    """把 RkllmServerSession（或鸭子对齐的 OllamaSession）.request 包成 enrichment 要的 LlmCall。

    复用调用方已 start 的活着 server；请求失败/解析失败返回 {}，绝不抛出（enrichment 是增强，不阻断主流程）。
    """
    counter = {"n": 0}

    def _call(messages: list[dict[str, str]], schema: dict[str, Any], *, max_tokens: int) -> dict[str, Any]:
        counter["n"] += 1
        request_dir = out_dir / "requests" / f"enrich-{counter['n']:04d}"
        try:
            result = session.request(
                _no_think(messages),
                request_dir,
                max_tokens=min(max_tokens, max_predict),
                phase="enrichment",
                request_id=f"enrich-{counter['n']:04d}",
                request_kind="enrichment",
                attempt=1,
                run_log=run_log,
            )
        except Exception:  # noqa: BLE001
            return {}
        return _loads_tolerant(str(result.get("content") or ""))

    return _call, counter


def run_enrichment_stage(
    *,
    session: Any,
    segments: list[dict[str, Any]],
    out_dir: "_pathlib.Path",
    chapter_summaries: list[str] | None = None,
    run_log: Any | None = None,
    max_predict: int = 2000,
) -> dict[str, Any]:
    """在摘要之后、复用同一活着 server，产出关键词/问答/金句/决策/层级大纲。

    返回 {"enrichment": {...}, "stats": {...}}；调用方负责写 enrichment.json 与并入结果。
    """
    started = _time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    llm_call, counter = make_session_llm_call(session, out_dir, run_log, max_predict=max_predict)
    result = enrich(segments, llm_call, chapter_summaries=chapter_summaries)
    stats = {
        "llm_calls": counter["n"],
        "keywords": len(result.get("keywords") or []),
        "qa": len(result.get("qa") or []),
        "quotes": len(result.get("quotes") or []),
        "decisions": len(result.get("decisions") or []),
        "has_outline": bool(result.get("outline_summary")),
        "elapsed_seconds": round(_time.time() - started, 3),
    }
    return {"enrichment": result, "stats": stats}

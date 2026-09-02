"""转写后处理（前置于 LLM 摘要）。

在 transcript_prepare 产出 canonical segments 之后、product_summary 之前插入。
分层原则（见 docs 与实验 [[meet-postprocess-experiments]]）：

    L0  canonical 原始转写（ASR 忠实输出，可能有切片重叠重复/同音专名错/口语）
     │  ① 重叠去重合并      —— 确定性、无损、零模型（时间戳 + 最长公共子串）
     │  ② 专名纠错          —— 无损（拼音候选初筛 + LLM 判定，只改同音近音专名）
    L1  无损修复版          —— 喂所有下游（摘要 / 决策抽取 / 证据链锚这一层）
     │  ③ 顺滑              —— 有损（删语气词/重复/口语，书面化，可能改写）
    L2  顺滑展示版          —— 仅供"给人看的逐字稿"，绝不喂抽取/证据链

设计要点：
- ① 不依赖 LLM，任何环境都能跑，最前置净化。
- ②③ 依赖一个可注入的 ``llm_call``（board 传 RKLLM 封装，PC 传 Ollama 封装），
  本模块不绑定具体推理后端，便于测试与跨环境复用。
- 每个 segment 携带 text(=L1) 与 display_text(=L2)；下游默认读 text。
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from pypinyin import lazy_pinyin


POSTPROCESS_VERSION = "postprocess.v1"

# 去重时"贴边"的判定窗口与最小公共子串长度。
_DEDUP_WINDOW = 20
_DEDUP_MIN_LCS = 3
# 专名候选：与词表条目的拼音编辑距离 <= 此值即视为疑似同音近音错。
_PINYIN_EDIT_MAX = 2


# ---- LLM 注入接口 -----------------------------------------------------------


class LlmCall(Protocol):
    """后处理需要的最小 LLM 能力：给 messages + JSON schema，返回解析后的 dict。

    board 与 PC 各自实现；解析失败应返回 {} 而非抛出，让后处理降级为"不改动"。
    """

    def __call__(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        max_tokens: int,
    ) -> dict[str, Any]: ...


# ---- 配置 -------------------------------------------------------------------


@dataclass(frozen=True)
class PostProcessConfig:
    enable_dedup: bool = True
    enable_proper_correction: bool = True
    enable_smoothing: bool = False  # 有损，默认关；只在需要展示逐字稿时开
    # 专名词表：给定领域后由 LLM 自拟 + 从材料抽取；为空则跳过纠错（降级为只去重）。
    lexicon: tuple[str, ...] = ()
    domain: str = ""
    pinyin_edit_max: int = _PINYIN_EDIT_MAX
    correction_max_tokens: int = 512
    smoothing_max_tokens: int = 512
    lexicon_max_tokens: int = 512


# ---- ① 重叠去重合并（确定性，无损，无 LLM） --------------------------------


def _lcs_span(a: str, b: str) -> tuple[int, int, int]:
    """a 的后缀与 b 的前缀的最长公共子串：返回 (长度, a 中结束位, b 中结束位)。"""
    m, n = len(a), len(b)
    best = end_a = end_b = 0
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        cur = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best, end_a, end_b = cur[j], i, j
        prev = cur
    return best, end_a, end_b


def dedup_overlaps(segments: list[dict[str, Any]], config: PostProcessConfig) -> dict[str, Any]:
    """去掉时间戳重叠导致的相邻段头尾重复文本（原地修改 text）。

    只在"前段结尾窗 vs 后段开头窗"的公共子串足够长、且贴住两侧边界时才切，
    避免误删正常的口语重复。返回统计。
    """
    removed_chars = 0
    fixed = 0
    for i in range(1, len(segments)):
        prev, cur = segments[i - 1], segments[i]
        if int(cur["start_ms"]) >= int(prev["end_ms"]):
            continue  # 时间戳无重叠，跳过
        ta, tb = prev["text"], cur["text"]
        if not ta or not tb:
            continue
        wa, wb = ta[-_DEDUP_WINDOW:], tb[:_DEDUP_WINDOW]
        length, end_a, end_b = _lcs_span(wa, wb)
        if length >= _DEDUP_MIN_LCS and end_a >= len(wa) - 2 and (end_b - length) <= 2:
            cur["text"] = tb[end_b:].lstrip("，。、！？；：\"'' ")
            removed_chars += end_b
            fixed += 1
    return {"segments_fixed": fixed, "chars_removed": removed_chars}


# ---- ② 专名纠错（拼音候选初筛 + LLM 判定，无损） ---------------------------


def _pinyin(text: str) -> str:
    return "".join(lazy_pinyin(text))


# 声母表（含 zh/ch/sh 双字母优先）；零声母（a/o/e/y/w 开头）返回空串或首拼母。
_INITIALS = [
    "zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l",
    "g", "k", "h", "j", "q", "x", "r", "z", "c", "s", "y", "w",
]


def _shengmu(syllable: str) -> str:
    for initial in _INITIALS:
        if syllable.startswith(initial):
            return initial
    return ""


def _is_cjk(text: str) -> bool:
    return all("一" <= ch <= "鿿" for ch in text)


# 语气词/虚字：含这些字的 n-gram 不参与专名匹配，挡"按摩呀→按摩椅"这类假阳性。
_FUNCTION_CHARS = set("呀啊吧呢吗嘛哦噢唉呗咯啦哈嗯哎的了着过呃")


def _rule_candidate(gram: str, word: str) -> str | None:
    """音节级候选规则：k 个音里恰好 (k-1) 个完全相同（音调无关），

    剩下 1 个不同的音其声母也相同 → 判为疑似同音近音专名错。
    返回 'exact'（完全同音）/ 'near'（近音）/ None（不是候选）。

    动机：ASR 专名错基本是"某个音听岔、声母不变"（秋英/秋叶/秋衣→蚯蚓，
    中间音变、声母都 y）。该规则精准框住这一模式，且拒掉"末字声母不同"的
    正常词（保健产 vs 保健品：末音 ch≠p，不匹配）。相比拼音编辑距离更准。
    """
    if any(ch in _FUNCTION_CHARS for ch in gram):
        return None
    p1 = lazy_pinyin(gram)
    p2 = lazy_pinyin(word)
    if len(p1) != len(p2):
        return None
    diff = [i for i in range(len(p1)) if p1[i] != p2[i]]
    if not diff:
        return "exact"
    if len(diff) == 1 and _shengmu(p1[diff[0]]) == _shengmu(p2[diff[0]]):
        return "near"
    return None


# 句法/词性判定 prompt：让弱模型做它擅长的"这词是否在专名位、替换后是否通顺"判断，
# 而非自由改写（改写会手痒改别的、遇同上下文翻案）。带 reason 强制先推理。
_JUDGE_SYSTEM = (
    "你是语音转写纠错判定器。语音识别可能把专有名词听错、写成读音相近的字。"
    "给你片段、疑似错词、候选专名，判断是否该替换。\n"
    "判断方法：\n"
    "1. 分析该词在句中的句法角色和词性：它是否正好在一个\"完整名词/专名\"应出现的位置"
    "（主语/宾语/定语中心词）。\n"
    "2. 替换后句子是否通顺、词性是否一致、语义是否成立。\n"
    "3. 若原词本身是完整通顺的词组、或跨越了词边界（如\"销售不出去\"里的\"销售不\""
    "是动词+否定副词，不是名词），替换成专名会不通顺、词性不对，则不替换。\n"
    "4. 只有该位置本应是专名、且替换后通顺、词性正确，才替换。\n"
    '先在 reason 里简述句法分析，再给 replace。输出 {"reason":"...","replace":true或false}'
)

_JUDGE_FEWSHOT = [
    {"role": "user", "content": "片段：就是销售不出去，因为\n疑似错词：销售不\n候选专名：销售部"},
    {"role": "assistant", "content": '{"reason":"销售不=动词销售+否定副词不,非名词,跨词边界;换销售部则\'销售部出去\'不通,词性不对","replace":false}'},
    {"role": "user", "content": "片段：都是市场饱和问题\n疑似错词：市场饱\n候选专名：市场部"},
    {"role": "assistant", "content": '{"reason":"市场饱和是完整词组(饱和为形容词),市场饱跨词边界,非名词位;不替换","replace":false}'},
    {"role": "user", "content": "片段：你不叫秋衣粉吗？\n疑似错词：秋衣粉\n候选专名：蚯蚓粉"},
    {"role": "assistant", "content": '{"reason":"秋衣粉处于\'叫X吗\'的宾语位置,是产品名词,换蚯蚓粉通顺、词性一致","replace":true}'},
    {"role": "user", "content": "片段：手里有一批护景仪\n疑似错词：护景仪\n候选专名：护颈仪"},
    {"role": "assistant", "content": '{"reason":"护景仪是\'一批X\'的宾语中心名词,换护颈仪通顺,是产品名","replace":true}'},
]

_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "replace": {"type": "boolean"}},
    "required": ["reason", "replace"],
}


def _judge_messages(window: str, gram: str, word: str) -> list[dict[str, str]]:
    return (
        [{"role": "system", "content": _JUDGE_SYSTEM}]
        + _JUDGE_FEWSHOT
        + [{"role": "user", "content": f"片段：{window}\n疑似错词：{gram}\n候选专名：{word}"}]
    )


def correct_proper_nouns(
    segments: list[dict[str, Any]],
    config: PostProcessConfig,
    llm_call: LlmCall,
) -> dict[str, Any]:
    """无损专名纠错：音节规则圈候选（CPU）→ 句法/词性 LLM 判定是否替换。

    分工：规则保召回（框住所有近音候选），LLM 保精度（按句法角色+词性+替换后
    通顺性判断，区分"正常词组/跨词边界" vs "专名误写"）。完全同音也过 LLM，
    以挡"销售不出去→销售部"这类同音撞车。LLM 失败则不改（降级）。

    实测（PC，qwen3:4b）：销售会 20 词表 5/5 纠对 0 误纠；物业会 0 误纠。
    可靠性关键在词表质量——含"常见词前缀"的条目（市场部）会让规则多圈候选，
    但句法判定能挡掉正常词组的假阳性。
    """
    if not config.lexicon:
        return {"skipped": "no_lexicon", "segments_corrected": 0, "llm_calls": 0}
    corrected = 0
    llm_calls = 0
    lexicon = tuple(config.lexicon)
    for seg in segments:
        text = seg["text"]
        # 逐个 3/4 字窗口找规则候选（专名多为 3-4 字）。
        for size in (3, 4):
            i = 0
            while i <= len(text) - size:
                gram = text[i : i + size]
                if not _is_cjk(gram) or gram in lexicon:
                    i += 1
                    continue
                matched = None
                for word in lexicon:
                    if len(word) == size and _rule_candidate(gram, word):
                        matched = word
                        break
                if matched is None:
                    i += 1
                    continue
                # 命中候选：取前后各 4 字上下文，交 LLM 按句法/词性判定。
                window = text[max(0, i - 4) : i + size + 4]
                llm_calls += 1
                result = llm_call(
                    _judge_messages(window, gram, matched),
                    _JUDGE_SCHEMA,
                    max_tokens=config.correction_max_tokens,
                )
                if bool(result.get("replace")):
                    text = text[:i] + matched + text[i + size :]
                    corrected += 1
                    i += size
                else:
                    i += 1
        seg["text"] = text
    return {"segments_corrected": corrected, "llm_calls": llm_calls}


# ---- ③ 顺滑（有损，写入 display_text，不动 text=L1） -----------------------


def _smoothing_messages(text: str) -> list[dict[str, str]]:
    system = (
        "你是口语顺滑器。删语气词(呃/嗯/啊/呗)、重复、结巴，让文本书面易读；"
        "不改原意、不增删信息、不做总结。以JSON输出 {\"smoothed\":\"文本\"}。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "片段：呃就是那个，我觉得没有没有用啊对不对？"},
        {"role": "assistant", "content": '{"smoothed":"我觉得没有用。"}'},
        {"role": "user", "content": "片段：" + text},
    ]


_SMOOTHING_SCHEMA = {
    "type": "object",
    "properties": {"smoothed": {"type": "string"}},
    "required": ["smoothed"],
}


def smooth_for_display(
    segments: list[dict[str, Any]],
    config: PostProcessConfig,
    llm_call: LlmCall,
) -> dict[str, Any]:
    """对 L1 顺滑，结果写入 display_text（L2）；text 保持 L1 不变。

    有损：可能改写/书面化，只供展示，绝不回写 text。
    """
    smoothed = 0
    for seg in segments:
        l1 = seg["text"]
        result = llm_call(
            _smoothing_messages(l1),
            _SMOOTHING_SCHEMA,
            max_tokens=config.smoothing_max_tokens,
        )
        l2 = str(result.get("smoothed") or "").strip()
        # 护栏：顺滑应更短或相当；异常膨胀（疑似乱码/复述）则退回 L1。
        seg["display_text"] = l2 if l2 and len(l2) <= len(l1) * 1.4 else l1
        if seg["display_text"] != l1:
            smoothed += 1
    return {"segments_smoothed": smoothed}


# ---- 词表生成（给定领域 → LLM 自拟专名；可选并入材料抽取） -----------------


_LEXICON_SCHEMA = {
    "type": "object",
    "properties": {"terms": {"type": "array", "items": {"type": "string"}}},
    "required": ["terms"],
}


def _dedup_terms(terms: Any) -> list[str]:
    seen: list[str] = []
    for term in terms or []:
        word = str(term).strip()
        if word and word not in seen:
            seen.append(word)
    return seen


# 抽取式 prompt：让 4B 从给定文本"挑出"专名（抽取任务，它擅长），而非凭领域"想"
# （生成任务，弱模型会给话题词而非易错专名——物业会实测翻车过）。
_EXTRACT_SYSTEM = (
    "你是会议专名抽取器。从给定文本中【挑出】其中真实出现的专有名词——"
    "产品名、项目名、专业术语、机构名、人名等，尤其是那些容易被语音识别听错写错、"
    "需要在纪要里保持正确的词。只抽取文本里确实出现的词，不要臆造、不要输出普通词组或话题词。"
    '以JSON输出 {"terms":[...]}。'
)


def extract_lexicon_from_materials(
    materials: str,
    config: PostProcessConfig,
    llm_call: LlmCall,
) -> list[str]:
    """主源：从会议材料（PPT/议程/参会名单/历史纪要）抽取专名。

    材料是人写的，专名写法正确、权威——这是纠错词表的首选来源。4B 只做抽取。
    """
    if not materials.strip():
        return []
    result = llm_call(
        [{"role": "system", "content": _EXTRACT_SYSTEM},
         {"role": "user", "content": "会议材料：\n" + materials.strip()[:4000]}],
        _LEXICON_SCHEMA,
        max_tokens=config.lexicon_max_tokens,
    )
    return _dedup_terms(result.get("terms"))


def discover_lexicon_from_transcript(
    segments: list[dict[str, Any]],
    config: PostProcessConfig,
    llm_call: LlmCall,
) -> list[str]:
    """备源：无材料时，从转写抽"疑似专名候选"。

    ⚠️ 转写可能含 ASR 错字，抽出的候选写法未必正确——仅作候选，需人工/材料确认
    正确写法后才可作为纠错词表。返回的每个词标注为候选（调用方负责确认）。
    """
    text = "".join(str(s.get("text") or "") for s in segments)
    if not text.strip():
        return []
    terms: list[str] = []
    # 分块抽取（避免超窗），汇总去重
    step = 3000
    for i in range(0, len(text), step):
        chunk = text[i : i + step]
        result = llm_call(
            [{"role": "system", "content": _EXTRACT_SYSTEM},
             {"role": "user", "content": "会议转写片段：\n" + chunk}],
            _LEXICON_SCHEMA,
            max_tokens=config.lexicon_max_tokens,
        )
        terms.extend(result.get("terms") or [])
    return _dedup_terms(terms)


def build_lexicon(
    config: PostProcessConfig,
    llm_call: LlmCall,
    *,
    materials: str = "",
    segments: list[dict[str, Any]] | None = None,
    manual_terms: tuple[str, ...] = (),
) -> dict[str, Any]:
    """构建纠错词表：主源（材料抽取）优先，无材料降级备源（转写抽候选），
    再并入人工补齐词（manual_terms）。

    返回 {terms, source, needs_confirmation}：
    - 主源/人工来的 terms 视为可信；备源来的标 needs_confirmation=True（写法待确认）。
    """
    if materials.strip():
        terms = extract_lexicon_from_materials(materials, config, llm_call)
        source = "materials"
        needs_confirm = False
    elif segments:
        terms = discover_lexicon_from_transcript(segments, config, llm_call)
        source = "transcript_candidates"
        needs_confirm = True  # 转写候选写法可能是错的，需确认
    else:
        terms, source, needs_confirm = [], "none", False
    # 并入人工补齐（权威，去重）
    merged = _dedup_terms(list(terms) + list(manual_terms))
    return {"terms": merged, "source": source, "needs_confirmation": needs_confirm}


# 兼容旧接口：generate_lexicon 保留名，改为走 build_lexicon（不再凭空生成）。
def generate_lexicon(
    domain: str,
    materials: str,
    config: PostProcessConfig,
    llm_call: LlmCall,
) -> list[str]:
    """[已改为抽取式] 从材料抽取专名（domain 仅作日志/兼容，不再用于凭空生成）。"""
    return build_lexicon(config, llm_call, materials=materials)["terms"]


# ---- 编排 -------------------------------------------------------------------


def run_postprocess(
    segments: list[dict[str, Any]],
    config: PostProcessConfig,
    llm_call: LlmCall | None = None,
) -> dict[str, Any]:
    """按 L0→(去重)→(纠错)=L1→(顺滑)=L2 顺序处理 canonical segments（原地）。

    - text 最终为 L1（无损），供下游摘要/决策/证据链使用。
    - display_text 为 L2（若开启顺滑），仅供展示。
    - 返回各步统计与版本，写入 stage 产物。
    """
    stats: dict[str, Any] = {"version": POSTPROCESS_VERSION, "steps": {}}

    if config.enable_dedup:
        stats["steps"]["dedup"] = dedup_overlaps(segments, config)

    if config.enable_proper_correction:
        if llm_call is None:
            stats["steps"]["proper_correction"] = {"skipped": "no_llm"}
        else:
            stats["steps"]["proper_correction"] = correct_proper_nouns(
                segments, config, llm_call
            )

    # L1 定格：text 此刻即无损修复版。
    for seg in segments:
        seg.setdefault("display_text", seg["text"])

    if config.enable_smoothing:
        if llm_call is None:
            stats["steps"]["smoothing"] = {"skipped": "no_llm"}
        else:
            stats["steps"]["smoothing"] = smooth_for_display(segments, config, llm_call)

    stats["nonempty_after"] = sum(1 for s in segments if s["text"].strip())
    return stats

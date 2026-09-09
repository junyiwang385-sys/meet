"""B 阶段:金标生成提示词(去实例化,防跨会污染)。

原则:提示词内**零本场真实词**;举例一律占位式;role 只在原文明确自述时才填。
生成模型建议 fable5(与后续 judge=opus-5、候选=本项目 4B 三者分离)。
"""
from __future__ import annotations

# 结构化输出 schema(供 agent 的 StructuredOutput 约束)
GOLDEN_SCHEMA = {
    "type": "object",
    "required": ["meeting", "overview", "parts", "fine_chapters",
                 "core_facts", "decisions", "action_items", "speakers"],
    "properties": {
        "meeting": {"type": "string"},
        "duration_s": {"type": "number"},
        "speech_end_s": {"type": "number"},
        "note": {"type": "string"},
        "overview": {"type": "object", "required": ["text", "refs"]},
        "parts": {"type": "array"},
        "fine_chapters": {"type": "array"},
        "core_facts": {"type": "array"},
        "decisions": {"type": "array"},
        "action_items": {"type": "array"},
        "speakers": {"type": "array"},
    },
}

_RULES = """你是会议评测参考金标整理员。只依据下方【参考时间线】(官方人工逐字标注)产出金标 JSON。你是在整理参考标签,不是评价任何模型输出。

严格规则:
1. 事实唯一来源是【参考时间线】。不得补充常识、真实姓名、原因、数字、owner、deadline。宁可少写,不可编造。
2. fine_chapters:12–18 个,按时间连续、不重叠;第一章 start_ref 必须是首段,最后一章 end_ref 必须是最后有效发言段;相邻章不得漏段。每章给 title、topic(一句,便于判相关性)、start_ref/end_ref、start_s/end_s(秒)、summary(2–4 句含重要事实/决定/分歧/限制)、refs(区间内代表性 seg-id)。
3. parts:2–4 个大部分,每个含 id、title、fine_ids;每个 fine_chapter 属于且仅属于一个 part,全覆盖。
4. core_facts:8–14 条原子事实(一条只表达一个重点,不复制 overview,不整章写成一条)。每条:id、text、importance(major|critical)、refs、**anchors(2–5 个)**。
   - anchors = 该事实成立必须出现的关键 token,优先数字、专名、人名、核心动作词;**必须是该 refs 原文里真实出现的词**(数字按原文写法,如原文说"八十万"就写"八十万")。
5. decisions:记录会上形成的决定与提议。每条:id、text、status(decision=明确拍板/要求执行;proposal=仅建议/列入考虑/讨论方向)、owner(明确责任说话人的 speaker_id,否则 null)、refs。**严禁把 proposal 标成 decision。**
6. action_items:只记录明确要求或明确承诺执行的任务;owner/deadline 不明确必须为 null,不推断;没有则空数组。
7. speakers:必须且只能包含时间线里出现的 speaker_id。每个:speaker_id、role、overview(只概括其本人说的)、refs。**role 仅当该发言人在原文明确自述身份时才填(如自称某职务),否则填 null——不要猜、不要按发言内容推断职务。**
8. 口误处理:原文明显口误保留原词,并在 summary/text 里用"(疑口误,应为…)"标注,不改写。
9. 静默/无发言时段不编任何内容;所有章节与事实止于最后有效发言段。
10. 所有 refs/start_ref/end_ref 必须是时间线里真实出现的 seg-id。提议不写成决定,可能性不写成事实,他人观点不错误归因。
11. overview 必须是对象 {"text": "...", "refs": ["seg-..."]},不能是纯字符串。speakers/decisions 等每个元素都是对象。

举例只示形式(占位,非本场内容):
  core_fact 示例形如 {"id":"CF01","text":"某部门上半年<某指标>约<数字>","importance":"critical","anchors":["<数字>","<某指标>"],"refs":["seg-000123"]}
  decision 示例形如 {"id":"D01","text":"<明确要求执行的事>","status":"decision","owner":"<seg里的speaker_id或null>","refs":["seg-..."]}

只输出一个合法 JSON 对象,顶层含 meeting/duration_s/speech_end_s/note/overview/parts/fine_chapters/core_facts/decisions/action_items/speakers。"""


def build_gen_prompt(meeting_id: str, timeline_text: str,
                     duration_s: float, speech_end_s: float) -> str:
    header = (
        f"meeting_id:{meeting_id}\n"
        f"duration_s:{duration_s:.1f}  speech_end_s:{speech_end_s:.1f}"
        f"(最后有效发言到此,之后为静默,不要标注)\n"
    )
    return f"{_RULES}\n\n=== 元信息 ===\n{header}\n=== 参考时间线 ===\n{timeline_text}\n"

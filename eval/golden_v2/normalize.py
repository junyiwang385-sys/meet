"""共用文本归一:去空白/标点 + 中文数字↔阿拉伯规范化。

目标:让 "八十万" / "80万" / "800000" 归一到同一形,anchor 校验与召回匹配才不被
数字形态坑到(旧 keypoint_recall 的单字映射会把 "八十万" 错成 "810万")。

覆盖:中文数字(含 十百千万亿 组合)、阿拉伯数+万/亿。
已知边界:纯位读法年份(如 "二零二零")不做位置展开——一般不作为事实 anchor。
"""
from __future__ import annotations

import re

_D = {"零": 0, "〇": 0, "一": 1, "壹": 1, "幺": 1, "二": 2, "贰": 2, "两": 2,
      "三": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6,
      "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9}
_U = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}

_PUNC = re.compile(r"[\s，。、；：！？,.;:!?…—\-~·()（）【】\[\]\"“”'’]+")
_CNNUM = re.compile(r"[零〇一壹幺二贰两三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟万萬亿億]+")
_ARBIG = re.compile(r"(\d+(?:\.\d+)?)\s*([万萬亿億])")


def _cn_section(s: str):
    """解析 <万 的中文数字段,如 八十 / 三百五。无法解析返回 None。"""
    total, cur = 0, 0
    for ch in s:
        if ch in _D:
            cur = _D[ch]
        elif ch in _U:
            total += (cur or 1) * _U[ch]
            cur = 0
        else:
            return None
    return total + cur


def _cn2int(s: str):
    for big, val in (("亿", 100000000), ("億", 100000000), ("万", 10000), ("萬", 10000)):
        if big in s:
            head, tail = s.split(big, 1)
            h = _cn2int(head) if head else 1
            t = _cn2int(tail) if tail else 0
            if h is None or t is None:
                return None
            return h * val + t
    return _cn_section(s)


def _canon_numbers(text: str) -> str:
    def ar(m: re.Match) -> str:
        n = float(m.group(1))
        unit = 10000 if m.group(2) in "万萬" else 100000000
        return str(int(n * unit))

    text = _ARBIG.sub(ar, text)

    def cn(m: re.Match) -> str:
        v = _cn2int(m.group(0))
        return str(v) if v is not None else m.group(0)

    return _CNNUM.sub(cn, text)


def norm(text) -> str:
    text = _PUNC.sub("", str(text or "")).lower()
    return _canon_numbers(text)


if __name__ == "__main__":
    for a, b in [("八十万", "80万"), ("七十万", "70万"), ("十", "10"), ("三百五十", "350")]:
        print(a, "->", norm(a), "|", b, "->", norm(b), "| match=", norm(a) == norm(b))

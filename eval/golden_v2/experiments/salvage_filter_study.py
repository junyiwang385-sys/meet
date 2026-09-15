"""跨 5 组(g1-g5)研究数字打捞的噪声/信号,验证通用过滤规则。纯确定性,无 Ollama。"""
import json, re, pathlib
BR = pathlib.Path(r"C:/Users/Admin/meet/ops/board-results/2026-09-02_003_enrichment-wire-board-verify")
IDS = {"g1":"学校","g2":"化妆品","g3":"学校S03","g4":"R002S08","g5":"R002S04"}

RAW = re.compile(r"[0-9零〇一二两三四五六七八九十百千万亿]+")
UNIT = "场|个|名|位|人|次|天|日|周|月|年|季度|元|块|万|亿|百万|千|度|%|％|倍|成|半|分之|斤|公斤|台|间|栋|层|门|瓶|箱|届|分钟|小时|米|套|条|项|轮|岁|折"
NUM = r"[几多好]?[0-9零〇一二两三四五六七八九十百千万亿]+"
DATA = re.compile(NUM + r"(?:" + UNIT + r")[一-鿿]{0,4}")

_FILLER = re.compile(r"^[一两幺]?[个块]")            # 一个/两个/一块(儿) 填充("a"/"一起")
def is_noise(s):
    if re.search(r"我是|我叫|我姓", s): return True          # 报工号/自我介绍
    if re.match(r"^[零〇幺]", s): return True                  # 零/幺打头=工号ID
    if _FILLER.match(s): return True                          # 一个/一块 填充(保留三个+/专用量词)
    if re.fullmatch(r"[一二两三]?[度样]", s[:2]): return True  # 一度/一样 语气
    return False

def transcript(g):
    d = json.load(open(BR/g/"harness/meeting_result.json", encoding="utf-8"))
    return "".join((s.get("text") or "") for s in (d.get("transcript") or {}).get("segments") or [])

for g, name in IDS.items():
    tx = transcript(g)
    raw = list(dict.fromkeys(tx[max(0,m.start()-7):m.end()+7].strip() for m in RAW.finditer(tx)))
    struct = list(dict.fromkeys(m.group(0) for m in DATA.finditer(tx)))
    clean = [x for x in struct if not is_noise(x)]
    dropped = [x for x in struct if is_noise(x)]
    print(f"\n===== {g} ({name}) =====")
    print(f"原始窗口={len(raw)}  结构化(数字+单位)={len(struct)}  过黑名单后clean={len(clean)}  黑名单丢={len(dropped)}")
    print("clean 样例:", " | ".join(clean[:22]))
    if dropped: print("黑名单丢的:", " | ".join(dropped[:10]))
    print("原始窗口里被结构化排除的(前12,多为噪声):", " | ".join([r for r in raw if not any(r in s or s in r for s in struct)][:12]))

# -*- coding: utf-8 -*-
"""Phase3 评测:base Qwen3-4B vs base+LoRA 在 train_L golden 子集上比 core_fact 召回(+低频)。
一次加载 base(4bit)→ 跑 base → 挂 LoRA(peft)→ 跑 tuned。输入=train_L TextGrid 建块(同训练口径)。
判据:召回↑=微调有效。 用法: python eval_finetune.py  (默认 g1/g2/g5)"""
import json, pathlib, sys, re
BASE = r"E:/models/Qwen3-4B"; ADAPTER = r"E:/models/qwen3-4b-meetlora"
MEET = [("g1","20200707_L_R001S04C01"),("g2","20200708_L_R002S05C01"),("g5","20200709_L_R002S04C01")]
OUT = r"C:/Users/Admin/meet/eval/finetune/_out/phase3_eval.txt"
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT/"src")); sys.path.insert(0, str(ROOT/"eval"/"golden_v2"))
from build_timeline import parse_textgrid
from meeting_agent.stages.product_summary import (
    _build_compact_ref_map, _build_compact_speaker_map, _block_summary_messages, BudgetPolicy)
from meeting_agent.stages.topic_segmentation import segment_blocks, SegmentationConfig
from meeting_agent.stages.summary_profiles import GENERIC_PROFILE
import score_candidate as SC

# 评测建块用小预算(ctx5120→块≤~3700token):匹配训练(数据过滤到≤4096)+ 装下 8G 推理。
# base/tuned 都用同一套块,对比公平。
BUDGET = BudgetPolicy(ctx=5120, output_tokens=768, safety_tokens=512, chars_per_token=1.55,
                      fixed_overhead_tokens=128, overlap_segments=0)

def blocks_of(mid):
    segs=[s for s in parse_textgrid(rf"E:/train_L/TextGrid/{mid}.TextGrid") if (s.get("text") or "").strip()]
    _,cref=_build_compact_ref_map(segs); _,cspk=_build_compact_speaker_map([s["speaker_id"] for s in segs])
    by=  {s["segment_id"]:s for s in segs}
    out=[]
    for b in segment_blocks(segs, BUDGET, SegmentationConfig())["blocks"]:
        bs=[by[i] for i in b["segment_ids"]]
        out.append(_block_summary_messages(bs, None, ref_map=cref, speaker_map=cspk, profile=GENERIC_PROFILE, key_data=None))
    return out

def main():
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    from peft import PeftModel
    log=open(OUT,"w",encoding="utf-8")
    def w(*a): s=" ".join(str(x) for x in a); print(s,flush=True); log.write(s+"\n"); log.flush()
    tok=AutoTokenizer.from_pretrained(BASE)
    bnb=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type="nf4",bnb_4bit_compute_dtype=torch.bfloat16,bnb_4bit_use_double_quant=True)
    model=AutoModelForCausalLM.from_pretrained(BASE,quantization_config=bnb,device_map={"":0},dtype=torch.bfloat16,attn_implementation="sdpa").eval()
    w("[loaded base 4bit]")

    # 预备各会 blocks + golden
    data={}
    for tag,mid in MEET:
        data[tag]=(blocks_of(mid), json.loads((ROOT/"eval/golden_v2/out"/f"{mid}.golden.json").read_text(encoding="utf-8")))
        w(f"{tag}: {len(data[tag][0])} 块")

    def gen_meeting(msgs_list):
        outs=[]
        for msgs in msgs_list:
            text=tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
            inputs=tok(text, return_tensors="pt", truncation=True, max_length=3072).to("cuda")  # 硬截断保 8G 装得下
            with torch.no_grad():
                g=model.generate(**inputs, max_new_tokens=512, do_sample=False)
            outs.append(tok.decode(g[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True))
            del inputs, g; torch.cuda.empty_cache()
        return SC.norm(" ".join(outs))

    def eval_all(label):
        w(f"\n===== {label} =====")
        rec=[]; lf=[]
        for tag,mid in MEET:
            cand=gen_meeting(data[tag][0]); r=SC.score(data[tag][1], cand)
            w(f"  {tag}: 召回={r['core_fact_recall']} ({r['recalled']}/{r['total']})  低频={r['lowfreq_recall']} ({r['lowfreq']})")
            rec.append(r['core_fact_recall'] or 0); lf.append(r['lowfreq_recall'] or 0)
        w(f"  均值: 召回={sum(rec)/len(rec):.3f}  低频={sum(lf)/len(lf):.3f}")
        return sum(rec)/len(rec)

    base_avg=eval_all("BASE(原始 4B)")
    model=PeftModel.from_pretrained(model, ADAPTER); model.eval()
    w("[attached LoRA]")
    tuned_avg=eval_all("TUNED(base+LoRA)")
    w(f"\n================ 判决 ================")
    w(f"核心事实召回 均值: BASE={base_avg:.3f} → TUNED={tuned_avg:.3f}  Δ={tuned_avg-base_avg:+.3f}")
    w("召回↑=微调有效; 若↓或持平需查(数据少/块长/过拟合)")
    log.close()

if __name__=="__main__":
    main()

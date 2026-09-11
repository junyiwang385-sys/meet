# -*- coding: utf-8 -*-
"""Phase2 QLoRA 训练:Qwen3-4B(4bit nf4)+ LoRA,在 train8.sft.jsonl(块摘要 chat 对)上微调。
本机 4060 8G:batch1 + grad accum + 梯度检查点 + paged_adamw_8bit + max_seq 8192(过滤超长)。
只训 assistant(prompt 掩码)。产出 LoRA adapter → E:/models/qwen3-4b-meetlora。
⚠️ 必须有 __main__ 守卫:Windows 上 DataLoader/worker 用 spawn 会重 import 本模块,
   无守卫会导致每个 worker 重新加载一遍 4B 模型、多进程抢 GPU(实测踩过)。"""
import json, pathlib, os
from transformers.trainer_utils import get_last_checkpoint
BASE = r"E:/models/Qwen3-4B"
DATA = r"C:/Users/Admin/meet/eval/finetune/_data/train8.sft.jsonl"
OUT  = r"E:/models/qwen3-4b-meetlora"
MAX_SEQ = 4096   # 8G 显存:5120 仍反向OOM,降4096(留17/44对)+ 显式启用GC

def main():
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    from peft import LoraConfig, prepare_model_for_kbit_training
    from trl import SFTConfig, SFTTrainer
    from datasets import Dataset

    tok = AutoTokenizer.from_pretrained(BASE)
    rows = []
    for ln in pathlib.Path(DATA).read_text(encoding="utf-8").splitlines():
        if not ln.strip(): continue
        msgs = json.loads(ln)["messages"]
        # 正确数 token:渲染成字符串再 tokenize(tokenize=True 返回 BatchEncoding,len()=2 是坑)
        s = tok.apply_chat_template(msgs, tokenize=False, enable_thinking=False)
        if len(tok(s)["input_ids"]) <= MAX_SEQ:
            rows.append({"messages": msgs})
    print(f"训练对: {len(rows)} (<= {MAX_SEQ} token)", flush=True)
    ds = Dataset.from_list(rows)

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(BASE, quantization_config=bnb, device_map={"": 0},
                                                 dtype=torch.bfloat16, attn_implementation="sdpa")
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model.enable_input_require_grads()  # QLoRA+PEFT+GC 关键:否则梯度检查点不真生效→激活爆显存
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                      target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"])
    print("MODEL_READY, building trainer...", flush=True)

    cfg = SFTConfig(
        output_dir=OUT, max_length=MAX_SEQ, packing=False,
        per_device_train_batch_size=1, gradient_accumulation_steps=16,
        num_train_epochs=3, learning_rate=2e-4, lr_scheduler_type="cosine", warmup_steps=2,
        logging_steps=1, save_strategy="epoch", bf16=True, optim="paged_adamw_8bit",
        gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
        assistant_only_loss=True, report_to="none", dataset_num_proc=1, dataloader_num_workers=0,
    )
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds, peft_config=lora, processing_class=tok)
    ckpt = get_last_checkpoint(OUT) if os.path.isdir(OUT) else None
    print(f"TRAINER_READY, resume_from={ckpt}, start train()", flush=True)
    trainer.train(resume_from_checkpoint=ckpt)
    trainer.save_model(OUT); tok.save_pretrained(OUT)
    print("DONE_TRAIN adapter ->", OUT, flush=True)
    print("max VRAM GB:", round(torch.cuda.max_memory_allocated()/1e9, 2), flush=True)

if __name__ == "__main__":
    main()

"""实测 LoRA 训练吞吐, 用于回答"最小模型 + 5 小时能训多少"。
只测真实的前向+反向一步的耗时, 不跑完整训练。
"""
import json
import os
import time
import sys

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model

MODEL_DIR = r"D:\Projects\qwen-local-tool-agent\models\Qwen3-0.6B"
OUT = r"D:\Projects\qwen-local-tool-agent\bench\train_bench.log"

results = []


def log(s=""):
    print(s)
    results.append(s)


def build_batch(tok, seq_len, batch_size):
    """构造与真实任务同量级的一条样本: system(schema+规则) + user + assistant(JSON)"""
    system = ("你是日程助手。把用户的中文请求转换为 JSON，只输出 JSON。"
              "time 一律放进 when 对象；与日程无关的请求输出 reject。") * 3
    user = "为我的周二上午九点添加一个计算机原理的课程"
    assistant = json.dumps({
        "status": "ok",
        "commands": [{
            "module": "class", "action": "add", "title": "计算机原理",
            "when": {"date_kind": "weekday", "date_value": "TU", "week_ref": "this",
                     "time": "09:00", "period": "am"}
        }]
    }, ensure_ascii=False)
    text = f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n{assistant}<|im_end|>"
    enc = tok(text, return_tensors="pt", truncation=True, max_length=seq_len, padding="max_length")
    ids = enc["input_ids"].repeat(batch_size, 1)
    attn = enc["attention_mask"].repeat(batch_size, 1)
    labels = ids.clone()
    labels[attn == 0] = -100
    return ids, attn, labels


def bench(seq_len, batch_size=1, steps=6, warmup=1):
    tok = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(MODEL_DIR, dtype=torch.float32, trust_remote_code=True)
    cfg = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, cfg)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    model.train()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4)

    ids, attn, labels = build_batch(tok, seq_len, batch_size)
    n_tok = int(attn.sum().item())

    times = []
    for i in range(steps + warmup):
        t0 = time.perf_counter()
        out = model(input_ids=ids, attention_mask=attn, labels=labels)
        out.loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        dt = time.perf_counter() - t0
        if i >= warmup:
            times.append(dt)

    avg = sum(times) / len(times)
    log(f"  seq_len={seq_len} batch={batch_size} → {avg:.2f} s/step  ({n_tok / avg:.0f} tok/s)"
        f"  可训练参数={trainable/1e6:.1f}M / 总参数={total/1e6:.0f}M")
    return avg, n_tok


log("=" * 78)
log(f"LoRA 训练吞吐实测 — Qwen3-0.6B, CPU(torch {torch.__version__}), float32")
log(f"torch 线程数: {torch.get_num_threads()}")
log("=" * 78)

runs = {}
for seq in (256, 512):
    avg, n_tok = bench(seq)
    runs[seq] = (avg, n_tok)

log("")
log("=" * 78)
log("换算: 5 小时能训多少 (batch=1, 单条样本; 实际用梯度累积等价于更大 batch)")
log("=" * 78)
BUDGET_H = 5.0
for seq, (avg, n_tok) in runs.items():
    steps_5h = BUDGET_H * 3600 / avg
    log(f"  seq_len={seq}: {steps_5h:,.0f} 步 ≈ {steps_5h:,.0f} 条样本 "
        f"→ 3,000 条数据集可跑 {steps_5h/3000:.1f} 个 epoch")
    log(f"             反向推算: 要跑满 3 个 epoch(9,000 步) 需要 {9000*avg/3600:.1f} 小时")

log("")
log("参考: 0.6B 的算力约是 1.7B 的 1/3, 同等配置下 1.7B 的 s/step 约为上表 x2.5~3")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(results))
print(f"\n已写入 {OUT}")

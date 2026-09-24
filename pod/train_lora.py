#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen3-0.6B LoRA 微调: 中文自然语言 -> 结构化日程工具调用

设计要点:
  1. 基座直接读镜像预置的 /model/ModelScope/Qwen/Qwen3-0.6B, 不下载
  2. 只在 assistant 段算 loss (prompt 全部 mask 成 -100), 否则模型会学会复读用户输入
  3. 训练文本走 Qwen3 官方 chat template 且 enable_thinking=False,
     与推理时完全一致 (否则会出现 train/inference 不一致的 think 块)
  4. 手写训练循环, 每步打印 loss / 速度 / ETA, 便于预估进度
"""
import argparse
import json
import math
import os
import time

import torch
from torch.utils.data import Dataset, DataLoader
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model, TaskType

MODEL_DIR = "/model/ModelScope/Qwen/Qwen3-0.6B"


class SchedDataset(Dataset):
    """一次性预分词到内存。

    原来在 __getitem__ 里实时做 apply_chat_template(Jinja) + 两次分词,
    每取一个样本要几十毫秒, 把 GPU 饿到 19% 利用率。预分词后热路径上没有 CPU 工作。
    """

    def __init__(self, path, tok, max_len):
        self.tok = tok
        self.max_len = max_len
        self.items = []
        self.skipped = 0
        rows = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))

        for r in rows:
            msgs = r["messages"]
            sys_user, assistant = msgs[:2], msgs[2]
            prompt_text = tok.apply_chat_template(
                sys_user, tokenize=False, add_generation_prompt=True, enable_thinking=False)
            full_text = tok.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=False, enable_thinking=False)
            prompt_ids = tok(prompt_text, add_special_tokens=False)["input_ids"]
            full_ids = tok(full_text, add_special_tokens=False)["input_ids"]

            n_prompt = len(prompt_ids)
            if n_prompt >= len(full_ids):
                self.skipped += 1
                continue
            if len(full_ids) > max_len:
                self.skipped += 1
                full_ids = full_ids[:max_len]
                n_prompt = min(n_prompt, max_len - 1)
            labels = list(full_ids)
            for j in range(n_prompt):
                labels[j] = -100
            self.items.append((torch.tensor(full_ids), torch.tensor(labels)))

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]


def collate(batch):
    maxlen = max(len(ids) for ids, _ in batch)
    pad = 0
    input_ids, labels, attn = [], [], []
    for ids, lab in batch:
        n = maxlen - len(ids)
        input_ids.append(ids.tolist() + [pad] * n)
        labels.append(lab.tolist() + [-100] * n)
        attn.append([1] * len(ids) + [0] * n)
    return {
        "input_ids": torch.tensor(input_ids),
        "labels": torch.tensor(labels),
        "attention_mask": torch.tensor(attn),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="/workspace/data/train.jsonl")
    ap.add_argument("--test", default="/workspace/data/test.jsonl")
    ap.add_argument("--out", default="/workspace/output")
    ap.add_argument("--model", default=MODEL_DIR)
    ap.add_argument("--precision", default="auto", choices=["auto", "bf16", "fp16", "fp32"],
                    help="Turing(2080Ti, sm_75) 不支持 bf16, 必须用 fp16")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--accum", type=int, default=2)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=640)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--log-every", type=int, default=10)
    ap.add_argument("--save-every", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = True
    os.makedirs(a.out, exist_ok=True)
    dev = torch.device("cuda")

    # 精度: Turing 无原生 bf16。
    # 注意: torch.cuda.is_bf16_supported() 在 sm_75 上会返回 True —— 它把"模拟支持"
    # 也算进去了, 而模拟 bf16 会大量 upcast 到 fp32, 显存爆掉还更慢。
    # 正确的判据是算力: 原生 bf16 需要 sm_80+。
    if a.precision == "auto":
        cap = torch.cuda.get_device_capability(0)
        a.precision = "bf16" if cap[0] >= 8 else "fp16"
        print(f"[auto] 算力 sm_{cap[0]}{cap[1]} -> 选用 {a.precision} "
              f"(is_bf16_supported() 报的是 {torch.cuda.is_bf16_supported()}, 不可信)", flush=True)
    use_amp = a.precision in ("bf16", "fp16")
    amp_dtype = torch.bfloat16 if a.precision == "bf16" else torch.float16
    scaler = torch.amp.GradScaler("cuda", enabled=(a.precision == "fp16"))

    print("=" * 84, flush=True)
    print(f"Qwen3-0.6B LoRA 微调 | 设备 {torch.cuda.get_device_name(0)} "
          f"(sm_{''.join(map(str, torch.cuda.get_device_capability(0)))})", flush=True)
    print(f"精度={a.precision} | amp={use_amp} | GradScaler={scaler.is_enabled()}", flush=True)
    print("=" * 84, flush=True)

    tok = AutoTokenizer.from_pretrained(a.model)
    t_tok = time.time()
    ds = SchedDataset(a.train, tok, a.max_len)
    dl = DataLoader(ds, batch_size=a.batch, shuffle=True, collate_fn=collate, num_workers=0)
    try:
        ds_test = SchedDataset(a.test, tok, a.max_len)
        dl_test = DataLoader(ds_test, batch_size=a.batch, shuffle=False, collate_fn=collate, num_workers=0)
    except Exception:
        ds_test, dl_test = None, None

    print(f"\n预分词完成({time.time()-t_tok:.1f}s): 训练集 {len(ds)} 条"
          f"(跳过 {ds.skipped}) | 测试集 {len(ds_test) if ds_test else 0} 条", flush=True)

    lens = sorted(len(x[0]) for x in ds.items)
    print(f"token 长度: 中位 {lens[len(lens)//2]} | p90 {lens[int(len(lens)*0.9)]} | 最大 {lens[-1]}", flush=True)

    sample_ids, sample_lab = ds[0]
    nprompt = sum(1 for x in sample_lab.tolist() if x == -100)
    print(f"样本0: 总 token={len(sample_ids)}, prompt(mask)={nprompt}, "
          f"监督 token={len(sample_ids)-nprompt}", flush=True)
    sup = [t for t, l in zip(sample_ids.tolist(), sample_lab.tolist()) if l != -100]
    print("监督段内容: " + tok.decode(sup)[:300], flush=True)

    # fp16 走 AMP: 权重保持 fp32 作为 master weights, 由 autocast 负责算子降精度
    load_dtype = torch.bfloat16 if a.precision == "bf16" else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        a.model, dtype=load_dtype, attn_implementation="sdpa")
    model = get_peft_model(model, LoraConfig(
        task_type=TaskType.CAUSAL_LM, r=a.lora_r, lora_alpha=a.lora_alpha,
        lora_dropout=0.05, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    ))
    model.to(dev)
    model.train()
    model.print_trainable_parameters()

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)

    total_steps = max(1, int(len(dl) * a.epochs / a.accum))
    warmup = max(1, int(total_steps * 0.03))

    def lr_at(step):
        if step < warmup:
            return a.lr * step / warmup
        prog = (step - warmup) / max(1, total_steps - warmup)
        return a.lr * 0.5 * (1 + math.cos(math.pi * prog))

    print(f"\n微批 batch={a.batch} | 梯度累积={a.accum} | 等效 batch={a.batch*a.accum} | "
          f"每 epoch {len(dl)} 微批 | 总优化步数={total_steps} | max_len={a.max_len}\n", flush=True)

    t_start = time.time()
    step = 0
    micro = 0
    running = 0.0
    n_run = 0
    grad_norm_acc = 0.0
    stop = False

    for epoch in range(math.ceil(a.epochs)):
        if stop:
            break
        for batch in dl:
            batch = {k: v.to(dev) for k, v in batch.items()}
            with torch.autocast("cuda", dtype=amp_dtype, enabled=use_amp):
                out = model(**batch)
                loss = out.loss / a.accum
            scaler.scale(loss).backward()
            running += out.loss.item()
            n_run += 1
            micro += 1

            if micro % a.accum == 0:
                lr = lr_at(step)
                for g in opt.param_groups:
                    g["lr"] = lr
                # fp16 下必须先 unscale 再裁剪, 否则梯度范数是放大过的
                scaler.unscale_(opt)
                gn = torch.nn.utils.clip_grad_norm_(params, 1.0)
                scaler.step(opt)
                scaler.update()
                opt.zero_grad(set_to_none=True)
                step += 1

                if step % a.log_every == 0 or step == 1:
                    el = time.time() - t_start
                    sps = step / el
                    remain = (total_steps - step) / sps if sps > 0 else 0
                    print(f"[ep{epoch+1}] step {step}/{total_steps} "
                          f"loss={running/n_run:.4f} lr={lr:.2e} gnorm={float(gn):.2f} "
                          f"{sps:.2f} step/s | 已用 {el/60:.1f}min | "
                          f"ETA {remain/60:.1f}min ({remain/total_steps*100:.0f}% 剩余)", flush=True)
                    running, n_run = 0.0, 0

                if step % a.save_every == 0:
                    ck = os.path.join(a.out, f"checkpoint-{step}")
                    model.save_pretrained(ck)
                    print(f"  -> 已保存 {ck}", flush=True)

                if step >= total_steps:
                    stop = True
                    break

    elapsed = time.time() - t_start
    print(f"\n训练完成: {step} 步, 用时 {elapsed/60:.2f} 分钟 ({step/elapsed:.2f} step/s)", flush=True)

    # 验证集 loss
    if dl_test is not None:
        model.eval()
        tot, nb = 0.0, 0
        with torch.no_grad(), torch.autocast("cuda", dtype=amp_dtype, enabled=use_amp):
            for batch in dl_test:
                batch = {k: v.to(dev) for k, v in batch.items()}
                tot += model(**batch).loss.item()
                nb += 1
        print(f"验证集 loss: {tot/max(1,nb):.4f} (共 {nb} 条)", flush=True)

    adir = os.path.join(a.out, "lora_adapter")
    model.save_pretrained(adir)
    tok.save_pretrained(adir)
    print(f"LoRA adapter 已保存: {adir}", flush=True)

    # 合并导出, 便于转 GGUF 或直接推理
    try:
        model.eval()
        merged = model.merge_and_unload()
        mdir = os.path.join(a.out, "merged")
        merged.save_pretrained(mdir, safe_serialization=True)
        tok.save_pretrained(mdir)
        print(f"合并模型已保存: {mdir}", flush=True)
    except Exception as e:
        print(f"合并失败(不影响 adapter 使用): {type(e).__name__}: {e}", flush=True)

    print(f"总耗时: {(time.time()-t_start)/60:.2f} 分钟", flush=True)


if __name__ == "__main__":
    main()

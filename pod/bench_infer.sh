#!/usr/bin/env bash
echo "=== GPU 现状 ==="
nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu,power.draw,clocks.sm --format=csv,noheader
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
echo
echo "=== 生成吞吐实测 (tok/s) ==="
cd ~/sched-lora && ~/ft-env/bin/python - <<'PY'
import time, torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
SYS = ("你是日程助手，把用户的中文请求转换为 JSON，只输出 JSON。"
 "status: ok=可执行, clarify=信息不足要反问, reject=与日程无关。"
 "commands[].module 取 class/exam/meeting/assignment/alarm/reminder/memo；"
 "when 含 date_kind(absolute/offset_day/weekday/unspecified)、date_value、week_ref(this/next)、"
 "time(HH:MM)、period(am/pm/none)、fuzzy、duration_min。"
 "规则：时间只能放进 when，不要放进 location 或 target_ref；不要自己计算绝对日期；"
 "用户没说上午下午时 period 填 none；与日程无关的请求用 reject 且 commands 为空。")
tok = AutoTokenizer.from_pretrained("base/Qwen3-0.6B")
if tok.pad_token_id is None: tok.pad_token = tok.eos_token
for impl in ("sdpa", "eager"):
    try:
        base = AutoModelForCausalLM.from_pretrained("base/Qwen3-0.6B", dtype=torch.float16,
                                                     attn_implementation=impl)
        m = PeftModel.from_pretrained(base, "output/lora_adapter").to("cuda").eval()
        p = tok.apply_chat_template([{"role":"system","content":SYS},
             {"role":"user","content":"下周二上午九点加一门计算机原理，在教三201"}],
             tokenize=False, add_generation_prompt=True, enable_thinking=False)
        ids = tok(p, return_tensors="pt").to("cuda")
        n_in = ids["input_ids"].shape[1]
        with torch.no_grad():
            m.generate(**ids, max_new_tokens=8, do_sample=False, pad_token_id=tok.pad_token_id)  # warmup
            torch.cuda.synchronize()
            t0 = time.time()
            out = m.generate(**ids, max_new_tokens=120, do_sample=False, pad_token_id=tok.pad_token_id)
            torch.cuda.synchronize()
            dt = time.time() - t0
        n_out = out.shape[1] - n_in
        print(f"  attn={impl:<6} prompt={n_in} tok  生成={n_out} tok  用时={dt:.2f}s  "
              f"→ {n_out/dt:.1f} tok/s")
        del m, base
        torch.cuda.empty_cache()
    except Exception as e:
        print(f"  attn={impl}: 失败 {type(e).__name__}: {str(e)[:100]}")
PY

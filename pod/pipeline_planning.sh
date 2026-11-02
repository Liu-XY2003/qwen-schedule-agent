#!/usr/bin/env bash
# 二阶段「规划抽取」训练流水线
#
# 与一阶段 pipeline_v4.sh 的区别:
#   · 数据集换成 gen_planning_dataset.py（反向构造 + 标签校验）
#   · 多一步 verify_planning_dataset.py —— **不通过就不训练**
#   · 基座默认换 1.7B/4B（一阶段的 0.6B 已经被 schedule_command 占用了）
#
# 用法:
#   BASE=~/sched-lora/base/Qwen3-1.7B bash pipeline_planning.sh 1.7b
#   BASE=~/sched-lora/base/Qwen3-4B   bash pipeline_planning.sh 4b
set -u
cd ~/sched-lora || exit 1
source ~/sched-lora/llama/env.sh 2>/dev/null || true

TAG="${1:-1.7b}"
BASE="${BASE:-}"
if [ -z "$BASE" ]; then
  case "$TAG" in
    1.7b) BASE=~/sched-lora/base/Qwen3-1.7B ;;
    4b)   BASE=~/sched-lora/base/Qwen3-4B ;;
    *)    echo "未知 TAG=$TAG，请用 BASE=... 显式指定基座"; exit 1 ;;
  esac
fi

PY="${PY:-$HOME/ft-env/bin/python}"
DATA=~/sched-lora/data-plan-$TAG
OUT=~/sched-lora/output-plan-$TAG
LOG=~/sched-lora/train-plan-$TAG.log

echo "########## 规划抽取训练 ($TAG) $(date) ##########"

echo
echo "=== 1. 让出显存 ==="
pkill -f "llama-server" 2>/dev/null
pkill -f "uvicorn app:app" 2>/dev/null
sleep 3
nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader

echo
echo "=== 2. 生成数据集 ==="
rm -rf "$DATA"
$PY gen_planning_dataset.py --train 4000 --test 400 --outdir "$DATA" 2>&1 | tail -7

echo
echo "=== 3. 校验标签正确性（不通过直接停） ==="
if ! $PY verify_planning_dataset.py "$DATA/train.jsonl"; then
  echo "!! 标签校验失败, 拒绝训练。反向构造的前提就是标签一定对, 不满足就不能用。"
  exit 2
fi
if ! $PY verify_planning_dataset.py "$DATA/test.jsonl"; then
  echo "!! 测试集标签校验失败, 拒绝训练。"
  exit 2
fi
echo "标签校验通过"

echo
echo "=== 4. 训练 ==="
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
rm -rf "$OUT"
$PY train_lora.py \
  --model "$BASE" \
  --train "$DATA/train.jsonl" \
  --test  "$DATA/test.jsonl" \
  --out   "$OUT" \
  --epochs 3 --batch 4 --accum 4 --precision fp16 --log-every 50 \
  > "$LOG" 2>&1
echo "训练结束:"; grep -E "训练完成|验证集|总耗时|FAIL|Error" "$LOG" | tail -5

echo
echo "=== 5. 转 GGUF + 量化 ==="
cd ~/sched-lora/gguf-work/llama.cpp-b11109 || exit 1
SRC="$OUT/merged"
F16=~/sched-lora/gguf-work/sched-plan-$TAG-f16.gguf
Q8=~/sched-lora/gguf-work/sched-plan-$TAG-Q8_0.gguf
Q4=~/sched-lora/gguf-work/sched-plan-$TAG-Q4_K_M.gguf
$PY convert_hf_to_gguf.py "$SRC" --outfile "$F16" --outtype f16 2>&1 | tail -2
"$LLAMA_BIN/llama-quantize" "$F16" "$Q8" Q8_0 2>&1 | tail -2
"$LLAMA_BIN/llama-quantize" "$F16" "$Q4" Q4_K_M 2>&1 | tail -2
ls -la "$Q8" "$Q4"

echo
echo "=== 6. 起 llama-server 供评测 ==="
pkill -f "llama-server" 2>/dev/null; sleep 2
nohup "$LLAMA_BIN/llama-server" -m "$Q4" -ngl 99 -c 8192 \
  --host 0.0.0.0 --port 18999 --jinja -np 1 --reasoning off \
  > ~/sched-lora/llama-plan-$TAG.log 2>&1 < /dev/null &
for i in $(seq 1 60); do
  sleep 2
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:18999/health 2>/dev/null)" = "200" ] \
    && { echo "llama-server ready ($((i*2))s)"; break; }
done

echo
echo "########## 完成 $(date) ##########"
echo "下一步（在本地机器上跑回归）:"
echo "  .venv-planner\\\\Scripts\\\\python.exe bridge\\\\eval_extraction.py --port 18999 --zero-shot --label \"$TAG 微调后\""
echo "  .venv-planner\\\\Scripts\\\\python.exe bridge\\\\eval_extraction.py --port 18999 --label \"$TAG 微调后+fewshot\""

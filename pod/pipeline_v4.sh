#!/usr/bin/env bash
set -u
cd ~/sched-lora || exit 1
source ~/sched-lora/llama/env.sh

echo "########## v4 流水线 $(date) ##########"

echo "=== 1. 停服务让出显存 ==="
pkill -f "uvicorn app:app" 2>/dev/null
pkill -f "llama-server" 2>/dev/null
sleep 3
nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader

echo
echo "=== 2. 生成 v4 数据 ==="
rm -rf data-v4
~/ft-env/bin/python gen_dataset.py --train 4000 --test 400 --outdir ~/sched-lora/data-v4 2>&1 | tail -5

echo
echo "=== 3. 训练 v4 ==="
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
rm -rf output-v4
~/ft-env/bin/python train_lora.py \
  --model ~/sched-lora/base/Qwen3-0.6B \
  --train ~/sched-lora/data-v4/train.jsonl \
  --test  ~/sched-lora/data-v4/test.jsonl \
  --out   ~/sched-lora/output-v4 \
  --epochs 3 --batch 4 --accum 4 --precision fp16 --log-every 50 \
  > ~/sched-lora/train-v4.log 2>&1
echo "训练结束:"; grep -E "训练完成|验证集|总耗时" ~/sched-lora/train-v4.log

echo
echo "=== 4. 转 GGUF + 量化 ==="
cd ~/sched-lora/gguf-work/llama.cpp-b11109
SRC=~/sched-lora/output-v4/merged
F16=~/sched-lora/gguf-work/qwen3-0.6b-sched-v4-f16.gguf
Q8=~/sched-lora/gguf-work/qwen3-0.6b-sched-v4-Q8_0.gguf
~/ft-env/bin/python convert_hf_to_gguf.py "$SRC" --outfile "$F16" --outtype f16 2>&1 | tail -2
"$LLAMA_BIN/llama-quantize" "$F16" "$Q8" Q8_0 2>&1 | tail -2
ls -la "$Q8"

echo
echo "=== 5. 启动 llama-server (v4) ==="
cd ~/sched-lora
nohup "$LLAMA_BIN/llama-server" -m "$Q8" -ngl 99 -c 2048 \
  --host 0.0.0.0 --port 8080 --jinja -np 1 --no-warmup \
  > ~/sched-lora/llama-server.log 2>&1 < /dev/null &
for i in $(seq 1 40); do
  sleep 2
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8080/health 2>/dev/null)" = "200" ] \
    && { echo "llama-server ready ($((i*2))s)"; break; }
done

echo
echo "=== 6. 启动 App ==="
nohup ~/ft-env/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8800 \
      > ~/sched-lora/app.log 2>&1 < /dev/null &
for i in $(seq 1 30); do
  sleep 2
  if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8800/api/health 2>/dev/null)" = "200" ]; then
    echo "App ready ($((i*2))s)"; curl -s http://127.0.0.1:8800/api/health; echo; break
  fi
done

echo
echo "########## v4 流水线完成 $(date) ##########"
ls -la ~/sched-lora/gguf-work/*v4*.gguf

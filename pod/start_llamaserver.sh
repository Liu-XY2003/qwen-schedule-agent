#!/usr/bin/env bash
source ~/sched-lora/llama/env.sh
pkill -f "llama-server" 2>/dev/null
sleep 2
M=~/sched-lora/gguf-work/qwen3-0.6b-sched-Q8_0.gguf
nohup "$LLAMA_BIN/llama-server" \
  -m "$M" -ngl 99 -c 2048 --host 0.0.0.0 --port 8080 \
  --jinja -np 1 --no-warmup \
  > ~/sched-lora/llama-server.log 2>&1 < /dev/null &
echo "launched pid=$!"
for i in $(seq 1 40); do
  sleep 2
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8080/health 2>/dev/null)
  if [ "$code" = "200" ]; then echo "ready after $((i*2))s"; exit 0; fi
done
echo "未就绪:"; tail -25 ~/sched-lora/llama-server.log; exit 1

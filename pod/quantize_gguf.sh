#!/usr/bin/env bash
cd ~/sched-lora/llama || exit 1
LLAMA=$PWD/llama-b11109
CUDART=$PWD/cudart-llama-b11109-bin-ubuntu-cuda-12.8-x64
export LD_LIBRARY_PATH="$LLAMA:$CUDART:${LD_LIBRARY_PATH:-}"

# 修好 env.sh (原来的在 set -u 下会报未绑定变量)
cat > ~/sched-lora/llama/env.sh <<EOF
export LLAMA_BIN=$LLAMA
export LD_LIBRARY_PATH=$LLAMA:$CUDART:\${LD_LIBRARY_PATH:-}
EOF
echo "=== env.sh ==="; cat ~/sched-lora/llama/env.sh

F16=~/sched-lora/gguf-work/qwen3-0.6b-sched-f16.gguf
echo
echo "=== 量化 ==="
for Q in Q8_0 Q4_K_M; do
  O=~/sched-lora/gguf-work/qwen3-0.6b-sched-${Q}.gguf
  echo "--- $Q ---"
  "$LLAMA/llama-quantize" "$F16" "$O" "$Q" 2>&1 | tail -4
  ls -la "$O" 2>/dev/null
done

echo
echo "=== 结果 ==="
ls -la ~/sched-lora/gguf-work/*.gguf

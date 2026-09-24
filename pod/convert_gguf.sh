#!/usr/bin/env bash
set -u
cd ~/sched-lora || exit 1
TAG=b11109
mkdir -p gguf-work && cd gguf-work

echo "=== 1. 下载 llama.cpp 源码 (转换脚本在里面) ==="
if [ ! -f "llama.cpp-$TAG/convert_hf_to_gguf.py" ]; then
  curl -sL --retry 3 --max-time 900 -o src.tar.gz \
    "https://github.com/ggml-org/llama.cpp/archive/refs/tags/$TAG.tar.gz"
  echo "  源码包 $(du -h src.tar.gz | cut -f1)"
  tar xzf src.tar.gz
fi
ls -d llama.cpp-$TAG

echo
echo "=== 2. 装 gguf 包 ==="
~/ft-env/bin/pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple gguf 2>&1 | tail -2
~/ft-env/bin/python -c "import gguf; print('gguf', gguf.__version__ if hasattr(gguf,'__version__') else 'ok')"

echo
echo "=== 3. 转换为 F16 GGUF ==="
SRC=~/sched-lora/output-v3/merged
OUT=~/sched-lora/gguf-work/qwen3-0.6b-sched-f16.gguf
cd llama.cpp-$TAG
~/ft-env/bin/python convert_hf_to_gguf.py "$SRC" --outfile "$OUT" --outtype f16 2>&1 | tail -15
ls -la "$OUT" 2>/dev/null || echo "  转换失败"

echo
echo "=== 4. 量化到 Q8_0 与 Q4_K_M ==="
source ~/sched-lora/llama/env.sh
for Q in Q8_0 Q4_K_M; do
  O=~/sched-lora/gguf-work/qwen3-0.6b-sched-${Q}.gguf
  echo "--- $Q ---"
  "$LLAMA_BIN/llama-quantize" "$OUT" "$O" "$Q" 2>&1 | tail -3
  ls -la "$O" 2>/dev/null
done

echo
echo "=== 5. 结果 ==="
ls -la ~/sched-lora/gguf-work/*.gguf

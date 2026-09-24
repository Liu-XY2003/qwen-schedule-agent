#!/usr/bin/env bash
set -u
cd ~/sched-lora || exit 1
TAG=b11109
mkdir -p llama && cd llama
GH="https://github.com/ggml-org/llama.cpp/releases/download/$TAG"
MIRROR="https://ghproxy.net/https://github.com/ggml-org/llama.cpp/releases/download/$TAG"

fetch() {
  local f="$1"
  [ -f "$f" ] && { echo "  [cached] $f"; return 0; }
  echo "  下载 $f"
  curl -sL --retry 3 --retry-delay 2 --speed-limit 51200 --speed-time 30 --max-time 1200 -o "$f" "$GH/$f"
  local sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
  if [ "$sz" -lt 100000 ]; then
    rm -f "$f"
    echo "  直连失败, 走 ghproxy"
    curl -sL --retry 3 --speed-limit 51200 --speed-time 30 --max-time 1800 -o "$f" "$MIRROR/$f"
    sz=$(stat -c%s "$f" 2>/dev/null || echo 0)
  fi
  echo "    -> $((sz/1024/1024)) MB"
}

echo "=== 1. 下载 CUDA 预编译版 ==="
fetch "llama-$TAG-bin-ubuntu-cuda-12.8-x64.tar.gz"
fetch "cudart-llama-$TAG-bin-ubuntu-cuda-12.8-x64.tar.gz"

echo
echo "=== 2. 解压 ==="
for f in *.tar.gz; do
  [ -f "$f" ] || continue
  echo "  解压 $f"
  tar xzf "$f" 2>/dev/null
done
ls -la

echo
echo "=== 3. 定位可执行文件 ==="
find . -maxdepth 3 -name 'llama-server' -o -maxdepth 3 -name 'llama-cli' | head
BIN=$(dirname "$(find . -maxdepth 3 -name 'llama-server' | head -1)")
echo "BIN=$BIN"
echo "$BIN" > /tmp/llama_bin_path

echo
echo "=== 4. 验证 CUDA 设备 ==="
if [ -n "$BIN" ] && [ -x "$BIN/llama-cli" ]; then
  LD_LIBRARY_PATH="$BIN:$LD_LIBRARY_PATH" "$BIN/llama-cli" --list-devices 2>&1 | head -20
else
  echo "  没找到 llama-cli"
fi

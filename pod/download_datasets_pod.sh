#!/usr/bin/env bash
# 在 pod 上下载能找到的公开函数调用/工具调用数据集
# 优先 hf-mirror (实测 926KB/s), 失败回退 huggingface.co (走平台预置学术加速代理, 185KB/s)
DEST=/workspace/data/external
mkdir -p "$DEST"
cd "$DEST"

MIRROR=https://hf-mirror.com
HF=https://huggingface.co

get() {
  local repo="$1" file="$2" out="$3" minbytes="$4"
  if [ -f "$out" ] && [ "$(stat -c%s "$out")" -ge "$minbytes" ]; then
    echo "[cached] $out ($(du -h "$out" | cut -f1))"
    return 0
  fi
  for base in "$MIRROR" "$HF"; do
    url="$base/datasets/$repo/resolve/main/$file"
    echo "[GET] $out  <- $base"
    curl -sL --retry 2 --max-time 1800 -o "$out" "$url"
    sz=$(stat -c%s "$out" 2>/dev/null || echo 0)
    if [ "$sz" -ge "$minbytes" ]; then
      echo "  [OK] $out = $((sz/1024/1024)) MB"
      return 0
    else
      echo "  [fail] got $sz bytes, trying next"
      rm -f "$out"
    fi
  done
  echo "  [GIVEUP] $out"
  return 1
}

echo "=========== 数据集下载开始 $(date) ==========="

get NobodyExistsOnTheInternet/xlam-function-calling-60k xlam_function_calling_60k.json xlam60k.json 10000000
get MadeAgents/xlam-irrelevance-7.5k          xlam-7.5k-irrelevancek.json        xlam_irrelevance_7.5k.json 1000000
get minpeter/xlam-function-calling-60k-parsed xlam-function-calling-60k.parquet  xlam60k_parsed.parquet 5000000
get NousResearch/hermes-function-calling-v1   func-calling.json                  hermes_func-calling.json 5000000
get NousResearch/hermes-function-calling-v1   func-calling-singleturn.json       hermes_func-calling-singleturn.json 5000000
get NousResearch/hermes-function-calling-v1   json-mode-singleturn.json          hermes_json-mode-singleturn.json 1000000
get NousResearch/hermes-function-calling-v1   glaive-function-calling-5k.json    hermes_glaive-5k.json 5000000
get Team-ACE/ToolACE                          data.json                          toolace_data.json 10000000
get Salesforce/APIGen-MT-5k                   apigen-mt_5k.json                  apigen_mt_5k.json 20000000
get glaiveai/glaive-function-calling-v2       glaive-function-calling-v2.json    glaive_function_calling_v2.json 50000000

echo
echo "=========== 下载结束 $(date) ==========="
ls -la "$DEST"
echo "总计: $(du -sh $DEST | cut -f1)"

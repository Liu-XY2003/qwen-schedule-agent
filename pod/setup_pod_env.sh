#!/usr/bin/env bash
# 在 CompShare GPU pod 上准备训练环境
set -x
echo "=========== 环境准备开始 $(date) ==========="

echo "--- 0. 探测已有 conda / python 环境 ---"
cat /root/.conda/environments.txt 2>/dev/null
ls -d /opt/conda /usr/local/miniconda3 /root/miniconda3 /root/anaconda3 2>/dev/null
echo "python3: $(python3 --version)"

echo "--- 1. 安装 pip 与 venv ---"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-pip python3-venv
echo "pip: $(python3 -m pip --version)"

echo "--- 2. 建虚拟环境 (放 /workspace, 与 / 同盘但独立) ---"
mkdir -p /workspace
if [ ! -d /workspace/venv ]; then
  python3 -m venv /workspace/venv
fi
/workspace/venv/bin/python -m pip install -q -U pip setuptools wheel
/workspace/venv/bin/python -m pip --version

echo "--- 3. 安装训练依赖 (Linux 上 PyPI 的 torch 自带 CUDA 运行时) ---"
/workspace/venv/bin/python -m pip install -q \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    torch transformers peft trl datasets accelerate

echo "--- 4. 验证 ---"
/workspace/venv/bin/python - <<'PY'
import torch, transformers, peft, trl, datasets
print("torch        :", torch.__version__)
print("cuda 可用    :", torch.cuda.is_available())
print("cuda 版本    :", torch.version.cuda)
if torch.cuda.is_available():
    print("GPU          :", torch.cuda.get_device_name(0))
    print("显存         :", round(torch.cuda.get_device_properties(0).total_memory/1024**3, 1), "GB")
    print("算力         :", torch.cuda.get_device_capability(0))
print("transformers :", transformers.__version__)
print("peft         :", peft.__version__)
print("trl          :", trl.__version__)
print("datasets     :", datasets.__version__)
PY

echo "--- 5. 冒烟测试: 在 4090 上做一次前向 ---"
/workspace/venv/bin/python - <<'PY'
import torch, time
d = torch.device("cuda")
a = torch.randn(4096, 4096, device=d, dtype=torch.bfloat16)
b = torch.randn(4096, 4096, device=d, dtype=torch.bfloat16)
for _ in range(5): a @ b
torch.cuda.synchronize()
t0 = time.perf_counter()
for _ in range(50): a @ b
torch.cuda.synchronize()
dt = time.perf_counter() - t0
print(f"bf16 matmul 4096^3: {2*4096**3*50/dt/1e12:.1f} TFLOPS   (4090 理论峰值 ~165 TFLOPS bf16)")
PY

echo "--- 6. 磁盘情况 ---"
df -h / /workspace

echo "=========== 环境准备完成 $(date) ==========="

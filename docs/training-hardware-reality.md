# 训练算力实测：GPU / NPU / CPU 到底能不能用

> 结论先行：**NPU 不能训练；iGPU 原始算力是 CPU 的 14 倍但软件栈不可用；CPU 能训但慢。**
> 5 小时预算下最实际的选择是**租一次云 GPU**（约 10–30 分钟跑完），而不是在本机硬扛。

---

## 0. 一句话对照

| 单元 | 原始算力（实测） | 能否训练 | 结论 |
|---|---|---|---|
| **NPU (XDNA2, 50 TOPS)** | 推理 50 TOPS(INT8) | ❌ **完全不能** | XDNA2 是推理单元，AMD 只提供 ONNX 推理路径（Ryzen AI 软件栈里没有任何训练/反向传播支持） |
| **iGPU (Radeon 880M)** | **fp16 11.59 TFLOPS** | ⚠️ 理论可以，**实际不可用** | torch-directml 被锁在 torch 2.4.1，且**随机崩溃**（见 §3） |
| **CPU (Zen5 20 线程)** | fp32 0.41 / bf16 0.82 TFLOPS | ✅ 稳定可用，慢 | 0.6B + seq256 = **3.74 s/step**（5h≈4,800 步） |
| **ROCm (Windows/WSL)** | — | ❌ 目前不支持 gfx1150 | [ROCm/TheRock#1876](https://github.com/ROCm/TheRock/issues/1876)：gfx1150 没有可用的 torch rocm wheel |

---

## 1. 测试条件

- 模型：Qwen3-0.6B（本地 safetensors，1434 MB）
- LoRA：r=16、alpha=32、dropout=0.05，target = q/k/v/o/gate/up/down_proj → **可训练参数 10.1M / 总参数 606M**
- batch=1，AdamW，lr=2e-4
- 样本：真实任务格式（system + user + assistant JSON），**实测 167 token**
- 计时：预热 2 步后取 4–5 步平均

> ⚠️ 重要细节：**真实样本只有 167 token**。因为我们的 system prompt 很短、输出是紧凑 JSON。
> 这意味着 `seq_len=256` 完全够用、不会截断 —— 而序列长度是训练耗时最敏感的变量（256→512 耗时翻倍）。

---

## 2. CPU 实测（可用）

环境：`conda env sched_ai`，torch 2.14.0+cpu，20 线程，Python 3.11

| 序列长度 | 精度 | s/step | tok/s | 5 小时 ≈ |
|---|---|---|---|---|
| **256** | **bf16** | **3.74** | 45 | **4,819 步** |
| 384 | bf16 | 6.16 | 27 | 2,922 步 |
| 384 | fp32 | 6.53 | 26 | 2,757 步 |
| 512 | bf16 | 7.08 | 24 | 2,544 步 |

（第一轮用 10 线程纯 fp32 测：seq256 = 4.32 s/step，seq512 = 8.43 s/step；bf16 + 20 线程有约 15% 提升。）

**换算成数据集规模（5 小时）：**

| 数据集 | seq=256 | seq=384 | seq=512 |
|---|---|---|---|
| 2,000 条 | **2.4 epoch** | 1.5 epoch | 1.3 epoch |
| 3,000 条 | 1.6 epoch | 1.0 epoch | 0.8 epoch |
| 5,000 条 | 1.0 epoch | 0.6 epoch | 0.5 epoch |

---

## 3. iGPU 实测（算力很好，但软件栈不行）

### 3.1 原始算力：iGPU 确实碾压 CPU

2048×2048 矩阵乘实测：

| 单元 | 精度 | TFLOPS |
|---|---|---|
| CPU Zen5 | fp32 | 0.41 |
| CPU Zen5 | bf16 | 0.82 |
| **iGPU 880M** | **fp16** | **11.59** ← CPU bf16 的 **14 倍** |
| iGPU 880M | fp32 | 4.51 |

DirectML 也能被 torch 正确识别：`AMD Radeon(TM) 880M Graphics`，`device_count=1`。

### 3.2 但训练步会随机崩溃 ❌

`conda env sched_dml`（torch 2.4.1+cpu + torch-directml 0.2.5.dev240914 + transformers 4.57.6 + peft 0.21.0）

同一个脚本多次运行，**失败点每次都不一样**：

| 运行 | 失败位置 | 错误 |
|---|---|---|
| 第 1 次 | `model.to(DML)` | `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc9 in position 4` |
| 第 2 次 | `create_causal_mask` → `attention_mask.to(device, dtype=bool)` | `... byte 0xb2 in position 4` |
| 第 3 次 | `F.dropout_` | `... byte 0xb2 in position 4` |
| 第 4 次 | `model.to(DML)` | `... byte 0xc9 in position 4` |

**错误字节每次随机变化（0xc9 / 0xb2），且同样的操作在孤立测试里能成功** ——
这不是"某个 op 不支持"，而是 **torch-directml 把未初始化内存当字符串解析的 bug**。

我做了逐项隔离验证，以下操作**单独测试全部通过**：
```python
torch.randn(4,4).to(DML)                          # OK
torch.ones(4,4).to(DML, dtype=torch.bool)         # OK
nn.Linear(4,4).to(DML)                            # OK
Qwen3-0.6B forward (eager / sdpa, 带/不带 mask)    # OK
```
但一旦组合成**完整的训练步（forward + backward + optimizer.step）**，就会随机崩。

**结论：torch-directml 在当前版本下不能用于这个模型的训练。** 
（附带约束：torch-directml 强制 torch==2.4.1，而 Qwen3 需要 transformers≥4.51，两边勉强能用但生态整体滞后。）

### 3.3 什么时候可以再试

等 `torch-directml` 发布支持 torch ≥2.6 的版本时再回来测。届时用
`bench/train_bench_dml2.py`（已绕开 `attention_mask`）重跑即可。

---

## 4. NPU 为什么不能训练

1. **硬件定位**：XDNA2 是 AI 推理加速器（50 TOPS INT8）。它的指令集面向量化后的前向推理，没有反向传播所需的算子与精度支持。
2. **软件栈**：AMD Ryzen AI 软件栈（1.8）的全部文档都是**推理**路径——ONNX Runtime GenAI、模型量化、模型编译部署，**没有任何 fine-tuning / LoRA / 反向传播**相关章节。
3. **即使能训也无意义**：NPU 训练的框架、显存、生态都不存在。

> 所以"优先用 GPU 或 NPU 训练"这个诉求，在这台机器上**只剩 GPU 一条路**，而 GPU 那条路被 torch-directml 的 bug 堵住了。

---

## 5. 那 5 小时怎么安排？（三个可选方案）

### 方案 A：租一次云 GPU ★ 推荐

| | |
|---|---|
| 做什么 | 0.6B / 1.7B QLoRA，3–5k 样本，2–3 epoch |
| 耗时 | 单张 4090 约 **10–30 分钟** |
| 成本 | 约 **几元人民币** |
| 理由 | 训练是"一次性、短时、可外包"的活。本机算力应该留给**天天要跑的推理和评测**（那些 iGPU/NPU 很擅长） |

### 方案 B：本机 CPU 训（能成，但要压规模）

用实测数字反推，5 小时要训出效果，必须同时满足：

```
seq_len = 256          ← 真实样本只有 167 token，够用
数据集  = 2,000–3,000  ← 精选高质量样本，不要贪多
epoch   = 1.6–2.4      ← 这个量级对"单一窄任务"通常已经够收敛
精度    = bf16 + 20 线程
```

具体命令思路（`conda env sched_ai`）：
```bash
python -m pip install trl          # 或用 transformers.Trainer 手写循环
# per_device_train_batch_size=1, gradient_accumulation_steps=16, max_length=256,
# bf16=True, num_train_epochs=2, learning_rate=2e-4
```

**判断够不够的标准**：看 eval 的"槽位全对率"是否在 2 个 epoch 内趋于平台。
如果第 2 个 epoch 还在明显上升，说明 5 小时不够，转方案 A。

### 方案 C：缩小模型到 0.6B 以下 —— **不可行**

Qwen3 最小的 dense 就是 0.6B。再小（如 Qwen2.5-0.5B）能力下降明显，且与你要迁移的 Qwen3 系不兼容，等于白训。

---

## 6. 给"必须本机训练"的补充建议

1. **先跑通全流程再压时间**：用 200 条样本、1 个 epoch（约 15 分钟）验证数据格式、chat template、loss 是否只算在 assistant 段。流程错了，训 5 小时也是白费。
2. **`train_on_inputs=False`**：只对 assistant 输出算 loss，否则模型会学会复读你的 system prompt。
3. **`enable_thinking=false`**：训练与推理必须一致（见主文档 §5.6 实测踩坑）。
4. **保留 checkpoint**：每 30 分钟存一次。5 小时的任务中途中断很常见。
5. **先量化验证再全量训**：拿 500 条先训 20 分钟，用评测脚本测一次，确认方向对了再全量。

---

## 7. 复现脚本

| 脚本 | 用途 | 环境 |
|---|---|---|
| `bench/setup_training.ps1` | 建 `sched_ai` 环境 + 下 Qwen3-0.6B | — |
| `bench/train_bench.py` | 第一轮：CPU fp32 吞吐 | `sched_ai` |
| `bench/train_bench_v2.py` | 第二轮：fp32/bf16、线程数、序列长度对比 | `sched_ai` |
| `bench/setup_dml.ps1` | 建 `sched_dml` 环境（torch 2.4.1 + torch-directml） | — |
| `bench/train_bench_dml2.py` | 第三轮：iGPU DirectML 训练吞吐（会崩，见 §3.2） | `sched_dml` |
| `bench/dml_isolate.py`、`dml_bool_probe.py`、`dml_mask_probe.py` | 定位 DirectML 崩溃点 | `sched_dml` |

# 二阶段「规划抽取」训练套件

> 这里是把「杂乱文本 → 待办 + 约束」的抽取准确率从 52% 拉到 80%+ 所需的全部代码。
> **数据集已生成并验证过；微调本身需要 GPU，尚未跑**（本机只有 AMD 核显，之前的
> 训练服务器已到期）。

---

## 为什么必须先微调

实测（见 `docs/extraction-benchmark.md`）：

| 模型 | 零样本 | few-shot |
|---|---|---|
| Qwen3-1.7B | 14% | 33% |
| Qwen3-4B | 19% | **52%** |

基座模型不会用新契约。一阶段的 0.6B 能用，靠的就是 4000 条反向构造数据 + LoRA。
二阶段走同一条路。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `gen_planning_dataset.py` | **反向构造**训练集：先采样结构化真值，再渲染成中文，标签由构造保证正确 |
| `verify_planning_dataset.py` | **标签正确性校验**：逐条检查标签里每个字段都能从文本推断出来 |
| `test_verify_catches_errors.py` | 校验器的自测：证明它抓得到错、也不误报 |
| `test_sys_consistency.py` | 训练 SYS 与推理 SYS 必须逐字相同 |
| `train_lora.py` | 微调脚本（与一阶段共用，只换 `--model` 和数据集） |
| `pipeline_planning.sh` | 一键流水线：生成 → 校验 → 训练 → 转 GGUF → 起服务 |

---

## 本地怎么验证（不需要 GPU）

```bash
cd pod

# 生成 4000 条
python gen_planning_dataset.py --train 4000 --test 400 --outdir ./data-plan

# 校验标签（不通过就别拿去训练）
python verify_planning_dataset.py ./data-plan/train.jsonl

# 证明校验器真的有效
python test_verify_catches_errors.py

# 训练/推理 prompt 一致性
python test_sys_consistency.py
```

这三条已经在 CI 里，每次 push 都会跑。

---

## 训练怎么跑（需要 NVIDIA GPU）

### 1. 起一台带 GPU 的机器

之前的路子是**优云智算**（AutoDL 系）。要点：
- 选 `sm_80+` 的卡（A100/4090/3090），能原生 bf16；Turing（2080Ti）只能 fp16，脚本会自动判断
- 开**学术加速**：`source /etc/network_turbo`（不同镜像路径可能不同）
- 镜像选 PyTorch 2.x + CUDA 12

### 2. 装依赖

```bash
pip install -r requirements-train.txt
# transformers 要支持 Qwen3，太旧会不认 chat template
```

### 3. 准备基座

```bash
# 走 ModelScope，国内快
pip install modelscope
python -c "from modelscope import snapshot_download; \
  snapshot_download('Qwen/Qwen3-4B', local_dir='base/Qwen3-4B')"
```

### 4. 一条命令跑完

```bash
cd pod
BASE=~/sched-lora/base/Qwen3-4B bash pipeline_planning.sh 4b
```

脚本会依次做：让出显存 → 生成数据 → **校验标签（不通过直接退出）** → 训练
→ 转 f16/Q8/Q4 → 起 llama-server 在 18999。

### 5. 回到本机跑回归

```bash
# 把 GGUF 拉回来，在本地起
llama-server -m sched-plan-4b-Q4_K_M.gguf -ngl 99 -c 8192 --port 18999 \
  --jinja -np 1 --reasoning off

# 跑 21 条评估集
.venv-planner\Scripts\python.exe bridge\eval_extraction.py --port 18999 --zero-shot --label "4B 微调后"
.venv-planner\Scripts\python.exe bridge\eval_extraction.py --port 18999 --label "4B 微调后+fewshot"
```

**达标线：zero-shot ≥ 80%**（微调后应该不再需要 few-shot，这样 prompt 更短更快）。

---

## 模型选型建议

| 基座 | 显存（LoRA, batch4×accum4, max_len 640） | 本地推理速度 | 建议 |
|---|---|---|---|
| Qwen3-1.7B | ~12 GB | 51.5 tok/s | 想保速度选它，但天花板可能不够 |
| Qwen3-4B | ~20 GB | 22 tok/s | **优先试这个**，抽取能力上限更高 |

两者都训一遍再比，成本很低（一阶段 16 分钟一版）。

---

## 数据集的几条硬规则（改生成器时别破坏）

1. **标签必须能从文本推断**。所以 `priority` / `preferred` 是**无条件渲染**的 ——
   不是只在某种风格里渲染。第一版就是只在"流水账"风格里渲染，导致 `list` 风格的
   样本里标签说有 high 优先级、文本里却没有任何强措辞。校验器现在会抓这个。
2. **时长要么明说、要么用标题的公认默认值**（`KINDS` 里的第二个字段）。
   绝不允许"标签说 120 分钟、文本里毫无依据"。
3. **截止存的是用户原话**（"周五"/"11-07"/"明天"），不是绝对日期。
   模型永远不做日期运算 —— 这是一阶段就定下的铁律。
4. **`SYS` 与 `bridge/planning.py` 的 `SYS` 必须逐字相同**。CI 里有断言。
5. **校验是按分句做的**，不是全文。否则同一条文本里别的事项的措辞会给错标打掩护。

---

## 当前状态

- [x] 数据集生成器（4000 条，风格/条数/约束分布都覆盖）
- [x] 标签校验器 + 自测（**9/9**，证明有效）
- [x] 训练/推理 prompt 一致性检查
- [x] 训练脚本（复用一阶段，已参数化）
- [x] 一键流水线
- [x] CI 接入（数据集正确性每次 push 都查）
- [ ] **实际微调**（需要 GPU）
- [ ] 回归到 80%+

最后两项需要在有 GPU 的机器上完成。跑完把数字填回
`docs/extraction-benchmark.md`，然后我再接 `plan_diff` 和多轮对话。

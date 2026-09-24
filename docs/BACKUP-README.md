# 日程助手 · 备份包说明

备份时间：2026-09-23
来源：优云智算 / <your-host> (`<user>@<your-host>`, Tailscale)，`~/sched-lora/`

---

## 一、这个项目是什么

一句话自然语言 → 本地微调模型 → 结构化指令 → **可视化日历**。

```
用户输入 "下下周二上午九点加一门计算机原理，在教三201"
   ↓ Qwen3-0.6B + LoRA（微调后）
   ↓ llama.cpp + json_schema 约束解码 → 必然合法的 JSON
{"status":"ok","commands":[{"module":"class","action":"add","title":"计算机原理",
  "when":{"date_kind":"weekday","date_value":"TU","week_offset":2,"time":"09:00","period":"am"},
  "location":"教三201"}]}
   ↓ 确定性时间解析 resolve_time()
   ↓ SQLite + Web 日历
写进日程：2026-10-06 09:00
```

---

## 二、备份内容

```
software/                     全部源码
  app.py                      Web 应用（FastAPI 后端 + 单页日历前端）
  executor.py                 执行层：时间解析 + 校验 + SQLite
  schema_models.py            Pydantic 契约 + 漂移检查
  gen_dataset.py              训练数据生成器（反向构造法）
  train_lora.py               LoRA 训练脚本（fp16/AMP）
  eval_lora3.py               评测脚本
  schedule_command.v1.json    v1 契约（历史）
  schedule_command.v2.json    v2 契约（当前，含 week_offset / month_offset）

schema/schedule_command.v2.json   唯一事实源

data/
  data-v4/train.jsonl         4000 条训练数据
  data-v4/test.jsonl          371 条测试数据
  schedule.db                 SQLite 日程库（含已录入的日程）
  train-v4.log                最终一版训练日志

model/
  lora_adapter/               LoRA 权重（50MB，可叠加到 Qwen3-0.6B 基座）
  qwen3-0.6b-sched-v4-Q8_0.gguf     部署用（~640MB，llama.cpp 直接加载）
  qwen3-0.6b-sched-v4-Q4_K_M.gguf   更小版本（~400MB）
```

**未包含**（可重新获取）：
- `base/Qwen3-0.6B`（1.5GB）— 官方基座，`modelscope download Qwen/Qwen3-0.6B`
- `output-v4/merged`（2.4GB）— 合并后的 HF 模型，可由 `lora_adapter` + 基座重新合并
- llama.cpp 运行时（745MB）— 从 GitHub Release 重新下载

---

## 三、如何跑起来（新机器）

### 1. 准备 Python 环境

```bash
python3 -m venv venv && source venv/bin/activate
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    fastapi uvicorn pydantic jsonschema
```

> 注意：**部署推理不需要 torch/transformers**。App 通过 HTTP 调用 llama-server。

### 2. 准备 llama.cpp

从 https://github.com/ggml-org/llama.cpp/releases 下载：
- `llama-bXXXXX-bin-ubuntu-cuda-12.8-x64.tar.gz`（CUDA 版）
- `cudart-llama-bXXXXX-bin-ubuntu-cuda-12.8-x64.tar.gz`（CUDA 运行时）

解压后设置：
```bash
export LLAMA_BIN=/path/to/llama-bXXXXX
export LD_LIBRARY_PATH=$LLAMA_BIN:/path/to/cudart:$LD_LIBRARY_PATH
```

### 3. 启动推理服务

```bash
$LLAMA_BIN/llama-server \
  -m model/qwen3-0.6b-sched-v4-Q8_0.gguf \
  -ngl 99 -c 2048 --host 0.0.0.0 --port 8080 --jinja -np 1
```

> `--jinja` 是必须的：它让服务按模型内置的 chat template 渲染对话，
> 并启用 `response_format=json_schema` 约束解码。

### 4. 启动 App

```bash
mkdir -p run && cd run
cp ../software/*.py ../schema/schedule_command.v2.json .
SCHED_LLAMA_URL=http://127.0.0.1:8080 \
  python -m uvicorn app:app --host 0.0.0.0 --port 8800
```

浏览器打开 `http://<IP>:8800`。

---

## 四、如果想重新训练

```bash
# 1. 生成数据（可复现，同种子同结果）
python gen_dataset.py --train 4000 --test 400 --outdir ./data-new

# 2. 训练（2080 Ti 上约 16 分钟；4090 上约 5 分钟）
python train_lora.py --model /path/to/Qwen3-0.6B \
    --train data-new/train.jsonl --test data-new/test.jsonl \
    --out output-new --epochs 3 --batch 4 --accum 4 --precision fp16

# 3. 转 GGUF
git clone --depth 1 https://github.com/ggml-org/llama.cpp
python llama.cpp/convert_hf_to_gguf.py output-new/merged \
    --outfile model-new-f16.gguf --outtype f16
$LLAMA_BIN/llama-quantize model-new-f16.gguf model-new-Q8_0.gguf Q8_0
```

**关键：`gen_dataset.py` 的 `SYS` 常量必须与 `app.py` 的 `SYS` 逐字节一致。**
system prompt 是模型契约的一部分 —— 实测换掉它之后真实用例通过率从 85% 掉到 0%。

---

## 五、设计要点（踩过的坑）

1. **不要让模型算日期**。模型只输出语义槽位（`date_kind`/`week_offset`/`period`…），
   绝对时间全部由 `resolve_time()` 确定性推导。实测模型会把"今年12月31号"算成 2023 年。

2. **`week_ref` 枚举表达不了"下下周"**。v1 用 `this`/`next`，模型只能把它压成 `next`
   → 静默写错一周。v2 改成数值 `week_offset`，同样的改动也解决了"下个月3号"。

3. **约束解码能让越界值结构上不可能出现**。实测无约束时 `fuzzy:"before"`（枚举外）
   会漏出来；加 `json_schema` 后 16/16 全部合规，且**速度几乎无损**（272 vs 281 tok/s）。

4. **推理后端决定速度**。HF `transformers.generate()` 逐 token 有 CPU 同步，实测仅
   **11.5 tok/s**；llama.cpp 是 **272 tok/s**（24 倍）。端到端延迟从 3.8s 降到 0.26s。

5. **反向构造法生成训练数据**：先采样结构化记录 → 再渲染成中文 → 标签由构造保证正确。
   反过来（先写句子再让模型标 JSON）会引入标注噪声。
   生成器有自校验：所有"必须出现在句中"的短语都会断言，不满足则丢弃该样本。

6. **口缩略说法要显式覆盖**："明早/今早/明晚/今晚"这些缩略形式如果训练数据里没有，
   模型会把日期整个丢掉（"加个明早八点的闹钟" → 落到今天）。

---

## 六、验收基线（可用来自查）

训练好后应满足：

| 测试 | 脚本 | 期望 |
|---|---|---|
| 契约无漂移 | `python schema_models.py schedule_command.v2.json` | ✅ 无漂移 |
| 日期解析回归 | `test_date_parsing.py`（13 例） | 13/13 |
| 偏移解析 | `test_offsets.py`（18 例） | 18/18 |
| 数据集可执行 | `verify_dataset_e2e.py`（4372 条） | failed=0 |
| 端到端验收 | `acceptance_v2.py`（21 例） | 21/21 |

关键样例：
- `下下周二上午九点…` → `2026-10-06`
- `下个月3号上午九点…` → `2026-10-03`
- `十月23号下午10点19…` → `2026-10-23 22:19`
- `加个明早八点的闹钟` → 明天 `08:00`
- `今天天气怎么样` → `reject`
- `今年12月31号…` → 追问（模型不知道当前年份，不猜）

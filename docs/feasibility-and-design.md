# 本地 Qwen 驱动结构化工具调用（日程 / 备忘录 / 闹钟助手）—— 可行性分析与落地方案

> 目标形态：`自然语言 → 本地模型 → 结构化指令 → 驱动本机工具`
> 约束：优先使用本机 GPU / NPU；后续可无缝替换为云端 API；本质上是一个 MCP 工具。

---

## 0. 结论速览（TL;DR）

| 问题 | 结论 |
|---|---|
| 技术上可行吗？ | **可行**。这是当前本地小模型最成熟的应用形态之一：输出空间小、可用约束解码保证 100% 合法 JSON。 |
| 难点在哪？ | **不在"能不能输出 JSON"，而在"中文口语时间归一化"和"训练数据从哪来"**。语法可以靠 grammar 强约束，语义只能靠数据。 |
| 必须先微调吗？ | **不必**，但**几乎肯定要做**。本机实测基线：约束解码下槽位全对率仅 **38%**，加 few-shot 到 **50%**（详见 §2.5）。这个缺口就是 LoRA 的 KPI。 |
| LoRA 能解决什么？ | 提升**领域语义**（模块分类、槽位抽取、中文时间表达、该不该 reject），目标把 **50% → 90%+**。它**不负责** JSON 合法性（那是 grammar 的活，实测已 100%）。 |
| 你的 schema 能用吗？ | 方向对，但 `{module, action, time, input}` 会撞三面墙：**没有日期**（周二 vs 下周二）、**没有"没听懂"出口**（所有输入被强行 add → 误触发）、**没有时长/提醒位**。建议改用本仓库的 `schema/schedule_command.v1.json`。 |
| 硬件够吗？ | 够。实测 **Ryzen AI 9 365 / 32GB DDR5-5600 / Radeon 880M iGPU / XDNA2 NPU 50 TOPS**。0.6B–4B 完全在本机舒适区，8B 也可行。 |
| 算力怎么分？ | **开发期主力走 iGPU（llama.cpp Vulkan）**，**交付期常驻走 NPU（AMD Ryzen AI 官方 hybrid 模式）**。两条路共用同一份 Schema + GGUF/ONNX 权重。 |

---

## 1. 需求拆解：把"问答→AI→结果→驱动工具"切成 5 层

```
┌──────────────────────────────────────────────────────────────────────┐
│ L1 输入层    麦克风/文本框 → 文本（可选 ASR，本阶段先做纯文本）      │
├──────────────────────────────────────────────────────────────────────┤
│ L2 语义层    本地 Qwen3 (+LoRA) + 约束解码(grammar) → 严格 JSON      │
│              ★ 只做语义归一化，不算绝对日期                          │
├──────────────────────────────────────────────────────────────────────┤
│ L3 校验层    JSON Schema 校验 → 确定性时间解析器 resolve(slots, now) │
│              → 消歧/反问/低置信度拦截                                │
├──────────────────────────────────────────────────────────────────────┤
│ L4 工具层    MCP Server：create_schedule / list_schedule / ...       │
│              （本地模型与云端 API 共用这一层，切换只改 base_url）     │
├──────────────────────────────────────────────────────────────────────┤
│ L5 执行层    SQLite 存储 + Windows 通知 / 任务计划 / .ics 导出       │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.1 本方案最重要的一条设计判断

> **把"用户说了什么（语义槽位）"和"那对应哪个绝对时间（推导结果）"彻底分开。**

模型输出：

```json
{"module":"class","action":"add","title":"计算机原理",
 "when":{"date_kind":"weekday","date_value":"TU","week_ref":"next","time":"09:00","period":"am"}}
```

`resolve_time()` 在**本地用确定性代码**把它算成 `2026-09-22T09:00:00+08:00`。

这么做换来三件事：

1. **可测试**：时间解析可以写单元测试，错了能定位是"模型理解错"还是"解析器算错"，不混在一起。
2. **可回归**：换模型、换量化、上 LoRA 时，解析器不动，指标可比。
3. **变简单**：小模型不用在"算今天是几号、下周二是哪天"上消耗能力 —— 这正是小模型最容易翻车的地方。

### 1.2 你给的例子与建议 schema 的对照

| 你的字段 | 问题 | 建议 |
|---|---|---|
| `module: class` | ✅ 保留 | 扩成枚举：class/exam/meeting/assignment/alarm/reminder/memo |
| `action: add` | ✅ 保留 | 扩成 add/update/delete/query/complete，但**第一阶段只实现 add** |
| `time: 9` | ❌ "周二上午九点"里的**周二丢了**；且 9 是上午还是晚上不明 | 换成 `when` 对象：`date_kind/date_value/week_ref/time/period/duration_min` |
| `input: 计算机原理` | ⚠️ 命名歧义（input 像"输入原文"） | 改名 `title` |
| —— | ❌ **没有"没听懂"的出口** | 加外层信封 `status: ok/clarify/reject` + `question` |

最后一条是**安全阀**。没有 `reject`，模型面对"今天天气怎么样"也必须挤出 `add`，误触发率不可能低。

---

## 2. 硬件实测结果与算力分配

### 2.1 本机实测（PowerShell + Node 双路核对）

| 项目 | 实测值 |
|---|---|
| CPU | AMD **Ryzen AI 9 365**（Strix Point，Zen5 + Zen5c，10 核 20 线程） |
| 内存 | 32 GB（2×16 GB Micron **DDR5-5600**，双通道，当前空闲约 17–18 GB） |
| iGPU | AMD **Radeon 880M**（RDNA 3.5，12 CU），驱动 32.0.13046.16，独占显存 512 MB + 共享内存 |
| NPU | **NPU Compute Accelerator Device**，PCI `VEN_1022&DEV_17F0`，状态 **OK**，类 `ComputeAccelerator`，驱动服务 `IpuMcdmDriver`（MCDM 驱动 → 可被 ONNX Runtime / Windows ML 调用） |
| 系统 | Windows 11 家庭版 **26200 (25H2)**，x64 |
| 磁盘 | C: 剩余 114 GB，D: 剩余 185 GB |
| 已有栈 | Anaconda(Py3.12.7 / Py3.10.4)、VS2022、WSL2(Ubuntu)、Clash 代理(127.0.0.1:7897)；**未安装** torch / Ollama / LM Studio / Ryzen AI 软件栈 |
| 网络实测 | `huggingface.co` 直连**不通**；`hf-mirror.com` + Clash 代理可用；GitHub Release 走代理约 **1 MB/s** 量级 |

### 2.2 三条推理路径对比（这是"优先 GPU/NPU"的决策依据）

| | **NPU（XDNA2，50 TOPS）** | **iGPU（Radeon 880M）** | **CPU（Zen5 20 线程）** |
|---|---|---|---|
| 跑法 | AMD Ryzen AI 1.8 → OGA，**hybrid（NPU 预填充 + GPU 解码）** 或 NPU-only | llama.cpp **Vulkan** / Ollama / LM Studio | llama.cpp CPU |
| 官方支持模型 | ✅ Qwen3-1.7B / 4B / 8B，均为 hybrid + full-optimized + long-context 三种变体（[官方清单](https://ryzenai.docs.amd.com/en/latest/llm_list.html)） | ✅ 任意 GGUF（Qwen3 全系含 LoRA 适配器） | ✅ 同上 |
| 上下文上限 | full-optimized ≤4K，long-context ≤16K | 只受内存限制 | 只受内存限制 |
| 约束解码 | OGA 示例脚本支持 guided generation（能力有，但接口没 llama.cpp 顺手） | ✅ 原生 `grammar` / `json_schema`，JSON Schema→GBNF 自动转换 | ✅ 同左 |
| 量化格式 | AMD 预编译 ONNX（自有量化流程） | GGUF（Q4_K_M 等，社区生态最全） | GGUF |
| 微调适配 | 微调后需**重走 OGA 量化/转换**，工具链对版本敏感（1.8 模型与旧版不兼容） | LoRA 可直接以适配器加载，或 merge 后转 GGUF | 同左 |
| 功耗/发热 | **最低**（可常驻，不占 GPU） | 高（与显示、游戏抢资源） | 高 |
| 上手成本 | 高（需装 Ryzen AI MSI + conda 环境 + 下多 GB 模型） | **低**（下个 zip + 一个 GGUF 就能跑） | 最低 |

### 2.3 结论：分阶段用不同单元

```
开发 / 调数据 / 评测 / 微调联调   →  iGPU（llama.cpp Vulkan），迭代最快
交付 / 常驻后台 / 省电待命        →  NPU（Ryzen AI hybrid），换来的功耗收益最大
降级 / 兜底                       →  CPU（模型没加载成功时保证功能不挂）
```

**不要一上来就啃 NPU**：NPU 路线会把"调模型"和"调工具链"两件难事叠在一起。等 Schema 和数据集冻结（Phase 4 结束）再迁 NPU，那时模型是确定的、只验证速度与精度不掉点。

> 你提到"优先用 GPU/NPU"，本方案全程满足：**推理 100% 在 iGPU 或 NPU 上，CPU 只做编排、解析和存储。** 唯一例外是"训练"，见 §5.4 的诚实说明。

### 2.4 让 GPU/NPU 真正吃满的配置清单

- **显存**：实测本机 iGPU 已可用 **16444 MiB（16 GB）**，无需再调 BIOS；8B Q4（~5 GB）可全量卸载。若显示可用显存偏小，再去 BIOS 调 UMA Frame Buffer 或 Adrenalin 的「可变显存(VGM)」。
- **全量卸载**：`-ngl 99`（llama.cpp）。部分卸载会因每层 PCIe/内存往返而**大幅**掉速。
- **线程**：CPU 侧 `-t 8`（给 P 核/系统留余量，20 线程全开反而更慢）。
- **NPU 性能模式**（Ryzen AI 路线）：
  ```
  cd C:\Windows\System32\AMD
  xrt-smi configure --pmode performance
  ```
- **电源计划**：Windows 电源模式设为「最佳性能」，否则 NPU/GPU 会降频。
- **内存带宽是真瓶颈**：DDR5-5600 双通道 ≈ 89.6 GB/s。实测（§2.5）Qwen3-4B Q4 解码 22.4 t/s，符合带宽预期；**4B 及以下才是这台机器的舒适区**。

### 2.5 本机实测基准（已跑通，非估算）

工具：llama.cpp Vulkan build **b11053**；GGUF 为 unsloth 的 Q4_K_M。

**A. 吞吐（`llama-bench -p 512 -n 128`）**

| 模型 | 体积 | iGPU 预填充 pp512 | **iGPU 解码 tg128** | CPU 预填充 | CPU 解码 |
|---|---|---|---|---|---|
| Qwen3-0.6B | 373 MB | 2135 t/s | **113.0 t/s** | 588 t/s | 105.9 t/s |
| **Qwen3-1.7B** | 1.03 GB | 704 t/s | **49.8 t/s** | 310 t/s | 41.7 t/s |
| Qwen3-4B | 2.32 GB | 222 t/s | **22.4 t/s** | 129 t/s | 14.2 t/s |

设备枚举：`AMD Radeon(TM) 880M Graphics (16444 MiB, 15622 MiB free)`，`fp16:1, bf16:0, matrix cores: KHR_coopmat`。
→ 共享显存已有 **16 GB**，8B Q4（~5 GB）也能全量卸载。

**关键推论（直接影响延迟预算）**：TTFT ≈ 提示词长度 / pp512。1.7B 上 500 token 提示 ≈ **0.71 s**；4B 上同样提示 ≈ **2.25 s**。
**所以"把系统提示+Schema+few-shot 压短"比"换更小的模型"对首字延迟更有效。**

**B. 真实 Schema 的约束解码对照（Qwen3-1.7B，8 条冒烟用例，`bench/probe_json.mjs`）**

| 条件 | JSON 合法 | 符合我们的 Schema | **槽位全对** | 平均延迟 | 平均输出 token |
|---|---|---|---|---|---|
| A 无约束 | 8/8 | **0/8** | 0/8 (0%) | 608 ms | 22 |
| B 约束解码 | 8/8 | **8/8** | 3/8 (**38%**) | 1347 ms | 50 |
| C 约束解码 + few-shot | 8/8 | **8/8** | 4/8 (**50%**) | 932 ms | 39 |

**三条硬结论：**

1. **无约束的"JSON 合法率 100%"是假象。** 模型输出的是它自己发明的字段（`{day, time, subject}`），**Schema 合规率 0/8**。约束解码的价值不是修 JSON 语法，而是**禁止模型自创 Schema** —— 对"要拿去驱动工具"的场景，这是必需品。
2. **格式 100% 正确 ≠ 语义正确。** 约束解码只把语义做到 38%。剩余失败模式高度集中，且**全都可以用数据覆盖**：
   - 槽位归错：时间被塞进 `location` / `target_ref`（不是 `when`）
   - 模块混淆：`alarm` ↔ `reminder`、`class` ↔ `meeting`
   - **该 `reject` 时不 reject**："今天天气怎么样"被执行成日程指令 ← **最危险的一类**
   - **该 `clarify` 时不 clarify**："帮我加个课"
3. **few-shot 是零成本收益**：槽位 38%→50%，延迟反降（1347→932 ms），因为模型学会少填可选字段（输出 token 50→39）。
   → 推论：**Schema 里可选字段越多，约束解码越慢**。Schema 要收紧（见 §3 的 `additionalProperties:false` 与条件必需设计）。

**这组数据就是本方案的可行性结论**：链路完全跑得通、格式问题已根治、**剩下的 50% 语义缺口正好是 LoRA 的靶子**。

---

## 3. 架构核心：一个 Schema，四处复用

```
                    ┌──────────────────────────────┐
                    │  schedule_command.v1.json    │  ← 唯一事实源
                    │  (JSON Schema)               │
                    └───────────────┬──────────────┘
        ┌───────────────┬───────────┼───────────┬───────────────┐
        ▼               ▼           ▼           ▼               ▼
  ①约束解码语法    ②LoRA训练标签  ③MCP工具定义  ④执行层校验   ⑤评测断言
   (GBNF/XGrammar)  (target JSON) (inputSchema) (jsonschema)  (字段比对)
```

**这是"以后能把本地模型换成 API"的全部秘密**：模型只是 ①+② 的一个可替换实现。换 API 时，③④⑤ 一行不改，①由服务端的 structured output / function calling 承担。

任何一方私自加字段 = 架构失效。所以这份 Schema 必须进 git，并在 CI 里校验"生成的 GBNF / MCP 定义 / 训练标签"三者与它一致。

---

## 4. 数据集方案（本方案的重心）

### 4.1 先说结论：没有现成数据集能直接用

公开数据集解决的是**通用工具调用格式**，不是**你的中文日程领域**：

| 数据集 | 规模 | 对你的价值 | 局限 |
|---|---|---|---|
| [Salesforce/xlam-function-calling-60k](https://huggingface.co/datasets/Salesforce/xlam-function-calling-60k) | 60k | 教"工具调用长什么样"（含 APIGen 自动校验流程） | 英文、API 五花八门、无中文相对时间 |
| [NousResearch/hermes-function-calling-v1](https://huggingface.co/datasets/NousResearch/hermes-function-calling-v1) | ~10k | `<tool_call>` 标签格式的先验 | 同上 |
| ToolACE / APIGen | 10k+ | 数据自动合成与**可验证性**方法论（[APIGen 论文](https://proceedings.neurips.cc/paper_files/paper/2024/file/61cce86d180b1184949e58939c4f983d-Paper-Datasets_and_Benchmarks_Track.pdf)） | 不能直接当训练集用 |
| Glaive-function-calling-v2 | 100k+ | 量大、格式统一 | 噪声多，需清洗 |

**所以：通用格式数据当"底料"（10–20%），真正的主力必须自己合成。**

### 4.2 合成方法：反向构造（Reverse Construction）★

不要"让教师模型读句子输出 JSON" —— 那样标签质量取决于教师模型的 JSON 准确率，还得再校验一轮。

要**反过来**：

```
① 按分布采样一个结构化记录 (ground truth)
      {module:class, action:add, title:计算机原理, weekday:TU, week_ref:next, time:09:00}
                    │
                    ▼
② 让教师模型/模板把这个记录"说人话"，生成 3–5 种不同口吻的中文表达
      "帮我把下周二上午九点的计算机原理加进课表"
      "周二9点有计算机原理课，记一下"
      "下周二的计算机原理，早上九点开课，加到日程"
                    │
                    ▼
③ 标签 = ①，由构造保证 100% 正确；表达 = ②，多样性由采样保证
```

**这一步把标注成本降到 0，并且标签精度是精确的**，而不是"教师模型大概对"。

采样分布要刻意做难度分层：

- **易**（~40%）：显式完整（"周三下午两点，高数课，教三 201"）
- **中**（~35%）：缺项、口语、省略主语（"加个明早八点的闹钟"）
- **难**（~20%）：多事项一句（"周二九点计算机原理，周三下午两点高数"→ 输出 2 条 commands）、指代（"把刚才那个改到十点"）、歧义（"九点"无上下午 → `period:none`）
- **负样本**（~5–10%）：闲聊/越界（"今天天气"→ `reject`）、信息不足（"加个课"→ `clarify`）

### 4.3 中文时间表达覆盖矩阵（必须逐格覆盖，这是错误率最高的地方）

| 类型 | 必须覆盖的说法 | 期望归一化 |
|---|---|---|
| 相对日 | 今天/明天/后天/大后天/今晚 | `offset_day: +0/+1/+2/+3` |
| 星期 | 周二 / 这周二 / 下周二 / 下下周二 / 礼拜二 / 周二上午 | `weekday + week_ref` |
| 钟点 | 九点 / 9:00 / 上午九点 / 早上九点 / 晚九点 / 21点 / 九点半 / 9点15 / 差一刻十点 | `time` + `period` |
| 模糊时段 | 早上 / 一大早 / 中午 / 午休 / 下午 / 傍晚 / 晚上 | `fuzzy: morning/noon/...` |
| 日期 | 9月22号 / 9/22 / 下个月3号 / 月底 | `date_kind:absolute` |
| 时长 | 两节课 / 一个半小时 / 90分钟 / 到十一点 | `duration_min` |
| 提醒 | 提前15分钟 / 前一天晚上提醒我 | `remind_before_min` |
| **跨月/跨年边界** | 12月31日说"明天"、周日说"下周一" | 解析器边界用例，必须单测 |

> 中文里"下周"在周日/周一的口语含义有歧义（有的地区周日算下周第一天）。**把它做成可配置规则并写进测试**，不要指望模型学会你家方言。

### 4.4 规模与配比建议

| 阶段 | 量 | 说明 |
|---|---|---|
| 冒烟 | 200–500 条 | 打通链路 + few-shot 示例来源 |
| 可用 | **3k–5k** | LoRA 的起步量，1.7B 上已能明显见效 |
| 稳 | **8k–15k** | 覆盖度足够，泛化到未见说法 |
| 配比 | 领域合成 75% / 通用工具调用 15% / 负样本 10% | 通用部分防止"只会这一件事"导致格式僵化 |
| 测试集 | **500 条，独立生成、人工过一遍** | 与训练集**不同分布种子**，永远不进训练 |

### 4.5 自动质检（合成数据的生命线）

1. **Schema 校验**：每条 target 必须过 `schedule_command.v1.json`（用 `jsonschema` 库）。
2. **往返一致性**：把 target 里的槽位用模板再渲染成一句规范中文，与原始表达做关键实体比对，冲突就丢。
3. **去重**：`(输入文本)` 精确去重 + `(target 结构)` 做相似度去重，防止模型背题。
4. **人工抽检 1%**：只抽"难"桶和 `clarify/reject` 桶。

### 4.6 数据格式（Chat JSONL，与 Qwen3 模板对齐）

```jsonl
{"messages":[{"role":"system","content":"<固定系统提示：角色+Schema+当前时间占位>"},{"role":"user","content":"为我的周二上午九点添加一个计算机原理的课程"},{"role":"assistant","content":"{\"status\":\"ok\",\"commands\":[{\"module\":\"class\",\"action\":\"add\",\"title\":\"计算机原理\",\"when\":{\"date_kind\":\"weekday\",\"date_value\":\"TU\",\"week_ref\":\"this\",\"time\":\"09:00\",\"period\":\"am\"}}]}"}]}
```

要点：

- **assistant 内容里不要有 markdown 代码块、不要有前后缀**，纯 JSON 一个对象。
- **Qwen3 必须关 thinking**：训练与推理都要 `enable_thinking=false`，否则 `<think>` 段会污染输出、拖慢 3–10 倍。这是 Qwen3 落地的头号坑。
- **当前时间不要写进训练样本的 system**（否则模型会记住固定日期）。训练时用占位符，推理时注入真实 now。

---

## 5. 微调方案

### 5.1 先不训：约束解码能免费拿到什么

| 能力 | 约束解码(grammar) | LoRA |
|---|---|---|
| JSON 结构 100% 合法 | ✅ 完全解决（实测 8/8） | ➖ 不负责 |
| **不越界、不自创字段** | ✅ 完全解决（实测 0/8 → 8/8） | ➖ |
| 枚举值不越界 | ✅ 完全解决 | ➖ |
| 中文口语 → 正确槽位 | ❌ 帮不上（实测仅 38%） | ✅ **这才是 LoRA 的价值** |
| "该 reject 时 reject" | ❌（实测把"今天天气"执行成了日程） | ✅ |
| 输出长度可控（省 token/降延迟） | ✅ 结构固定后变短 | ✅ 可进一步缩短 |

**实测基线：约束解码 + few-shot 后槽位全对率仅 50%。** 失败模式集中在四类，全部可用数据覆盖：槽位归错、`alarm/reminder` 混淆、不 reject、不 clarify。

**结论：Phase 2 一定会得出"要做 LoRA"的结论，但要先跑出 50% 这个基线数字** —— 它既是立项依据，也是验收基准（训完必须显著高于它，否则这次微调白做）。

### 5.2 基座选型

| 模型 | Q4 体积 | 本机 iGPU 实测解码 | 本机 iGPU 实测预填充 | 适配场景 |
|---|---|---|---|---|
| Qwen3-0.6B | ~0.4 GB | 113.0 t/s | 2135 t/s | 端侧/极限延迟；能力偏弱，需更多数据 |
| **Qwen3-1.7B** | ~1.1 GB | **49.8 t/s** | **704 t/s** | **推荐主力**：任务够窄，速度与延迟最优 |
| Qwen3-4B | ~2.5 GB | 22.4 t/s | 222 t/s | 难例、多事项、泛化更好；但 TTFT 会到 2 s 量级 |
| Qwen3-8B | ~5 GB | 约 11 t/s（按带宽外推） | 约 100 t/s | 想"一个模型干很多事"时；32 GB 内存可行 |

策略：**用 1.7B 做主交付，用 4B 当"难度上限对照组"**，评测集上直接对比再定。

### 5.3 LoRA 超参起点（1.7B / QLoRA）

| 项 | 建议值 |
|---|---|
| 方法 | QLoRA（4bit NF4）或 16bit LoRA（1.7B 在 16GB 显存内可全 LoRA） |
| r / alpha / dropout | 16 / 32 / 0.05（先试 r=16，欠拟合再上 32） |
| target_modules | `q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj` |
| lr | 1e-4 ~ 2e-4（cosine，warmup 3%） |
| epochs | 2–3（超过 3 极易过拟合到模板措辞） |
| batch | 1 × grad_accum 16 |
| max_seq_len | 1024（本任务 prompt+answer 通常 <700 token，别开大） |
| 损失 | **只对 assistant 段计算 loss**（`train_on_inputs=False`），否则模型学会复读用户输入 |

### 5.4 在哪训：三条路的真实情况（诚实版）

你要求"优先用本机 GPU/NPU"，这里必须把代价说清楚：

| 路径 | 可行性 | 说明 |
|---|---|---|
| **iGPU + PyTorch DirectML** | ⚠️ 可行但慢 | torch-directml 支持训练，但缺 flash-attn、bf16 支持有限，实测经验值比独显慢一个量级。1.7B QLoRA 3k 条约需**数小时**。适合"小步试跑 / 超参摸索"，不适合反复全量训练。 |
| **本机 + ROCm** | ❌ 目前不可靠 | Windows 原生 ROCm 对 `gfx1150`（Strix Point iGPU）的 PyTorch wheel 支持尚不完整（[TheRock#1876](https://github.com/ROCm/TheRock/issues/1876) 等 issue 在跟）；WSL 路线对 `gfx1151`(Strix Halo) 有 wheel，`gfx1150` 不确定。**不要把它当主计划。** |
| **NPU 训练** | ❌ 不适用 | NPU 是推理单元。 |
| **租单卡云 GPU（推荐）** | ✅ 最省时间 | 1.7B QLoRA、3k 样本、1 epoch 在单张 4090 上约 **10–20 分钟**。成本约几元。**训练是"一次性、短时、可外包"的活**，把本机算力留给它擅长的推理与评测。 |
| **CPU 训练** | ⚠️ 极慢 | 20 线程训 1.7B QLoRA 属"跑得动但没必要"。 |

**建议的算力分配**：本机 iGPU/NPU 负责**推理、评测、数据合成质检、批量跑 500 条测试集**（这些是天天要跑的）；**训练外包一次**（一小时完事）。这比在本机硬训 6 小时更符合"优先用本机算力"的初衷 —— 本机算力用在了高频环节。

如果你坚持全本机训练：先从 **0.6B + DirectML** 跑通全流程验证脚本正确，再上 1.7B 过夜训练。

### 5.5 训练产物 → 部署的两条出口

```
LoRA adapter
   ├── 方案 A（iGPU，推荐先做）：merge → convert_hf_to_gguf.py → Q4_K_M.gguf
   │        直接 llama.cpp 加载；也可保留 adapter 在运行时叠加（便于 A/B 对比）
   └── 方案 B（NPU）：merge → 按 AMD《Preparing OGA Models》重新量化/编译
            ⚠️ 工具链对版本敏感，1.8 的模型与 1.7 不兼容，务必锁定版本
```

**量化掉点必须实测**：merge 后先测 F16 精度，再测 Q4_K_M 精度，若"字段全对率"掉超过 3 个百分点，改用 Q5_K_M 或 Q8_0（1.7B 用 Q8 也只有 ~1.8GB，本机完全吃得下）。

### 5.6 已经踩到的两个坑（本机实测，不是听说）

1. **Qwen3 默认开 thinking，会直接把你的 JSON 任务吃掉。**
   本机实测：用 `llama-cli` 让 Qwen3-0.6B"只输出 JSON"，它进入 `[Start thinking]` 并开始长篇推理，**一个 JSON 都没输出**（日志见 `bench/bench.log` 末段）。
   对策：**训练与推理统一 `enable_thinking=false`**。llama.cpp 侧通过 `chat_template_kwargs` 传：
   ```json
   {"chat_template_kwargs": {"enable_thinking": false}}
   ```
   这是 Qwen3 落地的头号坑，不处理会让整个方案看起来"完全不可用"。

2. **约束解码会显著增加延迟，因为模型会去填可选字段。**
   实测：无约束平均输出 22 token / 608 ms；约束解码 50 token / 1347 ms（翻倍）；加了 few-shot 教它"只填必要的"之后降到 39 token / 932 ms。
   对策：**Schema 要收紧**。可选字段越多，语法分支越多，模型越容易生成一堆 `location`/`target_ref` 垃圾字段。
   具体做法：① 把"新增日程"和"修改日程"拆成两个工具/Schema，各自字段更少更必需；② 用 `max_tokens` 硬限；③ few-shot 里就示范简洁输出。

---

## 6. MCP / 工具层设计

### 6.1 第一阶段工具清单（只实现 5 个，全部围绕"新增"）

| 工具 | 作用 | 备注 |
|---|---|---|
| `create_schedule` | **核心**：接收 §3 的 envelope，写入本地库 | 支持一次多条 commands |
| `list_schedule` | 查询某天/某周日程 | 顺带解决指代与去重 |
| `update_schedule` | 改时间/标题 | 用 `target_ref` 定位 |
| `delete_schedule` | 删除 | **必须二次确认** |
| `resolve_time` | 槽位 → 绝对时间（纯函数，不暴露给模型） | 内部调用，不进 MCP 工具表 |

### 6.2 为什么值得做 MCP（而不是自定义函数）

- **换模型零成本**：今天 Qwen3 本地，明天 Claude/GPT 云 API，工具层不动。
- **换前端零成本**：你已有的 `D:\Projects\AI_ScheduleAssistant`（Android Compose 脚手架）以后可以直接连同一个 MCP Server，甚至反向演变成"手机发指令 → 电脑执行"。
- **生态复用**：Claude Desktop / Cursor / Trae 等都能直接挂上这个 Server 调试，等于免费得到一个可视化的联调窗口。

实现建议：Python `FastMCP`，因为你的解析器、数据合成、评测脚本都是 Python，同进程共用 Schema 与校验函数。

### 6.3 统一的模型入口（本地 ↔ API 切换的关键）

让本地推理服务对外暴露 **OpenAI 兼容的 `/v1/chat/completions`**：

| 后端 | 是否 OpenAI 兼容 |
|---|---|
| llama.cpp `llama-server` | ✅（含 `grammar` / `json_schema` 参数） |
| AMD Ryzen AI OGA Server Interface | ✅（官方提供 REST 接口） |
| Ollama / LM Studio | ✅ |
| 云端 API | ✅ 原生 |

于是切换只需要改一个 `base_url` + `model` 名：

```python
# config.yaml
llm:
  base_url: "http://127.0.0.1:8080/v1"   # ← 换 API 时只改这一行
  model: "qwen3-1.7b-schedule-lora"
  response_format: { type: "json_schema", json_schema: { schema: <读取 schedule_command.v1.json> } }
```

**并且要写一个"能力探测"层**：启动时探测后端是否支持 `json_schema`；不支持就退化为"prompt 内嵌 schema + 输出后正则提取 + 失败重试"。

### 6.4 约束解码落地（llama.cpp 侧）

```powershell
# 1) 启动服务（iGPU 全量卸载 + 并发 1）
llama-server.exe -m .\Qwen3-1.7B-Q4_K_M.gguf -ngl 99 -c 4096 --port 8080 -np 1

# 2) 请求时带 json_schema（llama.cpp 会自动转成 GBNF，输出必定合法）
#    response_format = {"type":"json_schema","json_schema":{"schema": <schedule_command.v1.json>}}
```

注意：**约束解码会让采样变慢一点**（每步要按语法掩码），但换来 100% 合法结构，对"驱动工具"这种场景是稳赚的。

### 6.5 确定性时间解析器（L3，最该写测试的地方）

```python
def resolve_time(when: dict, now: datetime, tz: str, prefs: dict) -> datetime:
    """纯函数：把语义槽位变成绝对时间。今天/明天/下周二/月底全部在这里定义。"""
    # 1) date_kind=offset_day → now.date() + n
    # 2) date_kind=weekday    → 本周/下周的该星期几（"周"起始日可配置）
    # 3) date_kind=absolute   → 解析日期
    # 4) time 缺省 → 用 fuzzy 映射（早上=08:00, 中午=12:00…）
    # 5) period=none 且 time<8 → 按用户作息推断（上班族 09:00 更可能是上午）
    # 6) 结果早于 now 且是相对日 → 顺延一周（说"周二"时已经过了周二）
    # 7) 冲突 → 抛 NeedClarify，触发反问
```

**这个函数要有 100+ 条单元测试**，它是"看起来智能"和"真的可靠"的分界线。

---

## 7. 执行层（备忘录 / 闹钟）

| 项 | 建议 |
|---|---|
| 存储 | SQLite 单文件（`schedule.db`），便于备份与后续同步 |
| 触发 | Python `APScheduler` 常驻 + Windows Toast 通知；或写 `schtasks` 计划任务（**进程死了也能触发**，更可靠） |
| 提醒去重 | 每条日程加 `notified_at` 字段，保证幂等 |
| 撤销 | 每次写操作返回 `undo_token`，支持"撤销刚才那条" |
| 时区 | 统一存本地时间 + `Asia/Shanghai`，跨时区先不做 |
| 危险操作 | `delete` 必须二次确认；`create` 在"低置信度"或"period=none"时必须回显确认 |
| 可观测 | 每次调用落一条日志：原文 / 模型原始输出 / 校验后 JSON / 解析出的绝对时间 / 最终动作。**这条日志是后面做数据飞轮的原材料。** |

---

## 8. 评测与验收（决定"要不要 LoRA"的唯一依据）

### 8.1 测试集

500 条独立生成 + 人工过筛，桶分布与 §4.2 一致，**永不进训练**。

### 8.2 指标定义

| 指标 | 定义 | 目标 |
|---|---|---|
| JSON 合法率 | 输出能解析且过 Schema | ≥ 99%（grammar 开启后应接近 100%） |
| 意图准确率 | `status` 判断正确（ok/clarify/reject） | ≥ 95% |
| **字段全对率** | 一条命令的所有槽位与标准答案完全一致的比例 | **≥ 90%**（核心指标） |
| 时间槽位准确率 | `when` 子对象全对 | ≥ 92% |
| 误触发率 | 负样本被错误执行 add 的比例 | ≤ 2% |
| 首字延迟 TTFT | 从请求到第一个 token | ≤ 1.0 s（1.7B，提示 ≤600 token 时实测可达 ~0.85 s） |
| 吞吐 | 解码 tokens/s | ≥ 15 tok/s（1.7B）/ ≥ 8（4B） |
| 端到端 p95 | 用户说话到提示写入完成 | ≤ 2.5 s |

### 8.3 go / no-go 门槛

```
Phase 2 基线（grammar + few-shot + Qwen3-1.7B/4B，500 条测试集）
   ├── 字段全对率 ≥ 90%  → 停，不要微调，直接进 NPU 迁移与工程化
   ├── 50% ~ 90%         → 做 LoRA（Phase 3-4），预期 +25~40 个百分点
   └── < 50%             → 先怀疑 Schema 设计与数据分布，不要盲目开训
```

> **已实测的起点**：8 条冒烟用例上，约束解码 38%、加 few-shot 50%（§2.5）。500 条测试集上的真实基线会落在这附近，
> 因此**本方案的实际路径几乎必然是"做 LoRA"**。冒烟数据的作用是：给出立项依据，并防止"训完不知道有没有变好"。

**评测脚本必须可重复跑**：`python eval.py --base-url ... --model ... --testset test.jsonl`，输出逐桶指标 + 失败样本清单（这是下一轮数据合成的直接输入，形成数据飞轮）。

---

## 9. 路线图

| 阶段 | 内容 | 交付物 | 预估 |
|---|---|---|---|
| **P0** | 环境：llama.cpp Vulkan + Qwen3 GGUF + Python 依赖；锁定代理与镜像 | 能命令行跑通一次 JSON 输出 | 0.5 天 |
| **P1** | 端到端打通：Schema → grammar → 模型 → 校验 → resolve_time → SQLite + 通知 | 一句话真的能建日程 | 2–3 天 |
| **P2** | 评测集(500) + 基线(few-shot, 1.7B/4B 各一次) | 基线指标表 → **是否微调的决策** | 2 天 |
| **P3** | 数据合成 3k–5k + 质检 + 人工抽检 | `train.jsonl` / `test.jsonl` | 3–5 天 |
| **P4** | LoRA 微调 + merge + 量化 + A/B 评测 | 微调模型 + 提升报告 | 1–2 天（训练本身约 20 分钟） |
| **P5** | MCP Server 封装 + NPU 迁移（Ryzen AI 1.8 hybrid） | `create_schedule` 工具 + NPU 版跑分 | 3–5 天 |
| **P6** | 换云端 API 验证"可替换性" + 对接 Android 前端 | base_url 一行切换成功 | 1–2 天 |

**关键：P2 是分水岭。** 不要在没跑基线之前就开始合成数据和训练。

---

## 10. 风险清单

| # | 风险 | 影响 | 概率 | 对策 |
|---|---|---|---|---|
| 1 | **中文相对时间归一化错误**（尤其"下周"、跨月、period 缺省） | 高（写错日程比不写更糟） | **高** | 语义/解析分离；解析器 100+ 单测；`period:none` 强制回显确认 |
| 2 | Qwen3 **thinking 模式**污染输出、拖慢推理 | 高 | 高 | 训练与推理统一 `enable_thinking=false`；grammar 兜底 |
| 3 | 合成数据"太干净"，真实口语没覆盖 | 中 | 高 | 难度分层采样；从真实日志回流补数据（§7 可观测） |
| 4 | NPU 工具链版本敏感、微调模型迁移麻烦 | 中 | 中 | 开发期就用 iGPU 路线；NPU 迁移放在 Schema/模型冻结之后；锁定 Ryzen AI 版本 |
| 5 | iGPU 共享显存不足 / 与系统抢内存 | 中 | 中 | 主力 1.7B/4B；BIOS UMA 调大；`-ngl` 全量卸载 |
| 6 | 本机 ROCm/DirectML 训练不稳 | 中 | 高 | 训练外包一次；本机只做推理与评测（§5.4） |
| 7 | 误触发（把闲聊当日程） | 高 | 中 | envelope 加 `reject`；负样本 ≥10%；低置信度强制确认 |
| 8 | 量化掉点 | 中 | 中 | F16/Q4/Q8 三档都测；1.7B 直接上 Q8 也够小 |
| 9 | 网络：HF 直连不通 | 低 | 已发生 | 用 `hf-mirror.com` + Clash 代理（本机 127.0.0.1:7897 实测可用） |
| 10 | 模型/工具链一升级就崩 | 中 | 中 | 锁版本（llama.cpp build、Ryzen AI 版本、模型 commit hash），写进 `requirements`/文档 |

---

## 11. 附录

### 11.1 本机实测基准数据

全部为**本机真实跑出**的数据（非估算）：

| 实验 | 脚本 | 原始日志 | 结论摘要 |
|---|---|---|---|
| 吞吐对比（iGPU vs CPU，3 个模型） | `bench/run_bench.ps1` | `bench/bench.log` | 1.7B：pp512 704 t/s、解码 49.8 t/s；约束解码 38%→few-shot 50% |
| 真实 Schema 约束解码三组对照 | `bench/probe_json.mjs` | `bench/constrained_test.log` | 无约束 Schema 合规 0/8；约束 8/8 但槽位仅 38%；+few-shot 50% |

完整数值见 §2.5。

### 11.2 环境待装清单

```powershell
# 1) 推理（iGPU 路线，最快见效）
#    llama.cpp Vulkan 预编译包 + GGUF 模型（脚本已自动化，见 bench/run_bench.ps1）

# 2) Python 依赖
conda create -n sched python=3.11 -y
conda activate sched
pip install jsonschema openai fastmcp apscheduler dateparser pyyaml
# 训练时另装：torch transformers peft trl bitsandbytes datasets

# 3) NPU 路线（Phase 5 再做）
#    下载 AMD Ryzen AI Software 1.8 MSI → 装 NPU 驱动 + conda 环境
#    拉取 amd/Qwen3-*-onnx-ryzenai-1.8-* 模型（hybrid 变体）
```

### 11.3 关键参考

- AMD Ryzen AI Software 1.8 —— [OGA 流程与 hybrid 模式](https://ryzenai.docs.amd.com/en/latest/hybrid_oga.html)、[NPU 支持模型清单](https://ryzenai.docs.amd.com/en/latest/llm_list.html)（含 Qwen3-1.7B/4B/8B）
- [AMD Ryzen AI 1.7 发布说明](https://www.phoronix.com/news/AMD-Ryzen-AI-Software-1.7)、[Ryzen AI / Radeon 本地 LLM 与 Lemonade](https://www.amd.com/en/developer/resources/technical-articles/2025/ryzen-ai-radeon-llms-with-lemonade.html)
- APIGen —— [可验证的函数调用数据合成方法论](https://proceedings.neurips.cc/paper_files/paper/2024/file/61cce86d180b1184949e58939c4f983d-Paper-Datasets_and_Benchmarks_Track.pdf)
- LoRA/工具调用的同类实践 —— [Qwen3-1.7B QLoRA 结构化函数调用](https://github.com/skartikapps/reasoning-tool-call-llm)
- llama.cpp 语法约束与工具调用讨论 —— [error-free tool calling](https://github.com/ggml-org/llama.cpp/discussions/21839)、[custom grammars + tool calls](https://github.com/ggml-org/llama.cpp/discussions/22408)
- ROCm 对 gfx1150 的支持现状 —— [ROCm/TheRock#1876](https://github.com/ROCm/TheRock/issues/1876)

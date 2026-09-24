# 外部数据集结构与现成框架选型

> 回答两个问题：① xlam / hermes 这些数据集到底长什么样？② 有没有现成框架能替代"输入→LLM→结构化输出→解析执行"这套自研流程？

---

## 第一部分：外部数据集结构

### 1.1 已拉取到本地的数据集

全部位于 `data/external/`（约 600 MB），字段级结构摘要见 [`dataset-structure-report.md`](dataset-structure-report.md)。

| 文件 | 记录数 | 大小 | 授权 |
|---|---|---|---|
| `xlam60k.json` | 60,000 | 91.7 MB | 原仓库已 gated，此处为公开镜像 |
| `xlam_irrelevance_7.5k.json` | 7,500 | 7.4 MB | 公开 |
| `xlam60k_parsed.parquet` | 60,000 | 24.9 MB | 公开（已解析版） |
| `hermes_func-calling.json` | 1,893 | 19.6 MB | apache-2.0 |
| `hermes_func-calling-singleturn.json` | 1,893 | 17.0 MB | apache-2.0 |
| `hermes_glaive-function-calling-5k.json` | 5,209 | 19.5 MB | apache-2.0 |
| `hermes_json-mode-singleturn.json` | 1,241 | 2.8 MB | apache-2.0 |
| `toolace_data.json` | 11,300 | 35.4 MB | apache-2.0 |
| `apigen_mt_5k.json` | 5,000 | 121.8 MB | **cc-by-nc-4.0（禁止商用）** |
| `glaive_function_calling_v2.json` | 112,960 | 258.6 MB | apache-2.0 |

### 1.2 ⚠️ xlam-60k 已经变成受限数据集

尝试直接下载 `Salesforce/xlam-function-calling-60k` 的结果：

```
HTTP 403  Access to dataset Salesforce/xlam-function-calling-60k is restricted
          and you are not in the authorized list.
```

**要拿原版必须在 HF 上申请授权**（需要账号 + 等审批）。本方案改用下载量最高的公开镜像 `NobodyExistsOnTheInternet/xlam-function-calling-60k`（内容一致）。

### 1.3 五种格式的真实结构对照

#### ① xlam-60k —— 最贴近"单步翻译"的格式

```json
{
  "id": 0,
  "query": "Where can I find live giveaways for beta access and games?",
  "answers": "[{\"name\": \"live_giveaways_by_type\", \"arguments\": {\"type\": \"beta\"}}]",
  "tools": "[{\"name\": \"live_giveaways_by_type\", \"description\": \"...\", \"parameters\": {...}}]"
}
```

- **三个字段全是平的**：`query`(自然语言) / `answers`(期望调用) / `tools`(可用工具定义)
- ⚠️ `answers` 和 `tools` **是"JSON 字符串"，不是嵌套对象** —— 读出来要再 `JSON.parse` 一次。这是最容易踩的坑。
- 单轮、无 system、无对话历史 → **结构上最接近你的场景**：一句话进，一个结构化调用出。
- 平均每条 1,019 字符；中文占比 0.1%（基本是英文）。

#### ② xlam-irrelevance-7.5k —— 专门做"不该调用"的负样本

```json
{ "query": "Who was the runner-up in the NCAA Final Four for the year 2019?",
  "tools": "[{...}]",
  "answers": "[]" }
```

- 结构同上，但 **`answers` 恒为空数组** —— 即"给了工具，但这个问题不该用工具"。
- 这正是你的 `reject` 类所需的监督信号，而且是**别人已经标好、可直接用的 7,500 条**。价值很高。

#### ③ hermes-function-calling —— 与 Qwen3 官方模板天然对齐

```json
{
  "id": "82088305-...",
  "conversations": [
    {"from": "system", "value": "You are a function calling AI model. ... <tools>[...]</tools>"},
    {"from": "human",  "value": "..."},
    {"from": "gpt",    "value": "<tool_call>\n{\"name\": \"...\", \"arguments\": {...}}\n</tool_call>"},
    {"from": "tool",   "value": "<tool_response>\n{\"name\": \"...\", \"content\": {...}}\n</tool_response>"},
    {"from": "gpt",    "value": "已经帮你查到了……"}
  ],
  "tools": "[...]",
  "category": "IoT and Home Automation",
  "subcategory": "Security Camera Management",
  "task": "View and Manage Security Camera Feeds"
}
```

- 角色用 `system/human/gpt/tool`（不是 OpenAI 的 `system/user/assistant/tool`），**需要一次字段重命名**。
- **关键发现**：它用的 `<tools>` + `<tool_call>{"name":..., "arguments":...}</tool_call>` 格式，**与 Qwen3 官方 chat template 内置的格式完全一致**（Qwen3 的模板原文就是这段 XML）。
  → 意味着 hermes 数据**几乎不用改造**就能喂给 Qwen3，格式先验直接对齐。
- 有 `category/subcategory/task` 三级标注，可用来做**分层采样**（避免某种工具类型过采样）。
- `func-calling-singleturn.json` 是它的单轮裁剪版（3 轮：system→human→gpt），**对你这一个任务更合适**，噪声更少。

#### ④ ToolACE —— 注意它的调用表示法完全不同

```json
{
  "system": "You are an expert in composing functions. ...",
  "conversations": [
    {"from": "user",      "value": "..."},
    {"from": "assistant", "value": "[Market Trends API(trend_type=\"MARKET_INDEXES\", country=\"us\")]"},
    {"from": "tool",      "value": "[{\"name\": \"Market Trends API\", \"results\": {...}}]"},
    {"from": "assistant", "value": "..."}
  ]
}
```

- 调用**不是 JSON**，而是 `[工具名(参数=值)]` 这种自定义伪代码 → **要用它必须先写转换器**，不能直接拿来训 JSON 输出。
- 10 轮长对话、平均 4,432 字符 —— 多轮工具循环，与你的单步任务形态差距较大。

#### ⑤ APIGen-MT-5k —— 多轮 agent 循环（最适合读它的"系统提示"写法）

角色序列：`human → gpt → human → function_call → observation → function_call → observation → gpt → human → gpt`

- `function_call` / `observation` 是**独立的角色**，即完整的 ReAct 式循环。
- `system` 字段是一份约 6,000 字符的**业务策略文档**（航司退改签规则），这是很值得学的写法：**把领域规则写在 system 里，而不是指望模型记住**。
- ⚠️ 许可证 `cc-by-nc-4.0` —— **不能商用**。

#### ⑥ glaive-v2 —— 量最大但结构最脏

```json
{ "system": "SYSTEM: You are a helpful assistant with access to the following functions...",
  "chat": "USER: ...\nASSISTANT: ... <|endoftext|>" }
```

- **整个对话塞在一个 `chat` 字符串里**，用 `USER:` / `ASSISTANT:` 手工分隔 → 必须写解析器。
- 112,960 条，但噪声多（含大量"我没有这个能力"的拒答）。现已被 hermes 清洗成 `glaive-function-calling-5k`，**建议直接用清洗版，不要碰原始 112k**。

### 1.4 结论：这些数据集能给你什么、不能给你什么

| | 能给 | 不能给 |
|---|---|---|
| **格式先验** | ✅ 工具调用长什么样、`<tool_call>` 怎么组织 | — |
| **负样本** | ✅ xlam-irrelevance-7.5k 的 7,500 条"不该调用" | — |
| **分层采样依据** | ✅ hermes 的 category/subcategory/task | — |
| **中文** | ❌ 全部 <0.2% 中文 | 中文口语表达 |
| **中文相对时间** | ❌ 完全没有 | "下周二上午九点" → 结构化 |
| **你的 4 字段 Schema** | ❌ 全部是五花八门的工具 | 你的 domain schema |
| **时间归一化任务** | ❌ | 模型该输出 `weekday+week_ref` 而非绝对日期 |

**所以配比结论不变**：外部通用数据 ≤20% 且**只用来教格式**；主力 75% 必须是自己反向合成的中文日程数据。

### 1.5 拉取到本地的用途建议

```
外部数据 (≤20%)                       自研合成数据 (≥75%)            负样本 (10%)
├─ hermes_func-calling-singleturn     ├─ 反向构造法生成                ├─ xlam-irrelevance-7.5k
│  (格式与 Qwen3 模板天然对齐)         │  (结构化记录→生成中文说法)      │  (直接改造成中文日程版)
├─ xlam60k (只取单轮结构做参照)        └─ 覆盖 §4.3 的时间表达矩阵      └─ 自造"加个课"类 clarify 样本
└─ xlam_irrelevance_7.5k (负样本)
```

---

## 第二部分：现成框架能替代到什么程度

### 2.1 先明确一件事：MCP 不是"框架"，是**协议**

MCP 只规定「工具如何被描述、发现和调用」。它**不包含 LLM 调用逻辑，也不管你怎么把中文变成 JSON**。
所以对你的流程：

| 你的设想环节 | MCP 管不管 | 现成替代品 | 结论 |
|---|---|---|---|
| 输入 → 调 LLM | ❌ 不管 | OpenAI 兼容客户端 | 几行代码 |
| **LLM → 结构化输出** | ❌ 不管 | **llama-server `--jinja` 内置 tool_call 解析** | ✅ **可完全代劳（已实测）** |
| **解析输出** | ❌ 不管 | 同上（直接返回 `tool_calls` 对象） | ✅ **可完全代劳（已实测）** |
| 校验 + 重试 | ❌ 不管 | Instructor / Pydantic AI / `jsonschema` | ✅ 可代劳 |
| **工具暴露与调用协议** | ✅ **这正是它的职责** | MCP SDK / FastMCP 2.x | ✅ 这就是 MCP |
| **时间解析 `resolve_time`** | ❌ 不管 | 无 | ❌ **必须自己写** |
| **执行（写库/通知/闹钟）** | ❌ 不管 | 无 | ❌ **必须自己写** |

**一句话：MCP 替代的是你流程里的"工具层"，不是"翻译层"。**

### 2.2 实测：llama-server 已经把"解析输出"这步做完了

我在本机用 `Qwen3-1.7B` + llama-server（`--jinja`，此版本默认开启）做了标准 OpenAI tools 协议测试，
把我们的 Schema 包装成 `create_schedule` 函数传入（脚本 `bench/probe_toolcall.mjs`，日志 `bench/toolcall_test.log`）：

| 用户输入 | finish_reason | 是否产出 tool_calls |
|---|---|---|
| 为我的周二上午九点添加一个计算机原理的课程 | `tool_calls` | ✅ name=`create_schedule`，arguments 是合法 JSON |
| 下周三下午三点有高数考试 | `tool_calls` | ✅ |
| 今晚提醒我买牛奶 | `tool_calls` | ✅ |
| **今天天气怎么样** | `stop` | ✅ **正确地没有调用工具** |
| 帮我写一段快速排序的代码 | `stop` | ✅ **正确地没有调用工具** |
| 帮我加个课 | `stop` | ⚠️ 没走 tool_calls，但在 content 里输出了 `{"status":"clarify",...}` |

**产出 tool_calls 3/6，其中参数合法 JSON 3/3；"该不该调用工具"判断正确 5/6。**

### 2.3 这个实测结果**修正了我上一轮的架构建议**（重要）

上一轮我建议：在 Schema 里加一个 `status: ok/clarify/reject` 的信封，用 grammar 强约束模型必须输出 JSON。

实测发现：**用 tool-calling 协议时，`reject` 这一半是免费得来的** —— 模型面对"今天天气"直接**不调用工具**，回复聊天内容即可。
而 grammar 强约束方案下，模型**被迫**输出我们 Schema 的 JSON，于是把"今天天气"硬塞成了 `class/query` 指令（这是最危险的一类误触发）。

**修正后的建议：**

```
主路径：tool-calling 协议（tool_choice=auto）
  ├─ 返回 tool_calls  → 执行
  └─ finish_reason=stop（没调工具）→ 当作闲聊/越界处理   ← reject 的出口，免费
兜底：content 里若出现 JSON，仍尝试解析（实测"帮我加个课"就落在这里）
```

`clarify` 仍然需要保留在你的 Schema 里（"帮我加个课"这类信息不足的请求，模型确实会调用工具但内容不完整）。

同时要记住实测暴露的**代价与残留问题**：
- 延迟更高：tool-calling 2.5–4.5 s，而 grammar 约束约 1.3 s
- **时间槽位依然是错的**：实测把"周二"变成 `date_value: "MO"`（周一）、把"下周三"变成 `"next"` —— 这恰好再次证明 §1.1 的判断：**绝不能指望模型算日期，必须 `resolve_time` 自己算**。

### 2.4 推荐的组件组合（几乎全是现成件）

```
┌─────────────────────────────────────────────────────────────┐
│ llama-server --jinja -ngl 99          ← 现成: 推理 + tool_call 解析
│   暴露 OpenAI 兼容 /v1/chat/completions                       │
└───────────────────────────┬─────────────────────────────────┘
                            │ tool_calls (已是结构化对象)
┌───────────────────────────▼─────────────────────────────────┐
│ 你的 orchestrator (~150 行 Python)     ← 自研: 校验 + 兜底 + 拦截
│   jsonschema 校验 → resolve_time(slots, now) → 低置信度则确认  │
└───────────────────────────┬─────────────────────────────────┘
                            │ 已确定要做什么
┌───────────────────────────▼─────────────────────────────────┐
│ MCP Server (FastMCP)                  ← 现成: 工具暴露协议
│   create_schedule / list_schedule / update / delete          │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ 执行层: SQLite + Windows 通知 + schtasks  ← 自研: 无可替代
└─────────────────────────────────────────────────────────────┘
```

**真正要你自己写的只有两块：`resolve_time`（时间归一化）和 执行层。** 其余全部是现成件。

### 2.5 为什么**不**建议上 LangChain / AutoGen 那类 Agent 框架

1. **你的任务不是 Agent，是翻译。** 一句话 → 一个结构化指令，**单步、无需规划、无需反思、无需多轮自主决策**。Agent 框架的价值（规划、记忆、多智能体）在这里用不上。
2. **会挡住你的精细控制。** 你后面要做 grammar 约束、要接 LoRA、要控制 chat template 和 `enable_thinking`，Agent 框架会把这些包起来，出问题极难定位。
3. **引入额外不确定性。** 框架自带 prompt 拼装和重试策略，会让"这次失败是模型的锅还是框架的锅"无法归因——而你恰恰需要一个干净的评测基线（见主文档 §8）。
4. **调试成本远高于收益。** 你这个 orchestrator 150 行就能写完，且每一行都可测。

**什么时候才该上框架**：当你需要"多步工具编排 + 条件分支 + 长期记忆"时（例如从"加日程"扩展到"帮我安排这周的学习计划"）。那时再引入不迟，而且因为你的工具层是标准 MCP，迁移成本很低。

### 2.6 MCP 生态里值得用的具体件

| 组件 | 用途 | 备注 |
|---|---|---|
| `mcp`（官方 Python SDK） | MCP server/client | 内置 FastMCP 风格装饰器 |
| `FastMCP` 2.x | 独立版 MCP 框架 | 写 server 最快；stdio 和 SSE 都支持 |
| `@modelcontextprotocol/sdk` | TypeScript 版 | 若你要接 Node 前端 |
| Claude Desktop / Cursor / Trae | **现成的 MCP Host** | ⭐ 开发期直接用它调你的 server，等于免费得到一个可视化联调窗口 |
| Instructor | JSON schema 校验 + 自动重试 | 与 OpenAI 兼容接口配合 |
| Pydantic AI | 类型化输出 + 校验 | 偏"框架"，按需 |

> 特别提醒：**开发期直接用 Cursor / Trae（你机器上都装了）当 MCP Host 来调你的 server**，比先写前端快得多。

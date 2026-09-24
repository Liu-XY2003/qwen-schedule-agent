# 工具接口对齐审查：数据集 ↔ Schema ↔ MCP

> 回答的问题：训练数据的 JSON 输出，和实际的工具接口能不能对上？
> 结论：**数据集与 Schema 已严格验证 100% 对齐；但"模型文本 → 工具调用"的桥还没有实现，这是当前唯一缺口。**

---

## 1. 已完成的验证（实测，非声称）

用 `jsonschema` (Draft 2020-12) 对全部 4372 条数据做严格校验：

```
===== train.jsonl (4000 条) =====
符合 schema: 4000/4000 = 100.00%
===== test.jsonl (372 条) =====
符合 schema: 372/372 = 100.00%
--- 标签里实际出现过的字段 ---
command 字段: action, location, module, notes, priority, remind_before_min, title, when
when 字段   : date_kind, date_value, duration_min, fuzzy, period, time, week_ref
越界 command: 无
越界 when   : 无
```

校验脚本：`pod/validate_dataset_vs_schema.py`（可随时重跑）。

**这是一个很强的保证**：生成器的 `build()` 是"先说后标"的，加上自校验断言，所以标签不可能出现 Schema 之外的字段或枚举值。

---

## 2. 工具接口契约（从 Schema 机械导出）

Schema 就是契约本身。MCP 的 `inputSchema` 用的就是 JSON Schema，**两者天然同构**，不需要转换：

| 契约项 | 取值 |
|---|---|
| `status` | `ok` / `clarify` / `reject` |
| `commands[]` 必填 | `module`, `action`, `title` |
| `module` | `class` / `exam` / `meeting` / `assignment` / `alarm` / `reminder` / `memo` |
| `action` | `add` / `update` / `delete` / `query` / `complete` |
| `when.date_kind` | `absolute` / `offset_day` / `weekday` / `unspecified` |
| `when.period` | `am` / `pm` / `none` |
| `when.*` | `date_value`, `week_ref`, `time`, `fuzzy`, `duration_min` |
| 可选 | `remind_before_min`, `location`, `priority`, `notes`, `target_ref` |

---

## 3. ⚠️ 真正的风险：两种"工具接口"范式，我的数据是前者

这是你担心的那个问题的准确形态。

### 范式 A：信封式（**当前数据集用的**）

模型输出的就是**一段 JSON 文本**，放在 `content` 里：

```
assistant content:
{"status":"ok","commands":[{"module":"class","action":"add","title":"计算机原理",
  "when":{"date_kind":"weekday","date_value":"TU","time":"09:00","period":"am"}}]}
```

### 范式 B：原生工具调用（MCP / OpenAI function calling / llama.cpp `--jinja`）

模型输出的是**带标签的工具调用**，由推理服务解析成结构化对象：

```
assistant content:
<tool_call>
{"name": "create_schedule", "arguments": {"module":"class","action":"add", ...}}
</tool_call>

→ 服务端解析后返回：
{"finish_reason":"tool_calls",
 "tool_calls":[{"function":{"name":"create_schedule","arguments":"{...}"}}]}
```

### 两者不通用，而且这是**真实存在**的坑

我的训练数据里**从来没有 `<tool_call>` 标签**。所以：

> 如果把微调后的模型直接挂在 OpenAI tools 协议后面，客户端拿到的是 `content`（一段 JSON 文本），**不是 `tool_calls`**。任何期待 `tool_calls` 的 MCP Host / Agent 框架都会认为"模型没调用工具"。

**旁证实测**（在 compshare pod 上，基座 Qwen3-1.7B + llama-server `--jinja`）：

| 输入 | finish_reason | 结果 |
|---|---|---|
| 周二上午九点计算机原理 | `tool_calls` | ✅ 正常产出 tool_calls |
| 帮我加个课 | `stop` | ⚠️ **JSON 落在 content 里，没走 tool_calls** |

基座模型尚且如此不稳定，一个**只被训练过范式 A** 的 LoRA 只会更彻底地走 A。

---

## 4. MCP 能不能支持？能，但需要一座桥

**必须理解 MCP 的定位**：MCP 是"工具如何被描述、发现、调用"的协议，它**不负责**让模型产出调用意图。模型侧那半截不归 MCP 管。

所以正确的分层是：

```
┌──────────────────────────────────────────────────────────┐
│ 模型 (LoRA)  →  输出信封 JSON (范式 A)                    │
└───────────────────────────┬──────────────────────────────┘
                            │ 一段文本
┌───────────────────────────▼──────────────────────────────┐
│ ★ 桥 (约 50 行)：JSON 解析 → jsonschema 校验 → 分发        │
│   - status=ok      → 调 MCP 工具                          │
│   - status=clarify → 回问用户                             │
│   - status=reject  → 当闲聊处理                           │
│   - 校验失败       → 重试 / 降级                          │
└───────────────────────────┬──────────────────────────────┘
                            │ 已校验的结构化参数
┌───────────────────────────▼──────────────────────────────┐
│ MCP Server (FastMCP)：create_schedule / list / update ...  │
│   inputSchema 直接引用 schedule_command.v1.json            │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│ 执行层：resolve_time(slots, now) → SQLite → 通知          │
└──────────────────────────────────────────────────────────┘
```

**关键点：桥不是缺陷，是分层设计的正常形态。** MCP 的 `inputSchema` 就是 JSON Schema —— 我们的 Schema 直接拿来用，零转换。桥的职责单一且可测。

---

## 5. 三条路线

| 路线 | 做法 | 成本 | 适用 |
|---|---|---|---|
| **① 信封式 + 桥** ★推荐先做 | 模型输出 JSON 文本，orchestrator 解析校验后调 MCP | 写 50 行桥 | Phase 1 端到端，最快见效 |
| **② ① + 约束解码** | 再用 llama.cpp 的 `json_schema` 参数保证 100% 合法 | 一个配置项 | 消除越界枚举（实测出现过 `fuzzy:"prev"`） |
| **③ 重训成原生 tool_call 格式** | 数据生成器改成输出 `<tool_call>{"name":...,"arguments":...}</tool_call>` | 改生成器 + 重训（4090 上 5 分钟） | 想让任何 MCP Host 直接挂载 |

**推荐顺序：① → ② → 看需要再 ③。**

理由：① 能最快暴露真实问题（时间解析、执行层、交互），而且这些跟输出范式无关。等端到端跑通了，③ 只是换个数据格式重训一次的事。

**唯一让我倾向尽早做 ③ 的理由**：如果最终要接 Claude Desktop / Cursor 这类现成 MCP Host，它们只认原生 tool_calls，桥必须放在 Host 之外（自己写客户端）。但那是 Phase 6 的事。

---

## 6. 顺带发现的一个评测漏洞（必须坦白）

校验时注意到：`test.jsonl` 372 条的 status 分布是 **`{'ok': 372}`** —— **一个 reject/clarify 都没有**。

原因：测试集去重时用"输入文本不与训练集重复"过滤，而 reject（14 条）和 clarify（10 条）来自**固定短语池**，全部在训练集里出现过，于是被整批过滤掉了。

**影响**：我之前报的"测试集 97.7%"**只覆盖了 ok 路径**。reject/clarify 从未被测试集检验过 —— 而我在手写真实用例里发现的 2 个失败，**恰好就是 reject/clarify 判错**。

**修法**：生成测试集时给 reject/clarify 用一套**独立的短语池**，或者在去重时按 status 分层保留。这是个一行逻辑但影响结论有效性的问题，值得下次训练前修掉。

---

## 7. 待办清单（按优先级）

1. **写桥 + MCP Server**（`create_schedule` 等 5 个工具），inputSchema 引用 `schedule_command.v1.json`
2. **写 `resolve_time()`** + 100 条单元测试（这是唯一无法外包给任何框架的部分）
3. **修测试集**：reject/clarify 用独立短语池，让评测覆盖三条路径
4. 开约束解码（路线 ②）
5. 视需要改造成原生 tool_call 格式重训（路线 ③）

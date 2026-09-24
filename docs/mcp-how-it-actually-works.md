# 现代 MCP 工具到底怎么做的？（对比"正则 + 写死参数"）

> 你的疑问：现在只知道"写死函数参数 → 正则把 JSON 转成 dict → 传进函数执行"，
> 这套流程刻板且任何错误都会失败。现代 MCP 是怎么做的？

---

## 0. 先说结论

你的做法缺的不是"更好的正则"，而是**一层机器可读的契约**。现代方案用五层机制替代它，
其中**约束解码**（让模型结构上不可能输出非法结构）是最关键的革新 —— 它把"格式错误"
从概率问题变成了不可能事件。

**全程没有任何正则。**

---

## 1. 你的做法为什么会"任何错误都失败"

```
模型输出自由文本 → 正则提取 → dict → func(**d)
```

这条链上没有一层在做**契约校验**，全靠格式巧合：

| 失败模式 | 后果 |
|---|---|
| 模型多输出一个字段 | `func(**d)` → `TypeError: unexpected keyword argument` |
| 缺一个字段 | `TypeError: missing required argument` |
| 枚举值写成 `"prev"` | 函数内部走到没有分支的 else → 静默错误或崩溃 |
| 数字写成字符串 `"9"` | 类型错误，或静默算错 |
| 嵌套结构变了 | 正则匹配到半截 → 解析出垃圾 dict |
| 前后多了一句解释 | 正则贪婪匹配 → 抓到多余内容 |

**根因**：正则做的是"文本→文本"的提取，而这里需要的是"数据→类型化参数"的**校验与绑定**。

---

## 2. 现代 MCP 的五层

### Layer 1 — 工具声明就是一份 JSON Schema

MCP 客户端发 `tools/list`，服务端返回：

```json
{
  "name": "create_schedule",
  "description": "创建日程/备忘/闹钟",
  "inputSchema": {
    "type": "object",
    "required": ["status", "commands"],
    "properties": {
      "status": {"enum": ["ok", "clarify", "reject"]},
      "commands": {"type": "array", "items": {"$ref": "#/$defs/Command"}}
    }
  }
}
```

**这份 `inputSchema` 就是我们的 `schema/schedule_command.v1.json`。** MCP 用的就是 JSON Schema，
格式完全一致，零转换。

> 对比：你的做法里，参数只存在于函数签名中，**模型看不见、校验器也不存在**。

### Layer 2 — 约束解码（Constrained Decoding）★ 最关键的革新

从 JSON Schema **自动编译成语法**（GBNF / XGrammar / Outlines），推理时**逐 token 屏蔽掉不符合语法的候选**：

```
schema ──编译──► 语法(GBNF) ──► 采样时掩码非法 token ──► 输出必然合法
```

各推理框架的接口：

| 框架 | 参数 |
|---|---|
| llama.cpp | `response_format: {"type":"json_schema","json_schema":{"schema":{...}}}` |
| vLLM | `guided_json={...}` 或 `structured_outputs` |
| SGLang | `json_schema=` / `regex=` |
| Ollama | `format: <schema>` |

**效果**：模型不可能输出不合法 JSON、不可能用枚举外的值、不可能漏必填字段。
本项目实测过它的价值：不加约束时模型会自己发明字段（`{"date":"WE","subject":"高数"}`），
加了之后结构合规率 0/8 → 8/8。

> 对比：你的做法里，"模型输出格式对不对"是**祈祷**；这里是**保证**。

### Layer 3 — 服务端按 chat template 解析成 tool_calls

模型输出的是模型自己的工具调用格式（Qwen3 是 `<tool_call>...</tool_call>`），
推理服务用**模型自带的 jinja 模板**把它解析成结构化对象：

```
模型生成:  <tool_call>{"name":"create_schedule","arguments":{...}}</tool_call>
                    ↓ llama.cpp --jinja / vLLM --enable-auto-tool-choice 解析
返回给客户端: {"finish_reason":"tool_calls",
              "tool_calls":[{"function":{"name":"create_schedule",
                                         "arguments":"{...}"}}]}
```

**不是正则** —— 是模板匹配 + JSON 解析。解析失败服务端会明确报错，而不是把半截文本丢给你。

> 这也是我在本项目里发现的**接口范式冲突**：我们的数据集训练模型输出"信封 JSON 文本"，
> 而不是 `<tool_call>` 格式。所以要走这条路，需要用 `gen_dataset.py` 改输出格式重训一次。

### Layer 4 — SDK 用 Pydantic 校验 + 签名绑定

FastMCP / MCP SDK 的写法（注意：**是普通 Python 函数 + 类型注解**）：

```python
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import Literal

class Command(BaseModel):
    module: Literal["class","exam","meeting","assignment","alarm","reminder","memo"]
    action: Literal["add","update","delete","query","complete"]
    title: str = Field(max_length=60)
    when: When | None = None

class ScheduleEnvelope(BaseModel):
    status: Literal["ok","clarify","reject"]
    commands: list[Command] = Field(default_factory=list, max_length=5)
    question: str | None = None

mcp = FastMCP("schedule")

@mcp.tool()
def create_schedule(env: ScheduleEnvelope) -> str:
    """创建日程。参数结构见 schema。"""
    ...
```

运行时发生的事：

1. SDK 从**类型注解自动导出** `inputSchema`（`ScheduleEnvelope.model_json_schema()`）
2. 收到 `tools/call` 的 arguments 后，交给 Pydantic **校验**（类型/枚举/必填/长度/范围）
3. 校验通过 → 按签名**绑定**参数 → 调用函数
4. 校验失败 → 返回结构化的 `isError: true` + 具体哪个字段错了

**参数不是"正则提取"的，是"schema 校验后绑定"的。** 多字段、少字段、类型错、枚举越界，
全部在进入你的业务代码之前就被拦住。

### Layer 5 — 错误回灌 + 向用户追问

- **错误回灌**：校验失败的报错作为 tool result 回给模型 → 模型改正 → 再调一次。
  这是现代 Agent 健壮性的真正来源，不是"一次必须全对"。
- **MCP elicitation**：工具可以主动向用户追问 —— 这**正好对应我们 Schema 里的 `status: "clarify"`**。

> 对比：你的做法里，错误意味着崩溃；这里错误是**正常对话的一部分**。

---

## 3. 对照总表

| 环节 | 你的做法 | 现代 MCP |
|---|---|---|
| **参数契约** | 写死在函数签名，机器不可读 | JSON Schema，模型与校验器共用同一份 |
| **模型输出格式** | 自由文本 | 约束解码 → 结构上不可能非法 |
| **提取参数** | **正则** | 模板解析成 `tool_calls` 对象 |
| **传参** | `func(**d)` 裸传 | Pydantic 校验 → 签名绑定 |
| **多/少/错字段** | `TypeError` 崩溃 | 结构化错误，指明字段 |
| **出错处理** | 失败 | 回灌给模型重试 / 追问用户 |
| **加一个参数** | 改函数 + 改正则 + 改 prompt（三处） | 改类型注解一处，schema 自动更新 |
| **枚举越界** | 靠运气 | 约束解码下不可能；退一步也有校验拦截 |

---

## 4. 落到本项目的具体映射

好消息：**我们的 `schedule_command.v1.json` 可以同时喂给这五层**，因为它本来就是 JSON Schema。

| MCP 层 | 本项目的对应物 | 状态 |
|---|---|---|
| L1 工具声明 | `schema/schedule_command.v1.json` → MCP `inputSchema` | ✅ 已有，零转换 |
| L2 约束解码 | llama.cpp `json_schema` 参数 | ⬜ 加一个配置项 |
| L3 tool_call 解析 | 需要把数据改成 `<tool_call>` 格式重训 | ⬜ 路线③ |
| L4 Pydantic 校验+绑定 | 用 Pydantic 定义 + FastMCP | ✅ **已用 `executor.py` 实现了等价逻辑** |
| L5 错误回灌/追问 | `status: clarify` → elicitation | ⬜ |

**我刚刚写的 `bridge/executor.py` 就是 L4 + L5 的等价物**（显式校验 + 显式失败，绝不静默）：

```python
def execute(envelope, store, now) -> Outcome:
    # 返回 executed / need_clarify / rejected / failed
    # 任何异常都被兜成 failed, 绝不静默失败
```

---

## 5. 一个立刻可以做的强化：契约一致性测试

这是防止"代码里的接口"和"训练数据契约"漂移的唯一可靠办法：

```python
def test_schema_never_drifts():
    """代码里的 Pydantic 模型 必须与训练数据用的 Schema 完全一致"""
    from bridge.models import ScheduleEnvelope       # Pydantic 定义
    on_disk = json.load(open("schema/schedule_command.v1.json", encoding="utf-8"))
    assert ScheduleEnvelope.model_json_schema() == on_disk, \
        "接口契约漂移了！训练数据与工具接口不再匹配"
```

把它放进 CI。这样只要你改了 Pydantic 模型而忘了改 Schema（或反之），测试立刻红。

配合已有的两个测试：
1. `validate_dataset_vs_schema.py` — 数据集 100% 符合 Schema
2. `verify_dataset_e2e.py` — **数据集任意一条输出都能驱动工具正常启动**（4372/4372）

三者合起来，才构成"数据集可被训练"的完整保证。

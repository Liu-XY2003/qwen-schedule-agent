#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP 服务端: 把日程能力以标准 MCP 协议暴露给任意 Agent 客户端。

## 这个文件的意义

整个项目的架构是「**一份 Schema，四处消费**」:

    schema/schedule_command.v2.json   ← 唯一事实源
        ├── 约束解码语法（llama.cpp 生成 GBNF）      bridge/llm.py
        ├── LoRA 训练标签格式                        pod/gen_dataset.py
        ├── 执行层入参校验                            bridge/executor.py
        └── MCP 工具定义（inputSchema）               ← 本文件

所以这里**不是**手写一套工具描述, 而是从同一份 JSON Schema 派生出来。
这样"模型能生成的 JSON"和"MCP 客户端看到的工具签名"永远一致 ——
改了 Schema 就自动同步, 不会出现"训练时是一个字段、调用时是另一个字段"的漂移。

## 为什么 MCP 而不是自定义 HTTP 接口

MCP(Model Context Protocol) 是工具/上下文暴露的标准协议。走它意味着:
  · Claude Desktop / Cursor / 其他 MCP 客户端可以**零适配**接入
  · 工具发现(tools/list)是协议内建的, 客户端不用读文档
  · 和"用正则去解析模型输出"是本质不同的层次: MCP 管的是
    "工具如何被描述、发现、调用", 不管"中文怎么变成 JSON"。

## 运行

    # stdio 模式（给本地 Agent 客户端用）
    .venv-planner\\Scripts\\python.exe bridge\\mcp_server.py

    # 自检: 列出工具并试调一次
    .venv-planner\\Scripts\\python.exe bridge\\mcp_server.py --selftest
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Literal

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from mcp.server.mcpserver import MCPServer  # noqa: E402

SCHEMA_PATH = HERE.parent / "schema" / "schedule_command.v2.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
CMD = SCHEMA["properties"]["commands"]["items"]["properties"]

MODULES = CMD["module"]["enum"]
ACTIONS = CMD["action"]["enum"]
DATE_KINDS = CMD["when"]["properties"]["date_kind"]["enum"]
PERIODS = CMD["when"]["properties"]["period"]["enum"]

# ★ 关键: 工具参数的类型**直接从 Schema 的枚举派生**, 而不是手写一遍字符串。
#   这样 MCP 客户端拿到的 inputSchema.enum 与约束解码用的 GBNF、训练标签、
#   执行层校验完全同源 —— 改 Schema 就自动同步, 不可能出现契约漂移。
ModuleT = Literal[*MODULES]
ActionT = Literal[*ACTIONS]
DateKindT = Literal[*DATE_KINDS]
PeriodT = Literal[*PERIODS]

mcp = MCPServer(
    name="schedule-assistant",
    instructions=(
        "本地日程助手。日程数据只存在本机 SQLite, 不联网、不上传。"
        "时间用结构化槽位表达(date_kind/week_offset/time), 由服务端确定性解析成绝对时间。"
    ),
)


def _contract_note() -> str:
    return (f"module 取 {'/'.join(MODULES)}; action 取 {'/'.join(ACTIONS)}。"
            "时间只放在 when 里: date_kind=absolute/offset_day/weekday/month_day/unspecified, "
            "weekday 配 week_offset(本周=0, 下周=1, 上週=-1), month_day 配 month_offset。"
            "不要自己算绝对日期。与日程无关的请求用 reject。")


# ---------------------------------------------------------------- 工具
@mcp.tool()
def add_schedule_item(
    module: ModuleT,
    title: str,
    action: ActionT = "add",
    when_date_kind: DateKindT = "unspecified",
    when_date_value: str = "",
    when_week_offset: int = 0,
    when_time: str = "",
    when_period: PeriodT = "none",
    when_duration_min: int = 0,
    location: str = "",
    notes: str = "",
) -> str:
    """添加/修改一条日程。module 是类别(上课/考试/会议/作业/闹钟/提醒/备忘)。

    时间用槽位表达, 不要传绝对日期 —— 由服务端解析。返回执行结果 JSON。
    """
    cmd = {
        "module": module, "action": action, "title": title,
        "when": {
            "date_kind": when_date_kind,
            "date_value": when_date_value,
            "week_offset": when_week_offset,
            "time": when_time,
            "period": when_period,
        },
    }
    if when_duration_min:
        cmd["when"]["duration_min"] = when_duration_min
    if location:
        cmd["location"] = location
    if notes:
        cmd["notes"] = notes
    return _execute({"status": "ok", "commands": [cmd]})


@mcp.tool()
def list_schedule() -> str:
    """列出本机所有日程（按时间排序）。"""
    import sqlite3
    db = os.environ.get("SCHED_DB") or str(HERE.parent / "local" / "schedule.db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id,module,title,start_ts,duration_min,location,notes "
        "FROM events ORDER BY start_ts IS NULL, start_ts, id").fetchall()
    conn.close()
    return json.dumps([dict(r) for r in rows], ensure_ascii=False)


@mcp.tool()
def plan_week(text: str) -> str:
    """把一段杂乱的日程素材(聊天记录/多条待办)排成一周计划。

    会先抽取成待办+约束, 再由 CP-SAT 求解器排出可行计划;
    排不出来时会说明是哪几条约束在冲突。
    """
    try:
        from planning import plan_from_text
    except ImportError as e:
        return json.dumps({"error": f"规划求解器不可用: {e}"}, ensure_ascii=False)
    env, res = plan_from_text(text)
    out = {"envelope": env}
    if res is None:
        out["message"] = env.get("question") or "没有可规划的事项"
    else:
        out["plan"] = {
            "feasible": res.feasible, "solve_ms": res.solve_ms,
            "violations": res.violations,
            "assignments": [{"title": a.title, "start": a.start.isoformat(),
                             "end": a.end.isoformat()} for a in res.assignments],
        }
    return json.dumps(out, ensure_ascii=False)


@mcp.tool()
def describe_contract() -> str:
    """返回工具契约的 JSON Schema（就是约束解码用的同一份）。"""
    return json.dumps(SCHEMA, ensure_ascii=False)


def _execute(envelope: dict) -> str:
    from executor import execute  # 复用一阶段执行层, 不另写一套
    try:
        outcome = execute(envelope)
    except Exception as e:
        return json.dumps({"status": "failed", "error": str(e)}, ensure_ascii=False)
    return json.dumps(
        {"status": outcome.kind, "notes": outcome.notes,
         "items": [getattr(i, "__dict__", str(i)) for i in getattr(outcome, "items", [])]},
        ensure_ascii=False, default=str)


# ---------------------------------------------------------------- 自检 / 入口
def _selftest() -> int:
    import asyncio
    tools = asyncio.run(mcp.list_tools())
    print(f"工具数: {len(tools)}")
    for t in tools:
        props = (t.input_schema or {}).get("properties") or {}
        print(f"  - {t.name}  参数 {len(props)} 个: {', '.join(props) or '(无)'}")

    by_name = {t.name: t for t in tools}
    ok = len(tools) >= 3

    # ★ 核心断言: MCP 工具的枚举必须与 JSON Schema 完全一致
    props = by_name["add_schedule_item"].input_schema["properties"]
    mod_enum = props["module"].get("enum")
    act_enum = props["action"].get("enum")
    print(f"\n工具 module 枚举 = Schema: {mod_enum == MODULES}  {mod_enum}")
    print(f"工具 action 枚举 = Schema: {act_enum == ACTIONS}  {act_enum}")
    ok = ok and mod_enum == MODULES and act_enum == ACTIONS

    # 每个有参数的工具都要有 inputSchema
    has_schema = all((t.input_schema or {}).get("type") == "object" for t in tools)
    print(f"每个工具都有 object 型 inputSchema: {has_schema}")
    ok = ok and has_schema
    return 0 if ok else 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    mcp.run()

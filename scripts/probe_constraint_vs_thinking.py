#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证: 加上 json_schema 约束解码后, Qwen3 的思考模式是否被自动压制。

假设: llama.cpp 把 grammar 作用在整个生成过程上。若 grammar 要求输出必须以 `{` 开头,
模型就没有余地先输出"让我想想…"这类思考文本, 于是思考被结构性地跳过。

如果成立, 这是个很有价值的结论:
一阶段为了"保证格式合法"引入的约束解码, 在二阶段同时解决了小模型"思考太慢"的问题。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

PROMPT = "把这句话转换成日程指令：下周二上午九点开会，时长一小时"

SCHEMA = {
    "type": "object",
    "properties": {
        "module": {"type": "string",
                   "enum": ["class", "exam", "meeting", "assignment", "alarm", "reminder", "memo"]},
        "title": {"type": "string"},
        "time": {"type": "string"},
        "duration_min": {"type": "integer"},
    },
    "required": ["module", "title", "time"],
    "additionalProperties": False,
}


def run(port: int, constrain: bool, max_tokens: int = 300):
    payload = {
        "model": "x",
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
    }
    if constrain:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "cmd", "schema": SCHEMA},
        }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})

    t0 = time.perf_counter()
    first_content = None
    n_reason = n_content = 0
    content_parts, reason_parts = [], []

    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.strip()
            if not line or not line.startswith(b"data:"):
                continue
            p = line[5:].strip()
            if p == b"[DONE]":
                break
            try:
                obj = json.loads(p)
            except Exception:
                continue
            d = (obj.get("choices") or [{}])[0].get("delta") or {}
            if d.get("reasoning_content"):
                n_reason += 1
                reason_parts.append(d["reasoning_content"])
            if d.get("content"):
                n_content += 1
                content_parts.append(d["content"])
                if first_content is None:
                    first_content = (time.perf_counter() - t0) * 1000

    total = (time.perf_counter() - t0) * 1000
    return {
        "first_content_ms": first_content, "total_ms": total,
        "n_reason": n_reason, "n_content": n_content,
        "content": "".join(content_parts),
        "reason": "".join(reason_parts),
    }


def main() -> int:
    port = int(sys.argv[1])
    label = sys.argv[2] if len(sys.argv) > 2 else ""

    for name, constrain in (("不加约束（自由生成）", False), ("加 json_schema 约束", True)):
        res = run(port, constrain)
        print(f"\n--- {label} · {name} ---")
        print(f"  思考 chunk : {res['n_reason']}")
        print(f"  正文 chunk : {res['n_content']}")
        print(f"  首字延迟   : {(res['first_content_ms'] or -1):.0f} ms")
        print(f"  总时长     : {res['total_ms']:.0f} ms")
        print(f"  输出       : {res['content'][:220]!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

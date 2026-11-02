#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查生产用的模型是否输出思考内容。

背景: 裸 Qwen3-4B 默认开启思考, 200+ token 全用于 reasoning, 正文一个不吐 —— 完全不可用。
但一阶段生产系统 (qwen3-0.6b-sched-v4, LoRA 微调后) 一直工作正常。
推测: 微调把"直接输出 JSON"固化进了模型, 顺带消除了思考行为。

用法: python scripts/probe_production_thinking.py 18080
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

port = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
PROMPT = "下下周二上午九点加一门计算机原理，在教三201"


def run() -> dict:
    body = {
        "model": "x",
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 256,
        "temperature": 0,
        "stream": True,
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = None
    n_r = n_c = 0
    reason, content = [], []
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
                n_r += 1
                reason.append(d["reasoning_content"])
            if d.get("content"):
                n_c += 1
                content.append(d["content"])
                if first is None:
                    first = (time.perf_counter() - t0) * 1000
    return {
        "first": first,
        "total": (time.perf_counter() - t0) * 1000,
        "n_r": n_r, "n_c": n_c,
        "reason": "".join(reason)[:200],
        "content": "".join(content)[:400],
    }


try:
    res = run()
except Exception as e:
    print(f"请求失败: {e}")
    sys.exit(1)

print(f"=== 生产模型 (llama-server :{port}) ===")
print(f"  思考 chunk : {res['n_r']}")
print(f"  正文 chunk : {res['n_c']}")
print(f"  首字延迟   : {(res['first'] or -1):.0f} ms")
print(f"  总时长     : {res['total']:.0f} ms")
if res["reason"]:
    print(f"  思考片段   : {res['reason']!r}")
print(f"  正文       : {res['content']!r}")
print()
if res["n_r"] == 0 and res["n_c"] > 0:
    print("结论: 生产模型【不思考】—— 微调已经把这个行为消除了")
elif res["n_r"] > 0:
    print("结论: 生产模型【也会思考】, 但正文仍能输出")
else:
    print("结论: 既没思考也没正文, 需要进一步查")

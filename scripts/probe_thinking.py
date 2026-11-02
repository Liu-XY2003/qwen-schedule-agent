#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确认 Qwen3 思考模式对流式输出的影响，并对比关掉思考后的 TTFT。

Qwen3 默认会先输出 reasoning_content（思考过程），再输出 content（正式回答）。
思考模式在交互式应用里是灾难：4B 在核显上 22 tok/s，500 个思考 token 就是 20+ 秒。

llama.cpp 关闭方式: 启动时加 --chat-template-kwargs '{"enable_thinking":false}'
或在 prompt 里加 /no_think（取决于模板）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

PROMPT = "把这句话转换成日程指令：下周二上午九点开会，时长一小时"


def probe(port: int, stream: bool, max_tokens: int = 200):
    body = json.dumps({
        "model": "x",
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": stream,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"})

    t0 = time.perf_counter()
    first_content = None
    first_any = None
    n_reason = n_content = 0
    text_reason = []
    text_content = []

    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.strip()
            if not line or not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                break
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            delta = (obj.get("choices") or [{}])[0].get("delta") or {}
            rc = delta.get("reasoning_content")
            ct = delta.get("content")
            now = (time.perf_counter() - t0) * 1000
            if rc:
                n_reason += 1
                text_reason.append(rc)
                if first_any is None:
                    first_any = now
            if ct:
                n_content += 1
                text_content.append(ct)
                if first_content is None:
                    first_content = now
                    if first_any is None:
                        first_any = now
    total = (time.perf_counter() - t0) * 1000
    return {
        "first_any_ms": first_any, "first_content_ms": first_content,
        "total_ms": total, "n_reason": n_reason, "n_content": n_content,
        "reasoning": "".join(text_reason)[:300], "content": "".join(text_content)[:300],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    r = probe(args.port, stream=True, max_tokens=200)
    print(f"\n=== {args.label} (stream=True, max_tokens=200) ===")
    print(f"  首个 chunk(任意) : {r['first_any_ms'] or -1:8.0f} ms")
    print(f"  首个 content     : {r['first_content_ms'] or -1:8.0f} ms")
    print(f"  总时长           : {r['total_ms']:8.0f} ms")
    print(f"  reasoning chunks : {r['n_reason']}")
    print(f"  content   chunks : {r['n_content']}")
    if r["reasoning"]:
        print(f"  思考片段: {r['reasoning'][:150]!r}")
    print(f"  正文片段: {r['content'][:150]!r}")
    verdict = "思考模式【开启】—— 交互场景必须关掉" if r["n_reason"] > 0 else "思考模式未触发"
    print(f"  判定: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

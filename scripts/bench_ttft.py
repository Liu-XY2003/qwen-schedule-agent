#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测首字延迟(TTFT) vs 总时长。

为什么单独测这个: 对话式界面里, 用户感知的"快不快"主要取决于**第一个字什么时候出来**,
而不是整段说完要多久。22 tok/s 但如果 300ms 就出首字并持续流式输出, 体感是可以接受的;
反之一次性返回 6 秒则是灾难。

用法 (先把目标模型起在某个端口):
    python scripts/bench_ttft.py --port 18999 --max-tokens 128 --runs 3
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

PROMPT = "把这句话转换成日程指令：下周二上午九点开会"


def one_run(port: int, max_tokens: int) -> tuple[float, float, int]:
    """返回 (TTFT毫秒, 总时长毫秒, 生成token数)"""
    body = json.dumps({
        "model": "x",
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    ttft = None
    chunks = 0
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
            if delta.get("content"):
                chunks += 1
                if ttft is None:
                    ttft = (time.perf_counter() - t0) * 1000
    total = (time.perf_counter() - t0) * 1000
    return ttft or total, total, chunks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    # 预热
    try:
        one_run(args.port, 16)
    except Exception as e:
        print(f"预热失败: {e}")
        return 1

    ttfts, totals, chunks = [], [], []
    for _ in range(args.runs):
        a, b, c = one_run(args.port, args.max_tokens)
        ttfts.append(a)
        totals.append(b)
        chunks.append(c)

    print(f"\n模型: {args.label or '?'}   max_tokens={args.max_tokens}   n={args.runs}")
    print(f"  首字延迟(TTFT) 中位 : {statistics.median(ttfts):8.0f} ms   (样本 {[round(x) for x in ttfts]})")
    print(f"  总时长         中位 : {statistics.median(totals):8.0f} ms")
    print(f"  生成 chunk 数  中位 : {statistics.median(chunks):8.0f}")
    med_total = statistics.median(totals) / 1000
    med_chunks = statistics.median(chunks) or 1
    print(f"  等效吞吐            : {med_chunks / med_total:8.1f} tok/s（按 chunk 计）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

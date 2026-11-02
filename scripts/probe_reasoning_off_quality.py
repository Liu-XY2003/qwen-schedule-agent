#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证给生产模型加 --reasoning off 是否影响正确性。

在提议"给现有服务关掉思考"之前必须验证: 关掉之后解析准确率不掉、延迟变快。
用生产用的 LoRA 微调 0.6B, 走真实 system prompt + json_schema, 跑一组代表性用例。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

ROOT = pathlib.Path(r"D:\Projects\qwen-local-tool-agent")

# 从 app.py 里取真实的 SYS（契约的一部分，必须逐字节一致）
app_src = (ROOT / "bridge" / "app.py").read_text(encoding="utf-8")
m = re.search(r"SYS = \(\n(.*?)\n\)", app_src, re.S)
SYS = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1)))
SCHEMA = json.loads((ROOT / "schema" / "schedule_command.v2.json").read_text(encoding="utf-8"))

CASES = [
    ("下下周二上午九点加一门计算机原理，在教三201", "2026-10-06", "class"),
    ("明天晚上七点半提醒我给家里打电话", "2026-11-03", "reminder"),
    ("加个明早八点的闹钟", "2026-11-03", "alarm"),
    ("下个月3号上午九点开会", "2026-12-03", "meeting"),
    ("十月23号下午10点19提醒我去寿司店买鲜花", "2026-10-23", "reminder"),
]


def call(port: int, text: str) -> dict:
    body = {
        "model": "x",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": text},
        ],
        "max_tokens": 256,
        "temperature": 0,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "env", "schema": SCHEMA}},
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        obj = json.loads(r.read().decode("utf-8"))
    ms = (time.perf_counter() - t0) * 1000
    content = obj["choices"][0]["message"].get("content") or ""
    return {"ms": ms, "raw": content, "usage": obj.get("usage", {})}


def resolve_weekday(year: int, month: int, day: int, target: str, week_offset: int):
    """按项目规则: 周一为 week_offset=0 的基准周."""
    import datetime as dt
    today = dt.date(year, month, day)
    monday = today - dt.timedelta(days=today.weekday())
    base = monday + dt.timedelta(weeks=week_offset)
    idx = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"].index(target)
    return base + dt.timedelta(days=idx)


def check(port: int, label: str):
    import datetime as dt
    print(f"\n{'='*70}\n{label}  (port {port})\n{'='*70}")
    ok = bad = 0
    total_ms = 0.0
    for text, want_date, want_mod in CASES:
        try:
            r = call(port, text)
        except Exception as e:
            print(f"  [ERR ] {text[:34]:36} {e}")
            bad += 1
            continue
        total_ms += r["ms"]
        try:
            env = json.loads(r["raw"])
        except Exception:
            print(f"  [JSON] {text[:34]:36} 输出不是合法 JSON")
            bad += 1
            continue
        cmd = (env.get("commands") or [{}])[0]
        mod = cmd.get("module")
        when = cmd.get("when") or {}
        # 只校验"模型是否把关键语义提对了"，绝对日期由 resolve_time 负责
        good_mod = mod == want_mod
        got_date = None
        if when.get("date_kind") == "weekday" and when.get("date_value"):
            today = dt.date(2026, 11, 2)
            d = resolve_weekday(today.year, today.month, today.day,
                                when["date_value"], when.get("week_offset") or 0)
            got_date = d.isoformat()
        elif when.get("date_kind") == "month_day":
            mo = when.get("month_offset") or 0
            today = dt.date(2026, 11, 2)
            y, mth = today.year, today.month + mo
            while mth > 12:
                mth -= 12
                y += 1
            try:
                got_date = dt.date(y, mth, int(when.get("date_value"))).isoformat()
            except Exception:
                got_date = None
        elif when.get("date_kind") == "absolute":
            got_date = when.get("date_value")

        date_ok = (got_date == want_date) if got_date else None
        status = "OK  " if (good_mod and date_ok is not False) else "BAD "
        if status == "OK  ":
            ok += 1
        else:
            bad += 1
        print(f"  [{status}] {text[:34]:36} mod={mod!s:10} date={got_date!s:12} "
              f"{r['ms']:6.0f}ms  ctoks={r['usage'].get('completion_tokens')}")
    print(f"\n  通过 {ok}/{len(CASES)}   平均 {total_ms/len(CASES):.0f} ms")
    return ok, bad, total_ms / len(CASES)


if __name__ == "__main__":
    port = int(sys.argv[1])
    label = sys.argv[2] if len(sys.argv) > 2 else f"port{port}"
    check(port, label)

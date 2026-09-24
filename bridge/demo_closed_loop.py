#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闭环演示: 从数据集的原始样本, 一路走到数据库里的绝对时间"""
import json
import sys
from datetime import datetime

sys.path.insert(0, r"D:\Projects\qwen-local-tool-agent\bridge")
from executor import Store, execute  # noqa: E402
import _console  # noqa: F401  (Windows 控制台 UTF-8 兜底)

DATA = r"D:\Projects\qwen-local-tool-agent\data\generated\train.jsonl"
NOW = datetime(2026, 9, 22, 15, 30, 0)   # 2026-09-22 是星期二

rows = [json.loads(l) for l in open(DATA, encoding="utf-8") if l.strip()]

# 挑几条有代表性的
picks = []
def want(pred, n=1):
    got = 0
    for r in rows:
        if got >= n:
            break
        env = json.loads(r["messages"][2]["content"])
        if env["status"] != "ok" or not env["commands"]:
            continue
        if "when" not in env["commands"][0]:      # memo 类没有 when
            continue
        if pred(env):
            picks.append(r); got += 1

want(lambda e: e["commands"][0]["when"].get("period") == "none"
     and e["commands"][0]["when"].get("date_kind") == "weekday")
want(lambda e: e["commands"][0]["when"].get("week_ref") == "next")
want(lambda e: e["commands"][0]["when"].get("date_kind") == "offset_day")
want(lambda e: e["commands"][0]["when"].get("date_kind") == "absolute")
want(lambda e: e["commands"][0]["when"].get("fuzzy"))
want(lambda e: e["commands"][0]["module"] == "memo")
want(lambda e: "remind_before_min" in e["commands"][0])
want(lambda e: len(e["commands"]) >= 2)
want(lambda e: e["commands"][0]["when"].get("duration_min") and
     "date_kind" not in e["commands"][0]["when"])
for r in rows:      # reject / clarify
    env = json.loads(r["messages"][2]["content"])
    if env["status"] in ("reject", "clarify"):
        picks.append(r)
        if sum(1 for x in picks if json.loads(x["messages"][2]["content"])["status"] == env["status"]) >= 2:
            break

# 去重并保持顺序
seen, uniq = set(), []
for r in picks:
    k = r["messages"][1]["content"]
    if k not in seen:
        seen.add(k); uniq.append(r)

store = Store(":memory:")
print("=" * 100)
print(f"闭环演示  |  『现在』= {NOW}   ({'星期二' if NOW.weekday()==1 else NOW.strftime('%A')})")
print("=" * 100)

for r in uniq:
    utt = r["messages"][1]["content"]
    env = json.loads(r["messages"][2]["content"])
    out = execute(env, store, NOW)
    print()
    print(f"用户说 : {utt}")
    print(f"模型出 : {json.dumps(env, ensure_ascii=False)}")
    if out.kind == "executed":
        for it in out.event["items"]:
            flags = []
            if it["ambiguous"]:
                flags.append("时间有歧义")
            if it.get("is_past"):
                flags.append("⚠️已过去")
            tag = ("  ← " + " / ".join(flags)) if flags else ""
            print(f"工具执行: ✅ #{it['id']} [{it['module']}] {it['title']}"
                  f"  →  绝对时间 {it['start']}{tag}")
            for rs in it.get("reasons", []):
                print(f"          · {rs}")
    elif out.kind == "need_clarify":
        print(f"工具执行: ❓ 反问用户 —— {out.detail}")
    else:
        print(f"工具执行: 🚫 {out.kind} —— {out.detail}")

print()
print("=" * 100)
print(f"数据库最终事件数: {store.count()}")
print("=" * 100)

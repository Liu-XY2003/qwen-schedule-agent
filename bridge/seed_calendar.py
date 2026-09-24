#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给新日历灌入示例日程, 并验证增删查"""
import os
import json
import urllib.request
import _console  # noqa: F401  (Windows 控制台 UTF-8 兜底)

API = os.environ.get("SCHED_API", "http://127.0.0.1:8800").rstrip("/")
def call(path, payload=None, method="POST"):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


print("=== 清空 ===")
print(call("/api/reset", {}))

SEEDS = [
    "明天上午八点高等数学，在教三201，提前15分钟提醒我",
    "明天下午两点操作系统实验课，在实验楼302",
    "后天上午十点计算机网络，提前10分钟提醒我",
    "本周五下午四点交编译原理大作业",
    "下周一上午九点线性代数，在教三105",
    "下周三下午三点有数据结构期中考试",
    "每天早上七点提醒我背单词",
    "今晚九点提醒我跑步",
    "记一下，实验室门禁密码是 8823",
]

print("\n=== 逐条添加 ===")
for s in SEEDS:
    try:
        j = call("/api/chat", {"text": s})
        ex = j.get("execution") or {}
        if ex.get("kind") == "executed":
            it = ex["items"][0]
            print(f"  OK  {s}\n      -> #{it['id']} {it['title']} @ {it['start']}"
                  + ("  ⚠歧义" if it.get("ambiguous") else ""))
        else:
            print(f"  XX  {s}\n      -> {ex.get('kind')} {ex.get('detail')}")
    except Exception as e:
        print(f"  !!  {s} -> {e}")

print("\n=== 当前日程 ===")
ev = call("/api/events", method="GET")["events"]
for e in ev:
    print(f"  #{e['id']:<3} {e['module']:<10} {str(e['start']):<20} {e['title']}")
memos = [e for e in ev if not e["start"]]
print(f"\n  总计 {len(ev)} 条（其中有时间 {len(ev)-len(memos)} 条，备忘 {len(memos)} 条）")

print("\n=== 测试删除最后一条 ===")
if ev:
    last = max(e["id"] for e in ev)
    print(" ", call(f"/api/events/{last}", method="DELETE"))
    print("  剩余:", len(call("/api/events", method="GET")["events"]))

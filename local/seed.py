#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理测试数据并灌入干净示例 (本机部署)"""
import json
import os
import urllib.request

API = os.environ.get("SCHED_API", "http://127.0.0.1:8800")


def call(p, pl=None, m="POST"):
    d = json.dumps(pl).encode("utf-8") if pl is not None else None
    r = urllib.request.Request(API + p, data=d,
                               headers={"Content-Type": "application/json"}, method=m)
    return json.loads(urllib.request.urlopen(r, timeout=120).read().decode("utf-8"))


print("清空:", call("/api/reset", {}))

SEEDS = [
    "明天上午八点高等数学，在教三201，提前15分钟提醒我",
    "明天下午两点操作系统实验课，在实验楼302",
    "后天上午十点计算机网络，提前10分钟提醒我",
    "本周五下午四点交编译原理大作业",
    "下周二上午九点线性代数，在教三105",
    "下下周二上午九点加一门计算机原理，在教三201",
    "下周三下午三点有数据结构期中考试",
    "下个月3号上午九点项目评审",
    "加个明早八点的闹钟",
    "记一下，实验室门禁密码是 8823",
]
ok = 0
for s in SEEDS:
    j = call("/api/chat", {"text": s})
    ex = j.get("execution") or {}
    it = (ex.get("items") or [{}])[0]
    good = ex.get("kind") == "executed"
    ok += good
    print(f"  {'OK ' if good else 'XX '}{str(it.get('title',''))[:16]:<18} @ {it.get('start','-')}")

ev = call("/api/events", m="GET")["events"]
print(f"\n成功 {ok}/{len(SEEDS)} | 日历共 {len(ev)} 条")
for e in sorted(ev, key=lambda x: (x["start"] or "9999")):
    print(f"  #{e['id']:<3} {e['module']:<10} {str(e['start'])[:16]:<17} {e['title']}")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端延迟测试: 本地 -> Tailscale -> App -> llama-server"""
import os
import json
import statistics
import time
import urllib.request

API = os.environ.get("SCHED_API", "http://127.0.0.1:8800").rstrip("/")
CASES = [
    "明天下午两点开会", "下周二上午九点计算机原理", "今晚提醒我买牛奶",
    "下个月3号上午九点项目评审", "记一下充电宝要还", "今天天气怎么样",
    "加个明早八点的闹钟", "下下周五下午四点交报告", "十月23号下午10点19买鲜花",
    "下下周二上午九点加一门计算机原理，在教三201",
]


def post(t):
    r = urllib.request.Request(API + "/api/chat",
                               data=json.dumps({"text": t}).encode("utf-8"),
                               headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    j = json.loads(urllib.request.urlopen(r, timeout=60).read().decode("utf-8"))
    return j, (time.time() - t0) * 1000


print("端到端延迟 (本地 → Tailscale → App → llama-server)")
print("-" * 88)
post(CASES[0])          # 热身
lat = []
for c in CASES:
    j, ms = post(c)
    lat.append(ms)
    it = ((j.get("execution") or {}).get("items") or [{}])[0]
    print(f"  {ms:7.0f}ms  模型 {j.get('gen_ms', 0):>5}ms  {c:<26} -> {it.get('start', '-')}")
lat.sort()
print("-" * 88)
print(f"中位 {statistics.median(lat):.0f}ms   平均 {sum(lat)/len(lat):.0f}ms   "
      f"最小 {lat[0]:.0f}ms   最大 {lat[-1]:.0f}ms")
print(f"\n对比: 改造前 (HF transformers 进程内推理) 平均约 3800ms")
print(f"提速约 {3800/(sum(lat)/len(lat)):.1f} 倍")

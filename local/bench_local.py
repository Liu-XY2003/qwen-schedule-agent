#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机 iGPU 部署的性能实测"""
import json
import statistics
import time
import urllib.request

API = "http://127.0.0.1:8800"
LLM = "http://127.0.0.1:18080"

CASES = [
    "下下周二上午九点加一门计算机原理，在教三201",
    "明天下午两点操作系统实验课，在实验楼302",
    "下个月3号上午九点项目评审",
    "加个明早八点的闹钟",
    "今晚提醒我买牛奶",
    "十月23号下午10点19提醒我去寿司店买鲜花",
    "本周五下午四点交编译原理大作业",
    "今天天气怎么样",
]


def post(t):
    r = urllib.request.Request(API + "/api/chat",
                               data=json.dumps({"text": t}).encode("utf-8"),
                               headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    j = json.loads(urllib.request.urlopen(r, timeout=120).read().decode("utf-8"))
    return j, (time.time() - t0) * 1000


print("=" * 90)
print("本机部署实测  (Ryzen AI 9 365 + Radeon 880M iGPU / llama.cpp Vulkan)")
print("=" * 90)

print("\n[1] 冷启动第一发")
j, ms = post(CASES[0])
print(f"    {ms:.0f}ms  (含 Vulkan shader 编译)")

print("\n[2] 稳定态 (连跑 3 轮)")
lat, gens = [], []
for rnd in range(3):
    for c in CASES:
        j, ms = post(c)
        lat.append(ms)
        gens.append(j.get("gen_ms", 0))
lat.sort()
print(f"    样本 {len(lat)} 次")
print(f"    端到端  中位 {statistics.median(lat):.0f}ms   平均 {sum(lat)/len(lat):.0f}ms   "
      f"最小 {lat[0]:.0f}ms   最大 {lat[-1]:.0f}ms")
print(f"    纯模型  中位 {statistics.median(gens):.0f}ms")

print("\n[3] 逐条结果")
for c in CASES:
    j, ms = post(c)
    ex = j.get("execution") or {}
    it = (ex.get("items") or [{}])[0]
    print(f"    {ms:6.0f}ms  {c[:30]:<32} -> {it.get('start', '-')}")

print("\n[4] 吞吐 (直接打 llama-server)")
body = {
    "messages": [{"role": "system", "content": "你是日程助手，把用户的中文请求转换为 JSON，只输出 JSON。"},
                 {"role": "user", "content": "下下周二上午九点加一门计算机原理，在教三201"}],
    "max_tokens": 120, "temperature": 0,
    "chat_template_kwargs": {"enable_thinking": False},
}
r = urllib.request.Request(LLM + "/v1/chat/completions",
                           data=json.dumps(body).encode("utf-8"),
                           headers={"Content-Type": "application/json"}, method="POST")
urllib.request.urlopen(r, timeout=60).read()          # 热身
t0 = time.time()
resp = urllib.request.urlopen(r, timeout=60).read()
dt = time.time() - t0
u = json.loads(resp.decode("utf-8")).get("usage", {})
ct = u.get("completion_tokens") or 0
print(f"    生成 {ct} token / {dt*1000:.0f}ms  ->  {ct/dt:.0f} tok/s")

print("\n" + "=" * 90)
print("对比参考:")
print("  本机 iGPU 部署        端到端 中位 ~%dms" % statistics.median(lat))
print("  服务器 2080Ti (llama.cpp)  端到端 中位 262ms  (但服务器 9/30 到期)")
print("  服务器 2080Ti (HF 旧版)     端到端 ~3800ms")
print("=" * 90)

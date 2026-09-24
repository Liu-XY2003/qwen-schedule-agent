#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过本地 HTTP 接口测试部署好的模型: 准确率 + 延迟"""
import os
import json
import time
import urllib.request
import _console  # noqa: F401  (Windows 控制台 UTF-8 兜底)

API = os.environ.get("SCHED_API", "http://127.0.0.1:8800").rstrip("/")
OUT = r"D:\Projects\qwen-local-tool-agent\bridge\web_e2e_report.txt"

CASES = [
    ("为我的周二上午九点添加一个计算机原理的课程",
     {"status": "ok", "module": "class", "title": "计算机原理", "time": "09:00"}),
    ("下周三下午三点有高数考试", {"status": "ok", "module": "exam", "time": "15:00"}),
    ("加个明早八点的闹钟", {"status": "ok", "module": "alarm", "time": "08:00"}),
    ("今晚提醒我买牛奶", {"status": "ok", "module": "reminder", "title": "买牛奶"}),
    ("今天天气怎么样", {"status": "reject"}),
    ("帮我加个课", {"status": "clarify"}),
    ("周五之前要交操作系统实验报告", {"status": "ok", "module": "assignment", "title": "操作系统实验报告"}),
    ("周四下午两点在教三201开班会", {"status": "ok", "module": "meeting", "time": "14:00", "location": "教三201"}),
    ("下周二上午十点，编译原理，实验楼302", {"status": "ok", "module": "class", "title": "编译原理"}),
    ("明天晚上七点半提醒我给家里打个电话", {"status": "ok", "module": "reminder", "time": "19:30"}),
    ("记一下，我的快递取件码是 8823", {"status": "ok", "module": "memo", "notes": "8823"}),
    ("麻烦帮我看看今天几号", {"status": "reject"}),
    ("我今天不想加日程，就是想问问你吃饭了没", {"status": "reject"}),
    ("下周一下午两点到四点有实验室安全培训", {"status": "ok", "module": "meeting", "time": "14:00"}),
    ("每天早上七点提醒我背单词", {"status": "ok", "module": "reminder", "title": "背单词"}),
]


def post(path, payload):
    req = urllib.request.Request(
        API + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def match(env, want):
    if env.get("status") != want["status"]:
        return False
    if want["status"] != "ok":
        return True
    if not env.get("commands"):
        return False
    c = env["commands"][0]
    if want.get("module") and c.get("module") != want["module"]:
        return False
    if want.get("title") and want["title"] not in str(c.get("title", "")):
        return False
    if want.get("time") and (c.get("when") or {}).get("time") != want["time"]:
        return False
    if want.get("location") and c.get("location") != want["location"]:
        return False
    if want.get("notes") and str(c.get("notes")) != want["notes"]:
        return False
    return True


lines = []
def say(s=""):
    print(s, flush=True)
    lines.append(str(s))

say("=" * 100)
say("部署后模型端到端测试 (通过 {API})")
say("=" * 100)

n_ok = n_tot = 0
lat, schema_bad = [], 0
for text, want in CASES:
    try:
        r = post("/api/chat", {"text": text})
    except Exception as e:
        say(f"XX  {text}\n      请求失败: {e}")
        n_tot += 1
        continue
    lat.append(r.get("total_ms", 0))
    if not r.get("schema_ok"):
        schema_bad += 1
    pred = r.get("envelope")
    ok = match(pred, want) if pred else False
    n_tot += 1
    n_ok += 1 if ok else 0
    flag = "OK " if ok else "XX "
    say(f"{flag} {text}")
    say(f"       模型: {r.get('model_raw','')[:150]}")
    ex = r.get("execution") or {}
    if ex.get("kind") == "executed":
        for it in ex.get("items", []):
            extra = []
            if it.get("ambiguous"):
                extra.append("歧义")
            if it.get("is_past"):
                extra.append("已过去")
            say(f"       执行: #{it['id']} [{it['module']}] {it['title']} → {it['start']}"
                + ("  ← " + "/".join(extra) if extra else ""))
    else:
        say(f"       执行: {ex.get('kind')} — {ex.get('detail')}")
    if r.get("schema_error"):
        say(f"       ⚠️ Schema: {'; '.join(r['schema_error'])}")
    say(f"       耗时: {r.get('total_ms')}ms (模型 {r.get('gen_ms')}ms)")
    say()

say("=" * 100)
say(f"真实用例通过 : {n_ok}/{n_tot} = {100*n_ok/max(1,n_tot):.0f}%")
say(f"Schema 不合规 : {schema_bad}/{n_tot}")
if lat:
    lat_sorted = sorted(lat)
    say(f"延迟         : 平均 {sum(lat)/len(lat):.0f}ms | 中位 {lat_sorted[len(lat)//2]}ms "
        f"| 最小 {min(lat)}ms | 最大 {max(lat)}ms")
say("=" * 100)

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("report ->", OUT)

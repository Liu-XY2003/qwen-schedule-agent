#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""证明「标签校验器」真的能抓到错误。

一个永远通过的校验器等于没有校验器。这个测试故意把标签改坏, 然后断言校验器**必须**报错。

★ 关键: 改坏必须是**有效的**改坏。
  第一版测试直接把 priority 设成 high, 但样本原本就是 high —— 等于没改,
  于是"漏报"其实是我的测试写错了, 不是校验器的问题。
  正确做法是改成"文本明确不支持的那个值":
    如果所在分句里没有任何强措辞, 才把 priority 改成 high —— 这时它一定是错的。
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gen_planning_dataset as g  # noqa: E402
import verify_planning_dataset as v  # noqa: E402

CHECKS = 0
FAILS: list[str] = []


def ok(name, cond, detail=""):
    global CHECKS
    CHECKS += 1
    if cond:
        print(f"OK   {name}")
    else:
        print(f"FAIL {name}  {detail}")
        FAILS.append(name)


rows = g.generate(400, 12345)
ok("生成样本非空", len(rows) > 300, f"只有 {len(rows)}")

# ---- 1. 原始数据必须 0 误报 ----
false_pos = sum(
    bool(v.check_one(r["messages"][1]["content"], json.loads(r["messages"][2]["content"])))
    for r in rows)
ok("原始数据集无误报", false_pos == 0, f"{false_pos} 条误报")


# ---- 2. 每类"有效改坏"都必须被抓到 ----
def _scope(text, title):
    return v.clause_of(title, v.split_clauses(text)) or text


def mut_dur(text, e):
    """改成一个分句里没出现、也不是默认值的时长。"""
    it = e["items"][0]
    sc = _scope(text, it["title"])
    for cand in (300, 20, 240, 40, 150):
        if cand == it.get("duration_min"):
            continue
        if any(p in sc for p in v.DUR_PAT.get(cand, [])):
            continue
        if v.TITLE_DEFAULT.get(it["title"]) == cand:
            continue
        it["duration_min"] = cand
        return True
    return False


def mut_deadline(text, e):
    it = e["items"][0]
    sc = _scope(text, it["title"])
    for cand in ("下下周五", "11-23", "后天"):
        if cand != it.get("deadline_date") and cand not in sc:
            it["deadline_date"] = cand
            return True
    return False


def mut_priority(text, e):
    it = e["items"][0]
    sc = _scope(text, it["title"])
    if not any(w in sc for w in v.HIGH_WORDS) and it.get("priority") != "high":
        it["priority"] = "high"
        return True
    if not any(w in sc for w in v.LOW_WORDS) and it.get("priority") != "low":
        it["priority"] = "low"
        return True
    return False


def mut_preferred(text, e):
    it = e["items"][0]
    sc = _scope(text, it["title"])
    for cand, words in (("eve", ["晚上"]), ("am", ["上午"]), ("pm", ["下午"])):
        if it.get("preferred") != cand and not any(w in sc for w in words):
            it["preferred"] = cand
            return True
    return False


def mut_keepfree(text, e):
    """加一个文本里完全没提到的 周X+时段 约束。"""
    for day, slot in (("SU", "evening"), ("SA", "morning"), ("MO", "afternoon")):
        combo = f"周{v.WD_CN[day]}{v.SLOT_CN[slot]}"
        if combo in text:
            continue
        s, en = v.SLOT_RANGE[slot]
        e.setdefault("constraints", []).append(
            {"kind": "keep_free", "weight": "hard", "day": day, "start": s, "end": en})
        return True
    return False


MUTATORS = {"时长": mut_dur, "截止": mut_deadline, "优先级": mut_priority,
            "时段偏好": mut_preferred, "keep_free": mut_keepfree}

for name, mut in MUTATORS.items():
    caught = tried = 0
    for r in rows:
        e = json.loads(r["messages"][2]["content"])
        text = r["messages"][1]["content"]
        if e.get("status") != "ok" or not e.get("items"):
            continue
        if v.check_one(text, json.loads(json.dumps(e))):
            continue                      # 原始就有问题的不参与
        if not mut(text, e):
            continue
        tried += 1
        if v.check_one(text, e):
            caught += 1
        if tried >= 60:
            break
    ok(f"能抓到「{name}」被改坏", tried >= 20 and caught == tried,
       f"{caught}/{tried}（有效样本数需≥20）")

# ---- 3. 端到端命令行退出码 ----
with tempfile.TemporaryDirectory() as d:
    good = os.path.join(d, "good.jsonl")
    badp = os.path.join(d, "bad.jsonl")
    with open(good, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    broken = []
    for r in rows[:60]:
        e = json.loads(r["messages"][2]["content"])
        text = r["messages"][1]["content"]
        if e.get("status") == "ok" and e.get("items") and not v.check_one(text, e):
            mut_priority(text, e)
        broken.append({"messages": [r["messages"][0], r["messages"][1],
                                    {"role": "assistant",
                                     "content": json.dumps(e, ensure_ascii=False)}]})
    with open(badp, "w", encoding="utf-8") as f:
        for b in broken:
            f.write(json.dumps(b, ensure_ascii=False) + "\n")

    def rc(p):
        return subprocess.run(
            [sys.executable, os.path.join(HERE, "verify_planning_dataset.py"), p],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace").returncode

    ok("干净数据命令行退出码=0", rc(good) == 0)
    ok("脏数据命令行退出码=1", rc(badp) == 1)

print()
if FAILS:
    print(f"失败 {len(FAILS)}/{CHECKS}: {FAILS}")
    sys.exit(1)
print(f"校验器自测通过 ({CHECKS} 项) —— 能抓到错误, 也不误报")

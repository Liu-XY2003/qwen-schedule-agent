#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查「训练用 system prompt」与「推理用 system prompt」是否逐字相同。

这个检查看起来小题大做, 但它防的是一类**静默失效**的 bug:
    · 训练时用的 SYS 与推理时的 SYS 差一个字
    · 模型在训练分布里没见过推理时的 prompt
    · 结果: 微调后准确率不升反降, 而训练 loss 看起来完全正常

一阶段就吃过这个亏, 所以把它变成 CI 断言: 改一处必须改两处。
"""
from __future__ import annotations

import importlib.util
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


gen = load(os.path.join(HERE, "gen_planning_dataset.py"), "gpd")
plan = load(os.path.join(REPO, "bridge", "planning.py"), "planning_mod")

fails = []
if gen.SYS != plan.SYS:
    fails.append("SYS 不一致")
    a, b = gen.SYS, plan.SYS
    i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
    print(f"首个差异在位置 {i}:")
    print(f"  训练: ...{a[max(0,i-30):i+40]}...")
    print(f"  推理: ...{b[max(0,i-30):i+40]}...")

# 标签里出现的字段必须是契约里声明过的
schema = plan.SCHEMA
item_props = set(schema["properties"]["items"]["items"]["properties"])
con_props = set(schema["properties"]["constraints"]["items"]["properties"])

for name, fields, allowed in (("ITEM_ORDER", gen.ITEM_ORDER, item_props),
                              ("CON_ORDER", gen.CON_ORDER, con_props)):
    extra = set(fields) - allowed
    if extra:
        fails.append(f"{name} 里有契约没声明的字段: {extra}")

# 生成器产出的样本必须能通过 planning.validate
rows = gen.generate(60, 777)
bad = 0
for r in rows:
    try:
        import json
        plan.validate(json.loads(r["messages"][2]["content"]))
    except Exception as e:
        bad += 1
        if bad == 1:
            print("首个不被 planning.validate 接受的样本:", e)
if bad:
    fails.append(f"{bad}/{len(rows)} 条样本过不了 planning.validate")

print(f"训练 SYS 长度={len(gen.SYS)} | 推理 SYS 长度={len(plan.SYS)}")
print(f"生成器字段 ⊆ 契约字段: {not fails}")

if fails:
    print("\n失败:", fails)
    sys.exit(1)
print("训练/推理契约一致")
sys.exit(0)

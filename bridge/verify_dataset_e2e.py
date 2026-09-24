#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
闭环验证: 把数据集里的**每一条** assistant 输出, 原样喂给执行模块, 看工具能否正常启动。

这正是"训练前必须确认"的那件事:
  如果数据集里任意一条输出作为工具输入会失败, 那这条数据就是在教模型做做不到的事。
"""
import json
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, r"D:\Projects\qwen-local-tool-agent\bridge")
from executor import Store, execute  # noqa: E402

import jsonschema  # noqa: E402
import _console  # noqa: F401  (Windows 控制台 UTF-8 兜底)

SCHEMA = r"D:\Projects\qwen-local-tool-agent\schema\schedule_command.v1.json"
DATA = r"D:\Projects\qwen-local-tool-agent\data\generated"
NOW = datetime(2026, 9, 22, 15, 30, 0)      # 固定"现在", 保证可复现

schema = json.load(open(SCHEMA, encoding="utf-8"))
validator = jsonschema.Draft202012Validator(schema)

report = []
def say(s=""):
    print(s, flush=True)
    report.append(str(s))

say("=" * 88)
say("闭环验证: 数据集输出 -> 执行模块")
say(f"固定的『现在』 = {NOW.isoformat()}")
say("=" * 88)

grand = Counter()
all_fail = []

for split in ("train", "test"):
    rows = [json.loads(l) for l in open(f"{DATA}\\{split}.jsonl", encoding="utf-8") if l.strip()]
    store = Store(":memory:")
    stats = Counter()
    fails = []

    for i, r in enumerate(rows):
        raw = r["messages"][2]["content"]
        # 1) JSON 可解析
        try:
            env = json.loads(raw)
        except Exception as e:
            stats["①JSON解析失败"] += 1
            fails.append((i, raw[:80], f"JSON解析失败: {e}"))
            continue
        # 2) Schema 校验
        errs = list(validator.iter_errors(env))
        if errs:
            stats["②Schema校验失败"] += 1
            fails.append((i, raw[:80], f"Schema: {errs[0].message}"))
            continue
        stats["schema_ok"] += 1
        # 3) 执行
        try:
            out = execute(env, store, NOW)
        except Exception as e:
            stats["④执行抛异常"] += 1
            fails.append((i, raw[:80], f"未捕获异常 {type(e).__name__}: {e}"))
            continue
        stats["exec_" + out.kind] += 1
        if out.kind == "failed":
            fails.append((i, raw[:80], out.detail))

    n = len(rows)
    say()
    say(f"===== {split}.jsonl  ({n} 条) =====")
    say(f"  ① JSON 可解析      : {n - stats['①JSON解析失败']}/{n}")
    say(f"  ② 通过 Schema 校验 : {stats['schema_ok']}/{n}")
    say(f"  ③ 执行结果         : executed={stats['exec_executed']}  "
        f"need_clarify={stats['exec_need_clarify']}  rejected={stats['exec_rejected']}  "
        f"failed={stats['exec_failed']}")
    say(f"  ④ 执行抛异常       : {stats['④执行抛异常']}")
    say(f"  → 写入数据库条数   : {store.count()}")
    if fails:
        say(f"  ⚠️ 失败 {len(fails)} 条, 前 10:")
        for i, snip, why in fails[:10]:
            say(f"     #{i}  {why}")
            say(f"         {snip}")
    else:
        say("  ✅ 全部成功执行")
    grand.update(stats)
    all_fail += [(split, i, why) for i, _, why in fails]

say()
say("=" * 88)
say("总计")
say("=" * 88)
tot = grand["schema_ok"] + grand["①JSON解析失败"] + grand["②Schema校验失败"]
say(f"  总条数            : {tot}")
say(f"  通过 Schema       : {grand['schema_ok']}")
say(f"  执行成功(executed): {grand['exec_executed']}")
say(f"  需追问(clarify)   : {grand['exec_need_clarify']}")
say(f"  拒绝(reject)      : {grand['exec_rejected']}")
say(f"  执行失败(failed)  : {grand['exec_failed']}")
say(f"  抛异常            : {grand['④执行抛异常']}")
say()
if all_fail:
    kinds = Counter(w.split(":")[0] for _, _, w in all_fail)
    say("失败原因分布:")
    for k, v in kinds.most_common():
        say(f"  {v:5d}  {k}")
else:
    say("✅ 数据集里任意一条输出, 执行模块都能正常启动")

with open(r"D:\Projects\qwen-local-tool-agent\bridge\e2e_report.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(report))
print("\nreport -> bridge/e2e_report.txt")

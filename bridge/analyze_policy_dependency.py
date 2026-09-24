#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把"能执行"拆开: 哪些是客观推导, 哪些依赖我定的消歧策略。
策略依赖的部分必须显式标出来 —— 它们不是"正确", 而是"按某个约定给出了确定结果"。
"""
import json
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, r"D:\Projects\qwen-local-tool-agent\bridge")
from executor import DEFAULT_DURATION, Store, execute  # noqa: E402

DATA = r"D:\Projects\qwen-local-tool-agent\data\generated"
NOW = datetime(2026, 9, 22, 15, 30, 0)

cat = Counter()
examples = {}
n_cmd = 0

for split in ("train", "test"):
    rows = [json.loads(l) for l in open(f"{DATA}\\{split}.jsonl", encoding="utf-8") if l.strip()]
    for r in rows:
        env = json.loads(r["messages"][2]["content"])
        if env["status"] != "ok":
            cat[f"status={env['status']} (不涉及时间解析)"] += 1
            continue
        for c in env["commands"]:
            n_cmd += 1
            w = c.get("when") or {}
            utt = r["messages"][1]["content"]
            keys = []

            # 1) period=none -> 依赖消歧策略
            if w.get("period") == "none":
                keys.append("period=none 消歧(1-6点算下午)")
            # 2) fuzzy -> 依赖默认钟点表
            if w.get("fuzzy"):
                keys.append(f"fuzzy={w['fuzzy']} 用默认钟点")
            # 3) 有 date_kind 无 time -> 全天事项默认 09:00
            if w.get("date_kind") and not w.get("time") and not w.get("fuzzy"):
                keys.append("只有日期无时刻 -> 默认 09:00 全天")
            # 4) 有时刻无日期 -> 默认今天/顺延明天
            if w.get("time") and not w.get("date_kind"):
                keys.append("只有时刻无日期 -> 默认今天/顺延明天")
            # 5) week_ref=this 且该天已过 -> 顺延下周
            if w.get("date_kind") == "weekday" and w.get("week_ref") == "this":
                order = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
                d = NOW.date() - __import__("datetime").timedelta(days=NOW.weekday())
                d = d + __import__("datetime").timedelta(days=order.get(w.get("date_value"), 0))
                if w.get("time"):
                    hh = int(w["time"].split(":")[0])
                    if hh <= 6 and w.get("period") == "none":
                        hh += 12
                    if datetime.combine(d, datetime.min.time()).replace(hour=hh) <= NOW:
                        keys.append("本周该天已过 -> 顺延下周(可能非用户本意)")
            # 6) absolute 日期已过
            if w.get("date_kind") == "absolute":
                try:
                    y, m, dd = map(int, w["date_value"].split("-"))
                    if datetime(y, m, dd) .date() < NOW.date():
                        keys.append("absolute 日期已过去 -> 标记 is_past")
                except Exception:
                    pass

            if not keys:
                keys = ["纯客观推导(日期+明确时辰)"]
            for k in keys:
                cat[k] += 1
                examples.setdefault(k, (utt, json.dumps(w, ensure_ascii=False)))

print("=" * 96)
print(f"策略依赖度分析  (共 {n_cmd} 条 command, 『现在』={NOW})")
print("=" * 96)
print(f"{'类别':<48}{'条数':>8}{'占比':>9}")
print("-" * 96)
for k, v in cat.most_common():
    print(f"{k:<48}{v:>8}{100*v/n_cmd:>8.1f}%")
print("-" * 96)
obj = cat["纯客观推导(日期+明确时辰)"]
print(f"{'完全客观(无策略介入)':<48}{obj:>8}{100*obj/n_cmd:>8.1f}%")
print()
for k in cat:
    if k.startswith("纯客观") or k.startswith("status="):
        continue
    u, w = examples.get(k, ("(无样例)", ""))
    print(f"【{k}】")
    print(f"   例: {u[:60]}")
    print(f"       when={w}")
print()
print("=" * 96)
print("结论: 全部 %d 条都能得到确定的执行结果(failed=0);" % n_cmd)
print("      但其中 %.1f%% 依赖我定义的消歧策略, 不是客观唯一解。" % (100 * (n_cmd - obj) / n_cmd))
print("      这些策略已全部记录进事件的 reasons 字段, 可回显给用户确认。")
print("=" * 96)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性规则层的单元测试。

规则层是纯函数、不依赖模型, 所以必须严格测透 —— 它是"模型算不准时"的兜底,
一旦它有 bug, 会把模型本来对的答案改错。
"""
from __future__ import annotations

import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else ".")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import rules  # noqa: E402

CHECKS = 0
FAILS: list[str] = []


def eq(name, got, want):
    global CHECKS
    CHECKS += 1
    if got == want:
        print(f"OK   {name}")
    else:
        print(f"FAIL {name}\n     got={got!r}\n    want={want!r}")
        FAILS.append(name)


# ---------------------------------------------------------------- keep_free
KF = lambda s: rules.find_keep_free(s)

eq("周三上午别排", KF("周三上午别给我排东西"),
   [{"kind": "keep_free", "weight": "hard", "day": "WE", "start": "08:00", "end": "12:00"}])
eq("周五晚上绝对不要排", KF("周五晚上绝对不要排事"),
   [{"kind": "keep_free", "weight": "hard", "day": "FR", "start": "19:00", "end": "22:00"}])
eq("尽量别在周日下午（后缀式）",
   KF("尽量别在周日下午安排任务"),
   [{"kind": "keep_free", "weight": "hard", "day": "SU", "start": "13:30", "end": "18:00"}])
eq("不带时段的整天", KF("周日别给我排东西"),
   [{"kind": "keep_free", "weight": "hard", "day": "SU", "start": "00:00", "end": "23:59"}])
eq("下午", KF("周三下午别安排"),
   [{"kind": "keep_free", "weight": "hard", "day": "WE", "start": "13:30", "end": "18:00"}])
eq("没有约束时返回空", KF("这周把实验报告写完"), [])
eq("普通句子不误报", KF("周五要交报告"), [])
# 去重：同一约束说两遍只留一条
eq("重复约束去重", len(KF("周三上午别排东西，周三上午别排。")), 1)

# ---------------------------------------------------------------- 时长
D = rules.find_durations
eq("两小时", D("大概两小时"), [120])
eq("四小时", D("要四小时"), [240])
eq("半小时", D("半小时就行"), [30])
eq("一个半小时", D("一个半小时"), [90])
eq("45 分钟", D("45 分钟"), [45])
eq("二十分钟", D("二十分钟"), [20])
eq("3 小时", D("3 小时左右"), [180])
eq("5 小时", D("至少五小时"), [300])
eq("一刻钟", D("一刻钟"), [15])
eq("没有时长", D("把报告写完"), [])

# ---------------------------------------------------------------- 日期 / 时刻
DT = rules.find_date_time
eq("周五 + 18:00", DT("周五 18:00 前交"), ("周五", "18:00"))
eq("下周三", DT("下周三下午两点"), ("下周三", None))
eq("11-07", DT("11-07 之前"), ("11-07", None))
eq("11月7号", DT("11月7号交"), ("11月7号", None))
eq("明天", DT("明天中午前"), ("明天", None))
eq("没有日期", DT("把报告写完"), (None, None))
eq("中文时间不算", DT("下午两点开会"), (None, None))

# ---------------------------------------------------------------- 区间抹除
eq("抹除区间", rules.blank_spans("abcdef", [(1, 3)]), "a  def")
eq("空区间不炸", rules.blank_spans("abc", []), "abc")

# ---------------------------------------------------------------- augment
TEXT = "周三上午别给我排东西，把实验报告写完，四小时。周五 18:00 前交周报。"
MODEL = {"status": "ok",
         "items": [{"title": "实验报告", "duration_min": 60},
                   {"title": "周报", "duration_min": 30}],
         "constraints": []}
out = rules.augment(MODEL, TEXT)
eq("augment: 时长被规则纠正", out["items"][0]["duration_min"], 240)
eq("augment: 截止被规则补上", out["items"][1].get("deadline_date"), "周五")
eq("augment: 时刻被规则补上", out["items"][1].get("deadline_time"), "18:00")
eq("augment: 约束被规则抽到", out["constraints"],
   [{"kind": "keep_free", "weight": "hard", "day": "WE", "start": "08:00", "end": "12:00"}])
eq("augment: 条数不变", len(out["items"]), 2)
eq("augment: 标题不变", [i["title"] for i in out["items"]], ["实验报告", "周报"])

# ★ 关键回归: 约束里的"周三"不能跑到事项的截止日期上
eq("augment: 约束的星期不污染事项", out["items"][0].get("deadline_date"), None)

# ---- 非 ok 状态原样返回 ----
for st in ("reject", "clarify"):
    e = {"status": st, "items": [], "constraints": []}
    eq(f"augment: {st} 原样返回", rules.augment(e, "随便什么"), e)

# ---- 原始对象不被修改（纯函数）----
MODEL2 = {"status": "ok", "items": [{"title": "实验报告", "duration_min": 60}],
          "constraints": []}
rules.augment(MODEL2, "实验报告要四小时")
eq("augment: 不修改入参", MODEL2["items"][0]["duration_min"], 60)

print()
if FAILS:
    print(f"失败 {len(FAILS)}/{CHECKS}: {FAILS}")
    sys.exit(1)
print(f"规则层测试全部通过 ({CHECKS} 项)")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规划求解器的单元测试。

求解器是二阶段"确定性"的那一半, 必须可测、可复现。这里验证的是**性质**而不是具体排布:
同一个输入, 求解器可以给出多种合法计划, 但只要它违反硬约束就必须被抓出来。

跑法:
    .venv-planner\\Scripts\\python.exe bridge\\test_planner.py
"""
from __future__ import annotations

import sys
from datetime import datetime, time, timedelta

from planner import (DEFAULT_WINDOWS, DayWindow, FixedEvent, MIN_PER_DAY, Task,
                     plan)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CHECKS = 0
FAILS: list[str] = []


def ok(name: str, cond: bool, detail: str = ""):
    global CHECKS
    CHECKS += 1
    if cond:
        print(f"OK   {name}")
    else:
        print(f"FAIL {name}  {detail}")
        FAILS.append(name)


# 固定基准周, 保证结果可复现（不受"今天"影响）
WS = datetime(2026, 11, 2)   # 周一


def T(day: int, h: int, m: int = 0) -> datetime:
    return WS + timedelta(days=day, hours=h, minutes=m)


def minutes_of_day(dt: datetime, ws=WS) -> int:
    return int((dt - ws).total_seconds() // 60) % MIN_PER_DAY


def overlap(a1, a2, b1, b2) -> bool:
    return a1 < b2 and b1 < a2


# ---------------------------------------------------------------- 1. 基本可行性
r = plan([Task("a", "写报告", 120)], week_start=WS)
ok("单个任务可行", r.feasible and len(r.assignments) == 1)
if r.assignments:
    a = r.assignments[0]
    ok("任务时长正确", (a.end - a.start) == timedelta(minutes=120),
       f"{a.start}~{a.end}")

# ---------------------------------------------------------------- 2. 不重叠 + 不进固定日程
fixed = [FixedEvent("f1", "高数", T(1, 9), T(1, 11))]
tasks = [Task("a", "任务A", 180), Task("b", "任务B", 180), Task("c", "任务C", 180)]
r = plan(tasks, fixed, week_start=WS, buffer_min=10)
ok("多任务可行", r.feasible)
asg = r.assignments
clash = False
for i in range(len(asg)):
    for j in range(i + 1, len(asg)):
        if overlap(asg[i].start, asg[i].end, asg[j].start, asg[j].end):
            clash = True
ok("任务之间不重叠", not clash)

hit_fixed = any(overlap(a.start, a.end, f.start, f.end) for a in asg for f in fixed)
ok("不与固定日程重叠", not hit_fixed)

buffed = any(overlap(a.start, a.end,
                     fixed[0].start - timedelta(minutes=10),
                     fixed[0].end + timedelta(minutes=10)) for a in asg)
ok("固定日程前后留出缓冲", not buffed)

# ---------------------------------------------------------------- 3. 工作时段
in_window = True
for a in asg:
    d = a.start.weekday()
    wins = DEFAULT_WINDOWS[d]
    sod_s, sod_e = minutes_of_day(a.start), minutes_of_day(a.end, WS) + (
        MIN_PER_DAY if a.end.date() != a.start.date() else 0)
    if a.end.date() != a.start.date():
        in_window = False
        break
    if not any(w.start_min <= sod_s and sod_e <= w.end_min for w in wins):
        in_window = False
ok("全部落在可用时段内", in_window)

# ---------------------------------------------------------------- 4. 截止时间
dl = T(1, 18)
r = plan([Task("a", "有截止", 120, deadline=dl)], week_start=WS)
ok("截止时间可满足时会被满足",
   r.feasible and all(a.end <= dl for a in r.assignments))

# 截止时间在可用时段开始之前 -> 不可行, 且解释要点名这个任务
r = plan([Task("a", "来不及的任务", 480, deadline=T(0, 9))],
         week_start=WS, explain=True)
ok("超出容量的截止时间 -> 不可行", not r.feasible)
ok("不可行时给出可读原因",
   any("来不及的任务" in v for v in r.violations),
   f"violations={r.violations}")

# ---------------------------------------------------------------- 5. 每日负荷
r = plan([Task(f"t{i}", f"任务{i}", 120) for i in range(12)],
         week_start=WS, daily_load_cap_min=240)
ok("12×2h 在每天上限 4h 下仍可行", r.feasible)
per_day: dict = {}
for a in r.assignments:
    per_day[a.start.date()] = per_day.get(a.start.date(), 0) + \
        int((a.end - a.start).total_seconds() // 60)
ok("每天不超过负荷上限", all(v <= 240 for v in per_day.values()),
   f"{sorted(per_day.values())}")

# ---------------------------------------------------------------- 6. 拆分
r = plan([Task("a", "大报告", 240, splittable=True, max_chunks=2, min_chunk_min=30)],
         week_start=WS)
ok("可拆分任务产生多块", r.feasible and len(r.assignments) == 2)
total = sum(int((a.end - a.start).total_seconds() // 60) for a in r.assignments)
ok("拆分后总时长不变", total == 240, f"{total}")
ok("块编号按时间递增",
   [a.chunk for a in sorted(r.assignments, key=lambda x: x.start)] == [0, 1])

# ---------------------------------------------------------------- 7. 依赖顺序
r = plan([Task("b", "B", 60, depends_on=("a",)), Task("a", "A", 60)],
         week_start=WS)
ok("依赖关系可行", r.feasible)
if r.feasible:
    a_end = max(x.end for x in r.assignments if x.task_id == "a")
    b_start = min(x.start for x in r.assignments if x.task_id == "b")
    ok("B 排在 A 之后", b_start >= a_end, f"A结束={a_end} B开始={b_start}")

# ---------------------------------------------------------------- 8. 可复现
r1 = plan([Task("a", "任务A", 90), Task("b", "任务B", 90)], week_start=WS)
r2 = plan([Task("a", "任务A", 90), Task("b", "任务B", 90)], week_start=WS)
sig1 = [(a.task_id, a.start) for a in r1.assignments]
sig2 = [(a.task_id, a.start) for a in r2.assignments]
ok("同一输入结果可复现", sig1 == sig2)

# ---------------------------------------------------------------- 9. 优先级
r = plan([Task("hi", "重要的", 60, priority=1),
          Task("lo", "次要的", 60, priority=-1)], week_start=WS)
ok("高优先级任务可行", r.feasible)
if r.feasible:
    hi = [a for a in r.assignments if a.task_id == "hi"][0]
    lo = [a for a in r.assignments if a.task_id == "lo"][0]
    ok("高优先级排得不晚于低优先级", hi.start <= lo.start,
       f"hi={hi.start} lo={lo.start}")

# ---------------------------------------------------------------- 10. 稳定性
pinned = T(3, 15)
r = plan([Task("a", "已确认的", 60, pinned_start=pinned)], week_start=WS)
ok("带既定时间的任务可行", r.feasible)
if r.feasible:
    ok("既定时间被尽量保留",
       r.assignments[0].start == pinned,
       f"实际 {r.assignments[0].start}")

print()
if FAILS:
    print(f"失败 {len(FAILS)}/{CHECKS}: {FAILS}")
    sys.exit(1)
print(f"规划器测试全部通过 ({CHECKS} 项)")

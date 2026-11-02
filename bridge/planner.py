#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日程规划求解器（CP-SAT 最小原型）

为什么要它
----------
二阶段的核心判断是：**规划不是语言问题**。让 LLM 直接排出计划，即使 GPT-4 在
自然语言规划基准（NATURAL PLAN, arXiv:2406.04520）上也只有 31%/35% 的求解率,
复杂度上去后低于 5%。正确做法是 LLM 只把自然语言翻译成约束, 由确定性求解器求解
（LLM+P, arXiv:2304.11477）。

本模块就是那个"确定性求解器"。它不依赖任何模型, 输入约束、输出计划,
所以**可单元测试、可解释、结果可复现**。

设计要点
--------
1. 时间用「距周一 00:00 的分钟数」表示, 全部是整数, 避免浮点与夏令时问题。
2. 不可用时段（夜间、固定日程）建成"阻塞区间", 和任务区间一起放进 NoOverlap。
   这样"任务不能跨出工作时段"是模型的自然结果, 不需要额外约束。
3. 硬约束违反 = 不可行; 此时**软化硬约束重解**, 报告是哪几条在打架
   —— 这比"排不出来"有用得多。
4. 软约束进目标函数（带权重）, 包括"稳定性"：尽量别动用户已确认的安排。

用法
----
    python bridge/planner.py            # 跑内置演示
    from planner import Task, FixedEvent, plan, DayWindow
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Iterable, Sequence

from ortools.sat.python import cp_model

MIN_PER_DAY = 24 * 60
MIN_PER_WEEK = 7 * MIN_PER_DAY

# 星期名（0=周一）
WD_CN = ["一", "二", "三", "四", "五", "六", "日"]


# ---------------------------------------------------------------- 数据结构
@dataclass(frozen=True)
class DayWindow:
    """一天的可用时段（相对当天 00:00 的分钟）。可给多个, 如上午+下午。"""
    start_min: int
    end_min: int

    def __post_init__(self):
        if not (0 <= self.start_min < self.end_min <= MIN_PER_DAY):
            raise ValueError(f"非法时段: {self.start_min}~{self.end_min}")


@dataclass
class Task:
    """一件待办。"""
    id: str
    title: str
    duration_min: int
    deadline: datetime | None = None
    priority: int = 0                  # 1 高 / 0 普通 / -1 低
    preferred: str | None = None       # "am" | "pm" | "eve" | None
    splittable: bool = False
    max_chunks: int = 2
    min_chunk_min: int = 30
    depends_on: tuple[str, ...] = ()
    pinned_start: datetime | None = None   # 上一版计划的时间, 用于稳定性


@dataclass
class FixedEvent:
    """不可移动的日程。"""
    id: str
    title: str
    start: datetime
    end: datetime

    @property
    def duration_min(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class Assignment:
    task_id: str
    title: str
    start: datetime
    end: datetime
    chunk: int = 0
    is_new: bool = True


@dataclass
class PlanResult:
    feasible: bool
    assignments: list[Assignment] = field(default_factory=list)
    objective: int | None = None
    violations: list[str] = field(default_factory=list)
    note: str = ""
    solve_ms: int = 0

    def by_day(self) -> dict[str, list[Assignment]]:
        out: dict[str, list[Assignment]] = {}
        for a in self.assignments:
            out.setdefault(a.start.strftime("%Y-%m-%d"), []).append(a)
        return out


# ---------------------------------------------------------------- 权重
@dataclass(frozen=True)
class Weights:
    """软约束权重。数值是"多少分钟的偏差等价于 1 分惩罚"的倒数关系, 便于调。"""
    preferred_window: int = 40     # 不在偏好时段的每分钟
    daily_load: int = 6            # 每天超出负荷上限的每分钟
    stability: int = 3             # 相对上一版计划偏移的每分钟
    priority: int = 2              # 高优先级任务的开始时刻（越早越好）
    chunking: int = 15             # 每多拆一块的固定惩罚（少拆更连贯）
    soft_hard: int = 10_000        # 解释阶段: 软化硬约束的惩罚单价


DEFAULT_WINDOWS = {
    0: [DayWindow(8 * 60, 12 * 60), DayWindow(13 * 60 + 30, 22 * 60)],
    1: [DayWindow(8 * 60, 12 * 60), DayWindow(13 * 60 + 30, 22 * 60)],
    2: [DayWindow(8 * 60, 12 * 60), DayWindow(13 * 60 + 30, 22 * 60)],
    3: [DayWindow(8 * 60, 12 * 60), DayWindow(13 * 60 + 30, 22 * 60)],
    4: [DayWindow(8 * 60, 12 * 60), DayWindow(13 * 60 + 30, 22 * 60)],
    5: [DayWindow(9 * 60, 12 * 60), DayWindow(14 * 60, 21 * 60)],
    6: [DayWindow(9 * 60, 12 * 60), DayWindow(14 * 60, 21 * 60)],
}

PREF_WINDOWS = {
    "am": (8 * 60, 12 * 60),
    "pm": (13 * 60 + 30, 18 * 60),
    "eve": (19 * 60, 22 * 60),
}


# ---------------------------------------------------------------- 核心
def plan(
    tasks: Sequence[Task],
    fixed: Sequence[FixedEvent] = (),
    *,
    week_start: datetime | None = None,
    windows: dict[int, list[DayWindow]] | None = None,
    daily_load_cap_min: int = 8 * 60,
    buffer_min: int = 10,
    weights: Weights = Weights(),
    max_seconds: float = 5.0,
    explain: bool = True,
) -> PlanResult:
    """求解一周计划。

    week_start   不传则取"今天所在周的周一 00:00"
    buffer_min   固定日程前后预留的缓冲（通勤/准备），任务不得落进这段
    """
    ws = _monday_of(week_start or datetime.now())
    windows = windows or DEFAULT_WINDOWS

    res = _solve(tasks, fixed, ws, windows, daily_load_cap_min, buffer_min,
                 weights, max_seconds, soften=False)
    if res.feasible or not explain:
        return res

    # 不可行 -> 软化硬约束重解, 找出是哪几条在打架
    soft = _solve(tasks, fixed, ws, windows, daily_load_cap_min, buffer_min,
                  weights, max_seconds, soften=True)
    res.violations = soft.violations
    res.note = "无可行解；以下是与之冲突的约束"
    return res


def _monday_of(dt: datetime) -> datetime:
    d = dt.date() - timedelta(days=dt.weekday())
    return datetime.combine(d, time(0, 0))


def _minutes(dt: datetime, ws: datetime) -> int:
    return int((dt - ws).total_seconds() // 60)


def _dt_from_min(m: int, ws: datetime) -> datetime:
    return ws + timedelta(minutes=int(m))


def _solve(tasks, fixed, ws, windows, load_cap, buffer_min, w: Weights, max_seconds, *, soften: bool):
    import time as _t
    t0 = _t.perf_counter()

    model = cp_model.CpModel()
    chunks = _expand(tasks)

    # ---- 阻塞区间: 不可用时段 + 固定日程
    blocked: list = []
    for day in range(7):
        avail = sorted(windows.get(day, []), key=lambda x: x.start_min)
        cursor = 0
        for win in avail:
            if win.start_min > cursor:
                blocked.append(_fixed_interval(model, day * MIN_PER_DAY + cursor,
                                               day * MIN_PER_DAY + win.start_min,
                                               f"off_{day}_{cursor}"))
            cursor = max(cursor, win.end_min)
        if cursor < MIN_PER_DAY:
            blocked.append(_fixed_interval(model, day * MIN_PER_DAY + cursor,
                                           (day + 1) * MIN_PER_DAY, f"off_{day}_tail"))
    for ev in fixed:
        s = _minutes(ev.start, ws)
        e = _minutes(ev.end, ws)
        if e <= 0 or s >= MIN_PER_WEEK:
            continue
        # 前后各留 buffer_min 的缓冲（通勤/准备），任务不得落进这段
        s = max(0, s - buffer_min)
        e = min(MIN_PER_WEEK, e + buffer_min)
        blocked.append(_fixed_interval(model, s, e, f"fixed_{ev.id}"))

    # ---- 任务区间
    intervals = list(blocked)
    by_id: dict[str, list[dict]] = {}
    penalties = []       # (weight, var) 形式的软约束惩罚
    hard_notes = []      # 软化模式下记录"哪条硬约束被违反"
    vio_vars: dict[str, object] = {}

    for tid, c in chunks.items():
        by_id[tid] = []
        for k, size in enumerate(c["sizes"]):
            lo = 0
            hi = MIN_PER_WEEK - size
            if hi < 0:
                raise ValueError(f"任务 {tid} 时长 {size} 分钟超过一周可用时间")
            st = model.NewIntVar(lo, hi, f"st_{tid}_{k}")
            en = model.NewIntVar(lo + size, MIN_PER_WEEK, f"en_{tid}_{k}")
            iv = model.NewIntervalVar(st, size, en, f"iv_{tid}_{k}")
            intervals.append(iv)
            by_id[tid].append({"start": st, "end": en, "size": size, "k": k})
    model.AddNoOverlap(intervals)

    for tid, c in chunks.items():
        task: Task = c["task"]
        starts = [x["start"] for x in by_id[tid]]

        # 硬约束: 截止时间
        if task.deadline is not None:
            dl = _minutes(task.deadline, ws)
            # 只处理落在本计划周内的截止; 更晚的视为"本周不紧急"
            if 0 <= dl <= MIN_PER_WEEK:
                if soften:
                    for x in by_id[tid]:
                        ok = model.NewBoolVar(f"ok_{tid}_{x['k']}")
                        model.Add(x["end"] <= dl).OnlyEnforceIf(ok)
                        model.Add(x["end"] > dl).OnlyEnforceIf(ok.Not())
                        penalties.append((w.soft_hard, ok.Not()))
                    hard_notes.append(
                        (f"任务「{task.title}」的截止时间 "
                         f"{task.deadline:%m-%d %H:%M} 无法满足", None))
                else:
                    for x in by_id[tid]:
                        model.Add(x["end"] <= dl)

        # 硬约束: 依赖顺序
        for dep in task.depends_on:
            if dep in by_id and by_id[dep]:
                dep_end = max(x["end"] for x in by_id[dep])
                for x in by_id[tid]:
                    if soften:
                        ok = model.NewBoolVar(f"dep_{dep}_{tid}_{x['k']}")
                        model.Add(x["start"] >= dep_end).OnlyEnforceIf(ok)
                        model.Add(x["start"] < dep_end).OnlyEnforceIf(ok.Not())
                        penalties.append((w.soft_hard, ok.Not()))
                    else:
                        model.Add(x["start"] >= dep_end)
                if soften:
                    hard_notes.append((f"任务「{task.title}」必须排在「{dep}」之后", None))

        # 软约束: 偏好时段
        if task.preferred in PREF_WINDOWS:
            p_lo, p_hi = PREF_WINDOWS[task.preferred]
            for x in by_id[tid]:
                mod = model.NewIntVar(0, MIN_PER_DAY - 1, f"mod_{tid}_{x['k']}")
                model.AddModuloEquality(mod, x["start"], MIN_PER_DAY)
                before = model.NewBoolVar(f"bef_{tid}_{x['k']}")
                after = model.NewBoolVar(f"aft_{tid}_{x['k']}")
                model.Add(mod < p_lo).OnlyEnforceIf(before)
                model.Add(mod >= p_lo).OnlyEnforceIf(before.Not())
                model.Add(mod >= p_hi).OnlyEnforceIf(after)
                model.Add(mod < p_hi).OnlyEnforceIf(after.Not())
                penalties.append((w.preferred_window, before))
                penalties.append((w.preferred_window, after))

        # 软约束: 稳定性（偏离上一版计划的时间）
        if task.pinned_start is not None:
            pin = _minutes(task.pinned_start, ws)
            for x in by_id[tid]:
                dev = model.NewIntVar(0, MIN_PER_WEEK, f"dev_{tid}_{x['k']}")
                model.AddAbsEquality(dev, x["start"] - pin)
                penalties.append((w.stability, dev))

        # 软约束: 高优先级尽早
        if task.priority > 0:
            for x in by_id[tid]:
                penalties.append((w.priority * task.priority, x["start"]))

        # 软约束: 少拆块
        if len(by_id[tid]) > 1:
            for x in by_id[tid][1:]:
                penalties.append((w.chunking, x["start"]))

    # ---- 软约束: 每日负荷上限
    for day in range(7):
        load_terms = []
        for tid, xs in by_id.items():
            for x in xs:
                day_var = model.NewIntVar(0, 6, f"d_{tid}_{x['k']}")
                model.AddDivisionEquality(day_var, x["start"], MIN_PER_DAY)
                is_d = model.NewBoolVar(f"isd_{tid}_{x['k']}_{day}")
                model.Add(day_var == day).OnlyEnforceIf(is_d)
                model.Add(day_var != day).OnlyEnforceIf(is_d.Not())
                load_terms.append(is_d * x["size"])
        if load_terms:
            load = model.NewIntVar(0, MIN_PER_DAY, f"load_{day}")
            model.Add(load == sum(load_terms))
            over = model.NewIntVar(0, MIN_PER_DAY, f"over_{day}")
            model.AddMaxEquality(over, [0, load - load_cap])
            penalties.append((w.daily_load, over))

    model.Minimize(sum(wt * var for wt, var in penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)
    elapsed = int((_t.perf_counter() - t0) * 1000)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return PlanResult(feasible=False, note="不可行", solve_ms=elapsed)

    out: list[Assignment] = []
    for tid, xs in by_id.items():
        entry = chunks[tid]["task"]
        parts = []
        for x in xs:
            s = _dt_from_min(solver.Value(x["start"]), ws)
            parts.append(Assignment(
                task_id=tid, title=entry.title,
                start=s, end=s + timedelta(minutes=x["size"]), chunk=0))
        # 按时间重排后重新编号 —— 求解器不保证 k=0 一定排在 k=1 前面,
        # 不重排的话界面上会出现"第 2 块"在"第 1 块"之前
        parts.sort(key=lambda a: a.start)
        for i, a in enumerate(parts):
            a.chunk = i if len(parts) > 1 else 0
        out.extend(parts)
    out.sort(key=lambda a: a.start)

    violations: list[str] = []
    if soften:
        for text, _ in _dedup(hard_notes):
            violations.append(text)

    return PlanResult(feasible=True, assignments=out,
                      objective=int(solver.ObjectiveValue()),
                      violations=violations, solve_ms=elapsed)


def _dedup(items):
    seen = set()
    for it in items:
        if it[0] in seen:
            continue
        seen.add(it[0])
        yield it


def _expand(tasks: Sequence[Task]) -> dict[str, dict]:
    """把任务展开成 1 或多块（可拆分任务）。"""
    out: dict[str, dict] = {}
    for t in tasks:
        if t.splittable and t.duration_min >= 2 * t.min_chunk_min:
            k = min(t.max_chunks, max(2, t.duration_min // max(1, t.min_chunk_min)))
            # 均分, 余数补给前面的块
            base = t.duration_min // k
            sizes = [base] * k
            sizes[0] += t.duration_min - base * k
            if min(sizes) < t.min_chunk_min:
                sizes = [t.duration_min]
        else:
            sizes = [t.duration_min]
        out[t.id] = {"task": t, "sizes": sizes,
                     "deadline_min": None}  # 截止时间在 _solve 里按 ws 计算
    return out


def _fixed_interval(model, s: int, e: int, name: str):
    if e <= s:
        e = s + 1
    st = model.NewConstant(s)
    sz = e - s
    en = model.NewConstant(e)
    return model.NewIntervalVar(st, sz, en, name)


# ---------------------------------------------------------------- 演示
def _demo():
    # Windows 控制台默认 GBK, 下面要打印 ✚ 这类符号, 不改编码会直接崩
    import sys
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    week_start = _monday_of(datetime.now())
    print(f"计划周: {week_start:%Y-%m-%d} (周{WD_CN[week_start.weekday()]}) 起\n")

    fixed = [
        FixedEvent("c1", "高等数学", week_start + timedelta(days=1, hours=9),
                   week_start + timedelta(days=1, hours=11)),
        FixedEvent("c2", "组会", week_start + timedelta(days=3, hours=15),
                   week_start + timedelta(days=3, hours=16)),
    ]
    tasks = [
        Task("t1", "操作系统实验报告", duration_min=240, priority=1,
             deadline=week_start + timedelta(days=4, hours=23, minutes=59),
             splittable=True, max_chunks=2, preferred="am"),
        Task("t2", "复习计算机组成", duration_min=180, priority=1, preferred="eve"),
        Task("t3", "写周报", duration_min=45, priority=0,
             deadline=week_start + timedelta(days=4, hours=18)),
        Task("t4", "健身", duration_min=60, priority=-1, preferred="eve"),
    ]

    r = plan(tasks, fixed, week_start=week_start)
    if not r.feasible:
        print("无可行解")
        for v in r.violations:
            print("  -", v)
        return

    print(f"目标值 {r.objective}   求解耗时 {r.solve_ms} ms\n")
    for day, items in sorted(r.by_day().items()):
        d = datetime.strptime(day, "%Y-%m-%d")
        print(f"{day} 周{WD_CN[d.weekday()]}")
        for a in items:
            tag = "✚" if a.is_new else "="
            print(f"  {tag} {a.start:%H:%M}-{a.end:%H:%M}  {a.title}"
                  + (f"（第 {a.chunk + 1} 块）" if a.chunk else ""))
        print()
    for ev in fixed:
        print(f"  固定: {ev.start:%m-%d %H:%M} {ev.title}")


if __name__ == "__main__":
    _demo()

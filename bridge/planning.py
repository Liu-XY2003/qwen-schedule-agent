#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二阶段规划链路: 非结构化素材 → 约束 → 计划。

分工（这是二阶段的核心设计）:
    ┌──────────────┐   planning_request.v1   ┌──────────┐   PlanResult   ┌────────┐
    │ 杂乱文本      │ ────LLM 抽取────────▶  │ 约束      │ ──CP-SAT──▶  │ 计划    │
    └──────────────┘   (约束解码保证格式)     └──────────┘   (确定性)    └────────┘

LLM **只做抽取**, 不做任何日期计算、不做排期。排期由 planner.py 完成。
这是"模型不算日期"原则在二阶段的表现。

本模块提供:
    SYS                  抽取用的 system prompt（属于契约, 不能随意改）
    extract()            调 llama-server 做抽取
    to_planner_inputs()  把抽到的信封转成 planner 的 Task / 窗口
    plan_from_text()     一步到位: 文本 → 计划
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import date, datetime, time, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = os.environ.get("SCHED_PLANNING_SCHEMA") or str(
    HERE.parent / "schema" / "planning_request.v1.json")
SCHEMA = json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))

# ★ 规划抽取可以用**与一阶段不同的模型**。
#   一阶段背 schedule_command 的 0.6B (LoRA 微调) 并不认识 planning_request 这套新契约,
#   用它做规划抽取效果很差。所以允许单独指定:
#     SCHED_PLAN_LLAMA_URL=http://127.0.0.1:18998   # 挂一个 4B 专门做规划
#   不设则退回 SCHED_LLAMA_URL, 方便只有一个小模型时也能跑通链路。
LLAMA_URL = (os.environ.get("SCHED_PLAN_LLAMA_URL")
             or os.environ.get("SCHED_LLAMA_URL", "http://127.0.0.1:18080")).rstrip("/")

# ★ system prompt 是契约的一部分。训练、评测、线上必须是同一份。
SYS = (
    "你是日程规划助手。用户给你一段非结构化的日程素材（可能是聊天记录、邮件片段、"
    "或几条待办混在一起）。你要抽出「需要占用时间去做的事」和「排期限制」，只输出 JSON。"
    "规则："
    "1. items 每条必须有 title 和 duration_min。原文说了时长就用原文（\"两个小时\"=120）；"
    "没说就按常识估（交一次作业≈60，读一篇论文≈45，写周报≈30）；完全估不出来就用 status=clarify。"
    "2. 闲聊、纯信息、已经做完的事不要放进 items。"
    "3. deadline_date 只写用户原本的日期说法（\"周五\"、\"11-07\"、\"明天\"），"
    "绝对不要自己换算成具体年月日。"
    "4. constraints 只抽用户明确说过的限制，不要脑补。\"别给我排东西\"属于 keep_free。"
    "5. 用户用了\"必须/绝对/别\"就是 hard，用了\"尽量/最好\"就是 soft。"
    "6. 素材里没有任何需要安排的事，用 status=reject。"
    "7. 信息不足无法排期，用 status=clarify 并在 question 里只问一个最关键的问题。"
)


# ---------------------------------------------------------------- 抽取
def set_llama_url(url: str) -> None:
    """切换推理地址（评测脚本要连不同端口的模型）。"""
    global LLAMA_URL
    LLAMA_URL = url.rstrip("/")


def _post(payload: dict, timeout: float = 180.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        LLAMA_URL + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def extract(text: str, *, llama_url: str | None = None,
            max_tokens: int = 512, fewshot: str | bool = "rich") -> dict:
    """文本 → planning_request 信封。失败抛异常。

    fewshot: False/"none" 不带示例; True/"lite" 两个; "rich" 五个(默认)。
    实测**必须开** —— 未经微调的基座模型面对这个复杂度的新契约, 零样本几乎一律
    输出 status=reject(1.7B 只有 14%)。示例覆盖多件事/约束/拒答/追问四类关键形态
    后准确率明显提升(见 docs/extraction-benchmark.md)。
    微调之后应改用 fewshot=False, 让 prompt 短下来、更快。
    """
    global LLAMA_URL
    if llama_url:
        LLAMA_URL = llama_url.rstrip("/")
    messages = [{"role": "system", "content": SYS}]
    if fewshot in (True, "lite", "fewshot"):
        messages += FEWSHOT
    elif fewshot == "rich":
        messages += FEWSHOT_RICH
    messages.append({"role": "user", "content": text})
    payload = {
        "model": "x",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "planning", "schema": SCHEMA}},
    }
    obj = _post(payload)
    raw = obj["choices"][0]["message"].get("content") or ""
    try:
        env = json.loads(raw)
    except Exception as e:
        raise ValueError(f"模型输出不是合法 JSON: {raw[:200]!r} ({e})")
    validate(env)
    return env


# ★ few-shot 示例也是契约的一部分: 与 SYS 一起决定模型的行为。
#
# 两档:
#   FEWSHOT       2 个例子（正常抽 / 应拒答）。最省 token, 但没覆盖"多件事"——
#                 而多件事恰恰是实测失败最多的一类。
#   FEWSHOT_RICH  5 个例子, 逐个覆盖已知失败模式:
#                 ① 多件事 + 时长分散在句子里（最常见的失败）
#                 ② keep_free 约束（最常漏抽）
#                 ③ 应拒答
#                 ④ 应追问
#                 ⑤ 单件事 + 明确截止（基准能力）
# 微调之后应改用 fewshot=False, 让 prompt 短下来。

FEWSHOT = [
    {"role": "user", "content":
        "周五前把设计文档发出去，大概三小时。周三上午别给我排事，要陪家人。"},
    {"role": "assistant", "content": json.dumps({
        "status": "ok",
        "items": [{
            "title": "设计文档", "duration_min": 180,
            "deadline_date": "周五", "priority": "high",
            "splittable": True, "preferred": "none",
        }],
        "constraints": [{
            "kind": "keep_free", "weight": "hard",
            "day": "WE", "start": "08:00", "end": "12:00",
        }],
    }, ensure_ascii=False, separators=(",", ":"))},
    {"role": "user", "content": "今天天气不错，刚吃完饭有点困。"},
    {"role": "assistant", "content": json.dumps({
        "status": "reject", "items": [], "constraints": [],
    }, ensure_ascii=False, separators=(",", ":"))},
]


def _fs(user, env):
    return [{"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(
                env, ensure_ascii=False, separators=(",", ":"))}]


# ① 多件事 + 时长分散（最常见的失败模式：只抽到一两件）
_FS_MULTI = _fs(
    "这周要做三件事：写完操作系统实验报告，大概要四个小时；读两篇论文，每篇一小时；"
    "再写个周报，半小时。",
    {"status": "ok", "items": [
        {"title": "操作系统实验报告", "duration_min": 240, "priority": "normal",
         "splittable": True, "preferred": "none"},
        {"title": "读论文", "duration_min": 60, "priority": "normal",
         "splittable": True, "preferred": "none"},
        {"title": "周报", "duration_min": 30, "priority": "normal",
         "splittable": True, "preferred": "none"},
    ], "constraints": []})

# ② 只说了约束、没说时长（约束最容易漏抽）
_FS_CONSTRAINT = _fs(
    "周五晚上绝对不要给我排事，我要休息。白天可以看看论文，两小时。",
    {"status": "ok", "items": [
        {"title": "看论文", "duration_min": 120, "priority": "normal",
         "splittable": True, "preferred": "none"},
    ], "constraints": [
        {"kind": "keep_free", "weight": "hard",
         "day": "FR", "start": "19:00", "end": "22:00"},
    ]})

# ④ 应追问（信息不足但用户确实想安排）
_FS_CLARIFY = _fs(
    "帮我安排一下这周的事情。",
    {"status": "clarify", "items": [], "constraints": [],
     "question": "你想安排哪几件事？每件大概需要多久？"})

FEWSHOT_RICH = (_FS_MULTI + _FS_CONSTRAINT + FEWSHOT + _FS_CLARIFY)


def validate(env: dict) -> None:
    """最小结构校验（不引 jsonschema, 保持依赖轻）。"""
    if env.get("status") not in ("ok", "clarify", "reject"):
        raise ValueError(f"status 非法: {env.get('status')!r}")
    if env["status"] == "ok" and not env.get("items"):
        raise ValueError("status=ok 但没有 items")
    if env["status"] == "clarify" and not env.get("question"):
        raise ValueError("status=clarify 但没有 question")
    for it in env.get("items") or []:
        if not it.get("title"):
            raise ValueError("item 缺 title")
        d = it.get("duration_min")
        if not isinstance(d, int) or not (5 <= d <= 600):
            raise ValueError(f"item 时长非法: {d!r}")


# ---------------------------------------------------------------- 日期解析
_WD = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_CN_WD = {"周一": "MO", "周二": "TU", "周三": "WE", "周四": "TH",
          "周五": "FR", "周六": "SA", "周日": "SU", "周天": "SU"}


def resolve_deadline(expr: str | None, today: date) -> date | None:
    """把模型给的**日期表达**解析成绝对日期。这属于确定性代码, 不是模型的工作。

    刻意做得"宽容": 实测模型会输出 ISO 星期码(FR)、带时间的组合(FR 18:00)、
    "周五"、"11-07" 等多种形态。这些都是**合理的表达**, 不该因为写法不同就当解析失败
    —— 结构校验放宽、语义策略收紧, 和项目既有的分层原则一致。
    """
    if not expr:
        return None
    s = str(expr).strip()
    if not s:
        return None

    # 先剔掉后面可能跟的时间, 例如 "FR 18:00" / "周五 18:00"
    s = re.split(r"[\sT]+", s)[0].strip()

    # ISO 星期码（模型常见输出）
    if s.upper() in _WD:
        code = s.upper()
        monday = today - timedelta(days=today.weekday())
        d = monday + timedelta(days=_WD[code])
        if d < today:                      # 本周已过 -> 下周
            d += timedelta(days=7)
        return d

    # 星期几（可能带"下/这/上"）。
    # ★ 注意 "下周五" 是 "下"+"周五", 不是 "下周"+"五" —— 前缀只能匹配到"周"之前。
    m = re.search(r"(下下|下|这|本|上)?\s*(周[一二三四五六日天])", s)
    if m:
        off = {"下下": 2, "下": 1, "这": 0, "本": 0, "上": -1, None: 0}[m.group(1)]
        code = _CN_WD[m.group(2)]
        monday = today - timedelta(days=today.weekday())
        d = monday + timedelta(weeks=off, days=_WD[code])
        if d < today and off == 0:
            d += timedelta(days=7)
        return d

    if s in ("今天", "今日"):
        return today
    if s in ("明天", "明日"):
        return today + timedelta(days=1)
    if s in ("后天",):
        return today + timedelta(days=2)

    # 2026-11-07 / 2026/11/07
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # 11-07 / 11/07 / 11月7日 / 11月7号
    m = re.fullmatch(r"(\d{1,2})[-/月](\d{1,2})[日号]?", s)
    if m:
        mo, dd = int(m.group(1)), int(m.group(2))
        for y in (today.year, today.year + 1):
            try:
                d = date(y, mo, dd)
            except ValueError:
                continue
            if d >= today:
                return d
        return None
    return None


def resolve_time(expr: str | None) -> time | None:
    if not expr:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(expr).strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None
    return time(h, mi)


# ---------------------------------------------------------------- 转成求解器输入
def to_planner_inputs(env: dict, today: date | None = None):
    """把抽取信封转成 (tasks, windows)。延迟导入 planner, 避免没装 ortools 时炸。

    constraints 里的 keep_free 会从可用时段里挖掉对应区间。
    """
    from planner import DEFAULT_WINDOWS, DayWindow, Task   # 延迟导入

    today = today or date.today()
    tasks: list[Task] = []
    for i, it in enumerate(env.get("items") or []):
        dl_date = resolve_deadline(it.get("deadline_date"), today)
        dl_time = resolve_time(it.get("deadline_time")) or time(23, 59)
        deadline = (datetime.combine(dl_date, dl_time) if dl_date else None)
        tasks.append(Task(
            id=f"t{i}",
            title=str(it.get("title") or f"事项{i}")[:40],
            duration_min=int(it.get("duration_min") or 60),
            deadline=deadline,
            priority={"high": 1, "normal": 0, "low": -1}.get(
                it.get("priority") or "normal", 0),
            preferred=(None if (it.get("preferred") or "none") == "none"
                       else it.get("preferred")),
            splittable=bool(it.get("splittable")),
        ))

    # 把 keep_free 从默认窗口里挖掉
    windows = {d: list(ws) for d, ws in DEFAULT_WINDOWS.items()}
    for c in env.get("constraints") or []:
        if c.get("kind") != "keep_free" or not c.get("day"):
            continue
        day = _WD[c["day"]]
        blk_start = resolve_time(c.get("start")) or time(0, 0)
        blk_end = resolve_time(c.get("end")) or time(23, 59)
        bs = blk_start.hour * 60 + blk_start.minute
        be = blk_end.hour * 60 + blk_end.minute
        kept: list[DayWindow] = []
        for w in windows[day]:
            if w.end_min <= bs or w.start_min >= be:
                kept.append(w)              # 完全不相交
                continue
            if w.start_min < bs:            # 左边剩一截
                kept.append(DayWindow(w.start_min, bs))
            if w.end_min > be:              # 右边剩一截
                kept.append(DayWindow(be, w.end_min))
        windows[day] = kept
    return tasks, windows


def plan_from_text(text: str, *, llama_url: str | None = None,
                   today: date | None = None):
    """一步到位: 文本 → (信封, 计划)。供 /api/plan 与演示使用。"""
    from planner import plan                       # 延迟导入

    env = extract(text, llama_url=llama_url)
    if env.get("status") != "ok":
        return env, None
    tasks, windows = to_planner_inputs(env, today)
    res = plan(tasks, [], windows=windows, week_start=None)
    return env, res


if __name__ == "__main__":
    import sys
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    demo = ("周三上午别给我排东西，这周得把操作系统实验报告写完，"
            "周五 23:59 前交；还有组会要准备个 20 分钟的进度汇报；"
            "另外想找两天各一小时去健身。")
    print("输入:", demo, "\n")
    env, res = plan_from_text(demo, llama_url=LLAMA_URL)
    print("抽取结果:")
    print(json.dumps(env, ensure_ascii=False, indent=2))
    if res and res.feasible:
        print(f"\n计划（目标值 {res.objective}, {res.solve_ms}ms）:")
        for a in res.assignments:
            print(f"  {a.start:%m-%d %H:%M}-{a.end:%H:%M}  {a.title}")
    elif res:
        print("\n无可行解:", res.violations)

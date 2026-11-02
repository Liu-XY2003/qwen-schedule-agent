#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2 模型全面验收: 日期格式 / 周偏移 / 月偏移

★ 期望值是**按运行当天动态计算**的, 不写死日期。
  早期版本把 "2026-10-06" 这类日期硬编码进用例, 结果两周后整个测试集自动失效
  (21 条只剩 5 条过), 看起来像模型坏了, 实际是测试过期 —— 更糟的是,
  它还把"上周二被顺延到本周二"这个 bug 固化成了期望值。
  验收套件必须能长期复现, 而且不能把错误行为写进期望。

★ 这个脚本是**破坏性**的 —— 每条用例都真的调用 /api/chat, 会往目标实例写日程。
  别对着自己的日常实例跑, 用临时库:

      .\\local\\run_acceptance_scratch.ps1          (Windows, 推荐)
      SCHED_DB=/tmp/acc.db SCHED_LLAMA_URL=http://127.0.0.1:18080 \\
        python -m uvicorn app:app --port 8899 &
      SCHED_API=http://127.0.0.1:8899 python acceptance_v2.py

退出码: 0 = 全过, 1 = 有用例失败, 2 = 目标库非空且未显式放行。
"""
import datetime as dt
import json
import os
import sys
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

API = os.environ.get("SCHED_API", "http://127.0.0.1:8800").rstrip("/")
NOW = dt.datetime.now()
TODAY = NOW.date()
print(f"验收目标: {API}")
print(f"基准时间: {NOW:%Y-%m-%d %H:%M} (周{'一二三四五六日'[TODAY.weekday()]})\n")


def get(p):
    return json.loads(urllib.request.urlopen(API + p, timeout=20).read().decode("utf-8"))


def post(p, d):
    r = urllib.request.Request(API + p, data=json.dumps(d).encode("utf-8"),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(r, timeout=180).read().decode("utf-8"))


# ---------------------------------------------------------------- 期望值
# 刻意用**独立于 executor 的直白日历运算**算期望, 不复用项目里的 resolve_*。
# 否则执行器有 bug 时测试会跟着错, 就测不出问题。

WD = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
CN_NUM = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七",
          8: "八", 9: "九", 10: "十", 11: "十一", 12: "十二"}
CN_DAY = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八",
          9: "九", 10: "十", 11: "十一", 12: "十二", 13: "十三", 14: "十四",
          15: "十五", 16: "十六", 17: "十七", 18: "十八", 19: "十九", 20: "二十",
          21: "二十一", 22: "二十二", 23: "二十三", 24: "二十四", 25: "二十五",
          26: "二十六", 27: "二十七", 28: "二十八", 29: "二十九", 30: "三十",
          31: "三十一"}


def exp_weekday(code: str, week_offset: int, hour: int = 9) -> str:
    """week_offset=0 指本周(周一为周首)。

    项目策略: 本周该时刻已过时顺延一周 —— 但**仅限 week_offset==0**。
    显式给了负数偏移(上周)时必须原样保留, 否则会差整整一周。
    """
    monday = TODAY - dt.timedelta(days=TODAY.weekday())
    d = monday + dt.timedelta(weeks=week_offset, days=WD[code])
    if week_offset == 0 and dt.datetime.combine(d, dt.time(hour)) <= NOW:
        d += dt.timedelta(days=7)
    return d.isoformat()


def exp_month_offset(day: int, month_offset: int) -> str:
    y, m = TODAY.year, TODAY.month + month_offset
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return dt.date(y, m, day).isoformat()


def exp_month_day_bare(day: int) -> str:
    """只给几号没给月份偏移: 本月还没到就是本月, 已过就是下个月。"""
    return exp_month_offset(day, 0 if TODAY.day <= day else 1)


def next_occurrence(month: int, day: int) -> dt.date:
    """该 月-日 的下一次出现(含今天)。"""
    for year in (TODAY.year, TODAY.year + 1):
        try:
            d = dt.date(year, month, day)
        except ValueError:
            continue
        if d >= TODAY:
            return d
    raise ValueError("无解")


# ---------------------------------------------------------------- 用例
# 期望值写法: "REJECT" / "CLARIFY" / 具体日期字符串 / ("weekday"|"month"|"bare"|"nth", ...)
TARGET_ABS = next_occurrence(10, 23)
GROUPS = {
    "① 原始 bug: 无年份绝对日期": [
        (f"{CN_NUM[TARGET_ABS.month]}月{TARGET_ABS.day}号下午10点19提醒我去寿司店买鲜花",
         TARGET_ABS.isoformat()),
        (f"{TARGET_ABS.month}月{TARGET_ABS.day}号下午10点19提醒我去寿司店买鲜花",
         TARGET_ABS.isoformat()),
        (f"{TARGET_ABS.month}/{TARGET_ABS.day} 下午10点19提醒我去寿司店买鲜花",
         TARGET_ABS.isoformat()),
        (f"{TARGET_ABS.year}年{TARGET_ABS.month}月{TARGET_ABS.day}号下午10点19提醒我去寿司店买鲜花",
         TARGET_ABS.isoformat()),
        (f"{CN_NUM[TARGET_ABS.month]}月{CN_DAY[TARGET_ABS.day]}号下午10点19提醒我去寿司店买鲜花",
         TARGET_ABS.isoformat()),
    ],
    "② 周偏移": [
        ("下下周二上午九点加一门计算机原理，在教三201", ("weekday", "TU", 2)),
        ("下周二上午九点加一门计算机原理", ("weekday", "TU", 1)),
        ("下下下周二上午九点开会", ("weekday", "TU", 3)),
        ("下下周三下午两点有高数考试", ("weekday", "WE", 2)),
        ("上周二下午三点开会", ("weekday", "TU", -1)),       # ← 曾经被错误顺延
        ("周二上午九点开会", ("weekday", "TU", 0)),
        ("大下周二上午九点开会", ("weekday", "TU", 2)),
        ("下下个星期二上午九点开会", ("weekday", "TU", 2)),
    ],
    "③ 月偏移": [
        ("下个月3号上午九点开会", ("month", 3, 1)),
        ("下下个月17号下午两点有考试", ("month", 17, 2)),
        ("这个月28号晚上八点交作业", ("month", 28, 0)),
        ("3号上午九点开会", ("bare", 3)),
    ],
    "④ 应被拒/追问": [
        ("今天天气怎么样", "REJECT"),
        ("帮我加个课", "CLARIFY"),
        ("下下下下下周二上午九点开会", "CLARIFY"),
    ],
}


def expected(spec):
    if isinstance(spec, str):
        if spec == "REJECT":
            return ("kind", "rejected")
        if spec == "CLARIFY":
            return ("kind", "need_clarify")
        return ("date", spec)
    kind = spec[0]
    if kind == "weekday":
        return ("date", exp_weekday(spec[1], spec[2]))
    if kind == "month":
        return ("date", exp_month_offset(spec[1], spec[2]))
    if kind == "bare":
        return ("date", exp_month_day_bare(spec[1]))
    if kind == "nth":
        return ("date", next_occurrence(spec[1], spec[2]).isoformat())
    raise ValueError(f"未知 spec: {spec}")


# --- 破坏性检查 ---
_ev_before = None
try:
    _ev_before = get("/api/health").get("events")
except Exception as e:
    print(f"无法读取目标实例 ({e}); 请确认服务已启动\n")

if _ev_before and not os.environ.get("SCHED_ALLOW_DIRTY"):
    print(f"[!] 目标库里已有 {_ev_before} 条日程, 而本脚本会往它写入约 20 条测试数据。")
    print("   改用临时数据库:")
    print("     .\\local\\run_acceptance_scratch.ps1          (Windows)")
    print("     SCHED_API=http://127.0.0.1:8899 python acceptance_v2.py")
    print("   确认要在当前实例上跑, 请设 SCHED_ALLOW_DIRTY=1。\n")
    raise SystemExit(2)

# ---------------------------------------------------------------- 跑
ok = tot = 0
failures = []
for gname, cases in GROUPS.items():
    print("=" * 96)
    print(gname)
    print("=" * 96)
    for text, spec in cases:
        want_kind, want_val = expected(spec)
        try:
            j = post("/api/chat", {"text": text})
        except Exception as e:
            tot += 1
            failures.append((text, f"请求异常 {e}"))
            print(f"XX  {text}\n      请求异常: {e}")
            continue
        ex = j.get("execution") or {}
        kind = ex.get("kind")
        it = (ex.get("items") or [{}])[0]
        got = (it.get("start") or "")[:10]

        if want_kind == "kind":
            good = kind == want_val
        else:
            good = (kind == "executed" and got == want_val)

        tot += 1
        ok += good
        if not good:
            failures.append((text, f"期望 {want_val} 实际 {kind}/{got or '-'}"))
        print(f"{'OK ' if good else 'XX '} {text}")
        print(f"      期望 {want_val:<12} 实际 {kind}/{got or '-'}")
        if not good:
            print(f"      模型 {j.get('model_raw','')[:150]}")

print("=" * 96)
print(f"总通过 {ok}/{tot} = {ok * 100 // max(tot, 1)}%")
if failures:
    print("\n失败明细:")
    for t, why in failures:
        print(f"  - {t}\n      {why}")
raise SystemExit(0 if ok == tot else 1)

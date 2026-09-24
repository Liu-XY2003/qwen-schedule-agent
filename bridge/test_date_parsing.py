#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""针对本次 bug 的回归测试: 直接测执行器, 不经过模型"""
import sys
from datetime import datetime

sys.path.insert(0, r"D:\Projects\qwen-local-tool-agent\bridge")
from executor import NeedClarify, Store, execute, resolve_time  # noqa: E402

NOW = datetime(2026, 9, 23, 0, 30, 0)   # 2026-09-23 周三

CASES = [
    # (说明, when, 期望 start 或 None, 期望 kind)
    ("标准 YYYY-MM-DD", {"date_kind": "absolute", "date_value": "2026-10-23", "time": "22:19", "period": "pm"}, "2026-10-23T22:19:00", "executed"),
    ("斜杠 M/D (本次 bug)", {"date_kind": "absolute", "date_value": "10/23", "time": "22:19", "period": "pm"}, "2026-10-23T22:19:00", "executed"),
    ("中文月 (本次 bug)", {"date_kind": "absolute", "date_value": "10月23", "time": "22:19", "period": "pm"}, "2026-10-23T22:19:00", "executed"),
    ("中文数字月", {"date_kind": "absolute", "date_value": "十月23号", "time": "22:19", "period": "pm"}, "2026-10-23T22:19:00", "executed"),
    ("横杠 M-D", {"date_kind": "absolute", "date_value": "10-23", "time": "09:00", "period": "am"}, "2026-10-23T09:00:00", "executed"),
    ("无年份已过 -> 顺延明年", {"date_kind": "absolute", "date_value": "1/5", "time": "09:00", "period": "am"}, "2027-01-05T09:00:00", "executed"),
    ("紧凑 YYYYMMDD", {"date_kind": "absolute", "date_value": "20261023", "time": "09:00", "period": "am"}, "2026-10-23T09:00:00", "executed"),
    ("今年12月31号 (模型曾编成2023)", {"date_kind": "absolute", "date_value": "2023-12-31", "time": "20:00", "period": "pm"}, None, "need_clarify"),
    ("真正的历史日期(去年)仍允许", {"date_kind": "absolute", "date_value": "2025-12-31", "time": "20:00", "period": "pm"}, "2025-12-31T20:00:00", "executed"),
    ("彻底看不懂 -> 问用户", {"date_kind": "absolute", "date_value": "下个月三号", "time": "09:00", "period": "am"}, None, "need_clarify"),
    ("不存在的日期", {"date_kind": "absolute", "date_value": "2026-02-30", "time": "09:00", "period": "am"}, None, "need_clarify"),
    ("星期写法容错 周一", {"date_kind": "weekday", "date_value": "周一", "time": "09:00", "period": "am"}, "2026-09-28T09:00:00", "executed"),
    ("相对日", {"date_kind": "offset_day", "date_value": "+2", "time": "14:00", "period": "pm"}, "2026-09-25T14:00:00", "executed"),
]

ok = bad = 0
print("=" * 96)
print(f"执行器回归测试   『现在』={NOW}")
print("=" * 96)
store = Store(":memory:")
for name, when, want_start, want_kind in CASES:
    env = {"status": "ok", "commands": [{"module": "reminder", "action": "add",
                                         "title": "测试", "when": when}]}
    try:
        out = execute(env, store, NOW)
        got_kind = out.kind
        got_start = out.event["items"][0]["start"] if out.event.get("items") else None
        detail = out.detail
    except NeedClarify as e:
        got_kind, got_start, detail = "need_clarify", None, str(e)
    except Exception as e:
        got_kind, got_start, detail = "EXC", None, f"{type(e).__name__}: {e}"

    good = (got_kind == want_kind) and (got_start == want_start)
    ok += good
    bad += (not good)
    print(f"{'OK ' if good else 'XX '} {name}")
    print(f"      when={when}")
    print(f"      期望: {want_kind} / {want_start}")
    print(f"      实际: {got_kind} / {got_start}" + (f"   ({detail})" if detail and not good else ""))
    print()

print("=" * 96)
print(f"通过 {ok}/{len(CASES)}")
print("=" * 96)

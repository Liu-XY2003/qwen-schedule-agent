#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2 偏移解析测试: 下下周 / 下下下周 / 上周 / 下个月X号"""
import sys
from datetime import datetime

sys.path.insert(0, r"D:\Projects\qwen-local-tool-agent\bridge")
from executor import Store, execute  # noqa: E402

NOW = datetime(2026, 9, 23, 0, 30, 0)   # 2026-09-23 周三; 本周一=09-21
store = Store(":memory:")

CASES = [
    # 说明, when, 期望日期
    ("周二(offset缺省)",      {"date_kind": "weekday", "date_value": "TU"}, "2026-09-29"),
    ("本周二",               {"date_kind": "weekday", "date_value": "TU", "week_offset": 0}, "2026-09-29"),
    ("下周二",               {"date_kind": "weekday", "date_value": "TU", "week_offset": 1}, "2026-09-29"),
    ("下下周二 ★本次bug",    {"date_kind": "weekday", "date_value": "TU", "week_offset": 2}, "2026-10-06"),
    ("下下下周二",            {"date_kind": "weekday", "date_value": "TU", "week_offset": 3}, "2026-10-13"),
    ("下下下下周二",          {"date_kind": "weekday", "date_value": "TU", "week_offset": 4}, "2026-10-20"),
    ("上周二",               {"date_kind": "weekday", "date_value": "TU", "week_offset": -1}, "2026-09-22"),
    ("上上周二",             {"date_kind": "weekday", "date_value": "TU", "week_offset": -2}, "2026-09-15"),
    ("下下周三",             {"date_kind": "weekday", "date_value": "WE", "week_offset": 2}, "2026-10-07"),
    # v1 兼容: 旧模型输出 week_ref
    ("v1 week_ref=next 兼容", {"date_kind": "weekday", "date_value": "TU", "week_ref": "next"}, "2026-09-29"),
    ("v1 week_ref=this 兼容", {"date_kind": "weekday", "date_value": "TU", "week_ref": "this"}, "2026-09-29"),
    # month_day
    ("26号(offset缺省->下次出现)", {"date_kind": "month_day", "date_value": "26"}, "2026-09-26"),
    ("这个月26号",           {"date_kind": "month_day", "date_value": "26", "month_offset": 0}, "2026-09-26"),
    ("下个月3号 ★月份偏移",   {"date_kind": "month_day", "date_value": "3", "month_offset": 1}, "2026-10-03"),
    ("下下个月17号",          {"date_kind": "month_day", "date_value": "17", "month_offset": 2}, "2026-11-17"),
    ("上个月20号",           {"date_kind": "month_day", "date_value": "20", "month_offset": -1}, "2026-08-20"),
    ("3号(已过->下次出现)",   {"date_kind": "month_day", "date_value": "3"}, "2026-10-03"),
    ("跨年: 下个月3号",       {"date_kind": "month_day", "date_value": "3", "month_offset": 1}, "2026-10-03"),
]

ok = bad = 0
print("=" * 92)
print(f"v2 偏移解析测试   『现在』= {NOW}  (周三)")
print("参考: 本周一=09-21 下周二=09-29 下下周二=10-06 下下下周二=10-13")
print("=" * 92)
for name, when, want in CASES:
    w = dict(when)
    w["time"] = "09:00"
    w["period"] = "am"
    env = {"status": "ok", "commands": [{"module": "class", "action": "add", "title": "T", "when": w}]}
    try:
        out = execute(env, store, NOW)
        got = out.event["items"][0]["start"][:10] if out.event.get("items") else out.kind
    except Exception as e:
        got = f"{type(e).__name__}: {e}"
    good = got == want
    ok += good
    bad += (not good)
    print(f"{'OK ' if good else 'XX '} {name:<28} 期望 {want}  实际 {got}")
print("=" * 92)
print(f"通过 {ok}/{len(CASES)}")

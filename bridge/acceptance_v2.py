#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2 模型全面验收: 日期格式 / 周偏移 / 月偏移

★ 注意: 这个脚本是**破坏性**的 —— 每条用例都真的调用 /api/chat, 会把日程写进
  目标实例的数据库。直接对着自己的日常实例跑, 会让日历里多出一堆测试数据
  (踩过一次: 21 条用例把 6 条真实日程的水位冲到 23 条)。

  所以默认只记录"跑之前的条数", 结束后提示你怎么清理; 想真正干净地跑, 请用
  SCHED_ALLOW_DIRTY=1 配合一个临时数据库:

      SCHED_DB=/tmp/acc.db SCHED_LLAMA_URL=http://127.0.0.1:18080 \
        python -m uvicorn app:app --port 8899 &
      SCHED_API=http://127.0.0.1:8899 SCHED_ALLOW_DIRTY=1 python acceptance_v2.py
"""
import json
import os
import sys
import urllib.request

# Windows 控制台默认 GBK, 打印 emoji 会直接 UnicodeEncodeError 崩掉。
# 这个脚本要在别人的机器上跑, 不能在"提醒用户有风险"这一步把自己搞死。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 默认打本机; 设 SCHED_API 可指向别处 (例如部署好的服务器)
API = os.environ.get("SCHED_API", "http://127.0.0.1:8800").rstrip("/")
print(f"验收目标: {API}\n")


def get(p):
    return json.loads(urllib.request.urlopen(API + p, timeout=20).read().decode("utf-8"))


def post(p, d):
    r = urllib.request.Request(API + p, data=json.dumps(d).encode("utf-8"),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(r, timeout=120).read().decode("utf-8"))


# --- 破坏性检查: 目标库里已经有数据且没显式放行, 就先说清楚再继续 ---
_ev_before = None
try:
    _ev_before = get("/api/health").get("events")
except Exception as e:
    print(f"无法读取目标实例 ({e}); 请确认服务已启动\n")

if _ev_before and not os.environ.get("SCHED_ALLOW_DIRTY"):
    print(f"[!] 目标库里已有 {_ev_before} 条日程, 而本脚本会往它写入约 21 条测试数据。")
    print("   建议改用临时数据库:")
    print("     SCHED_DB=/tmp/acc.db SCHED_LLAMA_URL=http://127.0.0.1:18080 \\")
    print("       python -m uvicorn app:app --port 8899 &")
    print("     SCHED_API=http://127.0.0.1:8899 python acceptance_v2.py")
    print("   确认要在当前实例上跑, 请设 SCHED_ALLOW_DIRTY=1。\n")
    raise SystemExit(2)


GROUPS = {
    "① 原始 bug: 无年份绝对日期": [
        ("十月23号下午10点19提醒我去寿司店买鲜花", "2026-10-23"),
        ("10月23号下午10点19提醒我去寿司店买鲜花", "2026-10-23"),
        ("10/23 下午10点19提醒我去寿司店买鲜花", "2026-10-23"),
        ("2026年10月23号下午10点19提醒我去寿司店买鲜花", "2026-10-23"),
        ("十月二十三号下午10点19提醒我去寿司店买鲜花", "2026-10-23"),
    ],
    "② 周偏移 (本次报告的问题)": [
        ("下下周二上午九点加一门计算机原理，在教三201", "2026-10-06"),
        ("下周二上午九点加一门计算机原理", "2026-09-29"),
        ("下下下周二上午九点开会", "2026-10-13"),
        ("下下周三下午两点有高数考试", "2026-10-07"),
        ("上周二下午三点开会", "2026-09-22"),
        ("周二上午九点开会", "2026-09-29"),
        ("大下周二上午九点开会", "2026-10-06"),
        ("下下个星期二上午九点开会", "2026-10-06"),
    ],
    "③ 月偏移": [
        ("下个月3号上午九点开会", "2026-10-03"),
        ("下下个月17号下午两点有考试", "2026-11-17"),
        ("这个月28号晚上八点交作业", "2026-09-28"),
        ("3号上午九点开会", "2026-10-03"),
    ],
    "④ 应被拒/追问": [
        ("今天天气怎么样", "REJECT"),
        ("帮我加个课", "CLARIFY"),
        ("下下下下下周二上午九点开会", "CLARIFY"),
        ("今年12月31号晚上八点跨年", "CLARIFY"),
    ],
}

ok = tot = 0
for gname, cases in GROUPS.items():
    print("=" * 96)
    print(gname)
    print("=" * 96)
    for text, want in cases:
        j = post("/api/chat", {"text": text})
        ex = j.get("execution") or {}
        kind = ex.get("kind")
        it = (ex.get("items") or [{}])[0]
        got = it.get("start", "")[:10] if it.get("start") else ""
        if want == "REJECT":
            good = kind == "rejected"
        elif want == "CLARIFY":
            good = kind == "need_clarify"
        else:
            good = (kind == "executed" and got == want)
        tot += 1
        ok += good
        print(f"{'OK ' if good else 'XX '} {text}")
        print(f"      期望 {want:<12} 实际 {kind}/{got or '-'}")
        print(f"      模型 {j.get('model_raw','')[:150]}")
        if not good:
            print(f"      详情 {ex.get('detail')}")
        print()
print("=" * 96)
print(f"总通过 {ok}/{tot} = {100*ok/tot:.0f}%")

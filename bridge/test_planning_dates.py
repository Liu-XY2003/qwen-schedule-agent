#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""planning.resolve_deadline / resolve_time 的单元测试。

这一层是**确定性代码**, 是二阶段里唯一可以严格断言的部分, 所以要测透。
模型输出什么写法我们控制不了, 但解析器必须对合理的写法都给出正确结果。
"""
from __future__ import annotations

import sys
from datetime import date, time

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else ".")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from planning import resolve_deadline, resolve_time  # noqa: E402

CHECKS = 0
FAILS: list[str] = []
TODAY = date(2026, 11, 2)          # 周一


def eq(name, got, want):
    global CHECKS
    CHECKS += 1
    if got == want:
        print(f"OK   {name}")
    else:
        print(f"FAIL {name}: got={got!r} want={want!r}")
        FAILS.append(name)


# ---- ISO 星期码（模型最常见的输出形态）----
eq("ISO FR", resolve_deadline("FR", TODAY), date(2026, 11, 6))
eq("ISO WE", resolve_deadline("WE", TODAY), date(2026, 11, 4))
eq("ISO MO(今天)", resolve_deadline("MO", TODAY), date(2026, 11, 2))
eq("ISO 带时间", resolve_deadline("FR 18:00", TODAY), date(2026, 11, 6))

# ---- 中文星期 ----
eq("周五", resolve_deadline("周五", TODAY), date(2026, 11, 6))
eq("这周五", resolve_deadline("这周五", TODAY), date(2026, 11, 6))
eq("下周五", resolve_deadline("下周五", TODAY), date(2026, 11, 13))
eq("下下周五", resolve_deadline("下下周五", TODAY), date(2026, 11, 20))
eq("上周五(过去)", resolve_deadline("上周五", TODAY), date(2026, 10, 30))

# ---- 相对 ----
eq("今天", resolve_deadline("今天", TODAY), date(2026, 11, 2))
eq("明天", resolve_deadline("明天", TODAY), date(2026, 11, 3))
eq("后天", resolve_deadline("后天", TODAY), date(2026, 11, 4))

# ---- 绝对写法 ----
eq("2026-11-07", resolve_deadline("2026-11-07", TODAY), date(2026, 11, 7))
eq("2026/11/07", resolve_deadline("2026/11/07", TODAY), date(2026, 11, 7))
eq("11-07", resolve_deadline("11-07", TODAY), date(2026, 11, 7))
eq("11/07", resolve_deadline("11/07", TODAY), date(2026, 11, 7))
eq("11月7日", resolve_deadline("11月7日", TODAY), date(2026, 11, 7))
eq("11月7号", resolve_deadline("11月7号", TODAY), date(2026, 11, 7))
# 已过去的月日 -> 明年
eq("10-01(已过)->次年", resolve_deadline("10-01", TODAY), date(2027, 10, 1))

# ---- 边界 ----
eq("空串", resolve_deadline("", TODAY), None)
eq("None", resolve_deadline(None, TODAY), None)
eq("无法识别", resolve_deadline("什么时候都行", TODAY), None)

# ---- 时间 ----
eq("18:00", resolve_time("18:00"), time(18, 0))
eq("09:05", resolve_time("09:05"), time(9, 5))
eq("23:59", resolve_time("23:59"), time(23, 59))
eq("非法 25:00", resolve_time("25:00"), None)
eq("非法 12:99", resolve_time("12:99"), None)
eq("非时间", resolve_time("下午"), None)
eq("空", resolve_time(""), None)

print()
if FAILS:
    print(f"失败 {len(FAILS)}/{CHECKS}: {FAILS}")
    sys.exit(1)
print(f"日期解析测试全部通过 ({CHECKS} 项)")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一份**中性演示数据**，专供截图使用。

为什么单独做一份：
  - 开源仓库和参赛材料都要公开展示截图, 不能带上真实的个人日程
    （比如"去校医院看医生"能推出所在学校, "实验室门禁密码"看起来像真凭据）
  - 也不该展示真实的服务地址（Tailscale IP / 内网 IP）

用法:
    python scripts/seed_demo.py <db-path>
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "demo.db"

# 相对"本周"生成, 保证截图里的日期永远是当前的、看起来像活数据
TODAY = dt.date.today()
MONDAY = TODAY - dt.timedelta(days=TODAY.weekday())


def at(day_offset: int, hour: int, minute: int = 0) -> str:
    return dt.datetime.combine(MONDAY + dt.timedelta(days=day_offset),
                               dt.time(hour, minute)).isoformat()


# (module, title, start_ts 或 None, duration_min, location, notes, ambiguous)
EVENTS = [
    ("class", "计算机原理", at(1, 9), 100, "教三201", None, 0),
    ("meeting", "组会", at(2, 15), 60, "综合楼508", None, 0),
    ("exam", "高数期中", at(3, 14), 120, "教一101", "提前 15 分钟到", 0),
    ("assignment", "操作系统实验报告", at(4, 18), None, None, "周五 23:59 前提交", 0),
    ("reminder", "给家里打电话", at(0, 19, 30), None, None, None, 0),
    ("alarm", "早起", at(1, 7, 30), None, None, None, 1),
    ("memo", "图书馆借的书 15 号到期", None, None, None, "《算法导论》", 0),
    ("memo", "组会要带的东西", None, None, None, "笔记本 + 上周进度", 0),
]

SQL = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  module TEXT NOT NULL, action TEXT NOT NULL, title TEXT NOT NULL,
  start_ts TEXT, duration_min INTEGER, remind_before_min INTEGER,
  location TEXT, priority TEXT, notes TEXT, ambiguous INTEGER DEFAULT 0,
  raw_when TEXT, created_at TEXT
);
"""

conn = sqlite3.connect(DB)
conn.executescript(SQL)
conn.execute("DELETE FROM events")
now = dt.datetime.now().isoformat()
for module, title, start, dur, loc, notes, amb in EVENTS:
    conn.execute(
        "INSERT INTO events (module, action, title, start_ts, duration_min,"
        " remind_before_min, location, priority, notes, ambiguous, raw_when, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (module, "add", title, start, dur, None, loc, None, notes, amb, None, now))
conn.commit()
n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
conn.close()
print(f"演示数据已写入 {DB}: {n} 条（周一起算 {MONDAY}）")

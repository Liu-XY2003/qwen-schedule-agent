#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日程工具执行模块（L3 校验/解析 + L4 工具 + L5 存储）

设计要点:
  1. 模型只做语义归一化, 绝不计算绝对日期; 绝对时间全部由 resolve_time() 确定性推导
  2. period=none 用一份显式的用户作息规则消歧, 并把歧义记录下来供 UI 确认
  3. 任何输入都必须给出确定的结果: executed / need_clarify / rejected / failed，
     绝不允许"静默失败"
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

# ------------------------------------------------------------------ 策略表

FUZZY_HOUR = {"morning": 8, "noon": 12, "afternoon": 14, "evening": 19, "night": 21}

DEFAULT_DURATION = {"class": 90, "exam": 120, "meeting": 60, "assignment": 60,
                    "alarm": 5, "reminder": 5, "memo": 0}

MODULE_CN = {"class": "课程", "exam": "考试", "meeting": "会议", "assignment": "作业",
             "alarm": "闹钟", "reminder": "提醒", "memo": "备忘"}

# period=none 的消歧规则: 用户说"三点"时, 到底指 03:00 还是 15:00?
# 这里用一条显式规则代替"猜": 1-6 点按下午/晚上理解, 7-12 点按上午理解。
# 真实系统应允许按用户历史行为调整, 并把这个歧义回显给用户确认。
AMBIGUOUS_AM_MAX = 6


class ExecError(Exception):
    pass


class NeedClarify(Exception):
    """信息不足, 应该向用户追问, 而不是报失败"""


# 绝对日期的宽容解析:
#   完整年份 2026-10-23 / 2026/10/23 / 2026年10月23号 / 20261023
#   缺年份   10-23 / 10/23 / 10月23号 / 十月23号   -> 取"下一个"该月日
# 缺年份时绝不猜年份, 而是由解析器按"下一次出现"推导, 并标记为有歧义。
_CN_DIGIT = {"零": "0", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
             "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
             "十一": "11", "十二": "12"}


def _cn2int(s: str) -> int | None:
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in _CN_DIGIT:
        return int(_CN_DIGIT[s])
    if s.startswith("十") and len(s) == 2 and s[1] in _CN_DIGIT:   # 十三
        return 10 + int(_CN_DIGIT[s[1]])
    if len(s) == 3 and s[1] == "十" and s[0] in _CN_DIGIT and s[2] in _CN_DIGIT:  # 二十三
        return int(_CN_DIGIT[s[0]]) * 10 + int(_CN_DIGIT[s[2]])
    return None


def _parse_absolute(v: str, today: date) -> tuple[date, bool]:
    """
    返回 (日期, 是否给了年份)。
    解析失败抛 NeedClarify —— 这是"没听懂", 该问用户, 不是失败。
    """
    s = str(v).strip()

    # 去掉常见修饰
    s = s.replace("年", "-").replace("月", "-")
    s = re.sub(r"[号日]$", "", s)
    s = s.replace("/", "-").replace(".", "-")
    s = s.replace(" ", "")

    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d), True
        except ValueError:
            raise NeedClarify(f"日期不存在: {y}年{mo}月{d}日")

    m = re.fullmatch(r"(\d{8})", s)
    if m:
        y, mo, d = int(s[:4]), int(s[4:6]), int(s[6:])
        try:
            return date(y, mo, d), True
        except ValueError:
            raise NeedClarify(f"日期不存在: {s}")

    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        return _month_day(mo, d, today), False

    # 中文数字月份: 十月23 / 十二月31 (replace 之后 "十" 还在)
    m = re.fullmatch(r"([零一二三四五六七八九十]{1,3})-(\d{1,2})", s)
    if m:
        mo = _cn2int(m.group(1))
        if mo:
            return _month_day(mo, int(m.group(2)), today), False

    raise NeedClarify(f"看不懂这个日期写法: {v!r}。请换个说法，例如「2026年10月23号」或「10月23号」")


def _month_day(mo: int, d: int, today: date) -> date:
    """没给年份时取"下一次出现"的该月日"""
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        raise NeedClarify(f"日期不存在: {mo}月{d}日")
    for year in (today.year, today.year + 1):
        try:
            cand = date(year, mo, d)
        except ValueError:
            continue
        if cand >= today:
            return cand
    raise NeedClarify(f"日期不存在: {mo}月{d}日")


@dataclass
class Outcome:
    kind: str                      # executed / need_clarify / rejected / failed
    detail: str = ""
    event_id: int | None = None
    event: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ 时间解析

def _resolve_date(when: dict, today: date) -> tuple[date | None, bool]:
    """返回 (日期, 是否给定了完整年份)"""
    dk = when.get("date_kind")
    if dk == "offset_day":
        v = str(when.get("date_value", "+0"))
        m = re.fullmatch(r"([+-]?\d+)", v)
        if not m:
            raise NeedClarify(f"看不懂相对日期: {v!r}")
        return today + timedelta(days=int(m.group(1))), True

    if dk == "weekday":
        dv = str(when.get("date_value", "")).strip().upper()
        order = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
        alias = {"周一": "MO", "周二": "TU", "周三": "WE", "周四": "TH", "周五": "FR",
                 "周六": "SA", "周日": "SU", "周天": "SU", "MON": "MO", "TUE": "TU",
                 "WED": "WE", "THU": "TH", "FRI": "FR", "SAT": "SA", "SUN": "SU"}
        dv = alias.get(dv, dv[:2] if len(dv) > 2 else dv)
        if dv not in order:
            raise NeedClarify(f"看不懂星期: {when.get('date_value')!r}")

        # v2: week_offset 数值; 同时兼容 v1 模型的 week_ref 枚举
        off = when.get("week_offset")
        if off is None:
            off = {"this": 0, "next": 1, "next2": 2, "none": 0}.get(
                str(when.get("week_ref", "this")), 0)
        try:
            off = int(off)
        except Exception:
            raise NeedClarify(f"看不懂周偏移: {off!r}")
        if not (-2 <= off <= 4):
            raise NeedClarify(f"周偏移 {off} 超出我能处理的范围（-2 ~ 4 周）")

        this_monday = today - timedelta(days=today.weekday())
        return this_monday + timedelta(days=order[dv], weeks=off), True

    if dk == "month_day":
        v = str(when.get("date_value", "")).strip()
        v = re.sub(r"[号日]$", "", v.replace("月", "-").split("-")[-1])
        try:
            day = int(v)
        except Exception:
            raise NeedClarify(f"看不懂这个日期: {when.get('date_value')!r}")
        if not (1 <= day <= 31):
            raise NeedClarify(f"日期不存在: {day} 号")

        if when.get("month_offset") is None:
            # 没给月份偏移 -> 取"下一次出现": 本月还没到就是本月, 已过就是下个月
            return _month_day_from_day(day, today, 0 if today.day <= day else 1), False
        moff = int(when["month_offset"])
        if not (-2 <= moff <= 4):
            raise NeedClarify(f"月偏移 {moff} 超出我能处理的范围（-2 ~ 4 个月）")
        return _month_day_from_day(day, today, moff), True

    if dk == "absolute":
        return _parse_absolute(when.get("date_value", ""), today)

    if dk == "unspecified" or dk is None:
        return None, True
    raise NeedClarify(f"未知的 date_kind: {dk!r}")


def _month_day_from_day(day: int, today: date, month_offset: int) -> date:
    """按月份偏移取某一天"""
    y, m = today.year, today.month + month_offset
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    try:
        return date(y, m, day)
    except ValueError:
        raise NeedClarify(f"日期不存在: {y}年{m}月{day}日")


def _resolve_clock(when: dict) -> tuple[time | None, bool]:
    """返回 (时刻, 是否有歧义)"""
    t = when.get("time")
    if t is None:
        fz = when.get("fuzzy")
        if fz and fz != "none":
            if fz not in FUZZY_HOUR:
                raise ExecError(f"未知 fuzzy: {fz!r}")
            return time(FUZZY_HOUR[fz], 0), True
        return None, False

    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(t).strip())
    if not m:
        raise ExecError(f"time 格式非法: {t!r}")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ExecError(f"time 越界: {t!r}")

    period = when.get("period", "none")
    if period == "am":
        if not (0 <= h <= 12):
            raise ExecError(f"period=am 但 time={t!r} 不是 12 小时制")
        hh = 0 if h == 12 else h
        return time(hh, mi), False
    if period == "pm":
        if not (0 <= h <= 12):
            # 已经是 24 小时制写法, 直接用
            return time(h, mi), False
        hh = 12 if h == 12 else h + 12
        return time(hh, mi), False

    if period == "none":
        if not (1 <= h <= 12):
            raise ExecError(f"period=none 但 time={t!r} 不是 1-12 点, 无法按 12 小时制解释")
        # 消歧: 1-6 点 -> 下午/晚上; 7-12 点 -> 上午/正午
        hh = h + 12 if h <= AMBIGUOUS_AM_MAX else (0 if h == 12 else h)
        return time(hh, mi), True

    raise ExecError(f"未知 period: {period!r}")


@dataclass
class Resolved:
    start: datetime | None
    ambiguous: bool = False
    is_past: bool = False
    note: str = ""
    reasons: list[str] = field(default_factory=list)


def resolve_time(when: dict | None, now: datetime) -> Resolved:
    """
    把语义槽位解析成绝对时间。

    返回 Resolved(start, ambiguous, is_past, note, reasons)。
    when 为空或既无日期又无时刻时 start=None。
    """
    if not when:
        return Resolved(None, note="无时间信息")

    d, year_given = _resolve_date(when, now.date())

    # 年份合理性闸门: 模型有时会凭训练数据里的年份瞎编(实测"今年12月31号"被输出成 2023-12-31)。
    # 一个日程助手里出现两年前的绝对日期, 几乎必然是模型出错, 宁可问用户也不要静默写错。
    if (d is not None and year_given and when.get("date_kind") == "absolute"
            and d.year < now.year - 1):
        raise NeedClarify(
            f"解析出的日期是 {d.isoformat()}，年份看起来不对（现在是 {now.year} 年）。"
            f"请把年份说清楚，例如「{now.year}年{d.month}月{d.day}号」。")

    clock, clock_ambiguous = _resolve_clock(when)
    reasons: list[str] = []
    if not year_given and d is not None:
        reasons.append(f"用户没给年份, 按「下一次出现的 {d.month} 月 {d.day} 日」解析"
                       f"→ {d.isoformat()}")
    if clock_ambiguous:
        if when.get("period") == "none":
            reasons.append(f"用户只说「{when.get('time')}」未说上午下午, 按作息规则消歧"
                           f"(1-{AMBIGUOUS_AM_MAX}点算下午)")
        else:
            reasons.append(f"模糊时段「{when.get('fuzzy')}」按默认钟点处理")

    if d is None and clock is None:
        return Resolved(None, ambiguous=bool(reasons), reasons=reasons, note="未指定日期与时刻")

    if d is None:
        # 只给时刻没给日期 -> 默认今天; 若今天该时刻已过, 顺延到明天
        d = now.date()
        start = datetime.combine(d, clock)
        if start <= now:
            start += timedelta(days=1)
            reasons.append("只给时刻未给日期, 今天该时刻已过, 顺延到明天")
        else:
            reasons.append("只给时刻未给日期, 默认今天")
        return Resolved(start, ambiguous=bool(reasons), reasons=reasons, note="ok")

    if clock is None:
        start = datetime.combine(d, time(9, 0))
        if start <= now:
            return Resolved(start, ambiguous=True, is_past=True, reasons=reasons,
                            note="只给日期未给时刻, 按全天事项(09:00)处理, 且该日期已过")
        return Resolved(start, ambiguous=bool(reasons), reasons=reasons,
                        note="只给日期未给时刻, 作为全天事项(默认 09:00)")

    start = datetime.combine(d, clock)

    # 过去时间处理: 日程助手把事件写进过去毫无意义。
    # 本周已过的星期几 -> 顺延到下周同一天(用户说"周一"时今天是周二, 几乎必然指下一个周一);
    # 其它情况(如 absolute 过去日期) -> 保留但标记 is_past, 交由上层决定是否确认。
    if start <= now:
        # 星期类: 本周已过的日子顺延(用户说"周一"而今天是周三, 几乎必然指下一个周一)
        if when.get("date_kind") == "weekday" and int(when.get("week_offset") or 0) <= 0:
            start += timedelta(days=7)
            reasons.append("本周该天已过, 顺延到下周同一天")
        else:
            return Resolved(start, ambiguous=bool(reasons), is_past=True, reasons=reasons,
                            note="解析出的时间已过去")

    return Resolved(start, ambiguous=bool(reasons), reasons=reasons, note="ok")


# ------------------------------------------------------------------ 存储

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  module TEXT NOT NULL,
  action TEXT NOT NULL,
  title TEXT NOT NULL,
  start_ts TEXT,
  duration_min INTEGER,
  remind_before_min INTEGER,
  location TEXT,
  priority TEXT,
  notes TEXT,
  ambiguous INTEGER DEFAULT 0,
  raw_when TEXT,
  created_at TEXT
);
"""


class Store:
    def __init__(self, path: str = ":memory:"):
        # check_same_thread=False + 锁: FastAPI 在线程池里执行同步 endpoint,
        # sqlite3 默认禁止跨线程复用连接
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self.conn.executescript(SCHEMA_SQL)

    def insert(self, row: dict) -> int:
        cols = ["module", "action", "title", "start_ts", "duration_min", "remind_before_min",
                "location", "priority", "notes", "ambiguous", "raw_when", "created_at"]
        vals = [row.get(c) for c in cols]
        with self._lock:
            cur = self.conn.execute(
                f"INSERT INTO events ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
            self.conn.commit()
            return cur.lastrowid

    def count(self) -> int:
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def fetch(self, sql: str, args: tuple = ()):
        with self._lock:
            return self.conn.execute(sql, args).fetchall()

    def execute(self, sql: str, args: tuple = ()):
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.rowcount

    def clear(self):
        with self._lock:
            self.conn.execute("DELETE FROM events")
            self.conn.commit()


# ------------------------------------------------------------------ 执行器

def execute(envelope: dict, store: Store, now: datetime) -> Outcome:
    """把一条信封 JSON 执行掉。任何异常都被兜成 failed, 绝不静默。"""
    status = envelope.get("status")
    if status == "reject":
        return Outcome("rejected", "与日程无关")
    if status == "clarify":
        return Outcome("need_clarify", envelope.get("question", "信息不足"))

    cmds = envelope.get("commands") or []
    if not cmds:
        return Outcome("failed", "status=ok 但没有 commands")

    done = []
    for i, c in enumerate(cmds):
        module = c["module"]
        title = c["title"]
        action = c["action"]

        if action != "add":
            # 数据集里目前只有 add; 其余 action 明确报"未实现"而不是静默成功
            return Outcome("failed", f"commands[{i}] action={action} 尚未实现")

        when = c.get("when")
        try:
            r = resolve_time(when, now)
        except NeedClarify as e:
            # 看不懂 = 该问用户, 不是失败。直接回一句能让用户改正的话。
            return Outcome("need_clarify", str(e))
        except ExecError as e:
            return Outcome("failed", f"commands[{i}] 时间解析失败: {e}")

        if r.start is None and module != "memo":
            return Outcome("failed", f"commands[{i}] module={module} 缺少可解析的时间")

        dur = c.get("when", {}).get("duration_min") or DEFAULT_DURATION.get(module, 60)
        eid = store.insert({
            "module": module, "action": action, "title": title,
            "start_ts": r.start.isoformat() if r.start else None,
            "duration_min": dur, "remind_before_min": c.get("remind_before_min"),
            "location": c.get("location"), "priority": c.get("priority"),
            "notes": c.get("notes"), "ambiguous": 1 if r.ambiguous else 0,
            "raw_when": json.dumps(when, ensure_ascii=False) if when else None,
            "created_at": now.isoformat(),
        })
        done.append({"id": eid, "module": module, "title": title,
                     "start": r.start.isoformat() if r.start else None,
                     "ambiguous": r.ambiguous, "is_past": r.is_past,
                     "note": r.note, "reasons": r.reasons})

    return Outcome("executed", f"{len(done)} 条已写入", event_id=done[0]["id"],
                   event={"items": done})

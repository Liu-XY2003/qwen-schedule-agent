#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性规则抽取: 把"模型不擅长但规则很擅长"的部分从模型手里拿回来。

## 为什么需要这一层

留出测试集上 4B 基座的逐字段表现（见 docs/extraction-benchmark.md）:
    status      95.0%
    item F1      0.926
    duration     87.0%
    deadline     52.6%
    keep_free    30.6%   ← 最差

但问题是: **约束和日期其实高度规则化**。
    "周三上午别给我排东西"  → keep_free WE 08:00-12:00
    "周五 18:00 前交"       → deadline 周五, 18:00
    "大概四小时"            → 240 分钟
这些用正则的准确率远高于 30.6%。让模型去做它本来就不擅长的事，
只会把整体准确率拖下去。

## 与模型的分工

    模型  : 理解语义、判断该不该拒答、抽出"有哪几件事"（这些规则做不了）
    规则  : 补齐/校正 结构化的字段（时长、日期说法、排期约束）

这和一阶段"模型只做语义归一化、绝不计算日期"是同一条原则的延伸。

## 用法

    from rules import augment
    env = augment(model_env, text)     # 返回补全后的信封
"""
from __future__ import annotations

import re

WD = {"一": "MO", "二": "TU", "三": "WE", "四": "TH", "五": "FR",
      "六": "SA", "日": "SU", "天": "SU"}

# 时段 -> (start, end)，与 planner.DEFAULT_WINDOWS 对齐
SLOTS = {
    "上午": ("08:00", "12:00"), "早上": ("08:00", "12:00"), "早晨": ("08:00", "12:00"),
    "中午": ("12:00", "13:30"), "下午": ("13:30", "18:00"),
    "傍晚": ("18:00", "19:00"), "晚上": ("19:00", "22:00"), "夜里": ("19:00", "22:00"),
    "全天": ("00:00", "23:59"), "整天": ("00:00", "23:59"),
}

# ---- 约束: 「周三上午别排东西」/「别在周日下午安排任务」
KF_PREFIX = re.compile(
    r"周(?P<wd>[一二三四五六日天])\s*(?P<slot>上午|早上|早晨|中午|下午|傍晚|晚上|夜里|全天|整天)?"
    r"[^。；;\n]{0,14}?(?P<neg>别|不要|不排|别排|空着|绝对不|留给|不能排)")
KF_SUFFIX = re.compile(
    r"别(?:在|把)?\s*周(?P<wd>[一二三四五六日天])\s*"
    r"(?P<slot>上午|早上|早晨|中午|下午|傍晚|晚上|夜里|全天|整天)?"
    r"[^。；;\n]{0,10}?(?:排|安排|占)")

HARD_WORDS = ("绝对", "必须", "一定", "别")
SOFT_WORDS = ("尽量", "最好", "能不", "如果可以")

# ---- 时长: 「四小时」「半小时」「一个半小时」「45 分钟」
CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10}
DUR_RX = re.compile(
    r"(?:(?P<h>一个)?半\s*(?:个)?小时"
    r"|(?P<num>[一二两三四五六七八九十\d]+)\s*(?:个)?\s*(?P<unit>小时|钟头)"
    r"|(?P<min>\d+|[一二两三四五六七八九十]+)\s*(?P<munit>分钟|分))")
QUARTER_RX = re.compile(r"一刻钟?|一刻")

# ---- 日期说法（只抓"表达"，不解析成绝对日期）
DATE_RX = re.compile(
    r"(?:(?:下下|下|这|本|上)?周[一二三四五六日天]"
    r"|\d{1,2}\s*[-/月]\s*\d{1,2}\s*[日号]?"
    r"|今天|明天|后天|大后天)")
TIME_RX = re.compile(r"(?<!\d)([01]?\d|2[0-3])\s*[:：]\s*([0-5]\d)(?!\d)")


def cn_to_int(s: str) -> int | None:
    """中文数字 -> 整数。要处理 "二十"/"三十"/"十五" 这种带"十"的写法。

    第一版只查 CN_NUM 字典, "二十分钟" 直接返回 None —— 而这是最常见的口语时长之一。
    """
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    if "十" in s:
        head, _, tail = s.partition("十")
        tens = CN_NUM.get(head, 1) if head else 1
        ones = CN_NUM.get(tail, 0) if tail else 0
        return tens * 10 + ones
    return CN_NUM.get(s)


def _dur_from_match(m: re.Match) -> int | None:
    g = m.group(0)
    # "半小时" / "一个半小时" —— 都含"半"和"小时", 靠有没有"一个"区分。
    # ★ 注意 h 组捕获的是 "一个", "半小时" 时它是 None, 所以不能用它判断"是不是半",
    #   要看匹配到的整段文本。
    if "小时" in g and "半" in g:
        return 90 if m.group("h") else 30
    if m.group("num"):
        v = cn_to_int(m.group("num"))
        return v * 60 if v else None
    if m.group("min"):
        return cn_to_int(m.group("min"))
    return None


def find_durations(clause: str) -> list[int]:
    out = []
    for m in DUR_RX.finditer(clause):
        d = _dur_from_match(m)
        if d:
            out.append(d)
    if not out and QUARTER_RX.search(clause):
        out.append(15)
    return out


def split_clauses(text: str) -> list[str]:
    parts = re.split(r"[\n；;。]|。另外，?|，然后|^\s*\d+[\)）]", text, flags=re.M)
    return [p.strip(" ，,：:。") for p in parts if p.strip(" ，,：:。")]


def find_keep_free(text: str, with_spans: bool = False):
    """从文本里抽 keep_free 约束。规则抽取, 不走模型。

    with_spans=True 时同时返回被占用的字符区间 —— 这些区间属于**约束**,
    不能拿来给事项抽日期/时长。否则 "周三上午别排东西，写实验报告四小时"
    会把"周三"错当成实验报告的截止日期。
    """
    out, seen, spans = [], set(), []
    for rx in (KF_PREFIX, KF_SUFFIX):
        for m in rx.finditer(text):
            wd = WD.get(m.group("wd"))
            if not wd:
                continue
            spans.append((m.start(), m.end()))
            slot = m.group("slot") or "全天"
            rng = SLOTS.get(slot, SLOTS["全天"])
            key = (wd, rng)
            if key in seen:
                continue
            seen.add(key)
            tail = text[m.start(): m.start() + 40]
            weight = "hard" if any(w in tail for w in HARD_WORDS) else \
                     ("soft" if any(w in tail for w in SOFT_WORDS) else "hard")
            out.append({"kind": "keep_free", "weight": weight,
                        "day": wd, "start": rng[0], "end": rng[1]})
    return (out, spans) if with_spans else out


def blank_spans(text: str, spans) -> str:
    """把指定区间替换成等长空格（保持其余文本原样）。"""
    if not spans:
        return text
    buf = list(text)
    for s, e in spans:
        for i in range(max(0, s), min(len(buf), e)):
            buf[i] = " "
    return "".join(buf)


def find_date_time(clause: str) -> tuple[str | None, str | None]:
    """在一个分句里找日期说法和时刻。"""
    d = None
    m = DATE_RX.search(clause)
    if m:
        d = re.sub(r"\s+", "", m.group(0))
    t = None
    mt = TIME_RX.search(clause)
    if mt:
        t = f"{int(mt.group(1)):02d}:{mt.group(2)}"
    return d, t


def _scope_for(title: str, clauses: list[str]) -> str | None:
    """找到该事项标题所在的分句。

    严格按"分句内查找", 找不到就返回 None（**绝不退化成全文查找**）。
    第一版找不到时用了全文, 结果模型标题与文本略有出入时会抓到别的事项的时长,
    把本来对的答案改错 —— duration 从 87% 掉到 83% 就是这么来的。
    """
    if not title:
        return None
    hits = [c for c in clauses if title in c]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        return min(hits, key=len)          # 取最短的, 通常是最贴切的
    # 退一步: 用标题里最长的、能在某个分句里找到的片段（≥2 字）
    best, best_len = None, 0
    for c in clauses:
        for n in range(len(title), 1, -1):
            for i in range(len(title) - n + 1):
                seg = title[i:i + n]
                if seg in c and n > best_len:
                    best, best_len = c, n
    return best if best_len >= 2 else None


def augment(env: dict, text: str) -> dict:
    """用规则补全/校正模型输出。规则优先, 模型结果作为兜底。

    只动三类字段: constraints / duration_min / deadline_*。
    不改 items 的条数和 title —— 那是模型的活, 规则判断不了。
    """
    if env.get("status") != "ok":
        return env

    out = {**env}
    items = [dict(it) for it in (env.get("items") or [])]

    # 先抽约束并拿到它们的字符区间, 再把区间抹掉。
    # 抹掉之后才按分句找事项的日期/时长, 否则约束里的"周三"会被算到事项头上。
    kf, spans = find_keep_free(text, with_spans=True)
    item_text = blank_spans(text, spans)
    clauses = split_clauses(item_text)

    for it in items:
        title = str(it.get("title") or "")
        scope = _scope_for(title, clauses)
        if scope is None:
            continue                       # 定位不到就保留模型原值, 宁可不改

        ds = find_durations(scope)
        if ds:
            it["duration_min"] = ds[0]

        d, t = find_date_time(scope)
        if d:
            it["deadline_date"] = d
        if t:
            it["deadline_time"] = t

    out["items"] = items

    # 约束: 规则全量接管（模型这一项只有 30.6%，规则高得多）
    model_kf = [c for c in (env.get("constraints") or [])
                if c.get("kind") == "keep_free"]
    out["constraints"] = kf if kf else model_kf
    return out


if __name__ == "__main__":
    import sys
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    samples = [
        "周三上午别给我排东西，把实验报告写完，四小时。周五 18:00 前交周报。",
        "周五晚上绝对不要排事。白天看看论文，一个半小时。",
        "尽量别在周日下午安排任务。上午写代码两小时。",
        "下周三下午两点开会一小时；别在周四晚上排事。",
    ]
    for s in samples:
        print("输入:", s)
        print("  约束:", find_keep_free(s))
        for cl in split_clauses(s):
            print(f"   分句 {cl!r} -> 时长 {find_durations(cl)} 日期 {find_date_time(cl)}")
        print()

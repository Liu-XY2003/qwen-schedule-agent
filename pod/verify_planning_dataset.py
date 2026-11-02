#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验规划数据集: **标签里的每个字段都必须能从输入文本推断出来**。

反向构造的整个价值建立在"标签一定对"之上。如果模板渲染漏说了什么、而标签却断言了，
模型学到的是瞎猜 —— 这种错误在训练 loss 上完全看不出来（loss 会很漂亮），
只有在真实评测时才会暴露。所以必须有一条独立于生成器的检查。

检查项（对每条 ok 样本）:
    duration_min   文本里出现了中文时长表达, 或标题属于有公认默认值的类型
    deadline_date  文本里逐字出现该日期说法
    deadline_time  文本里出现该时刻
    priority       high/low 时文本里出现对应措辞; normal 时不应出现强措辞
    preferred      !=none 时文本里出现该时段词
    keep_free      day+slot 的"周三上午"这类组合出现在文本里

用法:
    python verify_planning_dataset.py /path/to/train.jsonl
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

# 与生成器保持一致的表
DUR_PAT = {
    20: ["20 分钟", "二十分钟"], 30: ["半小时", "30 分钟", "半个小时"],
    40: ["40 分钟", "四十分钟"], 45: ["45 分钟", "四十五分钟"],
    60: ["一小时", "1 小时", "一个小时"], 90: ["一个半小时", "1.5 小时"],
    120: ["两小时", "2 小时", "两个小时"], 150: ["两个半小时", "2.5 小时"],
    180: ["三小时", "3 小时", "三个小时"], 240: ["四小时", "4 小时", "四个小时"],
    300: ["五小时", "5 小时", "五个小时"],
}
# 标题 -> 默认时长（生成器里 KINDS 的默认值）
from gen_planning_dataset import KINDS  # noqa: E402

TITLE_DEFAULT = {}
for _k, (_titles, _d, _s) in KINDS.items():
    for _t in _titles:
        TITLE_DEFAULT[_t] = _d

WD_CN = {"MO": "一", "TU": "二", "WE": "三", "TH": "四", "FR": "五", "SA": "六", "SU": "日"}
SLOT_CN = {"morning": "上午", "afternoon": "下午", "evening": "晚上"}
SLOT_RANGE = {"morning": ("08:00", "12:00"), "afternoon": ("13:30", "18:00"),
              "evening": ("19:00", "22:00")}

HIGH_WORDS = ["必须", "一定要", "最要紧", "优先", "务必", "要紧"]
LOW_WORDS = ["有空", "有时间", "随缘", "顺便", "不急"]
PREF_WORDS = {"am": ["上午"], "pm": ["下午"], "eve": ["晚上"]}
PREF_TO_SLOT = {"am": "morning", "pm": "afternoon", "eve": "evening"}


CLAUSE_SPLIT = re.compile(r"[\n；;。]|。另外，?|，然后|\)\s*\d*\)|^\s*\d+[\)）]", re.M)


def split_clauses(text: str) -> list[str]:
    """把一段文本切成"分句"。生成器是一事一句的, 所以按分句检查才准确。"""
    parts = [p.strip(" ，,：:。") for p in CLAUSE_SPLIT.split(text)]
    return [p for p in parts if p]


def clause_of(title: str, clauses: list[str]) -> str | None:
    """找到包含该标题的那个分句。找不到或命中多个分句时返回 None（退回全文检查）。"""
    hits = [c for c in clauses if title in c]
    return hits[0] if len(hits) == 1 else None


def check_one(text: str, env: dict) -> list[str]:
    """返回该样本的问题列表（空 = 通过）。

    ★ 必须按分句检查, 不能全文检查。
      否则一条文本里别的待办出现的"必须""两小时"会给被改坏的那条打掩护,
      校验器就会漏报 —— 自测里漏掉 1/6 到 1/2 就是这么来的。
    """
    errs = []
    if env.get("status") != "ok":
        return errs
    clauses = split_clauses(text)

    for i, it in enumerate(env.get("items") or []):
        title = it.get("title") or ""
        tag = f"items[{i}]{title}"
        scope = clause_of(title, clauses) or text

        d = it.get("duration_min")
        phrases = DUR_PAT.get(d, [])
        default = TITLE_DEFAULT.get(title)
        if not (any(p in scope for p in phrases) or default == d):
            errs.append(f"{tag} 时长 {d} 无法从其所在分句推断")

        dld = it.get("deadline_date")
        if dld and dld not in scope:
            errs.append(f"{tag} 截止说法 {dld!r} 未出现在分句里")

        dlt = it.get("deadline_time")
        if dlt and dlt not in scope:
            errs.append(f"{tag} 截止时刻 {dlt} 未出现在分句里")

        pr = it.get("priority")
        if pr == "high" and not any(w in scope for w in HIGH_WORDS):
            errs.append(f"{tag} 优先级 high 但分句里没有强措辞")
        if pr == "low" and not any(w in scope for w in LOW_WORDS):
            errs.append(f"{tag} 优先级 low 但分句里没有弱措辞")

        pf = it.get("preferred")
        if pf and pf != "none":
            if not any(w in scope for w in PREF_WORDS.get(pf, [])):
                errs.append(f"{tag} 时段偏好 {pf} 但分句里没提到")

    for j, c in enumerate(env.get("constraints") or []):
        day = c.get("day")
        rng_ = (c.get("start"), c.get("end"))
        slot = next((k for k, v in SLOT_RANGE.items() if v == rng_), None)
        if day not in WD_CN or slot is None:
            errs.append(f"constraints[{j}] day/时间段不合法: {day} {rng_}")
            continue
        combo = f"周{WD_CN[day]}{SLOT_CN[slot]}"
        # 约束也按分句定位, 避免被别处的同类组合掩护
        hits = [cl for cl in clauses if combo in cl]
        scope = hits[0] if len(hits) == 1 else text
        if combo not in scope:
            errs.append(f"constraints[{j}] {combo} 未出现在文本里")
            continue

        w = c.get("weight")
        if w == "hard" and not any(x in scope for x in ["别", "绝对", "不要"]):
            errs.append(f"constraints[{j}] weight=hard 但分句里没有强硬措辞")
        if w == "soft" and not any(x in scope for x in ["尽量", "最好", "能不"]):
            errs.append(f"constraints[{j}] weight=soft 但分句里没有缓和措辞")
    return errs


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "train.jsonl"
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    bad = 0
    by_kind = Counter()
    examples: dict[str, list[str]] = {}

    for r in rows:
        text = r["messages"][1]["content"]
        env = json.loads(r["messages"][2]["content"])
        errs = check_one(text, env)
        if errs:
            bad += 1
            for e in errs:
                key = e.split(" ")[1] if " " in e else e
                by_kind[key] += 1
                examples.setdefault(key, []).append(f"{text[:70]} || {e}")

    print(f"{path}: {len(rows)} 条")
    if not bad:
        print("全部通过 —— 标签与文本一致")
        return 0

    pct = bad * 100 / len(rows)
    print(f"不合格 {bad} 条 ({pct:.1f}%)")
    for k, n in by_kind.most_common():
        print(f"\n[{k}] {n} 处")
        for ex in examples[k][:2]:
            print("   ", ex)
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在**留出测试集**上评估抽取准确率（带置信区间）。

为什么不用那 21 条手写用例做结论:
    21 条里差 1 条就是 5 个百分点, 95% 置信区间大约 ±11 个百分点 ——
    52% 和 47% 在统计上完全分不开。拿它做"few-shot 变多了是好是坏"的判断是错的。

这个脚本用 gen_planning_dataset.py 生成的 test.jsonl（默认 344 条, 与训练集无重叠）,
跑 N 条, 按字段算准确率并给出 Wilson 95% 置信区间。

指标:
    status       ok / clarify / reject 判对的比例
    item F1      抽出的待办与真值的匹配程度（标题按子串匹配）
    duration     匹配上的待办里, 时长落在 ±50% 或 ±15 分钟内的比例
    deadline     真值有截止的待办里, 预测也给了截止且日期一致的比例
    keep_free    约束集合完全一致的比例
    sample       整条完全正确的比例（所有字段都对）

用法:
    python eval_on_dataset.py --port 18999 --n 100 --fewshot rich
    python eval_on_dataset.py --port 18999 --n 100 --zero-shot
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import planning  # noqa: E402

# 与 pod/verify_planning_dataset.py 一致的中文时长 -> 分钟
CN_DUR = {
    "20 分钟": 20, "二十分钟": 20, "半小时": 30, "30 分钟": 30, "半个小时": 30,
    "40 分钟": 40, "四十分钟": 40, "45 分钟": 45, "四十五分钟": 45,
    "一小时": 60, "1 小时": 60, "一个小时": 60,
    "一个半小时": 90, "1.5 小时": 90,
    "两小时": 120, "2 小时": 120, "两个小时": 120,
    "两个半小时": 150, "2.5 小时": 150,
    "三小时": 180, "3 小时": 180, "三个小时": 180,
    "四小时": 240, "4 小时": 240, "四个小时": 240,
    "五小时": 300, "5 小时": 300, "五个小时": 300,
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 置信区间 —— 小样本下比正态近似可靠得多。"""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def match_items(pred, gold):
    """按标题子串匹配。返回 [(pred_idx, gold_idx)]。"""
    pairs, used = [], set()
    for gi, g in enumerate(gold):
        gt = norm(g.get("title"))
        if not gt:
            continue
        for pi, p in enumerate(pred):
            if pi in used:
                continue
            pt = norm(p.get("title"))
            if gt in pt or pt in gt:
                pairs.append((pi, gi))
                used.add(pi)
                break
    return pairs


def dur_ok(pred_d, gold_d) -> bool:
    if not isinstance(pred_d, int) or not isinstance(gold_d, int):
        return False
    return abs(pred_d - gold_d) <= max(15, gold_d * 0.5)


def deadline_eq(a, b) -> bool:
    """日期表达不一定逐字相同（"周五" vs "FR" 都对），所以解析成绝对日期再比。"""
    from datetime import date
    today = date.today()
    da, db = planning.resolve_deadline(a, today), planning.resolve_deadline(b, today)
    if da is None and db is None:
        return norm(a) == norm(b)
    return da == db


def eval_one(text, gold, fewshot, use_rules=True):
    try:
        return planning.extract(text, fewshot=fewshot, use_rules=use_rules)
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="test.jsonl 路径")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--label", default="")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--fewshot", dest="fewshot", action="store_const", const="lite")
    g.add_argument("--fewshot-rich", dest="fewshot", action="store_const", const="rich")
    g.add_argument("--zero-shot", dest="fewshot", action="store_const", const=False)
    ap.add_argument("--no-rules", dest="use_rules", action="store_false", default=True,
                    help="关闭确定性规则层, 只测模型本身")
    ap.set_defaults(fewshot="rich")
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.data, encoding="utf-8")]
    rng = random.Random(a.seed)
    if a.n and a.n < len(rows):
        rows = rng.sample(rows, a.n)

    planning.set_llama_url(f"http://127.0.0.1:{a.port}")

    mode = {False: "零样本", "lite": "few-shot×2", "rich": "few-shot×5"}[a.fewshot]
    print(f"\n{'='*76}")
    rules_txt = "规则层开" if a.use_rules else "规则层关"
    print(f"数据集评估: {a.label or a.data}  [{mode} / {rules_txt}]  {len(rows)} 条")
    print(f"{'='*76}")

    n = ok_status = ok_sample = 0
    item_f1s, dur_hits, dur_tot = [], 0, 0
    dl_hits, dl_tot = 0, 0
    kf_hits, kf_tot = 0, 0
    t0 = time.time()

    for i, r in enumerate(rows, 1):
        text = r["messages"][1]["content"]
        gold = json.loads(r["messages"][2]["content"])
        pred = eval_one(text, gold, a.fewshot, a.use_rules)
        n += 1
        if pred is None:
            continue

        st_ok = pred.get("status") == gold.get("status")
        ok_status += st_ok

        if gold.get("status") != "ok":
            ok_sample += st_ok
            continue

        gp, gd = gold.get("items") or [], pred.get("items") or []
        pairs = match_items(gd, gp)
        tp = len(pairs)
        rec = tp / len(gp) if gp else 1.0
        prec = tp / len(gd) if gd else 1.0
        f1 = 0.0 if (rec + prec) == 0 else 2 * rec * prec / (rec + prec)
        item_f1s.append(f1)

        d_ok_all = True
        for pi, gi in pairs:
            if not dur_ok(gd[pi].get("duration_min"), gp[gi].get("duration_min")):
                d_ok_all = False
            if gp[gi].get("duration_min") is not None:
                dur_tot += 1
                dur_hits += dur_ok(gd[pi].get("duration_min"), gp[gi].get("duration_min"))
            if gp[gi].get("deadline_date"):
                dl_tot += 1
                dl_hits += deadline_eq(gd[pi].get("deadline_date"),
                                       gp[gi].get("deadline_date"))

        gkf = {(c.get("day"), c.get("start"), c.get("end"))
               for c in (gold.get("constraints") or [])}
        pkf = {(c.get("day"), c.get("start"), c.get("end"))
               for c in (pred.get("constraints") or [])}
        kf_ok = gkf == pkf
        if gkf:
            kf_tot += 1
            kf_hits += kf_ok

        if st_ok and f1 == 1.0 and d_ok_all and kf_ok and dl_hits == dl_tot:
            ok_sample += 1

        if i % 25 == 0:
            print(f"  ...{i}/{len(rows)}  ({(time.time()-t0)/i:.2f}s/条)")

    def pct(k, m):
        if m == 0:
            return "n/a"
        lo, hi = wilson(k, m)
        return f"{k/m*100:5.1f}%  [{lo*100:.0f}-{hi*100:.0f}]"

    print(f"\n{'指标':<14}{'结果':<26}样本数")
    print("-" * 76)
    print(f"{'status 判对':<14}{pct(ok_status, n):<26}{n}")
    print(f"{'sample 全对':<14}{pct(ok_sample, n):<26}{n}")
    print(f"{'item 平均F1':<14}{sum(item_f1s)/len(item_f1s) if item_f1s else 0:>15.3f}")
    print(f"{'duration 准':<14}{pct(dur_hits, dur_tot):<26}{dur_tot}")
    print(f"{'deadline 准':<14}{pct(dl_hits, dl_tot):<26}{dl_tot}")
    print(f"{'keep_free 准':<14}{pct(kf_hits, kf_tot):<26}{kf_tot}")
    print(f"\n耗时 {time.time()-t0:.0f}s")
    print(f"{'='*76}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

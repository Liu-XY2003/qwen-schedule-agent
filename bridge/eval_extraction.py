#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽取能力评估: 杂乱文本 → 待办 + 约束, 准不准?

这是二阶段**最关键的可行性验证**。求解器那一半已经证明可行; 剩下唯一的未知数
就是"能不能从人话里把待办和约束抽对"。如果这一环不达标, 二阶段的产品链路就
不成立 —— 所以要在投入大量开发之前先量出来。

评估口径（都算 per-case 通过/失败, 便于定位）:
    status          状态对不对（ok / clarify / reject）
    recall          期望的待办有没有都抽出来（按关键词匹配）
    precision       抽出来的待办里有没有多余的
    duration        时长是否在容差内（±50% 或 ±15 分钟, 取宽）
    deadline        期望有截止的, 是否抽到了日期
    constraint      keep_free 约束是否抽对（星期 + 时段）

用法:
    # 先起两个模型（都要 --reasoning off）
    llama-server -m Qwen3-1.7B-Q4_K_M.gguf -ngl 99 -c 4096 --port 18999 --jinja -np 1 --reasoning off
    llama-server -m Qwen3-4B-Q4_K_M.gguf   -ngl 99 -c 4096 --port 18998 --jinja -np 1 --reasoning off

    .venv-planner\\Scripts\\python.exe bridge\\eval_extraction.py --port 18999 --label 1.7B
    .venv-planner\\Scripts\\python.exe bridge\\eval_extraction.py --port 18998 --label 4B
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import planning  # noqa: E402

# ---------------------------------------------------------------- 用例
# 期望:
#   status: ok / clarify / reject
#   items:  [(关键词, 期望时长, 是否有截止)]   关键词只需出现在 title 里
#   keep_free: [(星期, 起, 止)] 或 []
CASES = [
    # ---- 纯待办列表 ----
    dict(text="这周要做三件事：写完操作系统实验报告，大概要四个小时；读两篇论文，每篇一小时；再写个周报，半小时。",
         status="ok",
         items=[("实验报告", 240, False), ("论文", 60, False), ("周报", 30, False)],
         keep_free=[]),

    dict(text="帮我把这些排一下：交高数作业、复习线代、买下周的菜。前两个各一小时，买菜半小时。",
         status="ok",
         items=[("高数", 60, False), ("线代", 60, False), ("买菜", 30, False)],
         keep_free=[]),

    # ---- 带截止 ----
    dict(text="操作系统实验报告周五 23:59 前交，得留出 4 小时写。另外周三下午两点要去开组会。",
         status="ok",
         items=[("实验报告", 240, True), ("组会", None, False)],
         keep_free=[]),

    dict(text="下周三上午九点有高数考试，提前两天开始复习，每天两小时。",
         status="ok",
         items=[("复习", 120, False)],
         keep_free=[]),

    dict(text="明天中午前把报销单交给财务，大概花 20 分钟。",
         status="ok",
         items=[("报销", 20, True)],
         keep_free=[]),

    # ---- 带约束 ----
    dict(text="周三上午别给我排任何东西，那天要去医院。其他时间随便，把实验报告写完就行，四小时。",
         status="ok",
         items=[("实验报告", 240, False)],
         keep_free=[("WE", "08:00", "12:00")]),

    dict(text="周五晚上绝对不要排事，我要休息。白天可以把论文看了，两小时。",
         status="ok",
         items=[("论文", 120, False)],
         keep_free=[("FR", "19:00", "22:00")]),

    dict(text="尽量别在周日下午安排任务吧。上午可以，写代码两小时。",
         status="ok",
         items=[("代码", 120, False)],
         keep_free=[("SU", "14:00", "21:00")]),

    # ---- 聊天记录形态 ----
    dict(text="""群里的消息摘一下：
小王：周五之前把设计文档发我
我：好的，大概需要三小时
小王：另外周一上午十点开个会，一小时
我：收到""",
         status="ok",
         items=[("设计文档", 180, True), ("会", 60, False)],
         keep_free=[]),

    dict(text="""邮件：
主题：下周安排
1) 周三前完成竞品分析（约 2 小时）
2) 周四 15:00 参加评审会（1 小时）
3) 有空整理一下会议记录（约 30 分钟）""",
         status="ok",
         items=[("竞品分析", 120, True), ("评审", 60, False), ("记录", 30, False)],
         keep_free=[]),

    # ---- 优先级判断 ----
    dict(text="必须先把论文改完投出去，这个最重要，留三小时。有时间的话整理一下桌面。",
         status="ok",
         items=[("论文", 180, True), ("桌面", 30, False)],
         keep_free=[]),

    dict(text="这周要紧的是把开题报告写完，至少五小时。健身什么的随缘，一小时就行。",
         status="ok",
         items=[("开题报告", 300, False), ("健身", 60, False)],
         keep_free=[]),

    # ---- 应 reject ----
    dict(text="今天天气真好，下午三点的太阳晒得人想睡觉。",
         status="reject", items=[], keep_free=[]),

    dict(text="谢谢，辛苦了，回头请你吃饭。",
         status="reject", items=[], keep_free=[]),

    dict(text="刚才那个会开得挺顺利的，大家都挺满意。",
         status="reject", items=[], keep_free=[]),

    # ---- 应 clarify ----
    dict(text="帮我安排一下这周的事情。",
         status="clarify", items=[], keep_free=[]),

    dict(text="有些事情要做，你看着办吧。",
         status="clarify", items=[], keep_free=[]),

    # ---- 口语化 / 缩略 ----
    dict(text="明早八点得去趟实验室，大概一小时。晚上想跑步，四十分钟。",
         status="ok",
         items=[("实验", 60, False), ("跑步", 40, False)],
         keep_free=[]),

    dict(text="这两天得把简历改一改，两小时吧。顺便看看有没有合适的岗位，一小时。",
         status="ok",
         items=[("简历", 120, False), ("岗位", 60, False)],
         keep_free=[]),

    # ---- 混合：多条 + 截止 + 约束 ----
    dict(text="""这周有点乱：
· 周三上午别排东西（要陪家人）
· 周五 18:00 前交实习周报，约 40 分钟
· 准备下周二的组会汇报，至少两小时
· 有空把借的书还了，半小时""",
         status="ok",
         items=[("周报", 40, True), ("汇报", 120, False), ("书", 30, False)],
         keep_free=[("WE", "08:00", "12:00")]),

    dict(text="周一至周五早上七点到八点我要背单词，别排其他事。白天把两篇课程论文各写三小时。",
         status="ok",
         items=[("论文", 180, False)],
         keep_free=[]),   # 每天早上的约束，v1 契约表达不了多个 day，先只测 items
]


# ---------------------------------------------------------------- 打分
def norm(s: str) -> str:
    return str(s or "").strip().lower()


def match_items(extracted, expected):
    """按关键词匹配。返回 (recall, precision, 时长对的数量)。"""
    used = set()
    hit = 0
    dur_ok = 0
    for kw, want_dur, _ in expected:
        for i, it in enumerate(extracted):
            if i in used:
                continue
            if kw in norm(it.get("title")):
                used.add(i)
                hit += 1
                if want_dur:
                    got = it.get("duration_min")
                    tol = max(15, want_dur * 0.5)
                    if isinstance(got, int) and abs(got - want_dur) <= tol:
                        dur_ok += 1
                break
    recall = hit / len(expected) if expected else 1.0
    precision = len(used) / len(extracted) if extracted else (1.0 if not expected else 0.0)
    return recall, precision, dur_ok


def check_deadlines(extracted, expected):
    """期望有截止的项, 是否抽到了 deadline_date。"""
    need = 0
    got = 0
    for kw, _, want_dl in expected:
        if not want_dl:
            continue
        need += 1
        for it in extracted:
            if kw in norm(it.get("title")) and it.get("deadline_date"):
                got += 1
                break
    return need, got


def check_keep_free(env, expected_kf):
    got = [(c.get("day"), c.get("start"), c.get("end"))
           for c in (env.get("constraints") or []) if c.get("kind") == "keep_free"]
    if not expected_kf:
        return 1.0, got
    hit = 0
    for want in expected_kf:
        for g in got:
            if g[0] == want[0] and g[1] == want[1] and g[2] == want[2]:
                hit += 1
                break
    return hit / len(expected_kf), got


def run_case(case, llama_url, fewshot: bool = True):
    try:
        env = planning.extract(case["text"], llama_url=llama_url, fewshot=fewshot)
    except Exception as e:
        return False, f"抽取失败: {str(e)[:90]}", {}

    reasons = []
    status_ok = env.get("status") == case["status"]
    if not status_ok:
        reasons.append(f"status {env.get('status')}≠{case['status']}")

    if case["status"] == "ok":
        ext = env.get("items") or []
        r, p, dok = match_items(ext, case["items"])
        need_dl, got_dl = check_deadlines(ext, case["items"])
        kf, kf_got = check_keep_free(env, case["keep_free"])
        if r < 1.0:
            reasons.append(f"recall {r:.2f}")
        if p < 1.0:
            reasons.append(f"precision {p:.2f}（多抽: {[i.get('title') for i in ext]}）")
        want_dur = sum(1 for _, d, _ in case["items"] if d)
        if dok < want_dur:
            reasons.append(f"时长 {dok}/{want_dur}")
        if need_dl and got_dl < need_dl:
            reasons.append(f"截止 {got_dl}/{need_dl}")
        if kf < 1.0:
            reasons.append(f"keep_free {kf:.2f}（抽到 {kf_got}）")
    return (not reasons), "; ".join(reasons), env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--limit", type=int, default=0)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--fewshot", dest="fewshot", action="store_const", const="lite",
                   help="两个示例")
    g.add_argument("--fewshot-rich", dest="fewshot", action="store_const", const="rich",
                   help="五个示例, 覆盖已知失败模式（推荐）")
    g.add_argument("--zero-shot", dest="fewshot", action="store_const", const=False,
                   help="不带示例, 测基座模型零样本能力")
    ap.set_defaults(fewshot="rich")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}"

    cases = CASES[: args.limit] if args.limit else CASES
    passed = 0
    mode = {False: "零样本", "lite": "few-shot×2", "rich": "few-shot×5"}[args.fewshot]
    print(f"\n{'='*84}\n抽取评估: {args.label} [{mode}]  ({len(cases)} 条)\n{'='*84}")
    for i, c in enumerate(cases, 1):
        ok, why, _ = run_case(c, url, fewshot=args.fewshot)
        passed += ok
        head = c["text"].replace("\n", " ")[:44]
        print(f"{'OK  ' if ok else 'FAIL'} [{i:02d}] {head}")
        if not ok:
            print(f"        {why}")
    pct = passed * 100 // max(len(cases), 1)
    print(f"\n{'='*84}\n{args.label} [{mode}]: {passed}/{len(cases)} = {pct}%\n{'='*84}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())

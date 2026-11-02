#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二阶段「规划抽取」训练集生成器（反向构造法）。

## 为什么用反向构造
正向做法是"先有文本，再人工标约束"，成本高且容易标错。反向构造是：
    先采样**结构化的真值**（几件事、各自多久、什么截止、什么限制）
    → 再用模板渲染成自然中文
    → 标签直接从真值生成
**标签由构造保证 100% 正确**，不需要人工标注，也不会出现"模型对了但标签错了"。
一阶段的 4000 条数据集就是这么来的（4372/4372 合规、failed=0）。

## 保证标签正确的三条硬规则
1. **时长必须可推断**：要么文本里明说了（"大概四小时"），要么标题属于有公认默认值的
   类型（"交作业"≈60分钟）。绝不出现"标签说是 120，但文本里没有任何依据"。
2. **截止必须是文本里出现过的说法**：标签存的是用户原话（"周五"/"11-07"/"明天"），
   不是绝对日期。模型永远不需要做日期运算。
3. **约束必须明说过**：keep_free 一定来自"别给我排东西"这类句子，不脑补。

## 用法
    python gen_planning_dataset.py --train 4000 --test 400 --outdir ./data
"""
from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter

# ---------------------------------------------------------------- 任务类型表
# (标题候选, 默认时长分钟, 是否可拆分)
# ★ 默认时长是"文本里不说时长时"的唯一合法取值 —— 训练时模型靠标题学这个映射。
KINDS = {
    "report":  (["实验报告", "课程设计报告", "论文初稿", "读书报告", "大作业",
                 "技术方案", "开题报告", "竞品分析"], 120, True),
    "read":    (["论文", "教材第三章", "技术文章", "课程资料", "参考文献"], 45, True),
    "admin":   (["周报", "报销单", "简历", "会议记录", "申请材料", "实习周报"], 30, True),
    "study":   (["复习高数", "复习线代", "背单词", "刷题", "整理笔记", "复习概率论"], 60, True),
    "meeting": (["组会", "项目例会", "班会", "评审会", "答辩", "面试", "需求评审"], 60, False),
    "class":   (["高等数学", "计算机原理", "操作系统", "数据结构", "计算机网络"], 90, False),
    "health":  (["健身", "跑步", "游泳", "打球", "散步"], 60, False),
    "chore":   (["买菜", "做饭", "打扫卫生", "取快递", "还书", "交电费"], 30, False),
    "coding":  (["写代码", "调 bug", "跑实验", "改稿", "复现实验"], 90, True),
}

# 能在中文里干净表达的时长
DURATIONS = [20, 30, 40, 45, 60, 90, 120, 150, 180, 240, 300]

DUR_CN = {
    20: ["20 分钟", "二十分钟"],
    30: ["半小时", "30 分钟", "半个小时"],
    40: ["40 分钟", "四十分钟"],
    45: ["45 分钟", "四十五分钟"],
    60: ["一小时", "1 小时", "一个小时"],
    90: ["一个半小时", "1.5 小时"],
    120: ["两小时", "2 小时", "两个小时"],
    150: ["两个半小时", "2.5 小时"],
    180: ["三小时", "3 小时", "三个小时"],
    240: ["四小时", "4 小时", "四个小时"],
    300: ["五小时", "5 小时", "五个小时"],
}

WD = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

# 启动期自检: 每个"默认时长"都必须能用中文干净地表达出来,
# 否则渲染时会 KeyError（这个坑真的踩过: class 默认写了 100 分钟）。
for _k, (_t, _d, _s) in KINDS.items():
    assert _d in DUR_CN, f"{_k} 的默认时长 {_d} 不在 DUR_CN 里"
assert set(DURATIONS) <= set(DUR_CN), "DURATIONS 里有无法表达的时长"
WD_CN = {"MO": "一", "TU": "二", "WE": "三", "TH": "四", "FR": "五", "SA": "六", "SU": "日"}
WD_PREFIX = {0: ["", "", "这", "本"], 1: ["下", "下个"], 2: ["下下", "下下个"], -1: ["上"]}

# 时段 -> keep_free 的窗口（与 planner.DEFAULT_WINDOWS 对齐）
SLOTS = {
    "morning": ("am", "08:00", "12:00", "上午"),
    "afternoon": ("pm", "13:30", "18:00", "下午"),
    "evening": ("eve", "19:00", "22:00", "晚上"),
}

QUESTIONS = [
    "你想安排哪几件事？每件大概需要多久？",
    "具体要做哪些事？大概各需要多长时间？",
    "这几件事分别是什么？大概各要多久？",
    "你手头有哪些事要安排？各需要多长时间？",
]

# ★ reject / clarify 必须**组合生成**。
#   如果只写死十几个例句, 去重后训练集里这两类就只有十几条, 模型学不会"什么时候该拒答"。
#   一阶段的做法也是组合(REJECTS 14 条 + 多种句式), 这里扩到能覆盖大部分闲聊场景。
_REJ_SCENE = [
    "今天天气真好", "外面下雨了", "今天地铁好挤", "食堂新出的菜还不错",
    "楼下新开了家咖啡店", "昨晚睡得不太好", "这个周末过得真快",
    "刚才路过操场看到有人在打球", "最近有点累", "今天风好大",
    "手机快没电了", "快递到了", "刚吃完饭", "窗外的树都黄了",
    "会议室的空调有点冷", "早上起晚了", "公交等了二十分钟",
]
_REJ_COMMENT = [
    "，晒得人想睡觉。", "，还好没迟到。", "，有点想回家了。",
    "，感觉一天又过去了。", "，不过心情还行。", "，希望明天好一点。",
    "，懒得动了。", "，还挺舒服的。", "，就是有点吵。",
]
_REJ_SOCIAL = [
    "谢谢，辛苦了，回头请你吃饭。", "早上好呀。", "好的收到，谢谢！",
    "哈哈哈这个太真实了。", "晚点聊，我先忙。", "你说得对。",
    "周末愉快！", "加油！", "我先撤了，拜拜。", "嗯嗯好的。",
]
_REJ_QUESTION = [
    "今天天气怎么样？", "明天会下雨吗？", "你叫什么名字？",
    "讲个笑话呗。", "1+1 等于几？", "北京到上海多远？",
    "推荐几部好看的电影。", "介绍一下量子计算。", "这道微积分怎么算？",
    "股市今天涨了吗？", "什么是区块链？", "帮我把这句话翻译成英文。",
]

# clarify: 用户想让人安排, 但没给出任何可排的信息
_CLR_LEAD = [
    "帮我安排一下", "帮我规划一下", "帮我排一排", "帮我理一理",
    "帮我看看怎么弄", "帮我整理一下", "帮我做个计划",
]
_CLR_OBJ = [
    "这周的事情", "最近的事情", "手头的事", "接下来要做的事",
    "这段时间的安排", "这周的活", "下周的打算", "",
]
_CLR_TAIL = [
    "。", "吧。", "，你看着办。", "，我有点乱。", "，谢谢。",
]

REJECTS = ["今天天气真好，下午的太阳晒得人想睡觉。"]
CLARIFIES = ["帮我安排一下这周的事情。"]


def make_reject(rng):
    r = rng.random()
    if r < 0.42:
        return rng.choice(_REJ_SCENE) + rng.choice(_REJ_COMMENT)
    if r < 0.74:
        return rng.choice(_REJ_SOCIAL)
    return rng.choice(_REJ_QUESTION)


def make_clarify(rng):
    return rng.choice(_CLR_LEAD) + rng.choice(_CLR_OBJ) + rng.choice(_CLR_TAIL)


def _unused():
    pass

CLAUSE_JOIN = ["；", "。另外，", "，然后", "；还有，", "。还有，"]


# ---------------------------------------------------------------- 真值结构
class Item:
    __slots__ = ("title", "dur", "explicit", "deadline", "deadline_time",
                 "priority", "splittable", "preferred", "kind")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


class Constraint:
    __slots__ = ("day", "slot", "hard", "weight_word")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def sample_item(rng, *, allow_default_dur=True):
    kind = rng.choice(list(KINDS))
    titles, default_dur, splittable = KINDS[kind]
    title = rng.choice(titles)

    # 时长: 70% 明说, 30% 靠标题默认值（这部分样本什么都不说）
    if allow_default_dur and rng.random() < 0.30:
        dur, explicit = default_dur, False
    else:
        dur, explicit = rng.choice(DURATIONS), True

    # 截止: 45% 有
    deadline = deadline_time = None
    if rng.random() < 0.45:
        deadline = sample_deadline_expr(rng)
        if rng.random() < 0.45:
            deadline_time = rng.choice(["23:59", "18:00", "12:00", "09:00"])

    # 优先级: 由措辞决定, 这里先定值, 渲染时配对应措辞
    priority = rng.choices(["high", "normal", "low"], [0.28, 0.52, 0.20])[0]

    preferred = "none"
    if rng.random() < 0.22:
        preferred = rng.choice(["am", "pm", "eve"])

    return Item(title=title, dur=dur, explicit=explicit, deadline=deadline,
                deadline_time=deadline_time, priority=priority,
                splittable=splittable, preferred=preferred, kind=kind)


def sample_deadline_expr(rng):
    """生成一个**用户本来说法**形式的截止表达（标签原样存它）。"""
    r = rng.random()
    if r < 0.42:
        d = rng.choice(WD)
        off = rng.choices([0, 1, 2], [0.6, 0.3, 0.1])[0]
        return f"{rng.choice(WD_PREFIX[off])}周{WD_CN[d]}"
    if r < 0.55:
        return rng.choice(["明天", "后天", "今天"])
    if r < 0.80:
        m = rng.randint(1, 12)
        d = rng.randint(1, 28)
        return f"{m:02d}-{d:02d}"
    m = rng.randint(1, 12)
    d = rng.randint(1, 28)
    return rng.choice([f"{m}月{d}日", f"{m}月{d}号"])


def sample_constraint(rng):
    day = rng.choice(WD)
    slot = rng.choice(["morning", "afternoon", "evening"])
    hard = rng.random() < 0.65
    return Constraint(day=day, slot=slot, hard=hard)


# ---------------------------------------------------------------- 渲染
def render_deadline(it):
    if not it.deadline:
        return ""
    if it.deadline_time:
        # 只给"日期 时刻", 后面由调用方补"之前弄完/截止"等后缀,
        # 否则会拼出"09:00 前之前弄完"这种重复。
        return f"{it.deadline} {it.deadline_time}"
    return it.deadline


def render_item(it, rng, style):
    """把一个 Item 渲染成一个自然句子。

    ★ 关键约束: 标签里的每个字段都必须能从这句话推断出来。
      所以 priority / preferred **无条件渲染**（不是只在某种风格里渲染）,
      否则模型看到的是"没说优先级", 标签却是 high —— 这是在教它瞎猜。
    """
    title, dur_cn = it.title, rng.choice(DUR_CN[it.dur])

    # 优先级措辞（normal 用"不说"来表达, 空串本身也是可推断的）
    if it.priority == "high":
        lead = rng.choice(["必须", "一定要", "最要紧的是", "优先", "务必"])
    elif it.priority == "low":
        lead = rng.choice(["有空的话", "有时间", "随缘", "顺便", "不急，"])
    else:
        lead = ""

    # 时段偏好（none 用"不说"表达）
    pref = ""
    if it.preferred != "none":
        slot_cn = {"am": "上午", "pm": "下午", "eve": "晚上"}[it.preferred]
        pref = rng.choice([f"最好在{slot_cn}", f"{slot_cn}做", f"安排在{slot_cn}"])

    dl = render_deadline(it)
    dl_tail = rng.choice([f"{dl}之前弄完", f"截止{dl}", f"{dl}要交"]) if dl else ""

    if style == "list":
        # 列表风格: 时长放在括号里, 更贴近真实的待办清单
        core = title + (f"（{dur_cn}）" if it.explicit else "")
        tail = "，".join(x for x in (pref, dl_tail) if x)
        return lead + core + ("，" + tail if tail else "")

    # 聊天 / 邮件 / 流水账: 同一套语义, 用"，"连成一句话。
    # ★ 必须用分隔符连接 —— 直接 "".join 会拼出
    #   "整理笔记晚上做01-08 09:00 之前弄完" 这种没有边界的句子。
    parts = [lead + title] if (lead or title) else []
    if it.explicit:
        parts.append(rng.choice([f"大概{dur_cn}", f"要{dur_cn}", f"{dur_cn}左右"]))
    if pref:
        parts.append(pref)
    if dl_tail:
        parts.append(dl_tail)
    return "，".join(parts)


def render_constraint(c, rng):
    _, _, _, slot_cn = ("", "", "", "")
    slot_cn = SLOTS[c.slot][3]
    day = f"周{WD_CN[c.day]}"
    if c.hard:
        body = rng.choice([f"{day}{slot_cn}别给我排东西",
                           f"{day}{slot_cn}绝对不要排事",
                           f"{day}{slot_cn}别安排任何事"])
    else:
        body = rng.choice([f"{day}{slot_cn}尽量别排",
                           f"{day}{slot_cn}最好空着",
                           f"{day}{slot_cn}能不排就不排"])
    return body


def render_text(items, cons, style, rng):
    """把真值渲染成一段自然中文。"""
    order = list(range(len(items)))
    rng.shuffle(order)

    clauses = []
    # 约束穿插在任意位置
    con_positions = sorted(rng.sample(range(len(items) + 1), min(len(cons), len(items) + 1)))
    ci = 0
    for pos in range(len(items) + 1):
        if ci < len(cons) and pos in con_positions:
            clauses.append(render_constraint(cons[ci], rng))
            ci += 1
        if pos < len(items):
            clauses.append(render_item(items[order[pos]], rng, style))

    if style == "list":
        head = rng.choice(["这周要做这几件事：", "待办：", "这周安排：", "帮我排一下这些："])
        return head + "；".join(clauses) + "。"
    if style == "chat":
        lines = []
        for cl in clauses:
            who = rng.choice(["小王：", "我：", "组长：", "同事："])
            lines.append(who + cl)
        return "\n".join(lines)
    if style == "email":
        subj = rng.choice(["下周安排", "本周待办", "接下来要做的事"])
        lines = [f"主题：{subj}"]
        for i, cl in enumerate(clauses, 1):
            lines.append(f"{i}) {cl}")
        return "\n".join(lines)
    # rambling
    lead = rng.choice(["这周有点乱，", "最近事情有点多，", "帮我理一下：", ""])
    return lead + rng.choice(CLAUSE_JOIN).join(clauses) + "。"


# ---------------------------------------------------------------- 标签
ITEM_ORDER = ["title", "duration_min", "deadline_date", "deadline_time",
              "priority", "splittable", "preferred"]
CON_ORDER = ["kind", "weight", "day", "start", "end"]


def make_envelope(items, cons):
    out_items = []
    for it in items:
        d = {"title": it.title, "duration_min": it.dur}
        if it.deadline:
            d["deadline_date"] = it.deadline
        if it.deadline_time:
            d["deadline_time"] = it.deadline_time
        d["priority"] = it.priority
        d["splittable"] = it.splittable
        d["preferred"] = it.preferred
        out_items.append({k: d[k] for k in ITEM_ORDER if k in d})
    out_cons = []
    for c in cons:
        _, start, end, _ = SLOTS[c.slot]
        d = {"kind": "keep_free", "weight": "hard" if c.hard else "soft",
             "day": c.day, "start": start, "end": end}
        out_cons.append({k: d[k] for k in CON_ORDER if k in d})
    return {"status": "ok", "items": out_items, "constraints": out_cons}


def dump(env):
    return json.dumps(env, ensure_ascii=False, separators=(",", ":"))


# ★ system prompt 必须与 bridge/planning.py 的 SYS **逐字相同**
#   （CI 里有断言；改一处必须改两处）
SYS = (
    "你是日程规划助手。用户给你一段非结构化的日程素材（可能是聊天记录、邮件片段、"
    "或几条待办混在一起）。你要抽出「需要占用时间去做的事」和「排期限制」，只输出 JSON。"
    "规则："
    "1. items 每条必须有 title 和 duration_min。原文说了时长就用原文（\"两个小时\"=120）；"
    "没说就按常识估（交一次作业≈60，读一篇论文≈45，写周报≈30）；完全估不出来就用 status=clarify。"
    "2. 闲聊、纯信息、已经做完的事不要放进 items。"
    "3. deadline_date 只写用户原本的日期说法（\"周五\"、\"11-07\"、\"明天\"），"
    "绝对不要自己换算成具体年月日。"
    "4. constraints 只抽用户明确说过的限制，不要脑补。\"别给我排东西\"属于 keep_free。"
    "5. 用户用了\"必须/绝对/别\"就是 hard，用了\"尽量/最好\"就是 soft。"
    "6. 素材里没有任何需要安排的事，用 status=reject。"
    "7. 信息不足无法排期，用 status=clarify 并在 question 里只问一个最关键的问题。"
)


# ---------------------------------------------------------------- 采样
def gen_ok(rng):
    n = rng.choices([1, 2, 3, 4, 5], [0.20, 0.28, 0.26, 0.16, 0.10])[0]
    # 标题去重（同一段里不会出现两个"实验报告"）
    pool = []
    items = []
    for _ in range(n):
        for _try in range(30):
            it = sample_item(rng)
            if it.title not in pool:
                pool.append(it.title)
                items.append(it)
                break

    n_con = 0 if rng.random() < 0.62 else rng.randint(1, 2)
    cons = [sample_constraint(rng) for _ in range(min(n_con, len(items) + 1))]

    style = rng.choices(["list", "chat", "email", "rambling"],
                        [0.34, 0.22, 0.18, 0.26])[0]
    text = render_text(items, cons, style, rng)
    return text, make_envelope(items, cons)


def generate(n, seed):
    rng = random.Random(seed)
    rows, seen, tries = [], set(), 0
    while len(rows) < n and tries < n * 40:
        tries += 1
        r = rng.random()
        if r < 0.11:
            utt = make_reject(rng)
            env = {"status": "reject", "items": [], "constraints": []}
        elif r < 0.19:
            utt = make_clarify(rng)
            env = {"status": "clarify", "items": [], "constraints": [],
                   "question": rng.choice(QUESTIONS)}
        else:
            utt, env = gen_ok(rng)
        if utt in seen:
            continue
        seen.add(utt)
        rows.append({"messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": utt},
            {"role": "assistant", "content": dump(env)},
        ]})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=4000)
    ap.add_argument("--test", type=int, default=400)
    ap.add_argument("--outdir", default="/workspace/data")
    ap.add_argument("--seed", type=int, default=20261103)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    train = generate(a.train, a.seed)
    test = generate(a.test, a.seed + 99991)
    tr_u = {r["messages"][1]["content"] for r in train}
    test = [r for r in test if r["messages"][1]["content"] not in tr_u]

    for name, rows in (("train.jsonl", train), ("test.jsonl", test)):
        p = os.path.join(a.outdir, name)
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{p}: {len(rows)}")

    st, ni, ncon, styles = Counter(), Counter(), Counter(), Counter()
    for r in train:
        o = json.loads(r["messages"][2]["content"])
        st[o["status"]] += 1
        ni[len(o.get("items") or [])] += 1
        ncon[len(o.get("constraints") or [])] += 1
        u = r["messages"][1]["content"]
        styles["email" if u.startswith("主题") else
               "chat" if "\n" in u and "：" in u else
               "list" if "；" in u else "rambling"] += 1
    print("status:", dict(st))
    print("items 条数分布:", dict(sorted(ni.items())))
    print("constraints 条数分布:", dict(sorted(ncon.items())))
    print("风格分布:", dict(styles))
    lens = [len(r["messages"][2]["content"]) for r in train[:1000]]
    print(f"assistant 平均字符: {sum(lens)/len(lens):.0f}")


if __name__ == "__main__":
    main()

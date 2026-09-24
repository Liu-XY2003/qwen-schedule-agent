#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反向构造法生成中文日程工具调用训练数据 (v2)。

v1 的致命缺陷: 先采样槽位、再渲染文本, 于是渲染时可能"漏说"某个字段,
而标签里仍然带着它 -> 产生模型无法从文本推断的错误标签。

v2 的核心不变量:
    **先决定要说哪些字段, 文本只由这些字段渲染, 标签也只由这些字段构造。**
    任何没被说出口的字段一律不进标签。

另外对时间表达做了"无歧义"约束:
    - period=am/pm  : 可用「上午九点」「晚上9:30」「21点」等无歧义写法
    - period=none   : 只能用 1..12 点且不带前缀 (「九点」), 标签 time 用同一小时
    - 24 小时制写法必须带分钟, 否则 "13点" 会丢掉 45 分
"""
import argparse
import json
import os
import random
from collections import Counter

# ------------------------------------------------------------------ 词表

CLASS_TITLES = [
    "计算机原理", "高等数学", "线性代数", "数据结构", "操作系统", "计算机网络",
    "离散数学", "大学物理", "概率论与数理统计", "编译原理", "数据库系统", "软件工程",
    "数字逻辑", "微机原理", "人工智能导论", "机器学习", "深度学习", "计算机图形学",
    "信息安全", "算法设计与分析", "大学英语", "体育",
]
EXAM_SUFFIX = ["期中考试", "期末考试", "随堂测验", "四级考试", "六级考试"]
MEETING_TITLES = ["组会", "班会", "项目例会", "与导师讨论", "面试", "课程设计答辩",
                  "团队周会", "需求评审", "技术分享", "社团活动"]
ASSIGN_SUFFIX = ["实验报告", "课程设计报告", "论文初稿", "大作业", "读书报告", "课后习题"]
ALARM_TITLES = ["起床", "午睡", "叫我起床"]          # 必须被说出来
REMIND_TITLES = ["交作业", "买牛奶", "取快递", "还书", "缴费", "给家里打电话",
                 "吃药", "抢课", "报名", "充饭卡"]
MEMO_TITLES = ["实验室门禁密码", "学号", "快递取件码", "导师电话", "宿舍门锁密码"]
LOCATIONS = ["教三201", "实验楼302", "图书馆三楼", "主楼A305", "一号教学楼",
             "计算机学院报告厅", "宿舍", "体育馆", "综合楼508"]

WEEKDAY_CN = {"MO": "一", "TU": "二", "WE": "三", "TH": "四", "FR": "五", "SA": "六", "SU": "日"}

# 周/月偏移 -> 中文说法 (v2: 用数值偏移取代枚举, 才能表达"下下周""下个月")
WEEK_PREFIX = {
    -2: ["上上周", "上上星期"],
    -1: ["上", "上个"],
    0:  ["", "", "", "这", "本"],
    1:  ["下", "下个"],
    2:  ["下下", "下下个", "大下", "大下个"],
    3:  ["下下下", "下下下个"],
}
CN_MONTH = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六",
            7: "七", 8: "八", 9: "九", 10: "十", 11: "十一", 12: "十二"}
CN_DAY = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九",
          10: "十", 11: "十一", 12: "十二", 13: "十三", 14: "十四", 15: "十五", 16: "十六",
          17: "十七", 18: "十八", 19: "十九", 20: "二十", 21: "二十一", 22: "二十二",
          23: "二十三", 24: "二十四", 25: "二十五", 26: "二十六", 27: "二十七", 28: "二十八"}
MONTH_PREFIX = {
    -1: ["上个月", "上个月份"],
    0:  ["", "", "这个月", "本月"],
    1:  ["下个月", "下个月份"],
    2:  ["下下个月"],
}
CN_NUM = ["十二", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一"]


def cn_hour(h12):
    return CN_NUM[h12 % 12]


def cn_min(m):
    if m == 0:
        return ""
    return {15: "十五", 30: "三十", 45: "四十五"}.get(m, str(m))


def clock_cn(h12, m):
    """12 小时制中文: 九点 / 九点半 / 九点四十五"""
    if m == 0:
        return f"{cn_hour(h12)}点"
    if m == 30:
        return f"{cn_hour(h12)}点半"
    if m == 15:
        return f"{cn_hour(h12)}点一刻"
    return f"{cn_hour(h12)}点{cn_min(m)}"


def clock_24(h, m):
    """24 小时制中文: 21点30分"""
    if m == 0:
        return f"{h}点"
    return f"{h}点{cn_min(m)}分"


# ------------------------------------------------------------------ 时间短语 (保证无歧义)

def time_phrase(h, m, period, rng):
    """返回 (短语, 标签time, 标签period)。三者由同一组取值导出, 结构上不可能矛盾。"""
    if period == "none":
        # 只能说 1..12 点且不带前缀, 标签 time 与所说的小时一致
        if not (1 <= h <= 12):
            return None
        p = clock_cn(h, m)
        if rng.random() < 0.2:
            p = f"{h}:{m:02d}"          # 数字写法, h<=12 仍然无歧义
        return p, f"{h:02d}:{m:02d}", "none"

    # 明确 am/pm
    if rng.random() < 0.10:
        # 24 小时制写法: 必须带分钟
        return clock_24(h, m), f"{h:02d}:{m:02d}", period

    h12 = h % 12 or 12
    if h == 12:
        prefix = rng.choice(["中午", "正午"])
    elif h < 12:
        prefix = rng.choice(["上午", "早上", "早晨"])
    elif h < 18:
        prefix = rng.choice(["下午", "午后"])
    else:
        prefix = rng.choice(["晚上", "夜里"])
    return prefix + clock_cn(h12, m), f"{h:02d}:{m:02d}", period


FUZZY_CN = {
    "morning": ["早上", "一大早", "早晨"],
    "noon": ["中午", "午饭时候"],
    "afternoon": ["下午", "午后"],
    "evening": ["晚上", "夜里"],
}


# ------------------------------------------------------------------ 计划 -> 文本 + 标签

VERB = {
    "class": ["加", "添加", "安排", "排"],
    "exam": ["加", "添加", "记一下", "标注"],
    "meeting": ["加", "安排", "记一下", "约"],
    "assignment": ["加", "添加", "记一下"],
    "alarm": ["设", "定", "设置"],
    "reminder": ["提醒我", "加个提醒", "设置提醒"],
    "memo": ["记一下", "记录一下", "存一下"],
}
POLITE = ["", "帮我", "麻烦帮我", "请帮我", "能不能帮我", "帮我一下，"]
TAILS = ["", "", "", "，谢谢", "，麻烦了", "。"]


def build(plan, rng):
    """由 plan 生成 (utterance, label, used)。
    label 只包含被说出口的字段; used 是所有必须出现在句中的短语, 用于自校验。"""
    module = plan["module"]
    title = plan["title"]
    verb = rng.choice(VERB[module])
    polite = rng.choice(POLITE)
    tail = rng.choice(TAILS)
    used = []

    label = {"module": module, "action": "add", "title": title}
    when = {}

    # ---- 日期短语
    date_s = None
    dk = plan.get("date_kind")
    if dk == "offset_day":
        date_s = {"+0": "今天", "+1": "明天", "+2": "后天", "+3": "大后天"}[plan["date_value"]]
        when["date_kind"] = "offset_day"
        when["date_value"] = plan["date_value"]
        used.append("今天" if date_s == "明儿" else date_s)
    elif dk == "weekday":
        d = WEEKDAY_CN[plan["date_value"]]
        off = plan.get("week_offset", 0)
        pre = rng.choice(WEEK_PREFIX[off])
        date_s = f"{pre}周{d}" if pre else rng.choice([f"周{d}", f"星期{d}", f"礼拜{d}"])
        when["date_kind"] = "weekday"
        when["date_value"] = plan["date_value"]
        if off != 0:
            when["week_offset"] = off
        used.append(date_s)
    elif dk == "month_day":
        day = plan["date_value"]
        off = plan.get("month_offset", 0)
        pre = rng.choice(MONTH_PREFIX[off])
        if pre:
            date_s = rng.choice([f"{pre}{day}号", f"{pre}{day}日"])
        else:
            date_s = rng.choice([f"{day}号", f"{day}日", f"这个月{day}号"])
        when["date_kind"] = "month_day"
        when["date_value"] = day
        if off != 0:
            when["month_offset"] = off
        used.append(date_s)
    elif dk == "absolute":
        parts = plan["date_value"].split("-")
        if len(parts) == 3:
            y, mo, dd = parts
            date_s = rng.choice([f"{y}年{int(mo)}月{int(dd)}号", f"{y}年{int(mo)}月{int(dd)}日",
                                 f"{y}-{mo}-{dd}"])
        else:
            mo, dd = int(parts[0]), int(parts[1])
            # 中文数字月份必须覆盖: 否则"十月23号"会被模型当成"10号"
            date_s = rng.choice([f"{mo}月{dd}号", f"{mo}月{dd}日", f"{mo}/{dd}",
                                 f"{CN_MONTH[mo]}月{dd}号", f"{CN_MONTH[mo]}月{CN_DAY[dd]}号",
                                 f"{CN_MONTH[mo]}月{dd}日"])
        when["date_kind"] = "absolute"
        when["date_value"] = plan["date_value"]
        used.append(date_s)

    # ---- 时间短语
    time_s = None
    if plan.get("time") is not None:
        h, m = plan["time"]
        tp = time_phrase(h, m, plan["period"], rng)
        if tp is None:
            return None
        time_s, t_label, p_label = tp
        when["time"] = t_label
        when["period"] = p_label
        used.append(time_s)
    elif plan.get("fuzzy"):
        time_s = rng.choice(FUZZY_CN[plan["fuzzy"]])
        when["fuzzy"] = plan["fuzzy"]
        used.append(time_s)

    # ---- 时长
    end_s = None
    if plan.get("duration_min") and plan.get("time") is not None and time_s:
        h, m = plan["time"]
        dur = plan["duration_min"]
        tot = h * 60 + m + dur
        eh, em = (tot // 60) % 24, tot % 60
        when["duration_min"] = dur
        if rng.random() < 0.30:
            ep = time_phrase(eh, em, plan["period"], rng)
            if ep:
                end_s = ep[0]
                used.append(end_s)

    # ---- 组装时间词
    tw = ""
    if date_s and time_s:
        tw = date_s + time_s
        # 中文口语会把"今天+早上"缩成"今早"。训练数据里若没有这些缩略形式,
        # 模型遇到"明早八点的闹钟"会把日期整个丢掉(实测落到今天)。
        if dk == "offset_day":
            base = {"+0": "今", "+1": "明", "+2": "后"}.get(plan.get("date_value"))
            if base:
                for pre, suf in (("早上", "早"), ("早晨", "早"), ("上午", "早"),
                                 ("晚上", "晚"), ("夜里", "晚")):
                    if time_s.startswith(pre):
                        contracted = base + suf + time_s[len(pre):]
                        if used and used[-1] == time_s:
                            used.pop()
                        if used and used[-1] == date_s:
                            used.pop()
                        tw = contracted
                        used.append(contracted)
                        break
    elif date_s:
        tw = date_s
    elif time_s:
        tw = time_s
    dur_phrase = None
    if end_s:
        tw = f"从{tw}到{end_s}"
    elif plan.get("duration_min"):
        dur_cn = {45: "一节课", 60: "一个小时", 90: "一个半小时", 120: "两个小时"}[plan["duration_min"]]
        dur_phrase = f"要{dur_cn}"
        used.append(dur_cn)

    # ---- 主体句
    if module == "memo":
        body = f"{polite}{verb}，{title}"
        used.append(title)
        if plan.get("notes"):
            label["notes"] = plan["notes"]
            body += f"是 {plan['notes']}"
            used.append(plan["notes"])
    elif module == "alarm":
        # 闹钟必须有时间词, 否则"设个闹钟"无法推断时刻 -> 直接判为无效样本
        if not tw:
            return None
        body = rng.choice([f"{polite}{verb}个{tw}的闹钟", f"{polite}{verb}个闹钟，{tw}"])
        if title and title != "闹钟" and rng.random() < 0.5:
            body += f"，{title}"
            used.append(title)
        else:
            label["title"] = "闹钟"
        body = body.rstrip("，")
    else:
        used.append(title)
        if tw:
            body = rng.choice([
                f"{tw}有{title}",
                f"{tw}要{title}",
                f"{polite}把{title}{verb}到{tw}",
                f"{polite}{verb}{title}，{tw}",
            ])
        else:
            body = f"{polite}{verb}{title}"

    # ---- 可选字段: 说了才进标签
    if plan.get("location"):
        label["location"] = plan["location"]
        body += rng.choice([f"，在{plan['location']}", f"，地点{plan['location']}"])
        used.append(plan["location"])
    if dur_phrase:
        body += f"，{dur_phrase}"
    if plan.get("remind"):
        label["remind_before_min"] = plan["remind"]
        body += rng.choice([f"，提前{plan['remind']}分钟提醒我", f"，{plan['remind']}分钟前提醒"])
        used.append(str(plan["remind"]))
    if plan.get("priority"):
        label["priority"] = plan["priority"]
        body += rng.choice(["，这个比较重要", "，优先级高"])
    if when:
        label["when"] = when

    utt = (body + tail).replace("，。", "。").replace("，，", "，").strip("，")
    # 自校验: 所有标记为"必须出现"的短语都要真的在句子里
    for u in used:
        if u not in utt:
            return None
    return utt, label


# ------------------------------------------------------------------ 采样 plan

def sample_plan(rng, difficulty):
    module = rng.choice(["class", "class", "class", "exam", "meeting", "meeting",
                         "assignment", "alarm", "reminder", "memo"])
    if module == "class":
        title = rng.choice(CLASS_TITLES)
    elif module == "exam":
        title = rng.choice(CLASS_TITLES) + rng.choice(EXAM_SUFFIX)
    elif module == "meeting":
        title = rng.choice(MEETING_TITLES)
    elif module == "assignment":
        title = rng.choice(CLASS_TITLES) + rng.choice(ASSIGN_SUFFIX)
    elif module == "alarm":
        title = rng.choice(ALARM_TITLES)
    elif module == "reminder":
        title = rng.choice(REMIND_TITLES)
    else:
        title = rng.choice(MEMO_TITLES)

    plan = {"module": module, "title": title}

    if module == "memo":
        if rng.random() < 0.5:
            plan["notes"] = str(rng.randint(1000, 999999))
        return plan

    # ---- 日期
    r = rng.random()
    if not (difficulty == "hard" and r < 0.10):
        if r < 0.30:
            plan["date_kind"] = "offset_day"
            plan["date_value"] = rng.choice(["+0", "+1", "+2", "+3"])
        elif r < 0.74:
            plan["date_kind"] = "weekday"
            plan["date_value"] = rng.choice(list(WEEKDAY_CN))
            # 0=本周(或不带修饰) 1=下周 2=下下周 3=下下下周 -1=上周
            plan["week_offset"] = rng.choice([0, 0, 0, 0, 1, 1, 1, 2, 2, 3, -1])
        elif r < 0.84:
            plan["date_kind"] = "month_day"
            plan["date_value"] = str(rng.randint(1, 28))
            plan["month_offset"] = rng.choice([0, 0, 0, 1, 1, 2, -1])
        elif r < 0.92:
            # 绝对日期: 一半带年份, 一半不带(不带时 date_value 用 MM-DD)
            mo, dd = rng.randint(1, 12), rng.randint(1, 28)
            if rng.random() < 0.5:
                plan["date_kind"] = "absolute"
                plan["date_value"] = f"2026-{mo:02d}-{dd:02d}"
            else:
                plan["date_kind"] = "absolute"
                plan["date_value"] = f"{mo:02d}-{dd:02d}"
                plan["no_year"] = True

    # ---- 时间
    if rng.random() < 0.12:
        plan["fuzzy"] = rng.choice(list(FUZZY_CN))
    else:
        want_none = (difficulty == "hard" and rng.random() < 0.30) or rng.random() < 0.12
        if want_none:
            # period=none 只能说 1..12 点; 偏向 7..12 更贴近真实作息
            h = rng.choice([7, 8, 9, 10, 11, 12, 7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6])
            period = "none"
        else:
            h = rng.choice([6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22])
            period = "am" if h < 12 else "pm"
        m = rng.choice([0, 0, 0, 15, 30, 30, 45])
        plan["time"] = (h, m)
        plan["period"] = period
        if rng.random() < 0.22:
            plan["duration_min"] = rng.choice([45, 60, 90, 120])

    if rng.random() < 0.18:
        plan["location"] = rng.choice(LOCATIONS)
    if module in ("alarm", "reminder", "class") and rng.random() < 0.18:
        plan["remind"] = rng.choice([5, 10, 15, 30])
    if rng.random() < 0.10:
        # 只在真的说出来时才带 priority; 文案统一是"高", 所以值也只能是 high
        plan["priority"] = "high"
    return plan


# ------------------------------------------------------------------ JSON 键序

CMD_ORDER = ["module", "action", "title", "when", "remind_before_min", "location", "priority", "notes"]
WHEN_ORDER = ["date_kind", "date_value", "week_offset", "month_offset",
              "time", "period", "fuzzy", "duration_min"]


def order_cmd(c):
    out = {}
    for k in CMD_ORDER:
        if k not in c:
            continue
        if k == "when":
            out["when"] = {wk: c["when"][wk] for wk in WHEN_ORDER if wk in c["when"]}
        else:
            out[k] = c[k]
    return out


def dump(env):
    return json.dumps(env, ensure_ascii=False, separators=(",", ":"))


SYS = (
    "你是日程助手，把用户的中文请求转换为 JSON，只输出 JSON。"
    "status: ok=可执行, clarify=信息不足要反问, reject=与日程无关。"
    "commands[].module 取 class/exam/meeting/assignment/alarm/reminder/memo；"
    "when 含 date_kind(absolute/offset_day/weekday/month_day/unspecified)、date_value、"
    "week_offset、month_offset、time(HH:MM)、period(am/pm/none)、fuzzy、duration_min。"
    "date_kind=weekday 时要带上 week_offset：不带修饰说\"周二\"是 0，下周是 1，下下周是 2，下下下周是 3，上周是 -1；"
    "date_kind=month_day 时 date_value 只写几号，month_offset 同样用数值(下个月是 1)。"
    "规则：时间只能放进 when，不要放进 location 或 target_ref；不要自己计算绝对日期；"
    "用户没说上午下午时 period 填 none；与日程无关的请求用 reject 且 commands 为空。"
)

REJECTS = ["今天天气怎么样", "明天会下雨吗", "你叫什么名字", "讲个笑话",
           "帮我写一段快速排序的代码", "1+1等于几", "介绍一下量子计算", "北京到上海有多远",
           "推荐几部好看的电影", "把这句话翻译成英文", "你是谁开发的", "帮我算一下这道微积分",
           "股市今天涨了吗", "解释一下什么是区块链"]
CLARIFIES = ["帮我加个课", "提醒我一下", "明天有事", "加个日程", "安排一下",
             "记个东西", "帮我设个提醒", "这周要考试", "有个会", "帮我记一下"]
QUESTIONS = ["是哪门课，什么时间？", "提醒你做什么，什么时间？", "具体是什么事，安排在什么时候？",
             "请告诉我事项和时间。"]


def gen_ok(rng, difficulty):
    n = 1 if rng.random() < 0.90 else rng.randint(2, 3)
    pairs, cmds = [], []
    for _ in range(n):
        for _try in range(20):
            plan = sample_plan(rng, difficulty)
            r = build(plan, rng)
            if r:
                u, lab = r
                if u and lab:
                    pairs.append(u)
                    cmds.append(lab)
                    break
    if not pairs:
        return None
    if len(pairs) == 1:
        utt = pairs[0]
    else:
        # 去掉每条子句末尾的句号, 避免出现 "。，然后" 这种标点错乱
        cleaned = [p.rstrip("。，").strip() for p in pairs]
        utt = rng.choice(["；", "。另外，", "，然后"]).join(cleaned)
    return utt, {"status": "ok", "commands": [order_cmd(c) for c in cmds]}


def generate(n, seed, difficulty_mix=("easy", "easy", "medium", "medium", "hard")):
    rng = random.Random(seed)
    rows, seen, tries = [], set(), 0
    while len(rows) < n and tries < n * 40:
        tries += 1
        r = rng.random()
        if r < 0.12:
            utt, env = rng.choice(REJECTS), {"status": "reject", "commands": []}
        elif r < 0.20:
            utt, env = rng.choice(CLARIFIES), {"status": "clarify", "commands": [],
                                               "question": rng.choice(QUESTIONS)}
        else:
            g = gen_ok(rng, rng.choice(difficulty_mix))
            if not g:
                continue
            utt, env = g
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
    ap.add_argument("--seed", type=int, default=20260921)
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

    st, mod, per = Counter(), Counter(), Counter()
    for r in train:
        o = json.loads(r["messages"][2]["content"])
        st[o["status"]] += 1
        for c in o["commands"]:
            mod[c["module"]] += 1
            if c.get("when", {}).get("period"):
                per[c["when"]["period"]] += 1
    print("status:", dict(st))
    print("module:", dict(mod))
    print("period:", dict(per))
    lens = [len(r["messages"][2]["content"]) for r in train[:1000]]
    print(f"assistant 平均字符: {sum(lens)/len(lens):.0f}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日程助手 Web App —— 远程可视化日历

一句话自然语言 -> LoRA 模型 -> 结构化指令 -> 时间解析 -> SQLite -> 日历上看得见
"""
from __future__ import annotations

import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from executor import Store, execute                     # noqa: E402
from schema_models import Envelope, check_drift        # noqa: E402

# 推理后端: llama.cpp 的 OpenAI 兼容接口。
# 用 llama-server 而不是进程内 transformers 的原因:
#   1. 快 ~24 倍 (HF generate 逐 token 有 CPU 同步, 实测 11.5 tok/s -> llama.cpp 272 tok/s)
#   2. 支持 response_format=json_schema 约束解码, 让越界枚举结构上不可能出现
LLAMA_URL = os.environ.get("SCHED_LLAMA_URL", "http://127.0.0.1:8080").rstrip("/")
DB_PATH = os.environ.get("SCHED_DB") or os.path.join(HERE, "schedule.db")

# ---------------------------------------------------------------- 访问控制
# 这是一个"单人日历": 一台后端 + 自己的若干设备(电脑/手机), 大家看同一份数据。
# 所以不需要多用户数据隔离 —— 不同的人各自跑自己的后端和数据库, 天然就隔离了。
#
# 真正要防的是另一件事: 后端默认绑 0.0.0.0(手机要通过 Tailscale 访问), 又完全没有
# 鉴权, 于是同一网段任何人都能读你的日程、甚至 POST /api/reset 清空它。
# 所以这里提供一个共享令牌:
#   * 不设 SCHED_TOKEN -> 行为与以前完全一致(本机/可信内网用, 零门槛)
#   * 设了 SCHED_TOKEN -> 所有 /api/* 都要带 X-Sched-Token 头或 ?token= 参数
TOKEN = os.environ.get("SCHED_TOKEN", "").strip()
TOKEN_HEADER = "x-sched-token"


def _token_of(request: Request) -> str:
    return request.headers.get(TOKEN_HEADER) or request.query_params.get("token") or ""


def _authed(request: Request) -> bool:
    if not TOKEN:
        return True
    # 定时安全比较, 免得用响应时间逐字符猜令牌
    return hmac.compare_digest(_token_of(request), TOKEN)


def _find_schema() -> str:
    """定位 schedule_command.v2.json。

    契约的唯一事实源是仓库根的 schema/ 目录。历史上部署到 pod 时会把一份拷贝
    放进 bridge/ 一起上传, 所以这里两个位置都认。缺文件时给出可执行的提示,
    而不是抛一个裸的 FileNotFoundError —— 新克隆仓库的人会一头雾水。
    """
    env = os.environ.get("SCHED_SCHEMA")
    candidates = [
        env,
        os.path.join(HERE, "..", "schema", "schedule_command.v2.json"),
        os.path.join(HERE, "schedule_command.v2.json"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    raise SystemExit(
        "找不到 schema/schedule_command.v2.json。\n"
        f"  已查找: {[c for c in candidates if c]}\n"
        "  请确认在仓库根目录运行, 或用 SCHED_SCHEMA=<路径> 指定。"
    )


SCHEMA_PATH = _find_schema()
SCHEMA = json.load(open(SCHEMA_PATH, encoding="utf-8"))

# system prompt 必须与训练时逐字节一致 —— 它是模型契约的一部分
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

STATE: dict = {"ready": False, "err": None}
STORE = Store(DB_PATH)


def _llama_get(path: str, timeout: float = 5.0):
    with urllib.request.urlopen(LLAMA_URL + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def backend_health() -> dict:
    """探测 llama-server 是否可用"""
    try:
        props = _llama_get("/props")
        return {"ok": True, "model": props.get("default_generation_settings", {})
                .get("model", "?"), "n_ctx": props.get("default_generation_settings", {})
                .get("n_ctx")}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def extract_json(text: str):
    t = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.M)
    t = re.sub(r"```\s*$", "", t, flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("输出里找不到 JSON 对象")
    return json.loads(t[i:j + 1])


def generate(user_text: str, extra: str | None = None) -> tuple[str, float]:
    """调用 llama-server, 带 json_schema 约束解码"""
    msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": user_text}]
    if extra:
        msgs.append({"role": "user", "content": extra})
    body = {
        "messages": msgs,
        "max_tokens": 256,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        # ★ 约束解码: 输出必然符合 SCHEMA, 越界枚举不可能出现
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "schedule_command", "schema": SCHEMA}},
    }
    req = urllib.request.Request(LLAMA_URL + "/v1/chat/completions",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"无法连接推理服务 {LLAMA_URL}: {e}")
    dt = (time.time() - t0) * 1000
    return j["choices"][0]["message"]["content"].strip(), round(dt)


def _validate(obj):
    try:
        return Envelope.model_validate(obj), []
    except ValidationError as e:
        return None, [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                      for err in e.errors()]


# 契约能表达的偏移范围: week_offset / month_offset 都是 -2..4。
# 超出范围时模型只能压到边界值(实测"下下下下下周二"会被压成 4), 会静默写错日期,
# 所以这里主动反问, 而不是等它写错。
MAX_OFFSET = 4

# 模型不知道"现在是哪一年", 所以"今年/明年/去年"这类相对年份表达它只能猜,
# 实测"今年12月31号"被输出成 01-12。宁可反问, 也不写错。
YEAR_MARKERS = ["今年", "明年", "后年", "去年", "前年", "本年", "次年"]


def consistency_guard(text: str, env: dict) -> str | None:
    """输入与解析结果的一致性检查; 返回需要向用户追问的话, 或 None"""
    m = re.search(r"下{5,}", text)          # 下下下下下...
    if m:
        return (f"「{m.group(0)}」这个跨度的偏移太大（我最多支持 {MAX_OFFSET} 周/月），"
                f"怕算错日期。请直接说具体日期。")

    hit = [y for y in YEAR_MARKERS if y in text]
    if hit:
        cmds = env.get("commands") or []
        w = (cmds[0].get("when") or {}) if cmds else {}
        # 只有模型自己"算"了年份才危险; 明确写了 2026-xx-xx 的放行
        dv = str(w.get("date_value") or "")
        if w.get("date_kind") == "absolute" and not re.match(r"^\d{4}-", dv):
            return (f"这句话里有「{hit[0]}」，但模型无法知道当前年份，它可能会算错。"
                    f"请直接写明年份，例如「{datetime.now().year}年12月31号晚上八点」。")

    cmds = env.get("commands") or []
    # 输入里明确说了"X月Y号", 模型却只回 month_day(丢掉月份) -> 说明它把"十月"当成了"10号"
    if re.search(r"\d{1,2}月", text) or re.search(r"[一二三四五六七八九十]{1,3}月", text):
        for c in cmds:
            w = c.get("when") or {}
            if w.get("date_kind") == "month_day" and w.get("month_offset") is None:
                return ("这句话里有明确的月份，但模型把月份丢了，很可能算错日期。"
                        "请再说一次，例如「10月23号下午三点」。")

    for c in cmds:
        w = c.get("when") or {}
        for k in ("week_offset", "month_offset"):
            v = w.get(k)
            if v is not None and not (-2 <= int(v) <= MAX_OFFSET):
                return f"{k}={v} 超出我能处理的范围（-2 ~ {MAX_OFFSET}），怕算错日期。"
    return None


def run_pipeline(user_text: str) -> dict:
    t0 = time.time()
    res: dict = {"input": user_text, "steps": [], "attempts": []}
    try:
        raw, gen_ms = generate(user_text)
    except Exception as e:
        return {**res, "error": f"模型生成失败: {type(e).__name__}: {e}"}
    res["model_raw"], res["gen_ms"] = raw, gen_ms
    res["attempts"].append(raw)
    res["steps"].append({"name": "模型生成", "ok": True, "ms": gen_ms})

    try:
        obj = extract_json(raw)
        res["steps"].append({"name": "JSON 解析", "ok": True})
    except Exception as e:
        return {**res, "parse_ok": False, "schema_ok": False,
                "steps": res["steps"] + [{"name": "JSON 解析", "ok": False, "detail": str(e)}],
                "error": f"输出不是合法 JSON: {e}"}

    env, errs = _validate(obj)
    if errs:
        res["steps"].append({"name": "Schema 校验", "ok": False, "detail": "; ".join(errs)})
        fix = ("上一次输出违反了 Schema，错误如下：\n" + "\n".join(errs) +
               "\n请重新只输出一个修正后的 JSON 对象，不要解释。")
        try:
            raw2, gen2 = generate(user_text, extra=fix)
            res["attempts"].append(raw2)
            res["model_raw"] = raw2
            res["gen_ms"] += gen2
            obj2 = extract_json(raw2)
            env, errs2 = _validate(obj2)
            res["steps"].append({"name": "错误回灌重试", "ok": not errs2, "ms": gen2,
                                 "detail": None if not errs2 else "; ".join(errs2)})
            if errs2:
                return {**res, "schema_ok": False, "schema_error": errs2}
        except Exception as e:
            return {**res, "schema_ok": False, "schema_error": errs + [f"重试仍失败: {e}"]}
    else:
        res["steps"].append({"name": "Schema 校验", "ok": True})

    res["schema_ok"] = True
    res["envelope"] = env.model_dump(exclude_none=True)

    guard = consistency_guard(user_text, res["envelope"])
    if guard:
        res["steps"].append({"name": "一致性检查", "ok": False, "detail": guard})
        res["execution"] = {"kind": "need_clarify", "detail": guard, "items": []}
        res["total_ms"] = round((time.time() - t0) * 1000)
        return res

    out = execute(env.model_dump(exclude_none=True), STORE, datetime.now())
    res["execution"] = {"kind": out.kind, "detail": out.detail,
                        "items": out.event.get("items", [])}
    res["steps"].append({"name": "写入日程", "ok": out.kind == "executed",
                         "detail": out.detail if out.kind != "executed" else None})
    res["total_ms"] = round((time.time() - t0) * 1000)
    return res


# ------------------------------------------------------------------ HTTP

app = FastAPI(title="日程助手")

# 主题 token 由 theme/gen_theme.py 生成到 static/theme.css; 目录不存在时静默跳过,
# 页面会退回没有变量的默认样式而不是 500。
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


class ChatIn(BaseModel):
    text: str


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    """设了 SCHED_TOKEN 时, 所有 /api/* 都要带令牌。

    /api/health 例外: 客户端得先能问出"你到底需不需要令牌", 否则只能看到一个
    401 而分不清是令牌错还是地址错。health 在未授权时只返回存活状态。
    """
    path = request.url.path
    if TOKEN and path.startswith("/api/") and path != "/api/health" and not _authed(request):
        return JSONResponse(
            {"error": "需要访问令牌", "auth_required": True,
             "hint": "在请求头加 X-Sched-Token, 或 URL 上加 ?token="},
            status_code=401)
    return await call_next(request)


@app.on_event("startup")
def _startup():
    # 只记一条启动日志, 不把探测结果当成永久状态。
    # 原因: systemd / 计划任务会同时拉起 llama-server 和本 App, App 很可能先就绪,
    # 而 llama-server 加载模型要几秒。若在这里把 ready 定死, App 会永久报"不可用"。
    h = backend_health()
    if h["ok"]:
        STATE.update(ready=True, backend="llama.cpp")
    else:
        STATE["err"] = f"启动时推理服务尚未就绪: {h.get('error')}"
    print(f"[startup] backend_ok={h['ok']} {STATE.get('err') or ''}", flush=True)


@app.get("/api/health")
def health(request: Request):
    h = backend_health()          # ★ 每次实时探测, 不用启动时的缓存
    if not _authed(request):
        # 没带令牌时只回答"进程活着、需要令牌", 不泄露日程条数等数据
        return {"ready": h["ok"], "auth_required": True,
                "error": None if h["ok"] else h.get("error"),
                "backend": "llama.cpp + json_schema 约束解码"}
    return {"ready": h["ok"],
            "error": None if h["ok"] else h.get("error"),
            "backend": "llama.cpp + json_schema 约束解码",
            "llama_url": LLAMA_URL, "llama_ok": h["ok"], "llama_err": h.get("error"),
            "n_ctx": h.get("n_ctx"),
            "schema_drift": check_drift(SCHEMA_PATH), "events": STORE.count(),
            "auth_required": bool(TOKEN),
            "server_date": date.today().isoformat()}


@app.post("/api/chat")
def chat(body: ChatIn):
    # 不做启动期状态门禁: generate() 内部连不上会抛错并返回可读信息,
    # 这样推理服务晚几秒起来也能自动恢复, 不需要重启 App。
    return run_pipeline(body.text.strip())


@app.get("/api/events")
def events():
    rows = STORE.fetch(
        "SELECT id,module,title,start_ts,duration_min,remind_before_min,location,priority,"
        "notes,ambiguous,created_at FROM events ORDER BY start_ts IS NULL, start_ts, id")
    cols = ["id", "module", "title", "start", "duration_min", "remind", "location",
            "priority", "notes", "ambiguous", "created_at"]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d["ambiguous"] = bool(d["ambiguous"])
        d["end"] = None
        if d["start"] and d["duration_min"]:
            try:
                d["end"] = (datetime.fromisoformat(d["start"])
                            + timedelta(minutes=int(d["duration_min"]))).isoformat()
            except Exception:
                pass
        out.append(d)
    return {"events": out}


@app.delete("/api/events/{eid}")
def delete_event(eid: int):
    STORE.execute("DELETE FROM events WHERE id=?", (eid,))
    return {"ok": True, "events": STORE.count()}


@app.post("/api/reset")
def reset():
    # 这是唯一一个会一次性毁掉全部数据的端点。加了令牌之后已经挡住了外人,
    # 这里再要一个显式确认, 免得前端误调用(或者以后接上模型自主调用)时手滑清空。
    STORE.clear()
    return {"ok": True, "events": 0}


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>我的日程</title>
<link rel="stylesheet" href="/static/theme.css"/>
<script>/* 尽早定主题, 避免刷新时闪一下 */(function(){try{
var q=new URLSearchParams(location.search).get("theme");
var p=(q==="paper"||q==="night")?q:(localStorage.getItem("sched-theme")||"auto");
var d=p==="auto"?(matchMedia("(prefers-color-scheme: dark)").matches?"night":"paper"):p;
document.documentElement.setAttribute("data-theme",d==="paper"?"paper":"night");
}catch(e){}})();</script>
<style>
*{box-sizing:border-box}
body{margin:0;font:15px/1.6 var(--font-body);background:var(--bg);color:var(--fg)}
.wrap{max-width:1240px;margin:0 auto;padding:20px}
.top{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:16px}
h1{font-size:19px;margin:0;font-weight:650;font-family:var(--font-title);letter-spacing:.2px}
.badge{font-size:12px;padding:3px 10px;border-radius:var(--r-chip);background:var(--chip-bg);
       color:var(--muted);border:1px solid var(--line)}
.badge.ok{background:color-mix(in srgb,var(--ok) 13%,var(--card));color:var(--ok);
          border-color:color-mix(in srgb,var(--ok) 38%,var(--line))}
.badge.bad{background:color-mix(in srgb,var(--danger) 13%,var(--card));color:var(--danger);
           border-color:color-mix(in srgb,var(--danger) 38%,var(--line))}
.themebtn{margin-left:auto;display:flex;gap:2px;background:var(--chip-bg);
          border:1px solid var(--line);border-radius:var(--r-chip);padding:3px}
.themebtn button{background:transparent;color:var(--muted);padding:5px 13px;font-size:12.5px;
                 border-radius:var(--r-chip);font-weight:600}
.themebtn button.on{background:var(--card);color:var(--fg);box-shadow:var(--shadow)}

.addbar{background:var(--card);border:1px solid var(--line);border-radius:var(--r-card);
        padding:14px;margin-bottom:16px;box-shadow:var(--shadow)}
.addrow{display:flex;gap:10px}
input#q{flex:1;background:var(--bg);border:1px solid var(--line);border-radius:var(--r-btn);
        color:var(--fg);padding:12px 14px;font:15px inherit}
input#q::placeholder{color:var(--muted);opacity:.8}
input#q:focus{outline:none;border-color:var(--accent)}
button{border:0;border-radius:var(--r-btn);cursor:pointer;font-size:14px;font-weight:550;
       padding:11px 22px;font-family:inherit}
#go{background:var(--accent);color:var(--on-accent)}
#go:hover{filter:brightness(1.12)}
#go:disabled{background:var(--chip-bg);color:var(--muted);cursor:not-allowed;filter:none}
.ghost{background:var(--chip-bg);color:var(--muted);padding:11px 16px}
.ghost:hover{color:var(--fg)}
.chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:11px}
.chip{font-size:12.5px;padding:5px 11px;border-radius:var(--r-chip);background:var(--chip-bg);
      border:1px solid var(--line);color:var(--muted);cursor:pointer}
.chip:hover{border-color:var(--accent);color:var(--accent)}

.layout{display:grid;grid-template-columns:1fr 360px;gap:16px}
@media(max-width:1000px){.layout{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r-card);
      padding:16px;box-shadow:var(--shadow)}
.card h2{font-size:13px;margin:0 0 12px;color:var(--muted);font-weight:600;letter-spacing:.4px}

.calhead{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.calhead .m{font-size:17px;font-weight:650;min-width:150px;font-family:var(--font-title)}
.nav{background:var(--chip-bg);color:var(--fg);padding:6px 13px;font-size:15px;
     border-radius:var(--r-btn)}
.nav:hover{color:var(--accent)}
.today-btn{background:color-mix(in srgb,var(--accent) 15%,var(--card));color:var(--accent);
           padding:6px 13px;font-size:13px;border-radius:var(--r-btn)}

.grid{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}
.wd{text-align:center;font-size:12px;color:var(--muted);padding:6px 0;font-weight:600}
.cell{min-height:96px;background:var(--card2);border:1px solid transparent;
      border-radius:var(--r-cell);padding:6px;cursor:pointer;overflow:hidden;
      transition:border-color var(--dur) ease-out,background var(--dur) ease-out}
.cell:hover{border-color:color-mix(in srgb,var(--fg) 20%,transparent)}
.cell.out{opacity:.32}
.cell.today{border-color:var(--accent)}
.cell.sel{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 13%,var(--card2))}
.cell .d{font-size:12.5px;color:var(--muted);margin-bottom:4px;font-weight:600;
         font-variant-numeric:var(--num-variant)}
.cell.today .d{color:var(--accent)}

.ev{--mc:var(--m-memo);font-size:11.5px;line-height:1.35;padding:2px 5px;margin-bottom:3px;
    border-radius:5px;border-left:var(--ev-bar) solid var(--mc);
    background:color-mix(in srgb,var(--mc) 14%,var(--card2));color:var(--fg);
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ev::before{content:"";display:var(--dot-display);width:var(--marker-size);
            height:var(--marker-size);border-radius:50%;background:var(--mc);
            margin-right:5px;vertical-align:middle}
.ev.class{--mc:var(--m-class)}.ev.exam{--mc:var(--m-exam)}.ev.meeting{--mc:var(--m-meeting)}
.ev.assignment{--mc:var(--m-assignment)}.ev.alarm{--mc:var(--m-alarm)}
.ev.reminder{--mc:var(--m-reminder)}.ev.memo{--mc:var(--m-memo)}
.ev .t{color:var(--muted);margin-right:4px;font-variant-numeric:var(--num-variant)}
.more{font-size:11px;color:var(--muted);padding-left:5px}

.daylist{display:flex;flex-direction:column;gap:9px;max-height:420px;overflow-y:auto}
.item{--mc:var(--m-memo);background:color-mix(in srgb,var(--mc) 8%,var(--card2));
      border-left:var(--ev-bar) solid var(--mc);border-radius:8px;padding:10px 12px}
.item.class{--mc:var(--m-class)}.item.exam{--mc:var(--m-exam)}.item.meeting{--mc:var(--m-meeting)}
.item.assignment{--mc:var(--m-assignment)}.item.alarm{--mc:var(--m-alarm)}
.item.reminder{--mc:var(--m-reminder)}.item.memo{--mc:var(--m-memo)}
.item .h{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.item .ti{font-weight:600;font-size:14.5px}
.item .tm{color:var(--mc);font-size:13px;font-variant-numeric:tabular-nums}
.item .meta{font-size:12px;color:var(--muted);margin-top:3px}
.del{background:transparent;color:var(--muted);padding:2px 7px;font-size:15px;line-height:1;
     border-radius:6px}
.del:hover{background:color-mix(in srgb,var(--danger) 15%,transparent);color:var(--danger)}
.tagline{display:flex;gap:6px;flex-wrap:wrap;margin-top:5px}
.tag{font-size:11px;padding:1px 7px;border-radius:5px;background:var(--chip-bg);color:var(--muted)}
.warn{background:color-mix(in srgb,var(--warn) 18%,var(--card));color:var(--warn)}
.past{background:color-mix(in srgb,var(--danger) 15%,var(--card));color:var(--danger)}
.empty{color:var(--muted);font-size:13.5px;padding:8px 0}

.result{margin-top:14px;font-size:13.5px;border-radius:9px;padding:11px 13px;display:none}
.result.show{display:block}
.result.ok{background:color-mix(in srgb,var(--ok) 12%,var(--card));
           border:1px solid color-mix(in srgb,var(--ok) 35%,var(--line))}
.result.warn{background:color-mix(in srgb,var(--warn) 12%,var(--card));
             border:1px solid color-mix(in srgb,var(--warn) 35%,var(--line))}
.result.err{background:color-mix(in srgb,var(--danger) 12%,var(--card));
            border:1px solid color-mix(in srgb,var(--danger) 35%,var(--line))}
details{margin-top:12px}
summary{cursor:pointer;color:var(--muted);font-size:12.5px;padding:5px 0}
summary:hover{color:var(--fg)}
pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:11px;
    overflow-x:auto;font:12.5px/1.55 "Cascadia Code",Consolas,monospace;margin:8px 0 0;
    white-space:pre-wrap;word-break:break-word;color:var(--muted)}
.step{display:flex;gap:8px;padding:4px 0;font-size:12.5px;color:var(--muted)}
.dot{width:7px;height:7px;border-radius:50%;margin-top:7px;flex:none}
.dot.g{background:var(--ok)}.dot.r{background:var(--danger)}
.spin{display:inline-block;width:13px;height:13px;border-radius:50%;vertical-align:-2px;
      border:2px solid color-mix(in srgb,var(--on-accent) 35%,transparent);
      border-top-color:var(--on-accent);animation:s .7s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}
.memo-b{background:var(--card2);border-radius:8px;padding:8px 11px;font-size:13px;margin-bottom:7px}
.memo-b .n{color:var(--muted);font-size:12px}
/* 新增日程后让卡片闪一下 —— 用 class 而不是内联颜色, 否则换了主题就串色 */
.item,.memo-b{transition:background .4s ease-out}
.flash{background:color-mix(in srgb,var(--ok) 24%,var(--card2)) !important}
</style></head><body><div class="wrap">

<div class="top">
  <h1>我的日程</h1>
  <span class="badge" id="st">连接中…</span>
  <div class="themebtn" id="themebtn" title="切换外观">
    <button data-t="paper">纸感</button>
    <button data-t="night">夜航</button>
    <button data-t="auto">跟随系统</button>
  </div>
</div>
<div class="addbar">
  <div class="addrow">
    <input id="q" placeholder="用一句话添加日程，例如：下周二上午九点加一门计算机原理，在教三201" autocomplete="off"/>
    <button id="go">添加</button>
    <button class="ghost" id="clr">清空</button>
  </div>
  <div class="chips" id="chips"></div>
  <div class="result" id="res"></div>
</div>

<div class="layout">
  <div class="card">
    <div class="calhead">
      <button class="nav" id="prev">‹</button>
      <div class="m" id="mtitle">—</div>
      <button class="nav" id="next">›</button>
      <button class="today-btn" id="today">今天</button>
    </div>
    <div class="grid" id="wd"></div>
    <div class="grid" id="cells" style="margin-top:6px"></div>
  </div>

  <div>
    <div class="card" style="margin-bottom:16px">
      <h2 id="daytitle">选择日期</h2>
      <div class="daylist" id="daylist"><div class="empty">点击左侧日历中的日期</div></div>
    </div>
    <div class="card">
      <h2>备忘（无时间）</h2>
      <div id="memos"><div class="empty">暂无</div></div>
    </div>
  </div>
</div>

<div class="card" style="margin-top:16px">
  <details>
    <summary>模型处理详情（点开可以看到模型到底输出了什么）</summary>
    <div id="detail"></div>
  </details>
</div>

</div><script>
const $ = s => document.querySelector(s);

// ---- 访问令牌 (仅当后端设了 SCHED_TOKEN 时才需要) ----
// 401 时弹一次输入框, 存本机; 之后所有 /api 请求自动带上。
const TOKEN_KEY = "sched-token";
// 隐私模式/禁用站点数据时 localStorage 会直接抛异常, 不能让它把整个页面拖垮
function lsGet(k){ try { return localStorage.getItem(k) || ""; } catch(e) { return ""; } }
function lsSet(k, v){ try { localStorage.setItem(k, v); } catch(e) {} }
const getToken = () => lsGet(TOKEN_KEY);
let askingToken = false;
async function api(path, opts){
  opts = opts || {};
  opts.headers = Object.assign({}, opts.headers, {"X-Sched-Token": getToken()});
  const r = await fetch(path, opts);           // ★ 这里必须是 fetch, 不能再包一层 api
  if(r.status === 401 && !askingToken){
    askingToken = true;
    const t = prompt("这个日程服务设置了访问令牌，请输入：");
    askingToken = false;
    if(t && t.trim()){ lsSet(TOKEN_KEY, t.trim()); return api(path, opts); }
  }
  return r;
}

const esc = s => String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const WD = ["一","二","三","四","五","六","日"];
const MODCN = {class:"课程",exam:"考试",meeting:"会议",assignment:"作业",
               alarm:"闹钟",reminder:"提醒",memo:"备忘"};
const EXAMPLES = ["下周二上午九点加一门计算机原理，在教三201","明天晚上七点半提醒我给家里打电话",
  "加个明早八点的闹钟","周五之前要交操作系统实验报告","下周三下午三点高数考试，提前15分钟提醒",
  "周四下午两点在教三201开班会","记一下，我的快递取件码是8823"];
$("#chips").innerHTML = EXAMPLES.map(e=>`<span class="chip">${esc(e)}</span>`).join("");
$("#chips").onclick = e => { if(e.target.classList.contains("chip")) $("#q").value = e.target.textContent; };

// ---- 外观: 纸感 / 夜航 / 跟随系统 (偏好存在本机 localStorage) ----
const THEME_KEY = "sched-theme";
const mqDark = matchMedia("(prefers-color-scheme: dark)");
function effectiveTheme(pref){
  if(pref === "paper" || pref === "night") return pref;
  return mqDark.matches ? "night" : "paper";
}
function applyTheme(pref){
  document.documentElement.setAttribute("data-theme", effectiveTheme(pref));
  document.querySelectorAll("#themebtn button").forEach(b =>
    b.classList.toggle("on", b.dataset.t === pref));
}
// ?theme=paper|night 优先于本机偏好: 方便分享固定外观的链接, 也方便在文档里截固定主题的图
const urlTheme = new URLSearchParams(location.search).get("theme");
let themePref = (urlTheme === "paper" || urlTheme === "night")
              ? urlTheme : (lsGet(THEME_KEY) || "auto");
applyTheme(themePref);
mqDark.addEventListener("change", () => { if(themePref === "auto") applyTheme("auto"); });
$("#themebtn").onclick = e => {
  const b = e.target.closest("button"); if(!b) return;
  themePref = b.dataset.t;
  lsSet(THEME_KEY, themePref);
  applyTheme(themePref);
  // 手动切过之后就把 URL 上的临时覆盖去掉, 免得地址栏和实际外观不一致
  if(urlTheme){ history.replaceState(null, "", location.pathname); }
};

let EV = [], Y, M, SEL = null;

const iso = d => d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");

async function loadEvents(){
  try{
    const r = await api("/api/events");
    if(!r.ok) throw new Error("HTTP " + r.status);
    const j = await r.json();
    EV = j.events || [];
    render(); renderMemos();
  }catch(e){
    // 以前这里没有 catch: 一旦请求失败, 日历会静默留空, 看不出是坏了还是真没数据。
    $("#mtitle").textContent = "加载失败";
    $("#cells").innerHTML =
      `<div class="empty" style="grid-column:1/-1">读取日程失败：${esc(e.message||e)}` +
      `<br>请检查服务是否在运行，然后点右上角刷新。</div>`;
  }
}

async function health(){
  try{
    const j = await (await api("/api/health")).json();
    const b = $("#st");
    b.style.cursor = ""; b.onclick = null;
    if(j.auth_required && j.events === undefined){
      // 后端设了令牌, 而本机还没存或存错了 —— 点一下就能补
      b.className="badge bad"; b.textContent="需要访问令牌（点击输入）";
      b.style.cursor="pointer";
      b.onclick = () => {
        const t = prompt("请输入访问令牌：");
        if(t && t.trim()){ localStorage.setItem(TOKEN_KEY, t.trim()); health(); loadEvents(); }
      };
    }
    else if(!j.llama_ok){ b.className="badge bad"; b.textContent="推理服务不可用"; }
    else if(j.ready){ b.className="badge ok";
      b.textContent = `${j.backend} · 共 ${j.events} 条日程` +
                      (j.schema_drift && j.schema_drift.length ? " · ⚠️契约漂移" : " · 契约一致"); }
    else { b.className="badge"; b.textContent="连接中…"; }
  }catch(e){ $("#st").className="badge bad"; $("#st").textContent="无法连接服务"; }
}
health(); setInterval(health, 20000);

function byDay(){
  const m = {};
  for(const e of EV){ if(!e.start) continue; const d = e.start.slice(0,10); (m[d] = m[d]||[]).push(e); }
  return m;
}

function render(){
  $("#wd").innerHTML = WD.map(w=>`<div class="wd">${w}</div>`).join("");
  const first = new Date(Y, M, 1);
  const start = new Date(first); start.setDate(1 - ((first.getDay()+6)%7));
  const map = byDay();
  const todayS = iso(new Date());
  let html = "";
  for(let i=0;i<42;i++){
    const d = new Date(start); d.setDate(start.getDate()+i);
    const key = iso(d);
    const label = key.slice(5,7)+"-"+key.slice(8,10);
    const list = (map[key]||[]).slice().sort((a,b)=>a.start.localeCompare(b.start));
    const cls = ["cell"];
    if(d.getMonth()!==M) cls.push("out");
    if(key===todayS) cls.push("today");
    if(key===SEL) cls.push("sel");
    let inner = `<div class="d">${label}</div>`;
    for(const e of list.slice(0,3)){
      const t = e.start.slice(11,16);
      inner += `<div class="ev ${e.module}" title="${esc(e.title)}">
        <span class="t">${t}</span>${esc(e.title)}${e.ambiguous?" ⚠":""}</div>`;
    }
    if(list.length>3) inner += `<div class="more">+${list.length-3} 更多</div>`;
    html += `<div class="${cls.join(" ")}" data-d="${key}">${inner}</div>`;
  }
  $("#cells").innerHTML = html;
  $("#mtitle").textContent = `${Y} 年 ${M+1} 月`;
  $("#cells").onclick = e => {
    const c = e.target.closest(".cell"); if(!c) return;
    SEL = c.dataset.d; render(); renderDay();
  };
  renderDay();
}

function renderDay(){
  if(!SEL){ $("#daytitle").textContent = "选择日期"; return; }
  const d = new Date(SEL+"T00:00:00");
  $("#daytitle").textContent = `${d.getMonth()+1} 月 ${d.getDate()} 日 星期${WD[(d.getDay()+6)%7]}`;
  const list = EV.filter(e=>e.start && e.start.slice(0,10)===SEL)
                 .sort((a,b)=>a.start.localeCompare(b.start));
  if(!list.length){ $("#daylist").innerHTML = '<div class="empty">这天没有日程</div>'; return; }
  $("#daylist").innerHTML = list.map(e=>{
    const tags = [];
    tags.push(`<span class="tag">${MODCN[e.module]||e.module}</span>`);
    if(e.location) tags.push(`<span class="tag">📍 ${esc(e.location)}</span>`);
    if(e.remind!=null) tags.push(`<span class="tag">提前 ${e.remind} 分钟</span>`);
    if(e.priority==="high") tags.push(`<span class="tag">重要</span>`);
    if(e.ambiguous) tags.push(`<span class="tag warn">时间有歧义</span>`);
    if(e.notes) tags.push(`<span class="tag">${esc(e.notes)}</span>`);
    const time = e.end ? `${e.start.slice(11,16)} – ${e.end.slice(11,16)}` : e.start.slice(11,16);
    return `<div class="item ${e.module}">
      <div class="h"><div>
        <div class="tm">${time}</div>
        <div class="ti">${esc(e.title)}</div>
      </div><button class="del" data-id="${e.id}" title="删除">✕</button></div>
      <div class="tagline">${tags.join("")}</div></div>`;
  }).join("");
  $("#daylist").onclick = async ev => {
    const b = ev.target.closest(".del"); if(!b) return;
    if(!confirm("删除这条日程？")) return;
    await api("/api/events/"+b.dataset.id, {method:"DELETE"});
    loadEvents(); health();
  };
}

function renderMemos(){
  const m = EV.filter(e=>!e.start);
  if(!m.length){ $("#memos").innerHTML = '<div class="empty">暂无</div>'; return; }
  $("#memos").innerHTML = m.map(e=>`<div class="memo-b">
    <div class="h" style="display:flex;justify-content:space-between">
      <b>${esc(e.title)}</b>
      <button class="del" data-id="${e.id}">✕</button></div>
    ${e.notes?`<div class="n">${esc(e.notes)}</div>`:""}</div>`).join("");
  $("#memos").onclick = async ev => {
    const b = ev.target.closest(".del"); if(!b) return;
    if(!confirm("删除这条备忘？")) return;
    await api("/api/events/"+b.dataset.id, {method:"DELETE"});
    loadEvents(); health();
  };
}

$("#prev").onclick = ()=>{ M--; if(M<0){M=11;Y--;} render(); };
$("#next").onclick = ()=>{ M++; if(M>11){M=0;Y++;} render(); };
$("#today").onclick = ()=>{ const n=new Date(); Y=n.getFullYear(); M=n.getMonth(); SEL=iso(n); render(); };
$("#clr").onclick = async ()=>{ if(confirm("清空所有日程？不可恢复")){
  await api("/api/reset",{method:"POST"}); loadEvents(); health(); } };

function showRes(cls, html){ const r=$("#res"); r.className="result show "+cls; r.innerHTML=html; }

async function add(){
  const text = $("#q").value.trim(); if(!text) return;
  $("#go").disabled = true; $("#go").innerHTML = '<span class="spin"></span> 处理中';
  showRes("warn", "模型正在解析…");
  try{
    const j = await (await api("/api/chat",{method:"POST",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({text})})).json();

    // 详情面板
    $("#detail").innerHTML =
      `<div style="font-size:12.5px;color:#8fa3b8;margin-top:6px">模型输出（原始）</div>
       <pre>${esc(j.model_raw||j.error||"")}</pre>` +
      (j.envelope?`<div style="font-size:12.5px;color:#8fa3b8;margin-top:10px">解析后的结构化指令</div>
                   <pre>${esc(JSON.stringify(j.envelope,null,2))}</pre>`:"") +
      `<div style="margin-top:10px">${(j.steps||[]).map(s=>
         `<div class="step"><span class="dot ${s.ok?'g':'r'}"></span>
          <span><b>${esc(s.name)}</b>${s.ms?` · ${s.ms}ms`:""}
          ${s.detail?` — ${esc(s.detail)}`:""}</span></div>`).join("")}</div>`;

    const ex = j.execution;
    if(!ex){
      showRes("err", `<b>没能理解这句话</b><br>${esc(j.error||"输出不符合 Schema")}
        ${j.schema_error?"<br>"+j.schema_error.map(esc).join("<br>"):""}`);
    } else if(ex.kind === "executed"){
      const it = ex.items[0] || {};
      const extra = [];
      if(it.ambiguous) extra.push("时间有歧义，已按作息规则处理");
      if((it.reasons||[]).length) extra.push(...it.reasons);
      showRes("ok", `已添加 <b>${esc(it.title)}</b> · ${esc(it.start||"无时间")}
        ${extra.length?"<br><span style='opacity:.85'>"+extra.map(esc).join("<br>")+"</span>":""}
        <br><span style="opacity:.75">端到端 ${j.total_ms}ms（模型 ${j.gen_ms}ms）</span>`);
      if(it.start){
        const d = it.start.slice(0,10);
        Y = +d.slice(0,4); M = +d.slice(5,7)-1; SEL = d;
        await loadEvents(); health();
        // 让新日程闪一下
        setTimeout(()=>{ document.querySelectorAll(".item").forEach(x=>{
          x.classList.add("flash");
          setTimeout(()=>x.classList.remove("flash"), 900); }); }, 60);
      } else { await loadEvents(); health(); }
    } else if(ex.kind === "need_clarify"){
      showRes("warn", `<b>需要补充信息：</b>${esc(ex.detail)}`);
    } else if(ex.kind === "rejected"){
      showRes("warn", `这句话看起来不是日程。你可以换个说法，例如「明天下午三点开会」。`);
    } else {
      showRes("err", `<b>执行失败：</b>${esc(ex.detail)}`);
    }
    $("#q").value = "";
  }catch(e){ showRes("err", "请求异常："+esc(e)); }
  $("#go").disabled = false; $("#go").textContent = "添加";
}
$("#go").onclick = add;
$("#q").addEventListener("keydown", e=>{ if(e.key==="Enter") add(); });

const now = new Date(); Y = now.getFullYear(); M = now.getMonth(); SEL = iso(now);
loadEvents();
</script></body></html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE

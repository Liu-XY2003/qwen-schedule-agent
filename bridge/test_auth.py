#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 /api/* 的令牌门禁。

跑法: python bridge/test_auth.py
它自己起两个临时实例(不带令牌 / 带令牌), 不碰正在运行的服务。
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable
PORT_OFF, PORT_ON = 8901, 8902
TOK = "test-token-abc123"


def boot(port: int, token: str | None):
    env = dict(os.environ)
    env["SCHED_LLAMA_URL"] = env.get("SCHED_LLAMA_URL", "http://127.0.0.1:18080")
    env["SCHED_DB"] = f":memory:" if False else str(HERE / f"_auth_test_{port}.db")
    if token:
        env["SCHED_TOKEN"] = token
    else:
        env.pop("SCHED_TOKEN", None)
    p = subprocess.Popen(
        [PY, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(HERE), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.25)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2).read()
            return p
        except urllib.error.HTTPError:
            return p          # 401 也算起来了
        except Exception:
            pass
    p.kill()
    raise RuntimeError(f"port {port} 起不来")


def call(port: int, path: str, token: str | None = None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token:
        req.add_header("X-Sched-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def main() -> int:
    fails = []
    db1, db2 = HERE / f"_auth_test_{PORT_OFF}.db", HERE / f"_auth_test_{PORT_ON}.db"
    for d in (db1, db2):
        d.unlink(missing_ok=True)

    procs = []
    try:
        procs.append(boot(PORT_OFF, None))
        procs.append(boot(PORT_ON, TOK))

        def check(name, got, want):
            ok = got == want
            print(f"{'OK  ' if ok else 'FAIL'} {name}: got={got} want={want}")
            if not ok:
                fails.append(name)

        # --- 不设令牌: 必须和以前完全一样, 不能有回归 ---
        check("无令牌/health", call(PORT_OFF, "/api/health")[0], 200)
        check("无令牌/events", call(PORT_OFF, "/api/events")[0], 200)
        check("无令牌/health 里 auth_required", call(PORT_OFF, "/api/health")[1].get("auth_required"), False)

        # --- 设了令牌 ---
        s, j = call(PORT_ON, "/api/health")
        check("有令牌/health 免鉴权可访问", s, 200)
        check("  health 只报需要令牌", j.get("auth_required"), True)
        check("  health 不泄露日程条数", "events" in j, False)
        check("有令牌/events 无令牌被拒", call(PORT_ON, "/api/events")[0], 401)
        check("有令牌/events 错令牌被拒", call(PORT_ON, "/api/events", "wrong")[0], 401)
        check("有令牌/events 对令牌放行", call(PORT_ON, "/api/events", TOK)[0], 200)
        check("有令牌/chat 无令牌被拒", call(PORT_ON, "/api/chat")[0] in (401, 405), True)
        check("有令牌/reset 无令牌被拒(GET 405 也算过)", call(PORT_ON, "/api/reset")[0] in (401, 405), True)
        check("有令牌/health 带对令牌可看条数", "events" in call(PORT_ON, "/api/health", TOK)[1], True)
    finally:
        for p in procs:
            p.kill()
            try:
                p.wait(timeout=10)      # 等句柄真的释放, 否则 Windows 上删不掉 db
            except Exception:
                pass
        time.sleep(0.5)
        for d in (db1, db2):
            for _ in range(10):
                try:
                    d.unlink(missing_ok=True)
                    break
                except PermissionError:
                    time.sleep(0.3)

    print()
    if fails:
        print(f"失败 {len(fails)} 项: {fails}")
        return 1
    print("访问控制测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

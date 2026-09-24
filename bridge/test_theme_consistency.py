#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主题一致性检查 —— 防止两端口径走散。

检查项:
  1. 生成物是最新的 (等价于 gen_theme.py --check)
  2. 网页 inline <style> 里用到的每个 var(--x) 都在 theme.css 里有定义
     (拼错变量名不会报错, 只会静默失效 —— 这种 bug 靠肉眼很难发现)
  3. 网页 inline <style> 里没有残留硬编码颜色
  4. 两个主题定义的变量集合完全一致 (少一个就会在某个主题下掉色)
  5. 安卓 Tokens.kt 的两套主题字段齐全, 且模块色数量 == 7

跑法: python bridge/test_theme_consistency.py
"""
import os
import re
import subprocess
import sys
from pathlib import Path

BRIDGE = Path(__file__).resolve().parent
ROOT = BRIDGE.parent
sys.path.insert(0, str(ROOT / "theme"))

fails: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    print(f"{'OK  ' if cond else 'FAIL'} {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


# ---------------------------------------------------------------- 1. 生成物最新
r = subprocess.run([sys.executable, str(ROOT / "theme" / "gen_theme.py"), "--check"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
check("生成物与 tokens.json 同步", r.returncode == 0, (r.stdout or "") + (r.stderr or ""))

css_path = BRIDGE / "static" / "theme.css"
css = css_path.read_text(encoding="utf-8")
app = (BRIDGE / "app.py").read_text(encoding="utf-8")

# ---------------------------------------------------------------- 2/3. inline style
i = app.index("<style>")
j = app.index("</style>", i)
inline = app[i:j]

defined = set(re.findall(r"(--[\w-]+)\s*:", css))
# --mc 这类"局部别名"是在页内 style 里现定义现用的 (--mc:var(--m-class)), 也要算数
defined |= set(re.findall(r"(--[\w-]+)\s*:", inline))
used = set(re.findall(r"var\((--[\w-]+)", inline))
missing = sorted(used - defined)
check("页内引用的 CSS 变量都有定义", not missing, f"未定义: {missing}")

hardcoded = re.findall(r"#[0-9a-fA-F]{3,8}\b", inline)
check("页内样式无硬编码颜色", not hardcoded, f"残留: {sorted(set(hardcoded))}")

# ---------------------------------------------------------------- 4. 两套主题变量齐全
# 注意两点:
#   1. 默认主题的选择器是 ":root,:root[data-theme=\"night\"]" (同时挂裸 :root 上),
#      所以不能锚定 "^:root\[", 要允许选择器里有多个逗号分隔项。
#   2. 生成器还会输出 ":root[data-theme=...]{color-scheme:dark}" 这种单行块。
#      因此要求 "{" 后面必须紧跟换行, 否则单行块会把后面整个 night 块吞进 body。
blocks = {}
for m in re.finditer(r'^([^\n{}]*:root[^\n{}]*)\{\n(.*?)^\}', css, re.S | re.M):
    selector, body = m.group(1), m.group(2)
    keys = re.findall(r'data-theme="(\w+)"', selector)
    if not keys:
        continue                      # 纯 :root 兜底块, 不进对比
    for k in keys:
        blocks.setdefault(k, set()).update(re.findall(r"(--[\w-]+)\s*:", body))
check("解析到 paper / night 两套主题", set(blocks) == {"paper", "night"}, f"实际: {sorted(blocks)}")
if len(blocks) == 2:
    a, b = (blocks.get("paper", set()), blocks.get("night", set()))
    check("两套主题变量集合一致", a == b,
          f"paper 独有 {sorted(a-b)}, night 独有 {sorted(b-a)}")

# ---------------------------------------------------------------- 5. 安卓 Tokens.kt
# 安卓在另一个仓库。开源后后端仓库单独克隆时这里不存在, 跳过而不是误报失败。
kt_env = os.environ.get("SCHED_KT_OUT")
kt_path = (Path(kt_env) if kt_env else
           ROOT.parent / "AI_ScheduleAssistant" / "app" / "src" / "main" / "java"
           / "com" / "liuxinyang" / "ai_scheduleassistant" / "ui" / "theme" / "Tokens.kt")
if kt_path.exists():
    kt = kt_path.read_text(encoding="utf-8")
    for obj in ("PAPER", "NIGHT"):
        check(f"Tokens.{obj} 存在", f"val {obj} = ThemePalette(" in kt)
    n_mod = kt.count("Color(0xFF")
    # 每套 12 个语义色 + 7 个模块色 = 19; 两套 38
    check("Tokens.kt 颜色数量符合预期 (19/套)", n_mod == 38, f"实际 {n_mod}")
    check("Tokens.kt 标注为自动生成", "AUTO-GENERATED" in kt)
    check("Tokens.kt 默认主题与 tokens.json 一致", 'DEFAULT_KEY = "night"' in kt)
else:
    print(f"跳过安卓检查: 未找到 {kt_path}")
    print("  (这是正常的 —— 后端仓库独立克隆时不含安卓工程)")

print()
if fails:
    print(f"失败 {len(fails)} 项: {fails}")
    sys.exit(1)
print("主题一致性检查全部通过")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""匿名评审前的个人信息扫描。

赛事（全国大学生软件创新大赛等）普遍要求**匿名评审**：
提交材料里不得出现校名、姓名、指导老师、学院、专业、班级。
开源仓库和截图同样属于"材料"，所以要先扫干净。

扫描项：
  · 邮箱 / 手机号
  · 真实姓名（含拼音变体）
  · 学校 / 学院 / 专业关键词
  · 本机用户名出现在路径里
  · git 提交者身份
  · 截图里的敏感内容（只能靠人工看，这里列清单）
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

# ★ 不能写死本机绝对路径: 写死后在 CI（Linux runner）上这些路径都不存在,
#   脚本会把所有根目录跳过, 报 "HIGH 0 处" 然后 exit 0 —— 检查形同虚设。
#   改为: 默认扫脚本所在仓库, 另外把同级的 Android 仓库也带上(如果存在)。
_HERE = Path(__file__).resolve().parent.parent
_SIBLINGS = [_HERE.parent / "AI_ScheduleAssistant"]
ROOTS = [_HERE] + [d for d in _SIBLINGS if d.is_dir()]
if os.environ.get("PRIVACY_ROOTS"):
    ROOTS = [Path(x) for x in os.environ["PRIVACY_ROOTS"].split(os.pathsep) if x]
SKIP_DIRS = {".git", "build", ".gradle", ".idea", ".kotlin", "_archive", "_release",
             "backup", "bench", "models", "node_modules", "__pycache__", ".dsh",
             "external", "generated",
             # 虚拟环境里全是第三方库, 扫它没有意义（会有上千条 __author__ 邮箱误报）
             ".venv", "venv", ".venv-planner", "site-packages"}
TEXT_EXT = {".md", ".py", ".kt", ".kts", ".ps1", ".sh", ".json", ".xml", ".yml",
            ".yaml", ".toml", ".properties", ".txt", ".service", ".gitignore",
            ".gitattributes", ".cfg", ".ini", ""}

# 分级: HIGH = 真能定位到具体的人, CI 里必须失败;
#       INFO = 可能相关但通常无害（示例数据、通用词汇），只提示。
# 不分级的话, 一堆"学院""取件码"之类的误报会让这个工具在 CI 里没法用。
HIGH_RULES = [
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    # 真实身份证 = 6 位地区码 + 8 位出生日期 + 3 位顺序码 + 1 位校验码。
    # 只数位宽会把 SHA256 哈希里的连续数字也误判成身份证。
    ("身份证号", re.compile(
        r"(?<!\d)[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")),
    ("可能的真实姓名(拼音)", re.compile(r"\b(liu[\s_-]?xiang[\s_-]?yang|zhang[\s_-]?san)\b", re.I)),
    ("本机用户名路径", re.compile(r"[\\/](Users|home)[\\/](zaoch|zao|liuxinyang)\b", re.I)),
    ("学号样式", re.compile(r"\b(20\d{8}|U20\d{6})\b")),
]

INFO_RULES = [
    ("学校/学院字样", re.compile(
        r"(北京[^\s,，。]{0,6}(大学|学院)|XX大学|学院|教务处|校团委|软件学院)")),
    ("像凭据的示例数据", re.compile(r"(门禁|取件码|密码)[^\n]{0,20}\d{3,}")),
]

RULES = HIGH_RULES + INFO_RULES
HIGH_NAMES = {n for n, _ in HIGH_RULES}


def walk(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() not in TEXT_EXT and p.name not in (".gitignore", ".gitattributes"):
            continue
        if p.stat().st_size > 2 * 1024 * 1024:
            continue
        yield p


def scan_files():
    for root in ROOTS:
        if not root.exists():
            continue
        yield from walk(root)


def scan():
    total = 0
    by_rule: dict[str, list[str]] = {}
    for root in ROOTS:
        if not root.exists():
            continue
        for p in walk(root):
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").split("\n")
            except Exception:
                continue
            for i, line in enumerate(lines, 1):
                if "audit_secrets" in str(p) or "privacy_audit" in str(p) or "_privacy" in str(p):
                    continue
                for name, rx in RULES:
                    m = rx.search(line)
                    if m:
                        by_rule.setdefault(name, []).append(
                            f"{p.relative_to(root.parent)}:{i}  {line.strip()[:100]}")
                        total += 1
    return total, by_rule


def git_authors():
    out = []
    for root in ROOTS:
        if not (root / ".git").exists():
            continue
        r = subprocess.run(["git", "-C", str(root), "log", "--format=%an <%ae>"],
                           capture_output=True, text=True, encoding="utf-8")
        seen = set()
        for line in (r.stdout or "").splitlines():
            if line and line not in seen:
                seen.add(line)
                out.append(f"{root.name}: {line}")
    return out


total, by_rule = scan()
high_hits = sum(len(v) for k, v in by_rule.items() if k in HIGH_NAMES)

# ★ 什么都没扫到 = 检查没生效, 必须报错。
#   第一版在 CI 上就是因为路径不存在导致 0 文件被扫, 却安静地"通过"了。
scanned = sum(1 for _ in scan_files())
if scanned == 0:
    print(f"扫描了 0 个文件 —— 检查没有生效！ROOTS={ROOTS}")
    sys.exit(2)
print(f"（已扫描 {scanned} 个文本文件）")

print("=" * 78)
print("个人信息扫描")
print("=" * 78)
if not by_rule:
    print("未发现明显个人信息")
for name, hits in by_rule.items():
    level = "HIGH" if name in HIGH_NAMES else "提示"
    print(f"\n[{level}] {name}  {len(hits)} 处")
    for h in hits[:12]:
        print("   ", h)
    if len(hits) > 12:
        print(f"    … 另有 {len(hits) - 12} 处")

print("\n" + "=" * 78)
print("git 提交者身份（匿名评审时这也是可识别信息）")
print("=" * 78)
for a in git_authors():
    print("  ", a)

print("\n" + "=" * 78)
print("截图里的人工检查项（脚本查不到，必须看图）")
print("=" * 78)
for root in ROOTS:
    for p in sorted(root.rglob("*.png")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        print("  ", p.relative_to(root.parent))

print(f"\n合计 HIGH {high_hits} 处 / 提示 {total - high_hits} 处")
if high_hits:
    print("存在能定位到个人的信息, 匿名评审前必须处理。")
    sys.exit(1)
print("无 HIGH 项; 提示项请自行确认（示例数据、通用词汇通常可保留）。")
sys.exit(0)

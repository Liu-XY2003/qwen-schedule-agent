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

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

ROOTS = [
    Path(r"D:\Projects\qwen-local-tool-agent"),
    Path(r"D:\Projects\AI_ScheduleAssistant"),
]
SKIP_DIRS = {".git", "build", ".gradle", ".idea", ".kotlin", "_archive", "_release",
             "backup", "bench", "models", "node_modules", "__pycache__", ".dsh",
             "external", "generated"}
TEXT_EXT = {".md", ".py", ".kt", ".kts", ".ps1", ".sh", ".json", ".xml", ".yml",
            ".yaml", ".toml", ".properties", ".txt", ".service", ".gitignore",
            ".gitattributes", ".cfg", ".ini", ""}

RULES = [
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("身份证号", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("可能的真实姓名(拼音)", re.compile(r"\b(liu[\s_-]?xiang[\s_-]?yang|zhang[\s_-]?san)\b", re.I)),
    ("本机用户名路径", re.compile(r"[\\/](Users|home)[\\/](zaoch|zao|liuxinyang)\b", re.I)),
    ("学校/学院关键词", re.compile(
        r"(北京[^\s,，。]{0,6}(大学|学院)|XX大学|学院|教务处|校团委|软件学院)")),
    ("学号样式", re.compile(r"\b(20\d{8}|U20\d{6})\b")),
    ("实验室/门禁/密码", re.compile(r"(门禁|取件码|密码)[^\n]{0,20}\d{3,}")),
]


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
print("=" * 78)
print("个人信息扫描")
print("=" * 78)
if not by_rule:
    print("未发现明显个人信息")
for name, hits in by_rule.items():
    print(f"\n[{name}]  {len(hits)} 处")
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

print(f"\n合计命中 {total} 处")
sys.exit(1 if total else 0)

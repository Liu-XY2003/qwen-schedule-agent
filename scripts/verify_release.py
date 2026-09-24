#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验已发布的 Release 资产与本地文件是否一致。

为什么需要它：`gh release create` 传完后如果某个资产上传中断，命令的退出码
不一定能反映出来，而 Release 页面上少一个 600MB 的文件是很容易被忽略的。
这里用 GitHub API 拿到远端资产，逐个比对大小，并尽可能比对 SHA256。

GitHub 会为较新的资产提供 `digest` 字段（形如 `sha256:...`），有的话就直接
比哈希，不用下载 1GB；没有就退化成只比大小，并明确说明这一点。

用法:
    python scripts/verify_release.py v0.1.0
    python scripts/verify_release.py v0.1.0 --repo Liu-XY2003/AI-ScheduleAssistant --stage <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(
    sys.stdout, "reconfigure") else None

REPOS = {
    "Liu-XY2003/qwen-schedule-agent": r"D:\Projects\qwen-local-tool-agent\_release\backend",
    "Liu-XY2003/AI-ScheduleAssistant": r"D:\Projects\AI_ScheduleAssistant\_release",
}


def find_gh() -> str:
    from shutil import which
    p = which("gh")
    if p:
        return p
    for c in (r"C:\Program Files\GitHub CLI\gh.exe",
              r"C:\Program Files (x86)\GitHub CLI\gh.exe",
              str(Path.home() / "AppData/Local/Programs/GitHub CLI/gh.exe")):
        if Path(c).is_file():
            return c
    raise SystemExit("找不到 gh。装一个: winget install --id GitHub.cli")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--repo", action="append", help="可重复；默认两个仓库都查")
    ap.add_argument("--stage", help="本地资产目录（只在使用 --repo 时有效）")
    args = ap.parse_args()

    gh = find_gh()
    repos = args.repo or list(REPOS)
    failures: list[str] = []

    for repo in repos:
        print(f"\n{'=' * 78}\n{repo}  {args.tag}\n{'=' * 78}")
        stage = Path(args.stage) if (args.stage and args.repo) else Path(REPOS.get(repo, "."))

        r = subprocess.run([gh, "api", f"repos/{repo}/releases/tags/{args.tag}"],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            print(f"  取 Release 失败: {(r.stderr or '').strip()[:200]}")
            failures.append(f"{repo}: 取不到 Release")
            continue

        rel = json.loads(r.stdout)
        print(f"  标题     : {rel.get('name')}")
        print(f"  草稿/预发: draft={rel.get('draft')} prerelease={rel.get('prerelease')}")
        print(f"  发布时间 : {rel.get('published_at')}")
        print(f"  说明长度 : {len(rel.get('body') or '')} 字符")

        assets = rel.get("assets") or []
        if not assets:
            print("  !! 没有任何资产")
            failures.append(f"{repo}: 无资产")
            continue

        print(f"  资产 {len(assets)} 个:")
        for a in sorted(assets, key=lambda x: x["name"]):
            name, size = a["name"], a["size"]
            local = stage / name
            digest = (a.get("digest") or "").removeprefix("sha256:")
            marks = []
            if not local.is_file():
                marks.append("本地无此文件")
            else:
                if local.stat().st_size != size:
                    marks.append(f"大小不符(本地 {local.stat().st_size})")
                if digest:
                    marks.append("SHA256 一致" if sha256(local) == digest else "!! SHA256 不符")
                else:
                    marks.append("远端无 digest，仅比了大小")
            status = "OK" if all("不符" not in m and "无此文件" not in m for m in marks) else "FAIL"
            if status == "FAIL":
                failures.append(f"{repo}/{name}: {'; '.join(marks)}")
            print(f"    [{status}] {name:44} {size/1024/1024:8.2f} MB  {'; '.join(marks)}")

    print()
    if failures:
        print(f"校验失败 {len(failures)} 项:")
        for f in failures:
            print("  -", f)
        return 1
    print("Release 校验全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

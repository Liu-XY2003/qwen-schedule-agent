#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""严格校验: 数据集里的 assistant 输出是否 100% 符合 schema/schedule_command.v1.json"""
import json
from collections import Counter

import jsonschema
from jsonschema import Draft202012Validator

SCHEMA = r"D:\Projects\qwen-local-tool-agent\schema\schedule_command.v1.json"
DATA = r"D:\Projects\qwen-local-tool-agent\data\generated"

schema = json.load(open(SCHEMA, encoding="utf-8"))
Draft202012Validator.check_schema(schema)
v = Draft202012Validator(schema)
print("JSON Schema 自身合法:", schema["title"])

# 检查 validator 用的是哪个 draft
print("validator:", v.__class__.__name__)

# 顺便把 schema 里的枚举打出来, 作为"工具接口契约"
cmd = schema["properties"]["commands"]["items"]
print("\n--- 工具接口契约 (从 schema 导出) ---")
print("status 枚举 :", schema["properties"]["status"]["enum"])
print("module 枚举 :", cmd["properties"]["module"]["enum"])
print("action 枚举 :", cmd["properties"]["action"]["enum"])
print("command 必填:", cmd["required"])
print("when 字段   :", list(cmd["properties"]["when"]["properties"]))
print("period 枚举 :", cmd["properties"]["when"]["properties"]["period"]["enum"])
print("date_kind   :", cmd["properties"]["when"]["properties"]["date_kind"]["enum"])

for split in ("train", "test"):
    path = f"{DATA}\\{split}.jsonl"
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    bad = []
    enum_hits = Counter()
    for i, r in enumerate(rows):
        out = r["messages"][2]["content"]
        try:
            obj = json.loads(out)
        except Exception as e:
            bad.append((i, "JSON解析失败", str(e), out[:120]))
            continue
        errs = sorted(v.iter_errors(obj), key=lambda e: e.path)
        if errs:
            bad.append((i, errs[0].validator + " @ " + "/".join(map(str, errs[0].path)),
                        errs[0].message, out[:200]))
        else:
            enum_hits[obj["status"]] += 1

    print(f"\n===== {split}.jsonl ({len(rows)} 条) =====")
    print(f"符合 schema: {len(rows)-len(bad)}/{len(rows)} = {100*(len(rows)-len(bad))/len(rows):.2f}%")
    print("status 分布:", dict(enum_hits))
    if bad:
        print(f"不合规 {len(bad)} 条, 前 5:")
        for i, why, msg, snippet in bad[:5]:
            print(f"  #{i} {why}: {msg}")
            print(f"      {snippet}")
    else:
        print("✅ 全部通过 JSON Schema 校验")

# 额外: 检查是否所有 label 字段都能被 schema 表达(无遗漏字段)
all_keys, all_when_keys = set(), set()
for split in ("train", "test"):
    for l in open(f"{DATA}\\{split}.jsonl", encoding="utf-8"):
        if not l.strip():
            continue
        o = json.loads(json.loads(l)["messages"][2]["content"])
        for c in o.get("commands", []):
            all_keys |= set(c)
            all_when_keys |= set(c.get("when", {}))
print("\n--- 标签里实际出现过的字段 ---")
print("command 字段:", sorted(all_keys))
print("when 字段   :", sorted(all_when_keys))
allowed_cmd = set(cmd["properties"])
allowed_when = set(cmd["properties"]["when"]["properties"])
print("schema 允许  :", sorted(allowed_cmd))
print("越界 command:", sorted(all_keys - allowed_cmd) or "无")
print("越界 when   :", sorted(all_when_keys - allowed_when) or "无")

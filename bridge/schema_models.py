#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具接口的 Pydantic 定义 —— MCP Layer 4 的落地。

这份模型和 schema/schedule_command.v1.json 必须永远保持一致。
check_drift() 会把两者的字段名/枚举/必填项逐项对比, 任何漂移立刻报出来。
"""
from __future__ import annotations

import json
from typing import Literal, Optional

from pydantic import BaseModel, Field
import _console  # noqa: F401  (Windows 控制台 UTF-8 兜底)

MODULE = Literal["class", "exam", "meeting", "assignment", "alarm", "reminder", "memo"]
ACTION = Literal["add", "update", "delete", "query", "complete"]
STATUS = Literal["ok", "clarify", "reject"]
DATE_KIND = Literal["absolute", "offset_day", "weekday", "month_day", "unspecified"]
PERIOD = Literal["am", "pm", "none"]
FUZZY = Literal["morning", "noon", "afternoon", "evening", "night", "none"]
PRIORITY = Literal["low", "normal", "high"]


class When(BaseModel):
    date_kind: Optional[DATE_KIND] = None
    date_value: Optional[str] = None
    # 这里故意放宽边界: JSON Schema 里的 -2..4 是"训练分布/约束解码"的范围,
    # 而这一层是"结构校验"。若模型给出了超范围的值(实测会输出 week_offset=5),
    # 应该让它通过结构校验、由执行层给出可读的追问, 而不是直接报校验失败。
    week_offset: Optional[int] = Field(default=None, ge=-99, le=99)
    month_offset: Optional[int] = Field(default=None, ge=-99, le=99)
    time: Optional[str] = None
    period: Optional[PERIOD] = None
    fuzzy: Optional[FUZZY] = None
    duration_min: Optional[int] = Field(default=None, ge=1, le=1440)


class Command(BaseModel):
    module: MODULE
    action: ACTION
    title: str = Field(max_length=60)
    when: Optional[When] = None
    remind_before_min: Optional[int] = Field(default=None, ge=0, le=10080)
    location: Optional[str] = Field(default=None, max_length=60)
    priority: Optional[PRIORITY] = None
    notes: Optional[str] = Field(default=None, max_length=200)
    target_ref: Optional[str] = None


class Envelope(BaseModel):
    status: STATUS
    # 与 Schema 一致: commands 是必填(reject 时给空数组), 不给默认值,
    # 这样模型漏输出 commands 会被校验抓住, 而不是静默当成空列表
    commands: list[Command] = Field(max_length=5)
    question: Optional[str] = Field(default=None, max_length=80)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


# ------------------------------------------------------------- 契约漂移检查

def _shape(node: dict) -> dict:
    """从 JSON Schema 抽出"契约要点": 字段名 / 枚举 / 必填"""
    out = {"fields": {}, "required": sorted(node.get("required", []))}
    for k, v in (node.get("properties") or {}).items():
        if "enum" in v:
            out["fields"][k] = {"enum": sorted(v["enum"])}
        elif v.get("type") == "array":
            item = v.get("items") or {}
            out["fields"][k] = {"array_of": _shape(item) if item.get("properties") else
                                ({"enum": sorted(item["enum"])} if "enum" in item else {"type": item.get("type")})}
        elif v.get("type") == "object" and v.get("properties"):
            out["fields"][k] = _shape(v)
        else:
            out["fields"][k] = {"type": v.get("type")}
    return out


def check_drift(schema_path: str) -> list[str]:
    """返回差异列表; 空列表 = 完全一致"""
    on_disk = json.load(open(schema_path, encoding="utf-8"))
    from_model = Envelope.model_json_schema()

    def norm_from_model(node: dict) -> dict:
        # pydantic 把 $ref 放在 $defs, 这里展开
        defs = from_model.get("$defs", {})

        def deref(v):
            if isinstance(v, dict) and "$ref" in v:
                return defs[v["$ref"].split("/")[-1]]
            return v

        out = {"fields": {}, "required": sorted(node.get("required", []))}
        for k, v in (node.get("properties") or {}).items():
            v = deref(v)
            if "enum" in v:
                out["fields"][k] = {"enum": sorted(v["enum"])}
            elif v.get("type") == "array":
                it = deref(v.get("items") or {})
                out["fields"][k] = {"array_of": norm_from_model(it) if it.get("properties")
                                    else ({"enum": sorted(it["enum"])} if "enum" in it else {"type": it.get("type")})}
            elif any(x.get("type") == "object" for x in v.get("anyOf", [])) or v.get("properties"):
                # Optional[Model] 会变成 anyOf[Model, null]
                cand = v if v.get("properties") else next(
                    (x for x in v.get("anyOf", []) if deref(x).get("properties")), None)
                cand = deref(cand) if cand else None
                out["fields"][k] = norm_from_model(cand) if cand else {"type": "object"}
            else:
                out["fields"][k] = {"type": "object" if v.get("anyOf") else v.get("type")}
        return out

    a = _shape(on_disk)
    b = norm_from_model(from_model)
    diffs = []

    def cmp(pa, x, y):
        fa, fb = set(x["fields"]), set(y["fields"])
        if fa - fb:
            diffs.append(f"{pa}: Schema 有但 Pydantic 缺 -> {sorted(fa - fb)}")
        if fb - fa:
            diffs.append(f"{pa}: Pydantic 有但 Schema 缺 -> {sorted(fb - fa)}")
        if x["required"] != y["required"]:
            diffs.append(f"{pa}: 必填不一致 Schema={x['required']} Pydantic={y['required']}")
        for k in fa & fb:
            va, vb = x["fields"][k], y["fields"][k]
            if "enum" in va and "enum" in vb and va["enum"] != vb["enum"]:
                diffs.append(f"{pa}.{k}: 枚举不一致 Schema={va['enum']} Pydantic={vb['enum']}")
            if "array_of" in va and "array_of" in vb:
                if isinstance(va["array_of"], dict) and "fields" in va["array_of"] \
                        and isinstance(vb["array_of"], dict) and "fields" in vb["array_of"]:
                    cmp(f"{pa}.{k}[]", va["array_of"], vb["array_of"])
            elif "fields" in va and "fields" in vb:
                cmp(f"{pa}.{k}", va, vb)
    cmp("Envelope", a, b)
    return diffs


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "schedule_command.v1.json"
    d = check_drift(p)
    if d:
        print("❌ 契约漂移:")
        for x in d:
            print("  -", x)
        sys.exit(1)
    print("✅ Pydantic 模型与", p, "完全一致, 无漂移")

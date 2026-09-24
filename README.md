# 本地日程助手（Qwen3-0.6B + LoRA + llama.cpp）

一句话中文 → 结构化工具调用 → **可视化日历**。

> 🟢 **线上地址：http://<your-host>:8800**（Tailscale）
> 备用：`http://180.201.177.206:8800`

---

## 最终形态

```
"下下周二上午九点加一门计算机原理，在教三201"
        ↓  Qwen3-0.6B + LoRA（微调）
        ↓  llama.cpp + json_schema 约束解码
{"status":"ok","commands":[{"module":"class","action":"add","title":"计算机原理",
  "when":{"date_kind":"weekday","date_value":"TU","week_offset":2,
          "time":"09:00","period":"am"},"location":"教三201"}]}
        ↓  Pydantic 契约校验 → resolve_time() 确定性解析
        ↓  SQLite → Web 月历
2026-10-06 09:00  计算机原理（教三201）
```

## 性能与正确性

| 指标 | 改造前（HF transformers） | 改造后（llama.cpp） |
|---|---|---|
| 吞吐 | 11.5 tok/s | **272 tok/s**（24×） |
| 端到端延迟 | ~3800 ms | **中位 262 ms**（15.6×） |
| Schema 越界 | 偶发（`fuzzy:"before"`） | **0 条**（结构上不可能） |
| 显存占用 | 1420 MiB | 1042 MiB |

| 验收项 | 结果 |
|---|---|
| 端到端用例 | **21/21** |
| 契约漂移 | 无 |
| 数据集可执行（4372 条） | failed=0 |

---

## 目录

```
├─ docs/
│  ├─ feasibility-and-design.md          最初可行性分析
│  ├─ mcp-how-it-actually-works.md       现代 MCP 五层机制
│  ├─ tool-interface-alignment.md        数据集↔Schema↔MCP 对齐审查
│  ├─ training-hardware-reality.md       GPU/NPU/CPU 训练实测
│  ├─ pod-training-run-report.md         首次训练运行报告
│  └─ BACKUP-README.md                   ★ 备份包说明（含恢复步骤）
├─ schema/
│  ├─ schedule_command.v1.json           契约 v1（历史）
│  └─ schedule_command.v2.json           ★ 契约 v2（唯一事实源）
├─ bridge/                               应用层
│  ├─ app.py                             Web 应用（FastAPI + 单页月历）
│  ├─ executor.py                        时间解析 + 执行 + SQLite
│  ├─ schema_models.py                   Pydantic 契约 + 漂移检查
│  └─ test_*.py / acceptance_v2.py       回归测试与验收
├─ pod/                                  数据生成与训练
│  ├─ gen_dataset.py                     反向构造法生成器
│  ├─ train_lora.py                      LoRA 训练（fp16/AMP）
│  └─ *.sh                               部署与运维脚本
└─ backup/                               ★ 本地备份（1043 MB，已校验）
   └─ sched-backup/
      ├─ model/      LoRA adapter + GGUF(Q8_0/Q4_K_M)
      ├─ software/   全部源码
      ├─ data/       训练数据 + schedule.db
      └─ README.md   恢复说明
```

---

## 关键设计决策（都是踩坑换来的）

1. **模型只做语义归一化，不算绝对日期**。绝对时间由 `resolve_time()` 确定性推导。
   实测模型会把"今年12月31号"算成 2023 年。

2. **契约要能表达用户的话**。v1 的 `week_ref: this|next` 无法表达"下下周"，
   模型只能压成 `next` → 静默写错一周。v2 改用数值 `week_offset` / `month_offset`。

3. **约束解码 > 事后校验**。`json_schema` 让越界值结构上不可能出现，且速度几乎无损。

4. **system prompt 是模型契约的一部分**。必须与训练时逐字节一致 ——
   实测换掉它之后真实用例通过率从 85% 掉到 0%。

5. **反向构造法生成训练数据**：先采样结构化记录，再渲染成中文，标签由构造保证正确。
   生成器自带"必须出现在句中"的短语断言，不满足则丢弃样本。

6. **口语缩略要说全**。"明早/今早/明晚/今晚"若训练数据里没有，
   模型会把日期整个丢掉（"加个明早八点的闹钟" → 落到今天）。

---

## 运维

```bash
ssh <your-host> "tail -f ~/sched-lora/app.log"            # App 日志
ssh <your-host> "tail -f ~/sched-lora/llama-server.log"   # 推理日志
ssh <your-host> "pkill -f 'uvicorn app:app'"              # 停 App
ssh <your-host> "pkill -f llama-server"                   # 停推理
```

⚠️ 临时账户 **2026-09-30 到期**，之后机器与日程库会被回收。
本地 `backup/sched-backup/` 已完整保存，可随时在别处恢复（步骤见其中的 `README.md`）。

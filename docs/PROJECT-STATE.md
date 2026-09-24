# 项目状态快照（供上下文压缩后恢复）

> 生成时间：2026-09-25 · 本机 `D:\Projects` · 用于在上下文压缩/新会话后快速恢复全貌

---

## 一、这是什么

**一句话中文 → 本地微调模型 → 结构化指令 → 可视化日历**，并有安卓客户端。

```
"下下周二上午九点加一门计算机原理，在教三201"
   ↓ Qwen3-0.6B + LoRA（自己微调）
   ↓ llama.cpp + json_schema 约束解码
{"status":"ok","commands":[{"module":"class","action":"add","title":"计算机原理",
  "when":{"date_kind":"weekday","date_value":"TU","week_offset":2,
          "time":"09:00","period":"am"},"location":"教三201"}]}
   ↓ Pydantic 契约校验 → resolve_time() 确定性解析
   ↓ SQLite → Web 月历 / 安卓 App
2026-10-06 09:00
```

---

## 二、文件地图

### 主项目 `D:\Projects\qwen-local-tool-agent\`

```
├─ README.md                      总览（最终形态 + 性能数据 + 关键决策）
├─ docs/
│  ├─ feasibility-and-design.md         最初可行性分析（含实测硬件数据）
│  ├─ mcp-how-it-actually-works.md      现代 MCP 五层机制
│  ├─ tool-interface-alignment.md       数据集↔Schema↔MCP 对齐审查
│  ├─ training-hardware-reality.md      GPU/NPU/CPU 训练实测
│  ├─ pod-training-run-report.md        首次训练运行报告
│  ├─ android-app-plan.md               安卓方案（含三路线对比）
│  ├─ BACKUP-README.md                  备份包恢复说明
│  └─ PROJECT-STATE.md                  ★ 本文件
├─ schema/
│  ├─ schedule_command.v1.json      v1（历史，week_ref 枚举）
│  └─ schedule_command.v2.json      ★ v2 唯一事实源（week_offset/month_offset）
├─ bridge/                          应用层（开发态）
│  ├─ app.py                        FastAPI + 单页月历前端
│  ├─ executor.py                   resolve_time + 执行 + SQLite
│  ├─ schema_models.py              Pydantic 契约 + 漂移检查
│  ├─ acceptance_v2.py              21 例端到端验收（支持 SCHED_API 环境变量）
│  ├─ test_date_parsing.py          13 例日期解析回归
│  ├─ test_offsets.py               18 例周/月偏移回归
│  ├─ verify_dataset_e2e.py         4372 条数据 → 执行器闭环验证
│  └─ validate_dataset_vs_schema.py 数据集 ↔ Schema 严格校验
├─ local/                           ★ 本机部署（Windows + Radeon 880M）
│  ├─ run_local.ps1                 一键启动（llama-server + App）
│  ├─ stop_local.ps1                停止
│  ├─ switch_model.ps1              切换量化档
│  ├─ seed.py                       清空+灌示例
│  ├─ start_emulator.ps1            启模拟器并等开机
│  ├─ install_and_launch.ps1        装 APK + 启动 + 截图
│  └─ screen_*.png / final_*.png    调试截图
├─ pod/                             数据生成、训练、部署脚本
│  ├─ gen_dataset.py                反向构造法生成器（SYS 常量=模型契约！）
│  ├─ train_lora.py                 LoRA 训练（fp16/AMP，Turing 适配）
│  ├─ systemd/sched-llama.service   ★ 服务器用户服务
│  ├─ systemd/sched-app.service     ★
│  ├─ install_systemd.sh            安装脚本
│  └─ *.sh                          各种部署/验证脚本
└─ backup/                          ★ 备份（1043 MB，已 MD5 校验）
   └─ sched-backup/
      ├─ model/      lora_adapter + GGUF Q8_0/Q4_K_M
      ├─ software/   全部源码
      ├─ schema/     v2 契约
      ├─ systemd/    unit 文件 + 安装脚本
      ├─ data/       4000 条训练数据 + schedule.db
      └─ README.md   恢复说明
```

### 安卓 `D:\Projects\AI_ScheduleAssistant\`

```
├─ README.md                       工程说明（含模拟器环境、调试记录）
└─ app/src/main/java/com/liuxinyang/ai_scheduleassistant/
   ├─ MainActivity.kt              Scaffold + 添加/日历/设置 三 Tab + 刷新按钮
   ├─ data/{Models,Api,Prefs}.kt   数据模型 / OkHttp 客户端 / 地址持久化
   └─ ui/{ScheduleViewModel,HomeScreen,CalendarScreen,SettingsScreen,Palette}.kt
```

---

## 三、当前运行状态

| 位置 | 状态 |
|---|---|
| **本机** `http://127.0.0.1:8800` | ✅ 运行中（llama-server 18080 + App 8800） |
| **本机 Tailscale** `http://<your-host>:8800` | ✅ 可达（手机/模拟器用这个） |
| **本机 WLAN** `http://<your-lan-ip>:8800` | ✅ 同一 WiFi 时可用 |
| **训练服务器** `http://<your-host>:8800` | ✅ systemd 已启用（`sched-llama` + `sched-app`） |
| **模拟器** `emulator-5554` | ✅ 已装 App，验证通过 |
| **你的手机** `2578dc7c` | 已连接 adb，待你自行安装 |

⚠️ 训练服务器是**临时账户，2026-09-30 到期**。

---

## 四、性能与验收基线

### 性能

| 环境 | 端到端延迟 | 吞吐 |
|---|---|---|
| 本机 iGPU（Q4_K_M） | **中位 850ms** | 71 tok/s |
| 本机 iGPU（Q8_0） | 中位 1044ms | 49 tok/s |
| 服务器 2080 Ti（llama.cpp） | 中位 262ms | 272 tok/s |
| 服务器 2080 Ti（HF 旧版，已弃用） | ~3800ms | 11.5 tok/s |

### 验收（改代码后必跑）

```powershell
cd D:\Projects\qwen-local-tool-agent\bridge

# ★ acceptance_v2 会往目标库真写数据, 别对着自己的日常实例跑。
#   用临时库: .\local\run_acceptance_scratch.ps1  (它会先验证闸门再生效)
$env:SCHED_API='http://127.0.0.1:8800'
python acceptance_v2.py        # 期望 21/21 (库里已有数据时会拒绝, 退出码 2)
python test_date_parsing.py    # 期望 13/13
python test_offsets.py         # 期望 18/18
python test_auth.py            # 期望 12/12 (访问控制)
python test_theme_consistency.py  # 期望 10/10 (两端主题不漂移)
python verify_dataset_e2e.py   # 期望 failed=0
python schema_models.py ..\schema\schedule_command.v2.json   # 期望无漂移
```

---

## 五、关键设计决策（都是踩坑换来的）

1. **模型只做语义归一化，不算绝对日期**。绝对时间由 `resolve_time()` 确定性推导。
   实测模型把"今年12月31号"算成 2023 年。

2. **契约要能表达用户的话**。v1 的 `week_ref: this|next` 无法表达"下下周"，
   模型只能压成 `next` → **静默写错一周**。v2 改用数值 `week_offset`/`month_offset`。

3. **约束解码 > 事后校验**。`json_schema` 让越界值结构上不可能出现
   （实测无约束时 `fuzzy:"before"` 会漏出来），且速度几乎无损（272 vs 281 tok/s）。

4. **system prompt 是模型契约的一部分**，必须与训练时逐字节一致。
   实测换掉它之后真实用例通过率从 85% 掉到 0%。
   → `gen_dataset.py` 的 `SYS` 与 `app.py` 的 `SYS` 必须相同。

5. **反向构造法生成数据**：先采样结构化记录，再渲染成中文，标签由构造保证正确。
   生成器自带"必须出现在句中"的短语断言。

6. **口语缩略要说全**。"明早/今早/明晚/今晚"若训练数据没有，
   模型会把日期整个丢掉（"加个明早八点的闹钟" → 落到今天）。

7. **`JSONObject.optString(k, fallback)` 遇 JSON null 返回字符串 `"null"`**（安卓端坑）。

8. **推理后端决定速度**。HF `generate()` 逐 token 同步只有 11.5 tok/s；
   llama.cpp 272 tok/s（24 倍）。

9. **分层校验**：结构校验放宽、语义策略收紧。模型给出 `week_offset=5` 时应让它
   通过结构校验、由执行层给出可读追问，而不是直接报校验失败。

10. **两端配色只能有一份事实源**。初版把 7 个模块色分别硬编码在网页 CSS 和安卓
    `Palette.kt`，必然走散。现在 `theme/tokens.json` → 生成器 → 两端，详见
    `docs/theming.md`。

11. **源码只能有一份**。`local/` 曾经放着 `app.py`/`executor.py`/`schema_models.py`
    的副本，靠人手 `Copy-Item` 同步 —— 实测已经分叉过一次，导致"改了代码但线上没变"。
    现在 `local/` 只放脚本和数据，服务用 `uvicorn --app-dir bridge` 跑源码。

12. **不要给"单人日历"硬塞多租户**。不同的人各自跑自己的后端和 SQLite，天然隔离；
    真正要防的是"把无鉴权的 0.0.0.0 服务暴露到网上"。见 §九。

---

## 六、待办 / 已知缺口

| 项 | 说明 | 优先级 |
|---|---|---|
| ~~本机开机自启~~ | ✅ **已完成**（见 §七） | ~~高~~ |
| `action` 只有 `add` | 改/删只能在界面上删，没有自然语言 update/delete | 中 |
| 无提醒推送 | 日程存在电脑端，手机不会主动提醒 | 中 |
| ~~UI 主题~~ | ✅ **已完成**：纸感 / 夜航，两端同源（见 §八、`docs/theming.md`） | ~~中~~ |
| ~~访问控制~~ | ✅ **已完成**：可选共享令牌（见 §九） | ~~高~~ |
| 开源准备 | LICENSE / .gitignore / CI / 架构图 / 脱敏 —— 进行中（见 `docs/roadmap-ui-and-opensource.md`） | **高** |
| 数据集负样本偏少 | reject/clarify 各只有 14/10 条 | 低 |
| 测试集无 reject/clarify | 去重时被固定短语池过滤掉了 | 低 |
| 灵异事件：多端并发写 | 网页和手机同时改同一份 SQLite，目前靠单机串行 + 锁，未做冲突提示 | 低 |

---

## 七、开机自启 —— ✅ 已完成（Windows）

服务器用 systemd（`sched-llama` + `sched-app`，已验证 kill -9 后 6 秒拉起）。
**本机是 Windows，systemd 文件一行都用不了**，做的是等价物：

```
计划任务 ScheduleAssistant  (触发器: 登录时 + 延迟20s)
        ↓
local\supervise.ps1  ← 常驻守候进程
        ├── llama-server :18080   (Vulkan / Radeon 880M)
        └── Web App      :8800
```

### 为什么用"守候进程"而不只是计划任务

计划任务本身只能"拉起来一次"，**做不到崩溃自愈**。
`supervise.ps1` 每 20 秒探活，挂了就重启，带退避（连续失败 >3 次则拉长间隔）。
计划任务只负责"登录后把它拉起来"，并配了失败重启作为第二道保险。

### 实测（已验证）

| 测试 | 结果 |
|---|---|
| 计划任务拉起两个服务 | ✅ llama 2s / App 1s 就绪 |
| `kill -9` llama-server | ✅ **15 秒自动恢复** |
| `kill -9` Web App | ✅ **25 秒自动恢复** |
| 恢复后端到端 | ✅ 1457ms |

### ⚠️ 踩到的坑：计划任务的 PATH 与交互式会话不同

App 反复"启动即退出"，错误是：

```
C:\msys64\ucrt64\bin\python.exe: No module named uvicorn
```

交互式会话里 `python` 解析到 anaconda，**计划任务上下文里却解析到 msys64 的 python**。
→ `supervise.ps1` 改为**主动探测一个确实能 `import uvicorn` 的解释器**，不依赖 PATH。

### 管理命令

```powershell
# 安装 / 更新（含立即验证）
& 'D:\Projects\qwen-local-tool-agent\local\install_autostart.ps1'

# 查看状态
& 'D:\Projects\qwen-local-tool-agent\local\install_autostart.ps1' -Status

# 卸载（同时停止守候进程）
& 'D:\Projects\qwen-local-tool-agent\local\install_autostart.ps1' -Uninstall

# 手动触发一次（等同登录）
Start-ScheduledTask -TaskName ScheduleAssistant

# 看守候日志
Get-Content 'D:\Projects\qwen-local-tool-agent\local\supervisor.log' -Tail 30

# 单独控制（不影响计划任务）
& 'D:\Projects\qwen-local-tool-agent\local\supervise.ps1' -Once    # 只启动一次
& 'D:\Projects\qwen-local-tool-agent\local\supervise.ps1' -Stop    # 全部停止
```

> 触发器刻意用 **AtLogOn 而不是 AtStartup**：推理要用 iGPU，
> 必须跑在用户的图形会话里，开机阶段（session 0）拿不到 GPU。

---

## 八、外观：纸感 / 夜航 —— ✅ 已完成

两端共用 `theme/tokens.json` 一份事实源，由 `theme/gen_theme.py` 生成
`bridge/static/theme.css`（网页 CSS 变量）和 `Tokens.kt`（安卓 Compose）。

```powershell
python theme\gen_theme.py            # 改完 tokens.json 后重新生成
python theme\gen_theme.py --check    # 校验是否漂移（进 CI）
python bridge\test_theme_consistency.py   # 10 项一致性检查
```

- **A 纸感**：暖米白 `#FAF8F5` + 衬线标题 + 淡色块事件条
- **B 夜航**：近黑 `#0E1116` + 无衬线 + 左侧 3px 色条

网页三档切换（纸感/夜航/跟随系统）存在 `localStorage`；安卓在设置页有三个
**实时预览**卡片。详见 **`docs/theming.md`**。

---

## 九、访问控制与数据隔离 —— ✅ 已完成

### 结论：不需要"多用户数据隔离"

这是**单人日历**：一个人，一台后端，自己的若干设备（电脑 + 手机）看同一份数据。
"我的电脑和手机共享日程"是**设计目标**，不是 bug。

不同的人用这个开源项目时，各自跑各自的后端和 SQLite 文件 —— **隔离是物理的**，
不存在跨用户串数据的可能。所以不需要 `user_id` 列、不需要多租户。

### 真正要修的：无鉴权的 0.0.0.0

后端默认绑 `0.0.0.0`（手机要走 Tailscale 访问），而 `/api/*` 此前**完全开放**。
同一网段任何人都能读日程，甚至 `POST /api/reset` 一条请求清空全部数据。

修法：可选共享令牌。

```powershell
# 不设 -> 行为与以前完全一致（本机/可信内网，零门槛）
# 设了 -> 所有 /api/* 都要带 X-Sched-Token 头 或 ?token= 参数
$env:SCHED_TOKEN = '<一串随机字符>'
```

- 用 `hmac.compare_digest` 做定时安全比较，避免按响应时间逐字符猜
- `/api/health` 免鉴权，但未授权时只回答"活着 + 需要令牌"，**不泄露日程条数**
  （否则客户端分不清"令牌错"和"地址错"）
- 网页端遇 401 弹一次输入框并记住；安卓端在设置页填
- 验收：`python bridge\test_auth.py` → 12/12

### 实测

| 场景 | 结果 |
|---|---|
| 不设令牌，`/api/events` | ✅ 200（无回归） |
| 设令牌，`/api/events` 不带令牌 | ✅ 401 |
| 设令牌，`/api/events` 带错令牌 | ✅ 401 |
| 设令牌，`/api/events` 带对令牌 | ✅ 200 |
| 设令牌，`/api/health` 免鉴权 | ✅ 200，且不含 `events` 字段 |

### 如果将来真的要多租户

不需要动 `app.py`：`Store` 已经是独立类，把 `events` 表加一列 `calendar TEXT`
并在 `Store.__init__` 里固定注入，所有查询自动带上作用域即可。现在不做，
因为单人场景下它只是徒增复杂度。

---

## 十、常用命令速查

```powershell
# 本机服务
D:\Projects\qwen-local-tool-agent\local\run_local.ps1      # 启动
D:\Projects\qwen-local-tool-agent\local\stop_local.ps1     # 停止

# 模拟器
D:\Projects\qwen-local-tool-agent\local\start_emulator.ps1 # 启动并等开机
& 'D:\sdk\platform-tools\adb.exe' install -r `
  'D:\Projects\AI_ScheduleAssistant\app\build\outputs\apk\debug\app-debug.apk'

# 构建安卓（必须 JDK 17）
cd D:\Projects\AI_ScheduleAssistant
$env:JAVA_HOME='C:\Program Files\Java\jdk-17'
.\gradlew.bat assembleDebug

# 服务器
ssh <your-host> "systemctl --user status sched-llama sched-app"
ssh <your-host> "systemctl --user restart sched-llama sched-app"
ssh <your-host> "journalctl --user -u sched-app -n 50"
```

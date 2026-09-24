# 路线图：UI 主题设计 + 开源准备

> 两部分：① 设计 1–2 套主题外观 ② 开源到 GitHub 的完整清单
> 前置阅读：`docs/PROJECT-STATE.md`

## 状态

| 部分 | 状态 |
|---|---|
| ① 两套主题（纸感 / 夜航） | ✅ **已完成并验证** —— 见 `docs/theming.md`，网页与安卓都已落地 |
| ② 开源准备 | 🚧 进行中 —— 见文末「实际进度」 |

第一部分下面保留的是**设计稿原案**（决策依据），实际实现与它的差异都记录在
「实现与设计的差异」一节。

---

# 第一部分：UI 主题设计

## 1.1 现状

当前 Android 端用的是 **Material3 默认主题**（`ui/theme/Theme.kt` 脚手架自带），
网页版用的是手写的深色配色。两者**视觉语言不统一**，也没有品牌感。

现有的**唯一品牌资产**是七类日程的配色（`ui/Palette.kt`），这套配色要保留：

| 类型 | 色值 | 语义 |
|---|---|---|
| 课程 class | `#3D7EFF` | 蓝 —— 规律、日常 |
| 考试 exam | `#F85149` | 红 —— 紧急、警示 |
| 会议 meeting | `#C9A6FF` | 紫 —— 社交、协作 |
| 作业 assignment | `#D3D95F` | 黄绿 —— 任务 |
| 闹钟 alarm | `#F0B357` | 橙 —— 时间点 |
| 提醒 reminder | `#3FB950` | 绿 —— 轻量 |
| 备忘 memo | `#8FA3B8` | 灰 —— 无时间、沉淀 |

## 1.2 方案 A：**纸感日程（Paper Schedule）** —— 浅色

**定位**：像一本高质量手账。适合长时间查看课表、正式场合。

| 项 | 设计 |
|---|---|
| 主背景 | 暖米白 `#FAF8F5`（不是纯白，减少刺眼） |
| 卡片 | `#FFFFFF` + 1px 描边 `#EAE6E0`，阴影极轻（elevation 1dp） |
| 主文字 | 墨黑 `#1C1B19` |
| 次文字 | `#8A8580` |
| 强调色 | 靛蓝 `#3D5AFE`（按钮/选中）/ 朱红 `#D93F3F`（删除） |
| 圆角 | **大**：卡片 16dp，按钮 12dp，日历格 10dp |
| 日历格 | 用**小圆点**表示有日程（不是色条），留白多，接近纸质日历 |
| 字体 | 标题用衬线（思源宋体 / Noto Serif SC），正文系统无衬线 |
| 动效 | 淡入 + 轻微上浮，200ms，避免弹跳 |

**视觉关键词**：留白、纸纹、衬线标题、低饱和。

## 1.3 方案 B：**夜航（Night Ops）** —— 深色

**定位**：像 Linear / Vercel 的暗色后台。适合夜间、科技感、开发者审美。

| 项 | 设计 |
|---|---|
| 主背景 | `#0E1116`（近黑但不纯黑） |
| 卡片 | `#161B22` + 1px 描边 `#252C37` |
| 文字 | `#E6E8EB` / 次 `#7D8B9A` |
| 强调色 | `#3D7EFF`（与 class 色一致） |
| 圆角 | **中**：卡片 12dp，按钮 9dp |
| 日历格 | 用**色条**（现有的 3px 左边框方案），信息密度高 |
| 字体 | 全无衬线，数字用等宽（`tabular-nums`，时间对齐好看） |
| 动效 | 快速 150ms，可选微弱的辉光/渐变 |
| 附加 | 结果卡片用"玻璃拟态"（半透明 + 背景模糊） |

**视觉关键词**：高对比、等宽数字、信息密度、冷静。

## 1.4 落地方式（两端一致）

主题要做成**一套 token，两个平台共用**，否则又会走散：

```
theme/
├─ tokens.json          ← 唯一事实源（颜色/圆角/字号/间距）
├─ Theme.kt             ← Android: 由 tokens 生成 Material3 ColorScheme
└─ theme.css            ← Web: 由 tokens 生成 CSS 变量
```

`tokens.json` 结构示例：

```json
{
  "name": "paper",
  "colors": {
    "bg": "#FAF8F5", "card": "#FFFFFF", "line": "#EAE6E0",
    "fg": "#1C1B19", "muted": "#8A8580", "accent": "#3D5AFE",
    "modules": { "class": "#3D7EFF", "exam": "#F85149", "...": "..." }
  },
  "radius": { "card": 16, "button": 12, "cell": 10 },
  "elevation": { "card": 1 }
}
```

**建议实现顺序**：
1. 先定 `tokens.json`（两套）
2. 网页版先改（改 CSS 变量，改完立刻能在浏览器看到，迭代快）
3. 满意后再映射到 Compose（`lightColorScheme()` / `darkColorScheme()` 传参）
4. 最后做应用图标 + 启动图

## 1.5 素材清单

| 素材 | 做法 | 是否需外部工具 |
|---|---|---|
| 应用图标（adaptive） | 手写 `vector drawable`（前景）+ 纯色背景层 | ❌ 直接写 XML |
| 启动图 | Android 12+ `SplashScreen` API，logo 用同一 vector | ❌ |
| 功能图标 | 用 Material Symbols（现有 `material-icons-extended` 够用） | ❌ |
| 日历格装饰 | 纯 Compose Canvas 绘制 | ❌ |
| 字体 | Noto Serif SC / Noto Sans SC（需下载 ttf，注意 OFL 许可） | ⚠️ 可选 |
| 宣传图/截图 | `adb exec-out screencap` + 加边框脚本 | ❌ |

**图标设计概念**（两套都要）：
- 主题 A：一本翻开的册子 + 一个对勾，线条风格，靛蓝描边
- 主题 B：日历网格 + 一个高亮格，实心风格，蓝渐变

---

## 实现与设计的差异（诚实记录）

| 设计稿 | 实际实现 | 原因 |
|---|---|---|
| 纸感日历格用**小圆点**标记 | 事件条前加圆点（`--dot-display`），日历格本身仍是小色块 | Compose 端日历格是 Canvas 画的小方块，改成圆点要动 `CalendarScreen` 的绘制逻辑；当前差异已经足够区分两套主题，先不动 |
| 夜航结果卡片用**玻璃拟态** | 实色卡片 | 模糊需要 `Modifier.blur` + 半透明层，在低端机上掉帧；且和"高对比"的定位有点冲突 |
| 内嵌 Noto Serif SC 字体 | 用系统 `FontFamily.Serif` | 内嵌中文字体 +5MB 起，对 0.6B 小模型项目不划算；已写进已知限制 |
| 纸感模块色沿用原 7 色 | 重新调深了一版 | 原色是为深色底选的，放白底对比度不够（如 `#D3D95F` 黄绿在白底上几乎看不清） |
| 纸感强调色 `#3D5AFE`、删除色 `#D93F3F` | 采用 | 一致 |
| 应用图标 / 启动图 | 未做 | 不阻塞主题验证，留到发布前 |

---

# 第二部分：开源到 GitHub

## 2.1 ⚠️ 先做安全审计（最重要）

仓库里现在混着**不该公开的东西**。开仓库前必须清理：

| 文件/目录 | 风险 | 处理 |
|---|---|---|
| `local/schedule.db` | **个人日程数据** | ❌ 删，加 .gitignore |
| `local/screen_*.png` `final_*.png` | 截图可能含个人信息 | ❌ 删（如需展示，重新截干净的） |
| `local/ui*.xml` `v*.xml` `f.xml` | UI dump，含界面文字 | ❌ 删 |
| `local/local.properties`（安卓） | 本机 SDK 路径 `D:\sdk` | ❌ 删，加 .gitignore |
| `backup/`（1043 MB） | 含模型 + 训练数据 + schedule.db | ❌ **绝对不提交** |
| `local/*.log` | 可能含 IP、请求内容 | ❌ |
| 硬编码的 Tailscale IP | `<your-host>` / `<your-host>`（你的私有网络） | ⚠️ 改成占位符或从配置读 |
| `pod/*.sh` 里的 `<your-host>` 主机名 | 暴露你的服务器 | ⚠️ 改成 `<your-host>` |
| GGUF 模型（378MB / 610MB） | 仓库体积 | ❌ 走 Release 附件或 HF/ModelScope |
| `models/` `bench/*.gguf` `bench/llama/` | 同上 + 第三方二进制 | ❌ |
| API key / 密码 | —— | ✅ 已确认没有（都是本地推理） |

**建议写一个 `scripts/audit_secrets.ps1`** 做自动化扫描（搜 IP、路径、邮箱、
`sk-`、`password`、`token`），提交前跑一遍。

## 2.2 仓库结构：单仓还是双仓？

| 方案 | 说明 | 推荐 |
|---|---|---|
| **双仓** | `qwen-schedule-agent`（后端/训练）+ `AI-ScheduleAssistant`（安卓） | ⭐ **推荐** |
| 单仓 monorepo | 一个仓库放两端 | 也可以，但 Android Studio 打开根目录会别扭 |

双仓的理由：两端技术栈完全不同（Python/Kotlin），发布节奏也不同，
而且安卓工程已经有自己的 Gradle 结构。

但**契约要共享**：`schedule_command.v2.json` 应该放在一个能被双方引用的地方 ——
最简单的做法是后端仓库作为"上游"，安卓仓库里放一份**带版本号的副本**并在 README 里注明来源。

## 2.3 后端仓库 `qwen-schedule-agent`

```
qwen-schedule-agent/
├─ README.md                 中英双语的快速开始 + 架构图 + 性能数据
├─ README.zh.md
├─ LICENSE                   ← 待定，见下
├─ .gitignore
├─ .gitattributes            (text=auto eol=lf)
├─ schema/schedule_command.v2.json
├─ bridge/                   应用层
├─ pod/                      数据生成与训练
├─ local/                    本机部署（清理后）
├─ docs/                     全部设计文档
├─ scripts/
│  ├─ audit_secrets.ps1
│  └─ release_model.md       如何发布模型
├─ tests/                    把散落的 test_*.py 归拢
└─ .github/workflows/ci.yml  Python 测试 + 契约漂移检查
```

**CI 内容**（`ubuntu-latest`，不需要 GPU）：
```yaml
- python -m pytest tests/                     # 日期解析 13 例 + 偏移 18 例
- python bridge/schema_models.py schema/schedule_command.v2.json   # 契约漂移
- python bridge/validate_dataset_vs_schema.py                       # 数据合规
- python bridge/verify_dataset_e2e.py                               # 闭环可执行
```
**注意**：`acceptance_v2.py` 需要跑着的服务，CI 里要 mock 或跳过。

## 2.4 安卓仓库 `AI-ScheduleAssistant`

```
├─ README.md                 含截图、构建步骤（强调 JAVA_HOME=17 这个坑）
├─ LICENSE
├─ .gitignore                ★ 删掉 local.properties 的追踪
├─ app/
├─ docs/
│  ├─ screenshots/           干净的截图
│  └─ themes/                两套主题的预览
└─ .github/workflows/build.yml   构建 debug APK 并上传 artifact
```

## 2.5 LICENSE 选择

| 许可 | 适合 | 注意 |
|---|---|---|
| **MIT** | 最宽松，最容易被采用 | ⭐ 推荐（个人项目、想让人用） |
| Apache-2.0 | 同样宽松 + **显式专利授权** | 如果担心专利问题 |
| AGPL-3.0 | 要求衍生品也开源 | 如果想防止被闭源商用 |

**⚠️ 模型权重的许可要单独考虑**：基座 Qwen3-0.6B 是 **Apache-2.0**，
微调后的 LoRA 权重通常沿用基座许可。README 里要写明"基座 Qwen3-0.6B (Apache-2.0)"。

**⚠️ 第三方许可要列清单**：
- llama.cpp — MIT
- Qwen3-0.6B — Apache-2.0
- 训练数据是**自己合成的**（这点很关键，不涉及数据集许可问题）
- 安卓端：OkHttp (Apache-2.0)、Compose (Apache-2.0)

## 2.6 README 要写什么（决定别人会不会用）

1. **一句话说清是什么** + 一张图/截图
2. **30 秒快速开始**（怎么跑起来，越短越好）
3. **它有什么不一样** —— 这是你的卖点，要突出：
   - ✅ **完全本地**：不用 API，不联网，隐私
   - ✅ **约束解码**：输出结构上不可能非法
   - ✅ **确定性时间解析**：模型不算日期，可单测
   - ✅ **契约驱动**：一份 JSON Schema 同时喂给训练/解码/工具/校验
   - ✅ 实测数据（272 tok/s、21/21 验收）
4. **架构图**
5. **训练是怎么做的**（反向构造法，这个方法论本身有价值）
6. **踩过的坑**（`docs/` 里那些实测记录是很好的内容，能涨 star）
7. 许可与致谢

## 2.7 发布物

| 产物 | 放哪 |
|---|---|
| 源码 | GitHub |
| LoRA adapter (50MB) | GitHub Release 附件 + HuggingFace |
| GGUF Q4_K_M (378MB) | GitHub Release / HuggingFace / ModelScope |
| APK | GitHub Releases（打 tag 时自动构建） |
| 演示 | 一段 GIF/短视频放 README 顶部（最有说服力） |

## 2.8 执行顺序（建议）

```
1. 安全审计 + 清理敏感文件          ← 必须先做
2. 定主题 token，先改网页版验证
3. 主题映射到安卓 + 重做截图
4. 补 LICENSE / .gitignore / CI
5. 写 README（中英）
6. 录演示 GIF
7. 建仓库、首次提交、发 Release
8. （可选）发到 V2EX / 掘金 / r/LocalLLaMA 宣传
```

---

# 需要你决定的三个点 —— ✅ 已定

1. **主题** → **两套都做**，支持跟随系统切换。✅ 已实现
2. **LICENSE** → **MIT**。✅ 已定（文件待补）
3. **仓库** → **双仓**。✅ 已定

---

# 实际进度（最新）

## ✅ 已完成

| 项 | 说明 |
|---|---|
| 两套主题 | 纸感 / 夜航，token 单一事实源，网页 + 安卓都落地并截图验证 |
| 主题跟随/覆盖 | 网页三档切换；安卓设置页实时预览卡片，显式选择可覆盖系统深浅色 |
| 访问控制 | 可选共享令牌 `SCHED_TOKEN`，12/12 测试通过（见 `PROJECT-STATE.md` §九） |
| 源码去重 | `local/` 里的 `app.py`/`executor.py`/`schema_models.py` 副本已删除，改 `--app-dir` 跑 `bridge/` 源码 |
| 契约路径自解析 | `app.py` 能自己找到 `schema/schedule_command.v2.json`（新克隆即可跑） |
| 验收脚本加闸 | `acceptance_v2.py` 检测到目标库非空会拒绝运行（退出码 2），不再污染真实日历 |
| 安全审计 | `scripts/audit_secrets.ps1`：私有 IP / 本机路径 / 邮箱 / 密钥 / 大文件 / BOM，**HIGH 归零** |
| 脱敏 | 20 处 Tailscale IP、WLAN IP、pod 主机名 → 占位符或环境变量；删掉 3 个泄露个人配置的脚本 |
| 仓库整理 | 179 → 75 文件；30 项运行产物删除，60 个被取代的脚本移到 `_archive/`（已 gitignore，本机保留） |
| LICENSE | MIT × 2 仓 |
| .gitignore / .gitattributes | 双仓；含"`.ps1` 必须 CRLF"和二进制规则 |
| CI | 双仓 GitHub Actions：BOM 检查 / 敏感信息审计 / 主题漂移 / 单元测试 / 数据集 schema / APK 构建 |
| 首次提交 | 双仓已 `git init` + commit，可直接 push（见 `docs/opensource-push-checklist.md`） |
| 回归测试 | 21/21（临时库）、13/13、18/18、12/12 鉴权、10/10 主题一致性 |

## 🚧 待办

```
1. 在 GitHub 建两个空仓库并 push        ← 步骤见 docs/opensource-push-checklist.md
2. 确认 LICENSE 版权人（当前按包名推断为 liuxinyang）
3. 写中英双语 README + 架构图           ← 门面，决定别人会不会用
4. 录演示 GIF（截图已有 7 张，在 docs/screenshots/）
5. 发 Release：LoRA adapter + GGUF + APK
6. 补应用图标 / 启动图
```

## ⚠️ 本轮新发现的坑（开源前必须处理）

1. **`.ps1` 必须带 UTF-8 BOM。** 计划任务用的是 PowerShell 5.1，无 BOM 的
   UTF-8 脚本会被当 GBK 读，中文字符串直接把解析搞崩（本轮踩过一次，
   `supervise.ps1` 启动即静默退出）。仓库里要么加 `.gitattributes` 强制，
   要么在 CI 里断言每个 `.ps1` 都有 BOM。

2. **`local/` 与 `bridge/` 的源码副本已经分叉过一次。** 已合并成单一源码，
   `fix_and_verify_race.ps1` / `check_sync.ps1` 这类"拷来拷去"的脚本已归档。

3. **批量替换 `fetch(` → `api(` 把 `api()` 函数自己内部那句也换了**，造成无限递归 ——
   所有请求挂死，页面显示"无法连接服务"。**静态语法检查查不出来**（递归语法合法），
   是把页面真的渲染出来截图才发现的。教训：UI 交付物必须真渲染一次看。

4. **验收脚本写真实数据。** 21 条用例把 6 条日程冲到 23 条，已加非空库拦截 +
   `local/run_acceptance_scratch.ps1` 走临时库。

5. **Windows 控制台 GBK 会把含 emoji 的输出打崩。** 5 个脚本受影响
   （`schema_models.py` 连测试结论都打不出来），统一用 `bridge/_console.py` 兜底。

6. **`Get-ChildItem -Recurse` 再过滤会超时。** `backup/` 1GB + `bench/llama` 整套构建产物，
   审计脚本必须在遍历时就剪枝。

7. **`Add-Content -Encoding UTF8` 会在文件中间插 BOM**（PS 5.1）。
   往已有文本文件追加内容要用 Python 或 `-Encoding utf8NoBOM`。

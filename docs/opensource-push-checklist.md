# 开源推送清单

两个仓库已经在本地 **git init + 首次提交** 完成。你只需要在 GitHub 建两个空仓库，
然后把下面命令里的 `<你的用户名>` 替换掉执行即可。

## 1. 先在 GitHub 建两个**空**仓库

- `qwen-schedule-agent` —— 后端 / 训练 / 部署
- `AI-ScheduleAssistant` —— 安卓客户端

> ⚠️ 建仓库时**不要**勾选 "Add a README / .gitignore / LICENSE"。
> 本地已经有一份，勾了会在 push 时报 `rejected (fetch first)`，还得多一步 merge。

## 2. 推送

```powershell
# ---- 后端 ----
cd D:\Projects\qwen-local-tool-agent
git remote add origin https://github.com/Liu-XY2003/qwen-schedule-agent.git
git branch -M main
git push -u origin main

# ---- 安卓 ----
cd D:\Projects\AI_ScheduleAssistant
git remote add origin https://github.com/Liu-XY2003/AI-ScheduleAssistant.git
git branch -M main
git push -u origin main
```

## 3. 推送前改这两处占位符

仓库是干净的，但有两处写的是推断值，请确认：

| 位置 | 当前值 | 说明 |
|---|---|---|
| 两个 `LICENSE` 的版权行 | `Copyright (c) 2026 Liu-XY2003` | 按你安卓包名 `com.liuxinyang.*` 推断的；要改成别的名字/邮箱就改这里 |
| 后端 `README.md` 的 clone 地址 | 见文件内 | 建完仓库后补上真实 URL |

改完再 `git commit --amend` 或追加一个提交。

## 4. 推送后要做的事

- **Release 附件**：LoRA adapter (50MB) + GGUF Q4_K_M (378MB) + Q8_0 (610MB) + APK。
  这些**不能进 git**（已 gitignore），走 Release 或 HuggingFace / ModelScope。
- **仓库描述与 topics**：建议 topics 填
  `llm` `qwen` `lora` `function-calling` `mcp` `local-first` `android` `jetpack-compose` `calendar` `llama.cpp`
- **README 演示 GIF**：`docs/screenshots/` 里已经有 7 张真实截图可以直接用。

## 5. 已内置的 CI（push 后自动跑）

**后端 `qwen-schedule-agent`**

| Job | 检查 |
|---|---|
| `hygiene` | 所有 `.ps1` 带 UTF-8 BOM · 主题生成物未漂移 · 敏感信息审计 |
| `test` | 日期解析 13/13 · 偏移 18/18 · 契约无漂移 · 主题一致性 10/10 |
| `auth` | 访问控制 12/12（起真实服务） |
| `dataset` | 生成 200 条数据，断言 100% 符合 schema |

**安卓 `AI-ScheduleAssistant`**

| Job | 检查 |
|---|---|
| `build` | JDK 17 编译 Debug APK 并上传产物 |
| `theme-token-guard` | `Tokens.kt` 存在且带自动生成标记（防手改） |

> CI 里跑的就是本地跑过的同一批命令，已经逐条验证过，不是摆设。

## 6. README 与截图

两份仓库都有中英双语 README，顶部互相链接：

| 仓库 | 中文 | 英文 |
|---|---|---|
| `qwen-schedule-agent` | `README.md` | `README.en.md` |
| `AI-ScheduleAssistant` | `README.md` | `README.en.md` |

架构图用的是 **Mermaid**（GitHub 原生渲染，不需要额外的图片文件，改起来就是改文本）。
全部 10 张图都用 `mermaid-cli` 实际渲染验证过语法 —— 语法错的话 GitHub 上会显示成
一坨源码，光看 Markdown 是发现不了的。

截图在 `docs/screenshots/`（后端仓 7 张，安卓仓 5 张），都是从模拟器
`adb shell screencap` 抓的真实画面，可直接用在 README 或 Release 说明里。

## 7. 已知的、故意保留的东西

- `docs/PROJECT-STATE.md` 等文档里有 `ssh <your-host>` 这种占位符 —— 原来的真实主机名
  已在开源清理时替换。文档本身保留（它们是项目最有价值的部分之一）。
- `_archive/` 目录（已 gitignore）里放着 60 个被取代的一次性脚本，只在你本机，不会进仓库。
  确认不再需要可以删掉。
- `docs/` 里提到 `CompShare`（优云智算）—— 那是公开的 GPU 云厂商名，等同提 AWS，
  不构成隐私问题。审计脚本会把它列为 MED，可忽略。
- `AI-ScheduleAssistant` 里的 `192.168.1.20` / `100.100.100.100` 是占位符，不是真实地址，
  CI 对它们做了白名单。

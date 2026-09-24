# 安卓 App 开发方案

> 目标：把"一句话加日程"做成手机 App。
> 现有资产：微调好的 Qwen3-0.6B（LoRA + GGUF）、FastAPI 后端、v2 契约、本地备份。

---

## 一、环境侦察结果

工程 `D:\Projects\AI_ScheduleAssistant` 是 Android Studio 生成的全新 Compose 脚手架
（`MainActivity` 只显示 "Hello Android"），但**工具链基本齐备**：

| 项 | 状态 |
|---|---|
| Android SDK | ✅ `D:\sdk`，platforms **android-36.1 / android-37.0**，build-tools 36.0.0/36.1.0 |
| Gradle | ✅ 9.5.0（wrapper 已配好） |
| AGP / Kotlin | ✅ 9.3.0 / 2.2.10，Compose BOM 2026.02.01 |
| 目标 SDK | compileSdk 37 / minSdk 26 / targetSdk 37 |
| **JDK 17** | ✅ 装在 `C:\Program Files\Java\jdk-17` |
| **`JAVA_HOME`** | ❌ **指向 Zulu 8** → AGP 9.3 要求 JDK 17+，**当前状态直接 build 会失败** |

**第一个要修的点**：构建时把 `JAVA_HOME` 指到 17：
```powershell
$env:JAVA_HOME='C:\Program Files\Java\jdk-17'
.\gradlew assembleDebug
```

---

## 二、关键约束：后端 5 天后就没了

`ai-server-412` 是**临时账户，2026-09-30 到期**，之后机器、模型、服务全部回收。

这直接决定了 App 的架构选择：

| 方案 | 依赖 | 到期后 |
|---|---|---|
| **A. 瘦客户端**（手机 → HTTP → 服务器推理） | 必须能连到一台跑着后端的机器 | ❌ **直接失效** |
| **B. 端侧推理**（模型跑在手机上） | 无 | ✅ **不受影响** |
| C. 混合：优先端侧，需要时走后端 | 可选 | ⚠️ 降级可用 |

---

## 三、推荐：**端侧推理（方案 B）**

理由不只是"防到期"：

1. **模型足够小**。Qwen3-0.6B 的 **Q4_K_M 只有 378MB**，Q8_0 是 640MB。装进 App 的 assets 完全可行。
2. **llama.cpp 官方支持 Android**（NDK 交叉编译，已有 `llama.android` 示例）。
3. **约束解码照样能用**。llama.cpp 的 GBNF / `json_schema` 是同一个 C++ 实现，端侧同样能保证输出合法。
4. **隐私 + 离线 + 零延迟**（不用过网络、不用等服务器）。
5. **技术上已验证**：GGUF 已经产出并实测可用（272 tok/s 在 2080 Ti 上；手机 CPU 上 0.6B Q4 预计 10–20 tok/s，对"一句话生成 60 token JSON"够用）。

**风险**：NDK 交叉编译、JNI 封装、模型资产打包（378MB 会让 APK 很大，需要用 asset pack 或首次启动下载）。

---

## 四、两阶段落地

### Phase 1：先做"瘦客户端"验证 UI（半天）

不碰 NDK，纯 Kotlin，把交互跑通：

```
MainActivity
 ├─ 输入框 + 发送按钮
 ├─ 结果卡片（显示模型输出的 JSON + 解析出的绝对时间）
 └─ 日程列表（RecyclerView / LazyColumn）
```

数据层用 Retrofit/OkHttp 调现成的 `/api/chat` 和 `/api/events`。
**价值**：把 UI/UX 和契约对接验证掉，这部分代码在 Phase 2 里能 100% 复用。

### Phase 2：换成端侧推理（2–4 天）

```
app/src/main/cpp/        llama.cpp 源码 (git submodule)
app/src/main/jni/        JNI 桥: Java_com_..._LlamaBridge_generate
app/src/main/assets/     qwen3-0.6b-sched-v4-Q4_K_M.gguf  (378MB)
app/src/main/java/.../
   LlamaBridge.kt        JNI 声明
   ScheduleEngine.kt     加载模型 + 约束解码 + JSON 解析
   ScheduleRepository.kt 本地 SQLite（Room）存日程
```

**契约不许变**：端侧和服务器端必须用同一份 `schedule_command.v2.json`，
以及**逐字节一致的 system prompt**（实测换掉它准确率从 85% 掉到 0%）。

---

## 五、v1 功能范围（建议）

| 做 | 不做 |
|---|---|
| 一句话添加日程（端侧推理） | 修改/删除（`action` 只有 `add`） |
| 月历视图 + 当天列表 | 多设备同步 |
| 本地 SQLite 存储 | 语音输入（可后续接 ASR） |
| 歧义提示（`period: none` 等） | 重复日程 |
| 契约校验失败时提示用户重说 | 云端账号体系 |

---

## 六、我需要你定的一个点

**端侧推理的模型怎么进 App？**

| 选项 | 说明 |
|---|---|
| ① 打进 APK assets | 简单直接，但 APK 会到 ~400MB |
| ② Asset Pack（Play Asset Delivery） | 规范做法，但只对 Play 分发生效 |
| ③ 首次启动时下载 | APK 小，但需要个下载源（又是服务器依赖） |

考虑到你现在是自用、侧载安装，**①最省事**。

# 外观系统：纸感 / 夜航

网页版和安卓 App 共用**同一份配色 token**，不允许各自手改。

## 为什么要有生成器

第一版把 7 个模块色分别写死在 `bridge/app.py` 的 CSS 里和安卓的 `Palette.kt` 里。
两处独立维护的结果是可预见的：改了一边忘了另一边，两端的颜色慢慢就对不上了。

现在的事实源只有 `theme/tokens.json` 一个文件：

```
theme/tokens.json  ──gen_theme.py──┬─→ bridge/static/theme.css         (网页: CSS 变量)
                                   └─→ .../ui/theme/Tokens.kt          (安卓: Compose Color)
```

生成物顶部都带 `AUTO-GENERATED ... DO NOT EDIT`。改配色 = 改 `tokens.json` + 重跑生成器。

```bash
python theme/gen_theme.py           # 重新生成两端
python theme/gen_theme.py --check   # 只校验是否漂移 (进 CI, 防回退)
```

## 两套主题

| | **A · 纸感** | **B · 夜航** |
|---|---|---|
| 定位 | 暖米白 + 衬线标题，像高质量手账 | 近黑底 + 高对比，Linear/Vercel 那类暗色后台 |
| 底色 | `#FAF8F5` | `#0E1116` |
| 卡片 | `#FFFFFF` + 柔和阴影 | `#161B22`，无阴影 |
| 标题字体 | `Noto Serif SC` / 宋体 | 无衬线 |
| 圆角 | 16 / 12 / 10 | 12 / 9 / 8 |
| 事件条形态 | 淡色块 + 圆点标记 | 左侧 3px 色条 |
| 数字 | 常规 | 等宽 (`tabular-nums`) |

模块色也不同 —— 夜航的亮色放在白底上对比度不够，纸感那套是专门为浅底调深过的：

| 模块 | 夜航 | 纸感 |
|---|---|---|
| class 课程 | `#3D7EFF` | `#2B5FD9` |
| exam 考试 | `#F85149` | `#C62828` |
| meeting 会议 | `#C9A6FF` | `#7C4DFF` |
| assignment 作业 | `#D3D95F` | `#8A7A00` |
| alarm 闹钟 | `#F0B357` | `#B26A00` |
| reminder 提醒 | `#3FB950` | `#1E8E3E` |
| memo 备忘 | `#8FA3B8` | `#6B7A8F` |

## 网页版

- `bridge/app.py` 挂载 `/static`，页面引入 `/static/theme.css`
- 主题写在 `<html data-theme="paper|night">` 上
- 页内所有样式只用 `var(--*)`，**没有一处硬编码颜色**（可用
  `grep -o '#[0-9a-fA-F]\{3,8\}' <style>` 段自检）
- 三档切换：纸感 / 夜航 / 跟随系统，存在 `localStorage["sched-theme"]`
- `<head>` 里有一段极短的同步脚本先定主题，避免刷新时闪一下白/黑

## 安卓版

- `Tokens.kt`（生成）提供 `ThemePalette` 数据类 + `Tokens.PAPER` / `Tokens.NIGHT`
- `Theme.kt` 把 token 映射成 Material3 `ColorScheme`
- `ui/Palette.kt` 的成员是 `@Composable get()`，从 `LocalPalette` 取值 ——
  所以屏幕里的 `Palette.Ok`、`Palette.of(module)` 调用点一行都不用改，换主题自动重组
- 设置页有三块**实时预览**的主题卡片（画出该主题的底色/边框/模块色），点一下即切换

### 两个踩过的坑

1. **M3 槽位必须全部显式赋值。** 只给 `background`/`surface` 时，`NavigationBar`
   的选中指示器用的是 `secondaryContainer`，不覆盖就退回 Material 基线紫色 ——
   底栏会出现一块和主题完全不搭的淡紫药丸。现在 `toColorScheme()` 把槽位填满。
2. **刻意不启用 `dynamicColor`。** 动态取色会把壁纸颜色混进来，同一台设备换个壁纸
   App 就变样，那"纸感/夜航"两套设计就名存实亡了。品牌色由 token 说了算。

## 已知限制

- 网页版用了 CSS `color-mix()`，需要 Chrome/Edge 111+（2023-03）。更老的浏览器上
  颜色混合类样式（徽章底色、事件条淡色底）会失效，退化成透明而不是崩掉。
- 纸感的衬线标题依赖系统有中文字体。安卓上走 `FontFamily.Serif`，
  不同厂商 ROM 的宋体/明体实现差异较大；要完全一致需内嵌字体文件（未做，避免 +5MB）。

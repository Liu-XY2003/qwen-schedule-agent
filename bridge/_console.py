# -*- coding: utf-8 -*-
"""让脚本在 Windows 控制台(默认 GBK 编码)上也能安全打印中文和 emoji。

背景: Windows 的 `cmd` / 重定向管道默认用 GBK 解码。脚本里 print 一个
✅ 或 ⚠️ 就会抛 UnicodeEncodeError 直接把整个脚本打断 —— 而且是在
"输出测试结论" 那一步崩, 看起来像是测试失败, 实际是编码问题。

用法: 在脚本 import 区加一行即可, 导入即生效。

    import _console  # noqa: F401
"""
import sys


def enable_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            # errors="replace" 是兜底: 万一终端实在编不出来, 也不要崩,
            # 顶多把该字符显示成问号。
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


enable_utf8()

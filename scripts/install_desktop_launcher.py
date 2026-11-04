#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在桌面生成「启动/停止日程助手」两个 cmd 脚本。

几个必须注意的点（踩过坑）:
  1. **.cmd 绝对不能带 UTF-8 BOM** —— cmd.exe 会把 BOM 当命令执行，报
     "'' 不是内部或外部命令"，而且窗口一闪就没了，很难排查。
  2. **编码要用 GBK(cp936)** —— 中文 Windows 的 cmd 默认代码页是 936，
     写 UTF-8 会显示成乱码。所以这里显式用 gbk 写。
  3. 换行用 CRLF —— 记事本和 cmd 都认。
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

ROOT = r"D:\Projects\qwen-local-tool-agent"


def desktop_dir() -> pathlib.Path:
    """找桌面目录。OneDrive 会把桌面重定向, 所以要问注册表, 不能假定 %USERPROFILE%\\Desktop。"""
    import winreg
    try:
        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        v, _ = winreg.QueryValueEx(k, "Desktop")
        p = pathlib.Path(os.path.expandvars(v))
        if p.is_dir():
            return p
    except Exception:
        pass
    return pathlib.Path(os.path.expanduser("~")) / "Desktop"


START = r"""@echo off
chcp 936 >nul 2>&1
setlocal
title 日程助手 - 启动

set "APP=http://127.0.0.1:8800"
set "ROOT=D:\Projects\qwen-local-tool-agent"
set "TASK=ScheduleAssistant"
set "LOG=%ROOT%\local\supervisor.log"

cls
echo ============================================================
echo    日程助手  -  本地服务启动器
echo ============================================================
echo.
echo    服务地址 : %APP%
echo    日志文件 : %LOG%
echo.

call :check
if errorlevel 1 goto start
echo   服务已经在运行了。
goto ready

:start
echo   [1/3] 服务未运行，正在启动...
schtasks /run /tn "%TASK%" >nul 2>&1
if errorlevel 1 (
    echo         计划任务不可用，改为直接启动守候进程...
    start "日程助手-守候" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\local\supervise.ps1"
)

echo   [2/3] 等待模型加载（约 10-40 秒）...
set /a n=0
:wait
call :check
if not errorlevel 1 goto ready
set /a n+=1
if %n% geq 50 goto failed
<nul set /p "=."
call :sleep 2
goto wait

:failed
echo.
echo   [失败] 等待 100 秒后服务仍未就绪。
echo          请打开日志查看原因: %LOG%
echo.
pause
exit /b 1

:ready
echo.
echo   [3/3] 服务已就绪，正在打开浏览器...
start "" "%APP%/?theme=paper"
echo.
echo   ------------------------------------------------------------
echo    服务在后台运行，关闭本窗口不会停止它。
echo    要停止请双击桌面上的「停止日程助手.cmd」
echo   ------------------------------------------------------------
call :sleep 8
exit /b 0

:check
powershell.exe -NoProfile -Command "try{$r=Invoke-RestMethod '%APP%/api/health' -TimeoutSec 2;if($r.ready){exit 0}else{exit 1}}catch{exit 1}" >nul 2>&1
exit /b %errorlevel%

:sleep
rem 用 ping 当 sleep。timeout 命令在 stdin 被重定向时会直接报错（例如从别的脚本调用时），
rem ping 则不受影响，行为稳定。
ping -n %1 127.0.0.1 >nul 2>&1
exit /b 0
"""

STOP = r"""@echo off
chcp 936 >nul 2>&1
setlocal
title 日程助手 - 停止

set "ROOT=D:\Projects\qwen-local-tool-agent"

cls
echo ============================================================
echo    日程助手  -  停止服务
echo ============================================================
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\local\stop_local.ps1"
echo.
echo   提示: 如果不想让它开机自动启动，以管理员身份运行:
echo         schtasks /change /tn ScheduleAssistant /disable
echo.
pause
"""


def write(path: pathlib.Path, text: str):
    # ★ gbk + CRLF + 无 BOM
    data = text.replace("\n", "\r\n").encode("gbk", errors="replace")
    path.write_bytes(data)
    return len(data)


def main():
    d = desktop_dir()
    print("桌面目录:", d)
    if not d.is_dir():
        print("桌面目录不存在，退出")
        return 1
    for name, text in (("启动日程助手.cmd", START), ("停止日程助手.cmd", STOP)):
        p = d / name
        n = write(p, text)
        print(f"  已写入 {p}  ({n} 字节, GBK 无 BOM)")

    # 自检: 不能有 BOM, 且能被 gbk 解回原文
    for name in ("启动日程助手.cmd", "停止日程助手.cmd"):
        b = (d / name).read_bytes()
        assert not b.startswith(b"\xef\xbb\xbf"), f"{name} 带了 BOM!"
        b.decode("gbk")
    print("自检通过: 无 BOM、GBK 可解码")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# =====================================================================
# 注册"日程助手"开机(登录)自启计划任务
#
#   .\install_autostart.ps1            安装/更新
#   .\install_autostart.ps1 -Uninstall 卸载
#   .\install_autostart.ps1 -Status    查看状态
#
# 设计说明:
#   - 触发器用 AtLogOn 而不是 AtStartup
#     理由: 推理要用 iGPU, 必须跑在用户的图形会话里; 开机阶段(session 0)拿不到。
#   - 实际的服务守护交给 supervise.ps1 (它自己带崩溃自愈和退避),
#     计划任务只负责"登录后把它拉起来", 并配置失败重启作为第二道保险。
#   - 隐藏窗口运行, 不干扰用户。
# =====================================================================
param(
    [switch]$Uninstall,
    [switch]$Status,
    [int]$DelaySeconds = 20      # 登录后延迟, 避开开机高峰
)
$ErrorActionPreference = 'Stop'

$TaskName = 'ScheduleAssistant'
$Root     = 'D:\Projects\qwen-local-tool-agent'
$Supervise = "$Root\local\supervise.ps1"

function Show-Status {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $t) { Write-Host "未安装"; return }
    $i = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "任务名   : $($t.TaskName)"
    Write-Host "状态     : $($t.State)"
    Write-Host "触发器   : $(($t.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ', ')"
    Write-Host "上次运行 : $($i.LastRunTime)  结果=$($i.LastTaskResult)"
    Write-Host "下次运行 : $($i.NextRunTime)"
    Write-Host "动作     : $(($t.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join ' | ')"
}

if ($Status) { Show-Status; exit 0 }

if ($Uninstall) {
    Write-Host "=== 卸载开机自启 ===" -ForegroundColor Cyan
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "  已删除计划任务 $TaskName" -ForegroundColor Green
    } else {
        Write-Host "  任务不存在"
    }
    # 顺手停掉守候进程
    & $Supervise -Stop
    exit 0
}

Write-Host "=== 安装开机自启 ===" -ForegroundColor Cyan

if (-not (Test-Path $Supervise)) { throw "找不到 $Supervise" }

# --- 动作: 隐藏窗口跑守候进程 ---
$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Supervise`"" `
    -WorkingDirectory "$Root\local"

# --- 触发器: 当前用户登录后, 延迟若干秒 ---
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$trigger.Delay = "PT${DelaySeconds}S"

# --- 设置 ---
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)      # 不限时, 守候进程要常驻
$settings.DisallowStartIfOnBatteries = $false

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description '日程助手: 登录后自动启动本地推理服务(llama-server)与 Web App, 并由 supervise.ps1 持续守护' `
    -Force | Out-Null

Write-Host "  已注册计划任务: $TaskName" -ForegroundColor Green
Write-Host ""
Show-Status

Write-Host "`n=== 立即验证 (跑一次守候进程的启动逻辑) ===" -ForegroundColor Cyan
& $Supervise -Once

Write-Host "`n完成。下次登录 Windows 会自动启动。" -ForegroundColor Green
Write-Host "手动启动: Start-ScheduledTask -TaskName $TaskName"
Write-Host "查看日志: Get-Content '$Root\local\supervisor.log' -Tail 30"
Write-Host "卸载    : & '$Root\local\install_autostart.ps1' -Uninstall"

# 停止本机日程助手
#
# ★ 顺序很重要: 必须**先**停守候进程。
#   否则守候进程会在 20 秒内把 llama-server 和 App 重新拉起来,
#   用户会以为"点了停止但服务还在"。
$ErrorActionPreference = 'SilentlyContinue'
$Root = 'D:\Projects\qwen-local-tool-agent'
$Supervise = Join-Path $Root 'local\supervise.ps1'

Write-Host "=== 停止本机服务 ===" -ForegroundColor Cyan

# 1) 停守候进程（它自己会杀端口占用者）
if (Test-Path $Supervise) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Supervise -Stop
}

# 2) 兜底: 万一有残留（比如守候进程没跑、服务是手动起的）
Start-Sleep -Seconds 1
foreach ($port in 18080, 8800) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($c) {
        $c | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
            $p = Get-Process -Id $_ -ErrorAction SilentlyContinue
            if ($p) {
                Write-Host "  停止 :$port  pid=$($p.Id) $($p.ProcessName)"
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

# 3) 确认
Start-Sleep -Seconds 1
$left = Get-NetTCPConnection -LocalPort 18080, 8800 -State Listen -ErrorAction SilentlyContinue
if ($left) {
    Write-Host "  ✗ 仍有残留，请检查任务管理器" -ForegroundColor Yellow
} else {
    Write-Host "  ✓ 已全部停止" -ForegroundColor Green
}

# 4) 关掉开机自启（避免下次登录又自动起来）—— 只在显式要求时做
if ($args -contains '-DisableAutostart') {
    schtasks /change /tn "ScheduleAssistant" /disable 2>$null | Out-Null
    Write-Host "  已禁用开机自启（重新启用: schtasks /change /tn ScheduleAssistant /enable）"
}

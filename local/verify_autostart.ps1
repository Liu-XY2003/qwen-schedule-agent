# 验证: 计划任务 -> 守候进程 -> 崩溃自愈
$ErrorActionPreference = 'Continue'
$Root = 'D:\Projects\qwen-local-tool-agent'
$Task = 'ScheduleAssistant'

function PortPid($p) {
    $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($c) { return ($c | Select-Object -First 1).OwningProcess } else { return $null }
}
function Up($p, $path = '/health') {
    try { Invoke-RestMethod "http://127.0.0.1:$p$path" -TimeoutSec 4 | Out-Null; return $true } catch { return $false }
}

Write-Host "=== 1. 通过计划任务启动 (模拟登录) ===" -ForegroundColor Cyan
Start-ScheduledTask -TaskName $Task
Start-Sleep -Seconds 8
$sup = Get-Process powershell -ErrorAction SilentlyContinue |
       Where-Object { $_.Id -ne $PID } |
       Sort-Object StartTime -Descending | Select-Object -First 1
Write-Host "  守候进程 pid: $(if($sup){$sup.Id}else{'未找到'})"
Write-Host "  llama :18080 -> pid=$(PortPid 18080)  健康=$(Up 18080)"
Write-Host "  app   :8800  -> pid=$(PortPid 8800)   健康=$(Up 8800 '/api/health')"

Write-Host "`n=== 2. 杀掉 llama-server, 看守候进程会不会自动拉起 ===" -ForegroundColor Cyan
$old = PortPid 18080
Write-Host "  旧 pid=$old, kill -9"
Stop-Process -Id $old -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Write-Host "  3s 后: 监听=$(if(PortPid 18080){'有'}else{'无'})  健康=$(Up 18080)"
Write-Host "  等待守候进程检测到 (间隔 20s) + 重启..."
$new = $null
for ($i = 1; $i -le 20; $i++) {
    Start-Sleep -Seconds 5
    $new = PortPid 18080
    if ($new -and $new -ne $old -and (Up 18080)) {
        Write-Host "  ✅ $($i*5)s 后自动恢复, 新 pid=$new" -ForegroundColor Green
        break
    }
}

Write-Host "`n=== 3. 杀掉 Web App 试试 ===" -ForegroundColor Cyan
$oldApp = PortPid 8800
Write-Host "  旧 pid=$oldApp, kill -9"
Stop-Process -Id $oldApp -Force -ErrorAction SilentlyContinue
$newApp = $null
for ($i = 1; $i -le 20; $i++) {
    Start-Sleep -Seconds 5
    $newApp = PortPid 8800
    if ($newApp -and $newApp -ne $oldApp -and (Up 8800 '/api/health')) {
        Write-Host "  ✅ $($i*5)s 后自动恢复, 新 pid=$newApp" -ForegroundColor Green
        break
    }
}

Write-Host "`n=== 4. 端到端确认 ===" -ForegroundColor Cyan
$body = @{ text = '下下周二上午九点加一门计算机原理，在教三201' } | ConvertTo-Json -Compress
try {
    $r = Invoke-RestMethod 'http://127.0.0.1:8800/api/chat' -Method Post `
        -ContentType 'application/json; charset=utf-8' `
        -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 90
    $it = ($r.execution.items | Select-Object -First 1)
    Write-Host "  ✅ $($it.title) @ $($it.start)  ($($r.total_ms)ms)"
} catch { Write-Host "  ❌ $($_.Exception.Message)" }

Write-Host "`n=== 5. 守候进程日志 ===" -ForegroundColor Cyan
Get-Content "$Root\local\supervisor.log" -Tail 18 -Encoding UTF8

Write-Host "`n=== 6. 计划任务状态 ===" -ForegroundColor Cyan
Get-ScheduledTaskInfo -TaskName $Task | Select-Object TaskName,LastRunTime,LastTaskResult,NumberOfMissedRuns | Format-List

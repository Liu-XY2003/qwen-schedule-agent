# 在临时数据库上跑 21 条验收, 不碰真实日历
$ErrorActionPreference = 'Continue'
$Root = 'D:\Projects\qwen-local-tool-agent'
$Py   = '$env:USERPROFILE\anaconda3\python.exe'
$Db   = "$env:TEMP\sched_acc.db"
$Port = 8903

Remove-Item $Db -Force -ErrorAction SilentlyContinue

# 1) 先确认闸门生效: 对着真实实例(6 条)应该拒绝运行
Write-Host "=== 1. 验证破坏性闸门 ===" -ForegroundColor Cyan
$env:SCHED_API = 'http://127.0.0.1:8800'
Remove-Item Env:\SCHED_ALLOW_DIRTY -ErrorAction SilentlyContinue
& $Py "$Root\bridge\acceptance_v2.py" 2>&1 | Select-Object -First 6
Write-Host "  退出码 = $LASTEXITCODE (期望 2 = 已拒绝)"

# 2) 起临时实例
Write-Host "`n=== 2. 起临时实例 (port $Port, db $Db) ===" -ForegroundColor Cyan
$env:SCHED_DB = $Db
$env:SCHED_LLAMA_URL = 'http://127.0.0.1:18080'
$proc = Start-Process -FilePath $Py `
    -ArgumentList @('-m','uvicorn','app:app','--app-dir',"$Root\bridge",'--host','127.0.0.1','--port',"$Port") `
    -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput "$env:TEMP\acc_app.log" -RedirectStandardError "$env:TEMP\acc_app.err"
for ($i=0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try { Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 3 | Out-Null; break } catch {}
}

# 3) 跑验收
Write-Host "`n=== 3. 在临时库上跑 21 条验收 ===" -ForegroundColor Cyan
$env:SCHED_API = "http://127.0.0.1:$Port"
& $Py "$Root\bridge\acceptance_v2.py" 2>&1 | Select-String -Pattern '通过|FAIL|OK  ' | Select-Object -Last 4
$acc = $LASTEXITCODE

Write-Host "`n=== 4. 收尾 ===" -ForegroundColor Cyan
Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Remove-Item $Db -Force -ErrorAction SilentlyContinue
Remove-Item Env:\SCHED_DB, Env:\SCHED_API -ErrorAction SilentlyContinue

$real = (Invoke-RestMethod 'http://127.0.0.1:8800/api/health').events
Write-Host "  真实日历仍有 $real 条 (必须还是 6)"
Write-Host "  验收退出码 = $acc"

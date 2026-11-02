# 在本机 (Windows + Radeon 880M iGPU) 启动日程助手
# 用法: powershell -ExecutionPolicy Bypass -File .\local\run_local.ps1
$ErrorActionPreference = 'Stop'

$Root   = 'D:\Projects\qwen-local-tool-agent'
$Llama  = "$Root\bench\llama"
$Local  = "$Root\local"
$Bridge = "$Root\bridge"           # 源码唯一位置
$Model  = "$Root\backup\sched-backup\model\qwen3-0.6b-sched-v4-Q8_0.gguf"
$LLMPort = 18080
$AppPort = 8800

Write-Host "=== 1. 停掉旧的本地实例 ===" -ForegroundColor Cyan
Get-Process llama-server,python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$Root*" -or $_.CommandLine -like "*$Root*" } |
    ForEach-Object { Write-Host "  kill $($_.Id) $($_.ProcessName)"; Stop-Process -Id $_.Id -Force }
# 更精确: 按端口找
foreach ($p in $LLMPort, $AppPort) {
    $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($c) { $c | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } }
}
Start-Sleep -Seconds 2

Write-Host "=== 2. 启动 llama-server (Vulkan / iGPU) ===" -ForegroundColor Cyan
$llmLog = "$Local\llama-server.log"
$llm = Start-Process -FilePath "$Llama\llama-server.exe" `
    -ArgumentList @('-m', $Model, '-ngl', '99', '-c', '8192',
                    '--host', '127.0.0.1', '--port', "$LLMPort",
                    '--jinja', '-np', '1',
                    # 关掉 Qwen3 思考模式: 结构化抽取用不上, 实测快 3.6 倍
                    '--reasoning', 'off') `
    -WorkingDirectory $Llama -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $llmLog -RedirectStandardError "$Local\llama-server.err.log"
Write-Host "  pid=$($llm.Id)  日志: $llmLog"

Write-Host "  等待就绪..." -NoNewline
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$LLMPort/health" -TimeoutSec 3
        if ($r.status -eq 'ok') { $ok = $true; break }
    } catch { }
}
if (-not $ok) {
    Write-Host "`n  启动失败, 日志尾部:" -ForegroundColor Red
    Get-Content $llmLog -Tail 25 -ErrorAction SilentlyContinue
    Get-Content "$Local\llama-server.err.log" -Tail 25 -ErrorAction SilentlyContinue
    exit 1
}
Write-Host " ok ($($i+1)s)" -ForegroundColor Green

Write-Host "=== 3. 启动 Web App ===" -ForegroundColor Cyan
$env:SCHED_LLAMA_URL = "http://127.0.0.1:$LLMPort"
$env:SCHED_DB = "$Local\schedule.db"
# --app-dir 指向 bridge/, 不再往 local/ 拷源码副本 (见 supervise.ps1 里的说明)
$app = Start-Process -FilePath 'python' `
    -ArgumentList @('-m', 'uvicorn', 'app:app', '--app-dir', $Bridge,
                    '--host', '0.0.0.0', '--port', "$AppPort") `
    -WorkingDirectory $Local -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput "$Local\app.log" -RedirectStandardError "$Local\app.err.log"
Write-Host "  pid=$($app.Id)"

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $h = Invoke-RestMethod "http://127.0.0.1:$AppPort/api/health" -TimeoutSec 3
        if ($h.ready) { break }
    } catch { }
}

Write-Host "`n=== 4. 健康检查 ===" -ForegroundColor Cyan
Invoke-RestMethod "http://127.0.0.1:$AppPort/api/health" | ConvertTo-Json -Depth 4

Write-Host "`n=== 5. 端到端测试 ===" -ForegroundColor Cyan
$body = @{ text = '下下周二上午九点加一门计算机原理，在教三201' } | ConvertTo-Json -Compress
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$res = Invoke-RestMethod "http://127.0.0.1:$AppPort/api/chat" -Method Post `
    -ContentType 'application/json; charset=utf-8' `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 120
$sw.Stop()
Write-Host "  输入: 下下周二上午九点加一门计算机原理，在教三201"
Write-Host "  模型: $($res.model_raw)"
Write-Host "  执行: $($res.execution.kind)  端到端 $([math]::Round($sw.Elapsed.TotalMilliseconds))ms (模型 $($res.gen_ms)ms)"

Write-Host "`n======================================================" -ForegroundColor Green
Write-Host " 打开浏览器:  http://127.0.0.1:$AppPort" -ForegroundColor Green
Write-Host " 停止服务:    .\local\stop_local.ps1" -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Green

# 切换模型量化档并重新测速
param([string]$Quant = 'Q4_K_M')
$ErrorActionPreference = 'Stop'
$Root  = 'D:\Projects\qwen-local-tool-agent'
$Llama = "$Root\bench\llama"
$Local = "$Root\local"
$Model = "$Root\backup\sched-backup\model\qwen3-0.6b-sched-v4-$Quant.gguf"
if (-not (Test-Path $Model)) { Write-Host "模型不存在: $Model" -ForegroundColor Red; exit 1 }
Write-Host "模型: $(Split-Path $Model -Leaf)  ($([math]::Round((Get-Item $Model).Length/1MB,0)) MB)" -ForegroundColor Cyan

foreach ($p in 18080) {
    $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($c) { $c | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } }
}
Start-Sleep -Seconds 2

$llm = Start-Process -FilePath "$Llama\llama-server.exe" `
    -ArgumentList @('-m', $Model, '-ngl', '99', '-c', '2048',
                    '--host', '127.0.0.1', '--port', '18080', '--jinja', '-np', '1') `
    -WorkingDirectory $Llama -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput "$Local\llama-$Quant.log" -RedirectStandardError "$Local\llama-$Quant.err.log"

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    try { if ((Invoke-RestMethod 'http://127.0.0.1:18080/health' -TimeoutSec 3).status -eq 'ok') { break } } catch { }
}
Write-Host "  llama-server 就绪 ($($i+1)s, pid=$($llm.Id))" -ForegroundColor Green

# 直接测吞吐
$body = @{
    messages = @(
        @{ role='system'; content='你是日程助手，把用户的中文请求转换为 JSON，只输出 JSON。' },
        @{ role='user';   content='下下周二上午九点加一门计算机原理，在教三201' }
    )
    max_tokens = 120; temperature = 0
    chat_template_kwargs = @{ enable_thinking = $false }
} | ConvertTo-Json -Depth 6 -Compress

# 热身
Invoke-RestMethod 'http://127.0.0.1:18080/v1/chat/completions' -Method Post `
    -ContentType 'application/json' -Body $body -TimeoutSec 60 | Out-Null

$lat = @()
foreach ($i in 1..5) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-RestMethod 'http://127.0.0.1:18080/v1/chat/completions' -Method Post `
        -ContentType 'application/json' -Body $body -TimeoutSec 60
    $sw.Stop()
    $ct = $r.usage.completion_tokens
    $lat += [math]::Round($sw.Elapsed.TotalMilliseconds)
    Write-Host ("    第{0}次: {1} token / {2}ms -> {3:N0} tok/s" -f $i, $ct, $sw.Elapsed.TotalMilliseconds, ($ct / $sw.Elapsed.TotalSeconds))
}
$lat = $lat | Sort-Object
Write-Host ("  $Quant 中位延迟 {0}ms" -f $lat[[int]($lat.Count/2)]) -ForegroundColor Yellow

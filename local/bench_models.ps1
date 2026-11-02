# 实测 Qwen3 各尺寸在核显上的吞吐，为二阶段选型提供依据
# 不碰正在跑的 18080，用独立端口逐个起
$ErrorActionPreference = 'Continue'
$Root = 'D:\Projects\qwen-local-tool-agent'
$Llama = "$Root\bench\llama\llama-server.exe"
$Port = 18999

$models = @(
    @{ Name='Qwen3-0.6B-Q4_K_M'; File="$Root\bench\Qwen3-0.6B-Q4_K_M.gguf" },
    @{ Name='Qwen3-1.7B-Q4_K_M'; File="$Root\bench\Qwen3-1.7B-Q4_K_M.gguf" },
    @{ Name='Qwen3-4B-Q4_K_M';   File="$Root\bench\Qwen3-4B-Q4_K_M.gguf"   }
)

$prompt = '把这句话转换成日程指令：下周二上午九点开会'
$results = @()

foreach ($m in $models) {
    if (-not (Test-Path $m.File)) { Write-Host "跳过 $($m.Name) (文件不存在)"; continue }
    Write-Host "=== 测 $($m.Name) ===" -ForegroundColor Cyan

    # 停掉上一轮的
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -EA SilentlyContinue
    if ($c) { Stop-Process -Id ($c|Select-Object -First 1).OwningProcess -Force -EA SilentlyContinue; Start-Sleep -Seconds 2 }

    $out = "$env:TEMP\bench_llama.log"
    $err = "$env:TEMP\bench_llama.err"
    $p = Start-Process -FilePath $Llama -ArgumentList @(
        '-m', $m.File, '-ngl', '99', '-c', '8192',
        '--host','127.0.0.1','--port',"$Port", '--jinja','-np','1'
    ) -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err

    $ready = $false
    for ($i=0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 1
        try { Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2 | Out-Null; $ready=$true; break } catch {}
        if ($p.HasExited) { break }
    }
    if (-not $ready) {
        Write-Host "  启动失败" -ForegroundColor Red
        Get-Content $err -Tail 5 -EA SilentlyContinue
        continue
    }
    Write-Host "  就绪，开始计时..." -NoNewline

    # 预热一次
    $body = @{ model='x'; messages=@(@{role='user';content=$prompt}); max_tokens=64; temperature=0 } | ConvertTo-Json -Depth 5 -Compress
    try { Invoke-RestMethod "http://127.0.0.1:$Port/v1/chat/completions" -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 300 | Out-Null } catch {}

    # 正式测 3 次，每次生成 128 token
    $body = @{ model='x'; messages=@(@{role='user';content=$prompt}); max_tokens=128; temperature=0 } | ConvertTo-Json -Depth 5 -Compress
    $lat = @()
    $tps = @()
    for ($k=0; $k -lt 3; $k++) {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        try {
            $r = Invoke-RestMethod "http://127.0.0.1:$Port/v1/chat/completions" -Method Post `
                    -ContentType 'application/json; charset=utf-8' `
                    -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 300
            $sw.Stop()
            $lat += $sw.Elapsed.TotalMilliseconds
            if ($r.usage) {
                $n = $r.usage.completion_tokens
                $tps += ($n / $sw.Elapsed.TotalSeconds)
            }
        } catch { $sw.Stop() }
    }

    $memMB = [math]::Round($p.WorkingSet64/1MB)
    $median = if ($lat.Count) { ($lat | Sort-Object)[[int]($lat.Count/2)] } else { 0 }
    $medTps = if ($tps.Count) { [math]::Round(($tps | Sort-Object)[[int]($tps.Count/2)],1) } else { 0 }
    Write-Host " ok"
    Write-Host ("  中位延迟 {0:N0} ms | {1} tok/s | 进程内存 {2} MB | n_ctx=8192" -f $median, $medTps, $memMB)

    $results += [pscustomobject]@{
        Model = $m.Name; LatencyMs = [math]::Round($median); TokPerSec = $medTps; MemMB = $memMB
    }

    Stop-Process -Id $p.Id -Force -EA SilentlyContinue
    Start-Sleep -Seconds 2
}

Write-Host "`n=== 汇总（核显 / Vulkan / Q4_K_M / n_ctx=8192）===" -ForegroundColor Green
$results | Format-Table -AutoSize

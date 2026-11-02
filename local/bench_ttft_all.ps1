# 逐个模型起服务并测 TTFT
$ErrorActionPreference = 'Continue'
$Root = 'D:\Projects\qwen-local-tool-agent'
$Llama = "$Root\bench\llama\llama-server.exe"
$Py = '$env:USERPROFILE\anaconda3\python.exe'
$Port = 18999

$models = @(
    @{ Name='Qwen3-0.6B'; File="$Root\bench\Qwen3-0.6B-Q4_K_M.gguf" },
    @{ Name='Qwen3-1.7B'; File="$Root\bench\Qwen3-1.7B-Q4_K_M.gguf" },
    @{ Name='Qwen3-4B';   File="$Root\bench\Qwen3-4B-Q4_K_M.gguf"   }
)

foreach ($m in $models) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -EA SilentlyContinue
    if ($c) { Stop-Process -Id ($c|Select-Object -First 1).OwningProcess -Force -EA SilentlyContinue; Start-Sleep -Seconds 2 }

    $p = Start-Process -FilePath $Llama -ArgumentList @(
        '-m', $m.File, '-ngl','99','-c','8192','--host','127.0.0.1','--port',"$Port",'--jinja','-np','1'
    ) -PassThru -WindowStyle Hidden -RedirectStandardOutput "$env:TEMP\t_llama.log" -RedirectStandardError "$env:TEMP\t_llama.err"

    $ready = $false
    for ($i=0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 1
        try { Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2 | Out-Null; $ready=$true; break } catch {}
        if ($p.HasExited) { break }
    }
    if (-not $ready) { Write-Host "  $($m.Name) 启动失败" -ForegroundColor Red; continue }

    & $Py "$Root\scripts\bench_ttft.py" --port $Port --label $m.Name --max-tokens 128 --runs 3
    Stop-Process -Id $p.Id -Force -EA SilentlyContinue
    Start-Sleep -Seconds 2
}

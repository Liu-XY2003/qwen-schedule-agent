# 对比 Qwen3-4B 在「思考开启 / 关闭」下的真实可用性（带 json_schema 约束）
$ErrorActionPreference = 'Continue'
$Root = 'D:\Projects\qwen-local-tool-agent'
$Llama = "$Root\bench\llama\llama-server.exe"
$Py = '$env:USERPROFILE\anaconda3\python.exe'
$Port = 18999
$Model = "$Root\bench\Qwen3-4B-Q4_K_M.gguf"

$configs = @(
    @{ Name = '4B · 思考默认(auto)'; Args = @() },
    @{ Name = '4B · --reasoning off'; Args = @('--reasoning','off') },
    @{ Name = '4B · --reasoning-budget 0'; Args = @('--reasoning-budget','0') }
)

foreach ($cfg in $configs) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -EA SilentlyContinue
    if ($c) { Stop-Process -Id ($c|Select-Object -First 1).OwningProcess -Force -EA SilentlyContinue; Start-Sleep -Seconds 2 }

    $a = @('-m',$Model,'-ngl','99','-c','8192','--host','127.0.0.1','--port',"$Port",'--jinja','-np','1') + $cfg.Args
    $p = Start-Process -FilePath $Llama -ArgumentList $a -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput "$env:TEMP\r.log" -RedirectStandardError "$env:TEMP\r.err"
    $ok = $false
    for ($i=0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 1
        try { Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2 | Out-Null; $ok = $true; break } catch {}
        if ($p.HasExited) { break }
    }
    if (-not $ok) { Write-Host "$($cfg.Name) 启动失败" -ForegroundColor Red; Get-Content "$env:TEMP\r.err" -Tail 4 -EA SilentlyContinue; continue }

    & $Py "$Root\scripts\probe_constraint_vs_thinking.py" $Port $cfg.Name
    Stop-Process -Id $p.Id -Force -EA SilentlyContinue
    Start-Sleep -Seconds 2
}

# 对比 1.7B / 4B 在「零样本」与「few-shot」下的抽取准确率
$ErrorActionPreference = 'Continue'
$Root = 'D:\Projects\qwen-local-tool-agent'
$Llama = "$Root\bench\llama\llama-server.exe"
$vp = "$Root\.venv-planner\Scripts\python.exe"
$Port = 18999

$models = @(
  @{ Name='Qwen3-1.7B'; File="$Root\bench\Qwen3-1.7B-Q4_K_M.gguf" },
  @{ Name='Qwen3-4B';   File="$Root\bench\Qwen3-4B-Q4_K_M.gguf"   }
)

foreach ($m in $models) {
  foreach ($fs in @('zero','fewshot')) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -EA SilentlyContinue
    if ($c) { Stop-Process -Id ($c|Select-Object -First 1).OwningProcess -Force -EA SilentlyContinue; Start-Sleep -Seconds 2 }

    $p = Start-Process -FilePath $Llama -ArgumentList @(
      '-m',$m.File,'-ngl','99','-c','4096','--host','127.0.0.1','--port',"$Port",
      '--jinja','-np','1','--reasoning','off'
    ) -PassThru -WindowStyle Hidden -RedirectStandardOutput "$env:TEMP\e.log" -RedirectStandardError "$env:TEMP\e.err"

    $ok=$false
    for ($i=0; $i -lt 90; $i++) { Start-Sleep -Seconds 1; try { Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2 | Out-Null; $ok=$true; break } catch {} }
    if (-not $ok) { "$($m.Name) 启动失败"; Get-Content "$env:TEMP\e.err" -Tail 4; continue }

    $flag = if ($fs -eq 'fewshot') { '--fewshot' } else { '--zero-shot' }
    & $vp "$Root\bridge\eval_extraction.py" --port $Port --label "$($m.Name) / $fs" $flag 2>&1 |
      Select-String -Pattern '抽取评估:|^\s+\d+/\d+ =|FAIL \[..\]'
    Stop-Process -Id $p.Id -Force -EA SilentlyContinue
    Start-Sleep -Seconds 2
  }
}

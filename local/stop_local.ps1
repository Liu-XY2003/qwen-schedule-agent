# 停止本机日程助手
$ErrorActionPreference = 'SilentlyContinue'
$Root = 'D:\Projects\qwen-local-tool-agent'

Write-Host "=== 停止本机服务 ===" -ForegroundColor Cyan
foreach ($port in 18080, 8800) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($c) {
        $c | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
            $p = Get-Process -Id $_ -ErrorAction SilentlyContinue
            if ($p) { Write-Host "  停止 :$port  pid=$($p.Id) $($p.ProcessName)"; Stop-Process -Id $p.Id -Force }
        }
    } else {
        Write-Host "  :$port 未监听"
    }
}
Start-Sleep -Seconds 1
$left = Get-NetTCPConnection -LocalPort 18080, 8800 -State Listen -ErrorAction SilentlyContinue
if ($left) { Write-Host "  仍有残留" -ForegroundColor Yellow } else { Write-Host "  ✓ 已全部停止" -ForegroundColor Green }

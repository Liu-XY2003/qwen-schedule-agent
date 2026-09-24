# 用干净克隆复现 CI 环境，确认审计在 CI 上也能过
$ErrorActionPreference = 'Continue'
$Root = 'D:\Projects\qwen-local-tool-agent'
$Tmp = Join-Path $env:TEMP ('ci-sim-' + [guid]::NewGuid().ToString('N').Substring(0, 8))

Write-Host "=== 干净克隆到 $Tmp ===" -ForegroundColor Cyan
git clone -q --no-hardlinks $Root $Tmp 2>&1 | Out-Null
if (-not (Test-Path $Tmp)) { Write-Host "克隆失败" -ForegroundColor Red; exit 1 }

Write-Host "=== 克隆里的文件数 ===" -ForegroundColor Cyan
$n = (Get-ChildItem $Tmp -Recurse -File -Force | Where-Object { $_.FullName -notmatch '\\\.git\\' }).Count
Write-Host "  $n 个文件"

Write-Host "`n=== 在克隆里跑审计 (等同 CI) ===" -ForegroundColor Cyan
powershell -NoProfile -ExecutionPolicy Bypass -File "$Tmp\scripts\audit_secrets.ps1" -Root $Tmp 2>&1 | Select-Object -Last 12
$auditExit = $LASTEXITCODE
Write-Host "审计退出码 = $auditExit (期望 0)"

Write-Host "`n=== 在克隆里跑 CI 的其余步骤 ===" -ForegroundColor Cyan
Push-Location $Tmp

Write-Host "-- .ps1 BOM 检查 --"
$bad = 0
foreach ($p in (Get-ChildItem -Recurse -Filter *.ps1 -File)) {
    $b = [System.IO.File]::ReadAllBytes($p.FullName)
    if ($b.Length -lt 3 -or $b[0] -ne 0xEF -or $b[1] -ne 0xBB -or $b[2] -ne 0xBF) {
        Write-Host "   缺少 BOM: $($p.FullName.Replace($Tmp,''))" -ForegroundColor Red; $bad++
    }
}
Write-Host "   缺 BOM 的 .ps1: $bad 个"

Write-Host "-- 主题漂移 --"
python theme\gen_theme.py --check 2>&1 | Select-Object -Last 2

Write-Host "-- 契约漂移 --"
Push-Location bridge; python schema_models.py ..\schema\schedule_command.v2.json 2>&1 | Select-Object -Last 1; Pop-Location

Pop-Location
Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "`n已清理 $Tmp" -ForegroundColor Green

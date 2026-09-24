# 等待模拟器 emulator-5554 完成开机
$ErrorActionPreference = 'Continue'
$adb = 'D:\sdk\platform-tools\adb.exe'
$dev = 'emulator-5554'

Write-Host "=== 等待 $dev 上线并完成开机 ===" -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Seconds 3
    $state = (& $adb -s $dev get-state 2>$null) -join '' -replace '\s', ''
    if ($state -eq 'device') {
        $b = (& $adb -s $dev shell getprop sys.boot_completed 2>$null) -join '' -replace '\s', ''
        if ($b -eq '1') { $ok = $true; Write-Host "  ✅ 开机完成 ($($i*3)s)" -ForegroundColor Green; break }
    }
    if ($i % 10 -eq 0) { Write-Host "  [$($i*3)s] state=$state" }
}
if (-not $ok) {
    Write-Host "  ⚠️ 仍未就绪" -ForegroundColor Yellow
    & $adb devices -l
    Write-Host "`n=== 模拟器日志 ===" -ForegroundColor Yellow
    Get-Content "$env:USERPROFILE\.android\avd\sched.avd\emulator-user.ini" -ErrorAction SilentlyContinue
    Get-Process qemu-system-x86_64 -ErrorAction SilentlyContinue | Select-Object Id,@{n='MB';e={[math]::Round($_.WorkingSet64/1MB,0)}}
    exit 1
}

Write-Host "`n=== 模拟器信息 ===" -ForegroundColor Cyan
"  型号 : $((& $adb -s $dev shell getprop ro.product.model) -join '')"
"  版本 : Android $((& $adb -s $dev shell getprop ro.build.version.release) -join '') (SDK $((& $adb -s $dev shell getprop ro.build.version.sdk) -join ''))"
"  ABI  : $((& $adb -s $dev shell getprop ro.product.cpu.abi) -join '')"
"  分辨率: $((& $adb -s $dev shell wm size) -join '')"

# 启动安卓模拟器并等待开机完成
param(
    [string]$Avd = 'sched',
    [switch]$Headless
)
$ErrorActionPreference = 'Continue'
$Env:JAVA_HOME = 'C:\Program Files\Java\jdk-17'
$emu  = 'D:\sdk\emulator\emulator.exe'
$adb  = 'D:\sdk\platform-tools\adb.exe'

Write-Host "=== 已有模拟器在跑吗 ===" -ForegroundColor Cyan
$running = & $adb devices | Select-String 'emulator-'
if ($running) { Write-Host "  已有一个在运行: $running"; }

$args = @('-avd', $Avd, '-no-snapshot-save', '-no-boot-anim', '-no-audio',
          '-gpu', 'host', '-memory', '3072', '-cores', '4')
if ($Headless) { $args += '-no-window' }

Write-Host "=== 启动 $Avd ($($args -join ' ')) ===" -ForegroundColor Cyan
$p = Start-Process -FilePath $emu -ArgumentList $args -PassThru
Write-Host "  pid=$($p.Id)  日志: D:\Projects\qwen-local-tool-agent\local\emulator.log"

Write-Host "=== 等待设备出现 ===" -ForegroundColor Cyan
& $adb wait-for-device
Write-Host "  设备已连接"

Write-Host "=== 等待开机完成 (最多 5 分钟) ===" -ForegroundColor Cyan
$booted = $false
for ($i = 0; $i -lt 100; $i++) {
    Start-Sleep -Seconds 3
    $b = (& $adb shell getprop sys.boot_completed 2>$null) -join '' -replace '\s', ''
    if ($b -eq '1') { $booted = $true; Write-Host "  ✅ 开机完成 ($($i*3)s)" -ForegroundColor Green; break }
}
if (-not $booted) {
    Write-Host "  ⚠️ 超时, 当前状态:" -ForegroundColor Yellow
    & $adb devices -l
}

Write-Host "=== 设备信息 ===" -ForegroundColor Cyan
& $adb shell getprop ro.build.version.release
& $adb shell getprop ro.product.cpu.abi
& $adb shell wm size

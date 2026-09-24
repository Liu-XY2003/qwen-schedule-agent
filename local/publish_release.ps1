<#
.SYNOPSIS
    把两个仓库的 v0.1.0 Release 一次性发出去。

.DESCRIPTION
    需要先装好 gh 并登录一次（只需一次）:

        winget install --id GitHub.cli
        gh auth login          # 选 GitHub.com -> HTTPS -> 浏览器登录

    然后直接跑本脚本即可。它做的事:
      1. 检查 gh 可用且已登录
      2. 打 tag 并推送
      3. 创建 Release, 上传资产 (后端 ~1026 MB, 安卓 ~18 MB)

    资产已经暂存在 _release/ 下并算好 SHA256; 本脚本不会重新打包。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File local\publish_release.ps1
    powershell -ExecutionPolicy Bypass -File local\publish_release.ps1 -DryRun
#>
param(
    [string]$Version = 'v0.1.0',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$Backend = 'D:\Projects\qwen-local-tool-agent'
$Android = 'D:\Projects\AI_ScheduleAssistant'
$Stage   = "$Backend\_release"

# ---------------------------------------------------------------- 前置检查
Write-Host "=== 1. 检查 gh ===" -ForegroundColor Cyan
$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Host @"
gh 未安装。二选一:

  A) 装 gh（之后一条命令发完，推荐）
     winget install --id GitHub.cli
     gh auth login            # GitHub.com -> HTTPS -> Login with a web browser
     然后重新跑本脚本

  B) 用网页手动发
     见本脚本末尾打印的"手动步骤"
"@ -ForegroundColor Yellow
    Write-Host "`n手动步骤: " -ForegroundColor Yellow
    Write-Host "  1) 打 tag:  cd $Backend; git tag $Version; git push origin $Version"
    Write-Host "              cd $Android; git tag $Version; git push origin $Version"
    Write-Host "  2) 打开 https://github.com/Liu-XY2003/qwen-schedule-agent/releases/new"
    Write-Host "     tag 选 $Version，标题填 v0.1.0 — 首次发布，说明粘贴 release-notes\$Version.md"
    Write-Host "     资产从 $Stage\backend 拖进去"
    Write-Host "  3) 打开 https://github.com/Liu-XY2003/AI-ScheduleAssistant/releases/new"
    Write-Host "     资产从 $Stage\android 拖进去"
    exit 1
}

$auth = & gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "gh 未登录。跑一次: gh auth login" -ForegroundColor Yellow
    Write-Host $auth
    exit 1
}
Write-Host "  gh 就绪" -ForegroundColor Green

# ---------------------------------------------------------------- 资产检查
Write-Host "`n=== 2. 检查资产 ===" -ForegroundColor Cyan
foreach ($side in 'backend','android') {
    $files = Get-ChildItem "$Stage\$side" -File -ErrorAction SilentlyContinue
    if (-not $files) { Write-Host "  缺少 $Stage\$side 的资产，请先跑打包脚本" -ForegroundColor Red; exit 1 }
    $mb = [math]::Round(($files | Measure-Object Length -Sum).Sum / 1MB, 1)
    Write-Host ("  {0,-8} {1} 个文件, {2} MB" -f $side, $files.Count, $mb)
}

if ($DryRun) {
    Write-Host "`n(-DryRun) 检查通过，未执行任何写操作" -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------- 打 tag
Write-Host "`n=== 3. 打 tag ===" -ForegroundColor Cyan
foreach ($repo in @(@('backend', $Backend), @('android', $Android))) {
    $name, $dir = $repo
    Push-Location $dir
    if (git tag -l $Version) {
        # ★ 必须写 ${name}: —— 写成 "$name:" 会被 PowerShell 当成驱动器限定变量
        Write-Host "  ${name}: tag $Version 已存在" -ForegroundColor Yellow
    } else {
        git tag -a $Version -m "$Version — 首次发布"
        git push origin $Version
        Write-Host "  ${name}: tag $Version 已创建并推送" -ForegroundColor Green
    }
    Pop-Location
}

# ---------------------------------------------------------------- 发 Release
Write-Host "`n=== 4. 创建 Release 并上传资产 ===" -ForegroundColor Cyan
Write-Host "  后端约 1026 MB, 上传需要几分钟, 请勿中断" -ForegroundColor Yellow

Push-Location $Backend
& gh release create $Version `
    --repo 'Liu-XY2003/qwen-schedule-agent' `
    --title "$Version — 首次发布" `
    --notes-file "$Backend\release-notes\$Version.md" `
    ($Stage + '\backend\*')
Pop-Location

Push-Location $Android
& gh release create $Version `
    --repo 'Liu-XY2003/AI-ScheduleAssistant' `
    --title "$Version — 首次发布" `
    --notes-file "$Android\release-notes\$Version.md" `
    ($Stage + '\android\*')
Pop-Location

Write-Host "`n=== 完成 ===" -ForegroundColor Green
Write-Host "  https://github.com/Liu-XY2003/qwen-schedule-agent/releases/tag/$Version"
Write-Host "  https://github.com/Liu-XY2003/AI-ScheduleAssistant/releases/tag/$Version"

<#
.SYNOPSIS
    开源前的敏感信息审计。

.DESCRIPTION
    扫描仓库里不该公开的东西: 私有网络地址、本机绝对路径、账号邮箱、
    密钥样式字符串、以及大文件。开源前必须跑一遍, CI 里也跑。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\audit_secrets.ps1
    powershell -ExecutionPolicy Bypass -File scripts\audit_secrets.ps1 -IncludeIgnored
#>
param(
    [string]$Root = (Resolve-Path "$PSScriptRoot\..").Path,
    [switch]$IncludeIgnored   # 连 .gitignore 里的文件一起扫 (查历史残留用)
)

$ErrorActionPreference = 'Continue'
$findings = New-Object System.Collections.ArrayList

function Add-Finding {
    param([string]$Severity, [string]$Category, [string]$File, [int]$Line, [string]$Sample)
    [void]$findings.Add([pscustomobject]@{
        Severity = $Severity; Category = $Category
        File = $File; Line = $Line; Sample = $Sample
    })
}

# 只扫文本类文件, 跳过二进制/模型/备份
# ★ 必须在**遍历时**就剪枝: backup/ 有 1GB、bench/llama 是整套 llama.cpp 构建产物,
#   先全量 Get-ChildItem -Recurse 再过滤要跑几分钟 (实测直接超时)。
$skipDirs = @('.git', 'node_modules', '.gradle', 'build', '.idea', '.dsh', '.kotlin',
              'backup', 'bench', 'models', 'venv', '.venv', '__pycache__',
              '.pytest_cache', 'screenshots',
              # 已 gitignore 的数据目录: 公开数据集下载物 + 生成的数据集
              'external', 'generated',
              # Release 资产暂存 (GGUF/APK 走 Release 不进 git) + 开源整理归档
              '_release', '_archive')

# 白名单: 命中这些的行不算问题 (公开的通用值, 不是你的私有信息)
$allowPatterns = @(
    '10\.42\.0\.0/16',        # Kubernetes 默认 Pod CIDR, 到处都是
    'audit_secrets\.ps1',     # 审计脚本自己的规则表里必然含这些关键词
    # 文档里惯用的示例地址 (等同 example.com)。README 和推送清单里会写
    # "把 192.168.1.20 换成你电脑的 IP", 这句说明本身会被误报成泄漏。
    '192\.168\.1\.20',
    '100\.100\.100\.100'
)
$skipExt  = @('.png','.jpg','.jpeg','.gif','.webp','.ico','.gguf','.bin','.safetensors',
              '.db','.zip','.gz','.tar','.apk','.jar','.exe','.dll','.so','.pyc',
              '.log','.mp4','.ttf','.otf','.woff','.woff2','.a','.o','.lib','.pdb')

function Get-ScannableFile {
    param(
        [string]$Dir,
        [double]$MaxSizeMB = 2,      # 文本扫描时跳过超大文件; 找大文件时放宽
        [switch]$BinaryToo           # 大文件检查也要看 .gguf/.dll 之类
    )
    foreach ($d in (Get-ChildItem -Path $Dir -Directory -Force -ErrorAction SilentlyContinue)) {
        if ($skipDirs -contains $d.Name) { continue }
        Get-ScannableFile -Dir $d.FullName -MaxSizeMB $MaxSizeMB -BinaryToo:$BinaryToo
    }
    foreach ($f in (Get-ChildItem -Path $Dir -File -Force -ErrorAction SilentlyContinue)) {
        if (-not $BinaryToo -and $skipExt -contains $f.Extension.ToLower()) { continue }
        if ($f.Length -gt ($MaxSizeMB * 1MB)) { continue }
        $f
    }
}

$files = @(Get-ScannableFile -Dir $Root)
if ($files.Count -eq 0) { Write-Host "没有可扫描的文件?" -ForegroundColor Red; exit 1 }

# --- 规则表 -------------------------------------------------------------
# 每条: 名称 / 严重度 / 正则 / 说明
$rules = @(
    @{ N='私有 Tailscale / 内网 IP'; S='HIGH'
       R='\b(100\.(6[4-9]|[7-9]\d|1[0-2]\d)\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b'
       D='暴露你的私有网络拓扑, 改成占位符 100.x.y.z / 192.168.x.x' }
    # ★ 公网 IP 比内网 IP 更容易漏 —— 它长得不像"隐私", 但直接把服务器暴露给全网。
    #   实测就在 README 里漏过一次 (180.201.177.206)。
    @{ N='公网 IPv4 地址'; S='HIGH'
       R='\b(?!10\.|127\.|0\.|255\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.|100\.(6[4-9]|[7-9][0-9]|1[0-2][0-9])\.)(([1-9][0-9]?|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\.){3}([1-9][0-9]?|1[0-9][0-9]|2[0-4][0-9]|25[0-5])\b'
       D='暴露服务器公网地址, 改成 <your-host> 或从环境变量读' }
    @{ N='本机 Windows 绝对路径'; S='MED'
       R='[A-Za-z]:\\\\?(Users|Projects|sdk)\\\\'
       D='暴露本机用户名和目录结构, 改成相对路径或环境变量' }
    @{ N='邮箱地址'; S='MED'
       R='[\w.+-]+@[\w-]+\.[\w.]+'
       D='确认是否是你本人的邮箱; LICENSE 里写版权人是有意的, 其余要清' }
    @{ N='疑似 API Key / Token'; S='HIGH'
       R='(?i)\b(sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|hf_[A-Za-z0-9]{20,})'
       D='密钥不能进仓库 —— 立刻吊销并改从环境变量读' }
    @{ N='硬编码口令赋值'; S='HIGH'
       R='(?i)(password|passwd|secret|api_?key|token)\s*[:=]\s*["''](?!\s*<|\.\.\.|YOUR|your|xxx)[^"'']{6,}["'']'
       D='改成从环境变量读 (本项目自身用 SCHED_TOKEN, 属正常)' }
    @{ N='内网主机名'; S='MED'
       R='(?i)\b(aiserver|compshare|podtcp|cpod-[\w-]+)\b'
       D='暴露你的服务器/平台账号, 改成 <your-host> 占位符' }
    @{ N='SSH 端口 + 用户组合'; S='MED'
       R='ssh\s+-p\s+\d{4,5}\s+\w+@'
       D='暴露 SSH 接入方式' }
)

Write-Host "扫描 $Root" -ForegroundColor Cyan
Write-Host "共 $($files.Count) 个文本文件`n"

foreach ($f in $files) {
    $rel = $f.FullName.Substring($Root.Length).TrimStart('\')
    if ($allowPatterns | Where-Object { $rel -match $_ }) { continue }   # 白名单文件
    $lineNo = 0
    try {
        foreach ($line in [System.IO.File]::ReadAllLines($f.FullName)) {
            $lineNo++
            foreach ($r in $rules) {
                if ($line -match $r.R) {
                    if ($allowPatterns | Where-Object { $line -match $_ }) { continue }
                    $sample = $line.Trim()
                    if ($sample.Length -gt 110) { $sample = $sample.Substring(0, 110) + '…' }
                    Add-Finding $r.S $r.N $rel $lineNo $sample
                }
            }
        }
    } catch { }
}

# --- 大文件 -------------------------------------------------------------
# ★ 只在**会被提交**的目录里找。backup/ 和 bench/ 在 .gitignore 里,
#   它们模型/二进制再大也不会进仓库, 报了只是噪音 (而且拖慢扫描)。
$big = @(Get-ScannableFile -Dir $Root -MaxSizeMB 5000 -BinaryToo | Where-Object { $_.Length -gt 5MB })
foreach ($b in $big) {
    $rel = $b.FullName.Substring($Root.Length).TrimStart('\')
    Add-Finding 'HIGH' '大文件 (>5MB)' $rel 0 ("{0:N1} MB" -f ($b.Length / 1MB))
}

# --- .ps1 必须带 UTF-8 BOM (计划任务用 PowerShell 5.1, 无 BOM 会按 GBK 读崩) ---
foreach ($p in (Get-ChildItem -Path $Root -Recurse -File -Filter *.ps1 -ErrorAction SilentlyContinue)) {
    $rel = $p.FullName.Substring($Root.Length).TrimStart('\')
    $bytes = [System.IO.File]::ReadAllBytes($p.FullName)
    if ($bytes.Length -lt 3 -or $bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF) {
        Add-Finding 'HIGH' '.ps1 缺少 UTF-8 BOM' $rel 0 'PowerShell 5.1 会按 GBK 解析, 中文直接崩'
    }
}

# --- 报告 ---------------------------------------------------------------
$order = @{ 'HIGH' = 0; 'MED' = 1; 'LOW' = 2 }
$sorted = $findings | Sort-Object @{E={$order[$_.Severity]}}, Category, File, Line

if (-not $sorted) {
    Write-Host "未发现敏感信息 —— 可以开源" -ForegroundColor Green
    exit 0
}

$byCat = $sorted | Group-Object Category | Sort-Object @{E={$order[$_.Group[0].Severity]}}, Name
foreach ($g in $byCat) {
    $sev = $g.Group[0].Severity
    $color = if ($sev -eq 'HIGH') { 'Red' } elseif ($sev -eq 'MED') { 'Yellow' } else { 'Gray' }
    Write-Host ("[$sev] {0}  ({1} 处)" -f $g.Name, $g.Count) -ForegroundColor $color
    foreach ($x in ($g.Group | Select-Object -First 12)) {
        $loc = if ($x.Line -gt 0) { "$($x.File):$($x.Line)" } else { $x.File }
        Write-Host ("    {0,-52} {1}" -f $loc, $x.Sample) -ForegroundColor DarkGray
    }
    if ($g.Count -gt 12) { Write-Host "    … 另有 $($g.Count - 12) 处" -ForegroundColor DarkGray }
    Write-Host ""
}

# ★ 用 @() 包住再取 .Count。
#   直接 (...).Count 在结果恰好为 1 个对象时, PowerShell 5.1 会给出空值 ——
#   表现就是"明明有 1 处 HIGH, 却报告 HIGH= 且退出码 0", CI 会直接放行。
$highCount = @($sorted | Where-Object { $_.Severity -eq 'HIGH' }).Count
$medCount  = @($sorted | Where-Object { $_.Severity -eq 'MED' }).Count
Write-Host ("合计 {0} 处:  HIGH={1}  MED={2}" -f @($sorted).Count, $highCount, $medCount)
if ($highCount -gt 0) {
    Write-Host "存在 HIGH 项, 开源前必须处理。" -ForegroundColor Red
    exit 1
}
Write-Host "无 HIGH 项; MED 项请逐条确认是否可接受。" -ForegroundColor Yellow
exit 0

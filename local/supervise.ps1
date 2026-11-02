# =====================================================================
# 日程助手 · 本机守候进程
#
# 职责: 保证 llama-server(18080) 和 Web App(8800) 一直在跑。
#       - 启动时不重复拉起已在运行的实例
#       - 任一服务挂掉自动重启, 带退避, 避免疯狂重启
#       - 单实例锁, 防止被启动两次
#
# 用法:
#   .\supervise.ps1              常驻守候 (由计划任务调用)
#   .\supervise.ps1 -Once        只启动+检查一次, 不进循环 (调试)
#   .\supervise.ps1 -Stop        停掉两个服务并退出
# =====================================================================
param(
    [switch]$Once,
    [switch]$Stop,
    [int]$IntervalSec = 20,
    [string]$Quant = 'Q4_K_M'      # Q4_K_M 比 Q8_0 快 1.5 倍且更小
)

$ErrorActionPreference = 'Continue'

# ---------------------------------------------------------------- 配置
$Root     = 'D:\Projects\qwen-local-tool-agent'
$LlamaDir = "$Root\bench\llama"
$LocalDir = "$Root\local"
$BridgeDir = "$Root\bridge"        # ★ 源码唯一位置
$Model    = "$Root\backup\sched-backup\model\qwen3-0.6b-sched-v4-$Quant.gguf"
$LlamaPort = 18080
$AppPort   = 8800
$LogFile   = "$LocalDir\supervisor.log"
$LockFile  = "$LocalDir\.supervisor.lock"
$MaxLogMB  = 4

# ★ 必须用绝对路径定位 python。
# 坑: 计划任务的 PATH 上下文与交互式会话不同 —— 实测它会解析到
#     C:\msys64\ucrt64\bin\python.exe (没有 uvicorn), 导致 App 反复"启动即退出"。
#     所以这里主动探测一个确实能 import uvicorn 的解释器。
function Resolve-Python {
    $cands = @(
        # 用环境变量拼, 不写死本机用户名 (仓库要公开)
        "$env:USERPROFILE\anaconda3\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:USERPROFILE\miniconda3\python.exe"
    )
    foreach ($c in @('python.exe', 'python3.exe')) {
        Get-Command $c -ErrorAction SilentlyContinue | ForEach-Object { $cands += $_.Source }
    }
    foreach ($p in ($cands | Select-Object -Unique)) {
        if (-not (Test-Path $p)) { continue }
        & $p -c "import uvicorn, fastapi, pydantic, jsonschema" 2>$null
        if ($LASTEXITCODE -eq 0) { return $p }
    }
    return $null
}
$PythonExe = Resolve-Python

# ---------------------------------------------------------------- 日志
function Write-Log {
    param([string]$Msg, [string]$Level = 'INFO')
    $line = "[{0}] [{1,-5}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Msg
    Write-Host $line
    try {
        if ((Test-Path $LogFile) -and (Get-Item $LogFile).Length -gt $MaxLogMB * 1MB) {
            Remove-Item "$LogFile.1" -ErrorAction SilentlyContinue
            Move-Item $LogFile "$LogFile.1" -Force -ErrorAction SilentlyContinue
        }
        Add-Content -Path $LogFile -Value $line -Encoding UTF8
    } catch { }
}

# ---------------------------------------------------------------- 工具

function Get-PortPid([int]$Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($c) { return ($c | Select-Object -First 1).OwningProcess }
    return $null
}

function Test-Http([string]$Url, [int]$TimeoutSec = 4) {
    try {
        $r = Invoke-RestMethod $Url -TimeoutSec $TimeoutSec
        return $r
    } catch { return $null }
}

function Stop-Port([int]$Port, [string]$Why) {
    $procId = Get-PortPid $Port
    if (-not $procId) { return $false }
    Write-Log "停止 :$Port (pid=$procId) —— $Why" 'WARN'
    try {
        Stop-Process -Id $procId -Force -ErrorAction Stop
    } catch {
        # 可能是别的用户的进程, 别硬来
        Write-Log "  停止失败: $($_.Exception.Message)" 'ERROR'
        return $false
    }
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Milliseconds 500
        if (-not (Get-PortPid $Port)) { return $true }
    }
    return $false
}

# ---------------------------------------------------------------- 启动

function Start-Llama {
    if (Get-PortPid $LlamaPort) { return $true }        # 已在跑, 不重复拉
    if (-not (Test-Path $Model)) {
        Write-Log "模型文件不存在: $Model" 'ERROR'; return $false
    }
    if (-not (Test-Path "$LlamaDir\llama-server.exe")) {
        Write-Log "llama-server.exe 不存在: $LlamaDir" 'ERROR'; return $false
    }
    Write-Log "启动 llama-server ($Quant)"
    # 每次启动截断日志, 避免无限增长
    $outLog = "$LocalDir\llama-server.log"
    $errLog = "$LocalDir\llama-server.err.log"
    Remove-Item $outLog, $errLog -ErrorAction SilentlyContinue
    $p = Start-Process -FilePath "$LlamaDir\llama-server.exe" `
        -ArgumentList @('-m', $Model, '-ngl', '99', '-c', '2048',
                        '--host', '127.0.0.1', '--port', "$LlamaPort",
                        '--jinja', '-np', '1',
                        # ★ 必须关掉 Qwen3 的思考模式。
                        #   实测: 开着时模型把整个 token 预算都耗在 reasoning 上,
                        #   4B 上甚至一个正文字都不输出。关掉后输出逐字一致,
                        #   延迟 ~1900ms -> ~526ms (3.6 倍)。
                        '--reasoning', 'off') `
        -WorkingDirectory $LlamaDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    Write-Log "  pid=$($p.Id)"

    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Http "http://127.0.0.1:$LlamaPort/health") {
            Write-Log "  llama-server 就绪 ($($i+1)s)"; return $true
        }
        if ($p.HasExited) { Write-Log "  llama-server 启动即退出, 见 $errLog" 'ERROR'; return $false }
    }
    Write-Log "  llama-server 超时未就绪" 'ERROR'
    return $false
}

function Start-App {
    if (Get-PortPid $AppPort) { return $true }
    if (-not $PythonExe) {
        Write-Log "找不到装了 uvicorn/fastapi 的 python 解释器 (PATH 里的 python 可能不对)" 'ERROR'
        return $false
    }
    Write-Log "启动 Web App (python=$PythonExe)"
    $outLog = "$LocalDir\app.log"
    $errLog = "$LocalDir\app.err.log"
    Remove-Item $outLog, $errLog -ErrorAction SilentlyContinue
    $env:SCHED_LLAMA_URL = "http://127.0.0.1:$LlamaPort"
    # ★ 用 --app-dir 指向 bridge/, 而不是往 local/ 里再拷一份 app.py。
    #   之前 local/ 有三份源码副本 (app/executor/schema_models), 改一边忘一边就会
    #   出现"代码改了但线上没变"的假象 —— 实测已经分叉过一次。
    #   数据库留在 local/ 下, 通过 SCHED_DB 指定。
    $env:SCHED_DB = "$LocalDir\schedule.db"
    $p = Start-Process -FilePath $PythonExe `
        -ArgumentList @('-m', 'uvicorn', 'app:app', '--app-dir', $BridgeDir,
                        '--host', '0.0.0.0', '--port', "$AppPort") `
        -WorkingDirectory $LocalDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    Write-Log "  pid=$($p.Id)"
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        $h = Test-Http "http://127.0.0.1:$AppPort/api/health"
        if ($h -and $h.ready) { Write-Log "  App 就绪 ($($i+1)s), 后端=$($h.backend)"; return $true }
        if ($p.HasExited) { Write-Log "  App 启动即退出, 见 $errLog" 'ERROR'; return $false }
    }
    Write-Log "  App 超时未就绪" 'ERROR'
    return $false
}

# ---------------------------------------------------------------- 单实例锁

if (Test-Path $LockFile) {
    $old = Get-Content $LockFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($old) {
        $alive = Get-Process -Id ([int]$old) -ErrorAction SilentlyContinue
        if ($alive -and $alive.ProcessName -match 'powershell|pwsh') {
            Write-Log "另一个守候进程已在运行 (pid=$old), 退出" 'WARN'
            exit 0
        }
    }
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
}
$PID | Out-File $LockFile -Encoding ASCII

# ---------------------------------------------------------------- -Stop

if ($Stop) {
    Write-Log "=== 停止服务 (-Stop) ==="
    Stop-Port $AppPort '手动停止' | Out-Null
    Stop-Port $LlamaPort '手动停止' | Out-Null
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    Write-Log "已停止"
    exit 0
}

# ---------------------------------------------------------------- 主流程

Write-Log "=== 守候进程启动 (pid=$PID, 间隔 ${IntervalSec}s) ==="
Write-Log "模型: $Quant  |  llama :$LlamaPort  |  app :$AppPort"
Write-Log "python: $(if($PythonExe){$PythonExe}else{'❌ 未找到可用解释器'})"
if (-not $PythonExe) { Write-Log "App 将无法启动, 请检查 Python 环境" 'ERROR' }

if (-not (Start-Llama)) { Write-Log "首次启动 llama-server 失败" 'ERROR' }
if (-not (Start-App))   { Write-Log "首次启动 App 失败" 'ERROR' }

if ($Once) {
    Write-Log "(-Once) 单次检查完成"
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    exit 0
}

$llamaFails = 0
$appFails = 0
try {
    while ($true) {
        Start-Sleep -Seconds $IntervalSec

        # --- llama-server ---
        $lh = Test-Http "http://127.0.0.1:$LlamaPort/health"
        if (-not $lh) {
            $llamaFails++
            Write-Log "llama-server 无响应 (第 $llamaFails 次)" 'WARN'
            Stop-Port $LlamaPort '无响应' | Out-Null
            # 退避: 连续失败就多等一会儿再拉, 避免死循环刷日志
            if ($llamaFails -gt 3) { Start-Sleep -Seconds ([Math]::Min(60, $llamaFails * 10)) }
            if (Start-Llama) { $llamaFails = 0 }
        } else { $llamaFails = 0 }

        # --- app ---
        $ah = Test-Http "http://127.0.0.1:$AppPort/api/health"
        if (-not $ah) {
            $appFails++
            Write-Log "Web App 无响应 (第 $appFails 次)" 'WARN'
            Stop-Port $AppPort '无响应' | Out-Null
            if ($appFails -gt 3) { Start-Sleep -Seconds ([Math]::Min(60, $appFails * 10)) }
            if (Start-App) { $appFails = 0 }
        } else { $appFails = 0 }
    }
}
finally {
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    Write-Log "=== 守候进程退出 ==="
}

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$root = 'D:\Projects\qwen-local-tool-agent\bench'
New-Item -ItemType Directory -Force -Path $root | Out-Null
$log = Join-Path $root 'bench.log'
function Log($m) { $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m; $line | Tee-Object -FilePath $log -Append }
$PROXY = 'http://127.0.0.1:7897'
function Get-File($url, $dest, $minMB) {
    if ((Test-Path $dest) -and ((Get-Item $dest).Length / 1MB) -ge $minMB) { Log ("cached: " + (Split-Path $dest -Leaf)); return $true }
    Log ("GET " + $url)
    if ($url -match 'hf-mirror\.com') {
        curl.exe -L --retry 3 --retry-delay 2 --connect-timeout 30 -s -o $dest $url
    } else {
        curl.exe -x $PROXY -L --retry 3 --retry-delay 2 --connect-timeout 30 -s -o $dest $url
    }
    $mb = if (Test-Path $dest) { [math]::Round((Get-Item $dest).Length / 1MB, 1) } else { 0 }
    Log ("  -> " + $mb + "MB")
    return ($mb -ge $minMB)
}

Log "=========== BENCH START ==========="

# ---------- llama.cpp Vulkan build ----------
$zip = Join-Path $root 'llama-vulkan.zip'
Get-File 'https://github.com/ggml-org/llama.cpp/releases/download/b11053/llama-b11053-bin-win-vulkan-x64.zip' $zip 25 | Out-Null
$llamaDir = Join-Path $root 'llama'
if (-not (Test-Path (Join-Path $llamaDir 'llama-cli.exe'))) {
    Log "extracting llama.cpp ..."
    try { Expand-Archive -Path $zip -DestinationPath $llamaDir -Force } catch { Log ("extract failed: " + $_.Exception.Message) }
}
$cli = Join-Path $llamaDir 'llama-cli.exe'
$bench = Join-Path $llamaDir 'llama-bench.exe'
Log ("llama-cli present: " + (Test-Path $cli))

# ---------- models ----------
$models = @(
    @{ name = 'Qwen3-0.6B-Q4_K_M.gguf'; url = 'https://hf-mirror.com/unsloth/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf'; min = 300 },
    @{ name = 'Qwen3-1.7B-Q4_K_M.gguf'; url = 'https://hf-mirror.com/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf'; min = 900 },
    @{ name = 'Qwen3-4B-Q4_K_M.gguf'; url = 'https://hf-mirror.com/unsloth/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf'; min = 2000 }
)
foreach ($m in $models) { Get-File $m.url (Join-Path $root $m.name) $m.min | Out-Null }

# ---------- device enumeration ----------
if (Test-Path $cli) {
    Log "--- devices (llama-cli --list-devices) ---"
    Log ((& $cli --list-devices 2>&1 | Out-String).Trim())
    Log "--- json-schema support? ---"
    Log (((& $cli --help 2>&1 | Out-String) -split "`n" | Select-String -Pattern 'json-schema|grammar' | Out-String).Trim())
}

# ---------- llama-bench: iGPU vs CPU ----------
foreach ($m in $models) {
    $model = Join-Path $root $m.name
    if (-not (Test-Path $model)) { continue }
    foreach ($ngl in 99, 0) {
        $tag = if ($ngl -eq 99) { 'iGPU(880M)' } else { 'CPU(Zen5)' }
        Log ("--- llama-bench " + $tag + " " + $m.name + " ---")
        $r = & $bench -m $model -ngl $ngl -p 512 -n 128 -r 3 -t 8 2>&1 | Out-String
        Log $r.Trim()
    }
}

# ---------- real task latency ----------
# 注意: b11053 起 llama-cli 用 -st/--single-turn 取代了旧的 -no-cnv
# 更贴近生产路径的对照实验见 probe_json.mjs (走 llama-server + json_schema)
$sys = 'You convert Chinese scheduling requests into JSON. Output only JSON matching the schema.'
$usr = '为我的周二上午九点添加一个计算机原理的课程'
foreach ($m in $models) {
    $model = Join-Path $root $m.name
    if (-not (Test-Path $model)) { continue }
    Log ("--- latency test " + $m.name + " (iGPU) ---")
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $out = & $cli -m $model -ngl 99 -st -t 8 -n 128 -p "$sys`n$usr" 2>&1 | Out-String
    $sw.Stop()
    Log ("wall=" + [math]::Round($sw.Elapsed.TotalSeconds, 1) + "s")
    Log ($out.Trim())
}
Log "=========== BENCH DONE ==========="

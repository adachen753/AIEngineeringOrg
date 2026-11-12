param(
    [switch]$UI,
    [switch]$DesktopBridge,
    [string]$Python = '',
    [string]$Node = 'node',
    [string]$AdapterEntry = 'adapter/src/server.ts',
    [int]$ApiPort = 8765,
    [int]$AdapterPort = 8766,
    [int]$UiPort = 8501,
    [int]$BridgePort = 8767,
    [string]$DataDir = '.aim-data'
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$stateDir = Join-Path $root '.aim-launch'
$stateFile = Join-Path $stateDir 'processes.json'
if (Test-Path -LiteralPath $stateFile) { throw 'Launch record exists. Run scripts/stop.ps1 first; do not overwrite ownership records.' }
if (-not $Python) { $Python = Join-Path $root '.venv/Scripts/python.exe' }
$pythonExe = (Get-Command $Python -ErrorAction Stop).Source
$nodeExe = (Get-Command $Node -ErrorAction Stop).Source
$entry = [IO.Path]::GetFullPath((Join-Path $root $AdapterEntry))
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw "Adapter entry missing: $entry. Install adapter sources or pass -AdapterEntry." }
if ($DesktopBridge -and (-not $env:AIM_BRIDGE_CONFIG -or $env:AIM_DESKTOP_BRIDGE_TOKEN.Length -lt 32)) { throw 'DesktopBridge requires AIM_BRIDGE_CONFIG and a token of at least 32 characters.' }
foreach ($port in @($ApiPort, $AdapterPort) + $(if ($UI) { @($UiPort) } else { @() }) + $(if ($DesktopBridge) { @($BridgePort) } else { @() })) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw "Port $port already occupied; no existing process will be killed." }
}
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$env:AIM_DATA_DIR = if ([IO.Path]::IsPathRooted($DataDir)) { [IO.Path]::GetFullPath($DataDir) } else { [IO.Path]::GetFullPath((Join-Path $root $DataDir)) }
$env:AIM_ADAPTER_URL = "http://127.0.0.1:$AdapterPort"
$env:AIM_ADAPTER_DATA = Join-Path $env:AIM_DATA_DIR 'adapter'
$env:AIM_API_URL = "http://127.0.0.1:$ApiPort"
$env:AIM_ADAPTER_DATA = Join-Path $env:AIM_DATA_DIR 'adapter'
$env:PORT = "$AdapterPort"
$env:HOST = '127.0.0.1'
$owned = [Collections.Generic.List[object]]::new()
function Start-Owned([string]$name, [string]$executable, [string[]]$arguments) {
    $process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $stateDir "$name.out.log") -RedirectStandardError (Join-Path $stateDir "$name.err.log")
    $process.Refresh()
    $owned.Add([pscustomobject]@{ name = $name; pid = $process.Id; started = $process.StartTime.ToUniversalTime().Ticks.ToString(); executable = $executable; adapter_data = $(if ($name -eq 'adapter') { $env:AIM_ADAPTER_DATA } else { $null }) })
    ConvertTo-Json -InputObject @($owned.ToArray()) | Set-Content -LiteralPath $stateFile -Encoding utf8
}
function Wait-Healthy([string]$url, [hashtable]$headers = @{}) {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try { Invoke-RestMethod -Uri $url -Headers $headers -TimeoutSec 2 | Out-Null; return } catch { Start-Sleep -Milliseconds 500 }
    }
    throw "Health check failed: $url. Inspect $stateDir logs."
}
try {
    if ($DesktopBridge) {
        Start-Owned 'desktop-bridge' $pythonExe @('-m', 'uvicorn', 'ai_manager.desktop_bridge:app', '--host', '127.0.0.1', '--port', "$BridgePort", '--workers', '1')
        Wait-Healthy "http://127.0.0.1:$BridgePort/health" @{ Authorization = "Bearer $env:AIM_DESKTOP_BRIDGE_TOKEN" }
    }
    Start-Owned 'adapter' $nodeExe @(('"' + $entry + '"'))
    Wait-Healthy "$env:AIM_ADAPTER_URL/health"
    Start-Owned 'backend' $pythonExe @('-m', 'uvicorn', 'ai_manager.api:app', '--host', '127.0.0.1', '--port', "$ApiPort", '--workers', '1')
    Wait-Healthy "$env:AIM_API_URL/health"
    if ($UI) {
        Start-Owned 'ui' $pythonExe @('-m', 'streamlit', 'run', 'ai_manager/ui.py', '--server.address', '127.0.0.1', '--server.port', "$UiPort", '--server.headless', 'true')
        Wait-Healthy "http://127.0.0.1:$UiPort/_stcore/health"
    }
    Write-Output "API: $env:AIM_API_URL ; logs: $stateDir"
    if ($UI) { Write-Output "UI: http://127.0.0.1:$UiPort" }
} catch {
    Write-Warning 'Startup failed; stopping only recorded owned processes.'
    & (Join-Path $PSScriptRoot 'stop.ps1')
    throw
}

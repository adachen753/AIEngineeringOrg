param()
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$stateFile = Join-Path $root '.aim-launch/processes.json'
if (-not (Test-Path -LiteralPath $stateFile)) { Write-Output 'No owned launch record.'; return }
$records = @(Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json)
$unresolved = $false
[array]::Reverse($records)
foreach ($record in $records) {
    $process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    try {
        $sameStart = $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $record.started
        $samePath = [IO.Path]::GetFullPath($process.Path) -eq [IO.Path]::GetFullPath($record.executable)
        if (-not ($sameStart -and $samePath)) {
            Write-Warning "PID $($record.pid) identity changed; will not stop it."
            continue
        }
        & taskkill.exe /PID $process.Id /T /F | Out-Null
        if ($LASTEXITCODE -ne 0 -and -not $process.HasExited) { throw 'Owned process-tree stop failed' }
        $process.WaitForExit(10000) | Out-Null
        if (-not $process.HasExited) { throw 'Process did not exit' }
    } catch {
        $unresolved = $true
        Write-Warning "Unable to confirm stop of owned PID $($record.pid): $_"
    }
}
foreach ($record in $records) {
    if ($record.name -ne 'adapter' -or -not $record.adapter_data) { continue }
    $directory = [IO.Path]::GetFullPath($record.adapter_data)
    $normalized = $directory.Replace('\', '/').TrimEnd('/').ToLowerInvariant()
    foreach ($protected in @('q:/graphconnectors/cwzclaude', 'q:/graphconnectors/sources/dev/cwzclaude-sql')) {
        if ($normalized -eq $protected -or $normalized.StartsWith($protected + '/')) { throw 'Protected adapter directory; refusing mutation' }
    }
    $lockFile = Join-Path $directory '.exclusive.lock'
    if (-not (Test-Path -LiteralPath $lockFile -PathType Leaf)) { continue }
    $owner = Get-Content -LiteralPath $lockFile -Raw | ConvertFrom-Json
    if ($owner.pid -ne $record.pid -or (Get-Process -Id $owner.pid -ErrorAction SilentlyContinue)) {
        $unresolved = $true
        Write-Warning 'Adapter lock ownership cannot be safely reconciled; retained.'
        continue
    }
    Remove-Item -LiteralPath $lockFile
}
if ($unresolved) { throw 'Some owned processes could not be stopped; ownership record retained.' }
Remove-Item -LiteralPath $stateFile
Write-Output 'Recorded owned process trees stopped. Data and logs retained. Active workflows require recovery inspection.'

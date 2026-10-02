$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$syncScript = Join-Path $projectRoot 'sync_web.py'
$pythonPath = 'C:\Users\antho\AppData\Local\Programs\Python\Python313\python.exe'
$resultPath = Join-Path $projectRoot 'logs\web_sync_install.json'
try {
    $syncAction = New-ScheduledTaskAction -Execute $pythonPath -Argument ('"' + $syncScript + '"') -WorkingDirectory $projectRoot
    $syncTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $syncSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    # Reuse the daily collector's existing S4U identity, which works when logged out.
    $syncPrincipal = (Get-ScheduledTask -TaskName 'r_monitor_daily').Principal
    Register-ScheduledTask -TaskName 'r_monitor_web_sync' -Action $syncAction -Trigger $syncTrigger -Settings $syncSettings -Principal $syncPrincipal -Description 'Synchronise eSaver family registration records from the hub inbox every minute; no external HTTP calls.' -Force | Out-Null
    Start-ScheduledTask -TaskName 'r_monitor_web_sync'
    @{ ok = $true; task = 'r_monitor_web_sync'; at = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
    & $pythonPath (Join-Path $projectRoot 'main.py') --build-only
    if ($LASTEXITCODE -ne 0) { throw 'Task installed but web status rebuild failed' }
} catch {
    @{ ok = $false; error = $_.Exception.Message; at = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
    exit 1
}

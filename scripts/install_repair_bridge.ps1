param([switch]$Preview)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$pythonw = Join-Path (Split-Path (Get-Command python).Source) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'pythonw.exe is unavailable' }
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonw -Argument '-B -m src.repair_bridge --work' -WorkingDirectory $root
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 6) -MultipleInstances IgnoreNew
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
if ($Preview) {
 [PSCustomObject]@{name='RMonitorCodexRepair';action=$action;principal=$principal;settings=$settings;trigger=$trigger} | ConvertTo-Json -Depth 3
 exit 0
}
$backup = Join-Path $root 'logs\repair_bridge'
New-Item -ItemType Directory -Force -Path $backup | Out-Null
$existing = Get-ScheduledTask -TaskName 'RMonitorCodexRepair' -TaskPath '\' -ErrorAction SilentlyContinue
if ($existing) { Export-ScheduledTask -TaskName 'RMonitorCodexRepair' -TaskPath '\' | Set-Content -LiteralPath (Join-Path $backup ('before_'+(Get-Date -Format yyyyMMdd_HHmmss)+'.xml')) -Encoding Unicode }
Register-ScheduledTask -TaskName 'RMonitorCodexRepair' -TaskPath '\' -Action $action -Principal $principal -Settings $settings -Trigger $trigger -Description 'Offline isolated Codex repair only; daily bank writer remains r_monitor_daily; no connectors, no external HTTP, no push.' -Force | Out-Null
$task = Get-ScheduledTask -TaskName 'RMonitorCodexRepair' -TaskPath '\'
if ([string]$task.Principal.LogonType -ne 'Interactive' -or [string]$task.Principal.RunLevel -ne 'Limited' -or $task.Actions.Execute -ne $pythonw -or $task.Actions.Arguments -ne '-B -m src.repair_bridge --work' -or $task.Actions.WorkingDirectory -ne $root) { throw 'Installed task identity verification failed' }
'RMonitorCodexRepair installed and verified; bank writer unchanged'

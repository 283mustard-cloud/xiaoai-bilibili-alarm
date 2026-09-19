$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$appScript = Join-Path $projectRoot 'alarm_app.py'
$pythonExe = (Get-Command python -ErrorAction Stop).Source
$appAction = New-ScheduledTaskAction -Execute $pythonExe -Argument ('"' + $appScript + '"') -WorkingDirectory $projectRoot
$appTrigger = New-ScheduledTaskTrigger -AtLogOn
$appSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName 'XiaoAiBiliAlarm-App' -Action $appAction -Trigger $appTrigger -Settings $appSettings -Description 'Local alarm dashboard and schedule runner' -Force | Out-Null
Disable-ScheduledTask -TaskName 'XiaoAiBiliAlarm-Prepare' -ErrorAction SilentlyContinue | Out-Null
Disable-ScheduledTask -TaskName 'XiaoAiBiliAlarm-Play' -ErrorAction SilentlyContinue | Out-Null
Write-Output 'Dashboard startup task registered; old fixed-time tasks disabled.'

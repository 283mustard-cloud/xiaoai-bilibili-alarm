# Run as administrator. Registers the dashboard/scheduler to start at sign-in.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$appScript = Join-Path $projectRoot 'alarm_app.py'

# Prefer a project virtual environment, then the python launcher, then PATH.
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $pythonExe = $venvPython
} else {
    $pythonExe = (Get-Command python -ErrorAction Stop).Source
}
Write-Output "Using interpreter: $pythonExe"

$appAction = New-ScheduledTaskAction -Execute $pythonExe -Argument ('"' + $appScript + '"') -WorkingDirectory $projectRoot
$appTrigger = New-ScheduledTaskTrigger -AtLogOn
# StartWhenAvailable catches up when sign-in happened after the alarm time.
# WakeToRun is deliberately NOT set: it only wakes the machine for triggers of
# this task, and this task has no daily trigger - the schedule lives inside
# alarm_app.py. A sleeping machine therefore cannot be woken at the alarm time;
# keep it awake, or register a separate daily wake timer at your play time.
$appSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName 'XiaoAiBiliAlarm-App' -Action $appAction -Trigger $appTrigger -Settings $appSettings -Description 'Local alarm dashboard and schedule runner' -Force | Out-Null
Disable-ScheduledTask -TaskName 'XiaoAiBiliAlarm-Prepare' -ErrorAction SilentlyContinue | Out-Null
Disable-ScheduledTask -TaskName 'XiaoAiBiliAlarm-Play' -ErrorAction SilentlyContinue | Out-Null
Write-Output 'Dashboard startup task registered; old fixed-time tasks disabled.'
Write-Output 'The scheduler runs inside the signed-in user session, and this task has no daily trigger, so:'
Write-Output '  - the computer must stay logged in;'
Write-Output '  - a sleeping computer will NOT be woken for the alarm.'
Write-Output 'If wake-up matters, create a separate daily wake timer at your play time:'
Write-Output '  powercfg /waketimers   # list;  Task Scheduler can also wake a task you give a daily trigger'

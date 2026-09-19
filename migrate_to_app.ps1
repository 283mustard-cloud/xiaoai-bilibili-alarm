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
# WakeToRun so a sleeping machine is woken for the alarm; StartWhenAvailable
# catches up if the wake-up or sign-in happened late.
$appSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName 'XiaoAiBiliAlarm-App' -Action $appAction -Trigger $appTrigger -Settings $appSettings -Description 'Local alarm dashboard and schedule runner' -Force | Out-Null
Disable-ScheduledTask -TaskName 'XiaoAiBiliAlarm-Prepare' -ErrorAction SilentlyContinue | Out-Null
Disable-ScheduledTask -TaskName 'XiaoAiBiliAlarm-Play' -ErrorAction SilentlyContinue | Out-Null
Write-Output 'Dashboard startup task registered; old fixed-time tasks disabled.'
Write-Output 'Note: the scheduler lives in the signed-in user session, so the computer must stay logged in.'

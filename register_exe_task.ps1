# Points the startup task at the packaged exe instead of alarm_app.py.
#
# Run as administrator:
#     powershell -ExecutionPolicy Bypass -File .\register_exe_task.ps1
#
# Both launchers run the same scheduler; run only one of them.
param(
    [string]$ExeName = 'XiaoAiBiliAlarm.exe',
    [string]$TaskName = 'XiaoAiBiliAlarm-App',
    [switch]$KeepWindow
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $projectRoot $ExeName
if (-not (Test-Path $exe)) { throw "exe not found: $exe (build it with build_exe.ps1)" }

# Keep a copy of the current task definition so this is reversible.
$backup = Join-Path $projectRoot 'logs\task-backup-App.xml'
New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Export-ScheduledTask -TaskName $TaskName | Set-Content -Path $backup -Encoding UTF8
    Write-Output "Previous task definition backed up to $backup"
}

# New-ScheduledTaskAction rejects an empty -Argument, so only pass it when set.
$actionArgs = @{ Execute = $exe; WorkingDirectory = $projectRoot }
if ($KeepWindow) { $actionArgs['Argument'] = '--no-window' }
$action = New-ScheduledTaskAction @actionArgs
$trigger = New-ScheduledTaskTrigger -AtLogOn
# Interactive logon type keeps the tray icon in the signed-in desktop session;
# a password-less account therefore works without storing credentials.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited
# No WakeToRun: this task has no daily trigger, so it could not wake the machine
# at the alarm time anyway (the schedule lives inside the app).
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'Alarm tray app (scheduler + dashboard + tray icon)' -Force | Out-Null

Write-Output "Registered $TaskName -> $exe $(if ($KeepWindow) { '--no-window' } else { '(tray + window)' })"
Write-Output "Starting it now..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 12
$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Output ("state={0} lastRun={1}" -f (Get-ScheduledTask -TaskName $TaskName).State, $info.LastRunTime)
Write-Output "A tray icon should now be visible near the clock."

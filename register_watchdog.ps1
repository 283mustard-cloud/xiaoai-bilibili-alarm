# Registers the port watchdog: every 5 minutes, restart the alarm app task if
# nothing is listening on the dashboard port. Run as administrator.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$watchScript = Join-Path $projectRoot 'watch_alarm.ps1'
$taskName = 'XiaoAiBiliAlarm-Watchdog'
# The watchdog may need to stop/start another task, hence Highest.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $watchScript + '"') `
    -WorkingDirectory $projectRoot
# Task Scheduler cannot repeat indefinitely. A trigger that starts daily at
# 02:00 and repeats every 5 minutes for 24 hours therefore covers every moment
# without a lapse and re-arms itself each day, unlike a one-off window that
# silently expires (which leaves NextRunTime empty and the check never runs).
$startAt = (Get-Date).Date.AddHours(2)
$trigger = New-ScheduledTaskTrigger -Daily -At $startAt
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At $startAt `
        -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'Restart the alarm app if port 58100 stops listening' -Force | Out-Null

Write-Output "Registered $taskName (every 5 minutes)."
Write-Output "It runs as $($principal.UserId), so it only works while that user is signed in."
Write-Output "Check its activity with:  Get-Content '$projectRoot\logs\watchdog.log'"

# Run only after XiaoMusic can play the MP3 on the physical speaker.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = (Get-Command python -ErrorAction Stop).Source
$prepareScript = Join-Path $projectRoot 'prepare_episode.py'
$playScript = Join-Path $projectRoot 'play_alarm.py'
$serverScript = Join-Path $projectRoot 'launch_xiaomusic.py'

$serverAction = New-ScheduledTaskAction -Execute $pythonExe -Argument ('"' + $serverScript + '"') -WorkingDirectory $projectRoot
$prepareAction = New-ScheduledTaskAction -Execute $pythonExe -Argument ('"' + $prepareScript + '"') -WorkingDirectory $projectRoot
$playAction = New-ScheduledTaskAction -Execute $pythonExe -Argument ('"' + $playScript + '"') -WorkingDirectory $projectRoot
$serverTrigger = New-ScheduledTaskTrigger -AtLogOn
$prepareTrigger = New-ScheduledTaskTrigger -Daily -At 07:00
$playTrigger = New-ScheduledTaskTrigger -Daily -At 07:30
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$serverSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

Register-ScheduledTask -TaskName 'XiaoAiBiliAlarm-XiaoMusic' -Action $serverAction -Trigger $serverTrigger -Settings $serverSettings -Description 'Start XiaoMusic at sign-in' -Force | Out-Null
Register-ScheduledTask -TaskName 'XiaoAiBiliAlarm-Prepare' -Action $prepareAction -Trigger $prepareTrigger -Settings $settings -Description 'Prepare the selected Bilibili audio' -Force | Out-Null
Register-ScheduledTask -TaskName 'XiaoAiBiliAlarm-Play' -Action $playAction -Trigger $playTrigger -Settings $settings -Description 'Play the configured alarm' -Force | Out-Null
Write-Output 'Registered XiaoMusic startup, preparation, and playback tasks.'

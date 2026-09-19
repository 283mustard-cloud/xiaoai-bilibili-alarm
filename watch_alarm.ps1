# Keeps the alarm dashboard/scheduler listening, because the app task itself
# cannot recover from an external kill: its restart settings only apply to
# failures Task Scheduler observes (which is why a killed service previously
# stayed down until it was started by hand).
#
# Registered by watch_alarm.ps1 as a task that runs every 5 minutes.
param(
    [int]$Port = 58100,
    [string]$TaskName = 'CSWanShiWu-App',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $projectRoot 'logs'
$logPath = Join-Path $logDir 'watchdog.log'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

function Write-Log([string]$message) {
    Add-Content -Path $logPath -Value "$stamp $message" -Encoding UTF8
}

# Keep the log from growing without bound.
if ((Test-Path $logPath) -and (Get-Item $logPath).Length -gt 500KB) {
    $tail = Get-Content $logPath -Tail 300
    Set-Content -Path $logPath -Value $tail -Encoding UTF8
}

$listening = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($listening) {
    if ($DryRun) { Write-Output "OK: port $Port is listening (pid $($listening[0].OwningProcess))" }
    # One heartbeat a day proves the watchdog itself is still running, without
    # filling the log with a line every five minutes.
    $lastBeat = if (Test-Path $logPath) { (Get-Content $logPath -Tail 1) -join ' ' } else { '' }
    if ($lastBeat -notmatch ('^' + (Get-Date -Format 'yyyy-MM-dd') + '.*heartbeat')) {
        Write-Log "heartbeat: port $Port healthy (pid $($listening[0].OwningProcess))"
    }
    exit 0
}

Write-Log "port $Port is not listening"
if ($DryRun) {
    Write-Output "MISSING: port $Port is not listening; would start task '$TaskName'"
    exit 2
}

# Resolve the task. Get-ScheduledTask -TaskName matches names only, so a task
# in a subfolder is found by scanning paths; this also avoids tripping the
# module's ErrorActionPreference handling. Throwing an error record (instead of
# a string) keeps this reliable when ErrorActionPreference is Stop.
function Find-AlarmTask([string]$name) {
    $simple = $name.TrimStart('\')
    foreach ($task in (Get-ScheduledTask -ErrorAction SilentlyContinue)) {
        if ($task.TaskName -eq $simple) { return $task }
        $full = ($task.TaskPath + $task.TaskName).TrimStart('\')
        if ($full -eq $simple) { return $task }
    }
    return $null
}

try {
    $task = Find-AlarmTask $TaskName
    if ($null -eq $task) {
        throw New-Object System.Management.Automation.ItemNotFoundException "scheduled task '$TaskName' was not found"
    }
    $taskPath = $task.TaskPath
    $taskName = $task.TaskName

    if ($task.State -eq 'Running') {
        # The task process may be alive but not serving (or the state may be
        # stale after a kill). Give it a moment, then force a clean restart.
        Start-Sleep -Seconds 15
        if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
            Write-Log "task $taskName was running; port came up by itself"
            exit 0
        }
        Write-Log "task $taskName is running but port $Port stayed closed; restarting it"
        Stop-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5
    }

    # A start can be refused (0x1) while Task Scheduler still considers the
    # previous instance active, so retry a few times before giving up.
    $started = $false
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        try {
            Start-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction Stop
            $started = $true
        } catch {
            Write-Log "start attempt $attempt failed: $($_.Exception.Message)"
        }
        for ($wait = 0; $wait -lt 8; $wait++) {
            Start-Sleep -Seconds 3
            if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
                Write-Log "started task $taskName; port $Port is listening again"
                exit 0
            }
        }
        if ($started) {
            # ${attempt} needs braces: "$attempt:" would parse as a drive path.
            Write-Log "attempt ${attempt}: task $taskName started but port $Port is still closed"
        }
    }
    Write-Log "ERROR: could not restore port $Port via task $taskName after 4 attempts"
    exit 1
} catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    exit 1
}

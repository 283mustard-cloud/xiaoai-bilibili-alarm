# Builds the alarm tray app as a single self-contained .exe with PyInstaller.
#
# Run from the project directory that holds config.json:
#     powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
#
# The exe contains Python, tkinter, the dashboard HTML, pystray and Pillow.
# Downloading Bilibili audio still shells out to a real Python interpreter for
# yt-dlp (see python_exe() in prepare_episode.py): yt-dlp must run in its own
# process so it stays independently updatable, and bundling it would add
# roughly 100 MB.
#
# This file is deliberately pure ASCII: Windows PowerShell 5.1 reads .ps1 files
# as ANSI unless they carry a UTF-8 BOM, so non-ASCII literals here would break
# on a Chinese-locale machine. The Chinese exe name is built from code points.
param(
    [string]$BuildRoot = 'C:\DSH\Codex\build',
    [switch]$Console,
    [switch]$Ascii
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$entry = Join-Path $projectRoot 'alarm_gui.py'
if (-not (Test-Path $entry)) { throw "alarm_gui.py not found in $projectRoot" }

if ($Ascii) {
    $Name = 'XiaoAiBiliAlarm'
} else {
    # U+5C0F U+7231 U+0042 U+7AD9 U+95F9 U+949F  =>  the Chinese product name
    $Name = -join ([char]0x5C0F, [char]0x7231, 'B', [char]0x7AD9, [char]0x95F9, [char]0x949F)
}

# A dedicated build venv is preferred so building never disturbs the runtime.
$venv = Join-Path $projectRoot '.venv-build\Scripts\python.exe'
$python = if (Test-Path $venv) { $venv } else { (Get-Command python -ErrorAction Stop).Source }
Write-Output "Interpreter : $python"
Write-Output "Output name : $Name"

& $python -c "import PyInstaller, pystray, PIL"
if ($LASTEXITCODE -ne 0) {
    throw "Missing build deps. Install with: $python -m pip install pyinstaller pystray pillow"
}

# Heavy optional services are excluded from the bundle: XiaoMusic runs as its
# own process and yt-dlp is invoked through an external interpreter.
$excludeModules = @(
    'xiaomusic', 'miservice', 'aiohttp', 'aiosignal', 'frozenlist', 'multidict', 'yarl',
    'fastapi', 'starlette', 'uvicorn', 'pydantic', 'pydantic_core', 'anyio', 'h11',
    'sentry_sdk', 'ga4mp', 'qrcode', 'rich', 'pygments', 'websockets', 'watchdog',
    'Crypto', 'Cryptodome', 'mutagen', 'edge_tts', 'apscheduler', 'sqlalchemy',
    'matplotlib', 'numpy', 'pandas', 'scipy', 'pytest', 'setuptools', 'pip'
)

# Build one flat argument array and splat it. Splatting a variable with @ is
# the only reliable form here: "@excludes" is just an array literal containing
# the string "-excludes" and would be passed to PyInstaller verbatim.
$arguments = @(
    '-m', 'PyInstaller',
    '--noconfirm', '--clean', '--onefile',
    '--name', $Name,
    '--distpath', (Join-Path $BuildRoot 'dist'),
    '--workpath', (Join-Path $BuildRoot 'work'),
    '--specpath', (Join-Path $BuildRoot 'spec')
)
if ($Console) { $arguments += @('--console') } else { $arguments += @('--windowed') }
$arguments += @(
    '--hidden-import', 'pystray._win32',
    '--collect-submodules', 'pystray',
    '--collect-submodules', 'yt_dlp',
    '--collect-submodules', 'chinese_calendar',
    '--collect-data', 'chinese_calendar',
    '--collect-all', 'imageio_ffmpeg'
)
foreach ($module in $excludeModules) { $arguments += @('--exclude-module', $module) }
$arguments += @($entry)

Write-Output "Building with $($arguments.Count) PyInstaller arguments..."
& $python @arguments

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$exe = Join-Path $BuildRoot "dist\$Name.exe"
Write-Output ""
Write-Output "Built: $exe"
Write-Output ("Size : {0:N1} MB" -f ((Get-Item $exe).Length / 1MB))
Write-Output ""
Write-Output "Deploy: copy it next to config.json (the exe treats its own folder as the project root)."
Write-Output "  Copy-Item '$exe' '$projectRoot\'"
Write-Output "Then point the startup task at the exe instead of alarm_app.py."

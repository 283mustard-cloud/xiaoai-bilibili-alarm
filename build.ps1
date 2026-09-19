$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$output = Join-Path $root 'publish'
dotnet publish (Join-Path $root 'XiaoAiAlarm.csproj') -c Release --self-contained false -o $output
Write-Output "Published to $output"

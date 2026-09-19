$ErrorActionPreference = 'Stop'
$name = 'CS Alarm XiaoMusic LAN'
$existing = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
if ($existing) {
    Remove-NetFirewallRule -DisplayName $name
}
New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort 58090 -Profile Private,Public -RemoteAddress LocalSubnet | Out-Null

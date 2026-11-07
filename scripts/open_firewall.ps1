#Requires -RunAsAdministrator
# Laptop 1 only, once. Allows Laptop 2 on the SAME private LAN to reach MQTT (1883) and the dashboard (1880).
# Rules are limited to the Private profile and the local subnet: nothing is exposed to public networks.
#   powershell -ExecutionPolicy Bypass -File scripts\open_firewall.ps1
New-NetFirewallRule -DisplayName "SmartClass MQTT 1883 (private LAN)" -Direction Inbound -Protocol TCP -LocalPort 1883 `
    -Profile Private -RemoteAddress LocalSubnet -Action Allow | Out-Null
New-NetFirewallRule -DisplayName "SmartClass Node-RED 1880 (private LAN)" -Direction Inbound -Protocol TCP -LocalPort 1880 `
    -Profile Private -RemoteAddress LocalSubnet -Action Allow | Out-Null
# The Mosquitto installer may register a Windows service with its default config, which occupies port 1883.
$svc = Get-Service mosquitto -ErrorAction SilentlyContinue
if ($svc) { Stop-Service mosquitto -ErrorAction SilentlyContinue; Set-Service mosquitto -StartupType Manual; Write-Host "Stopped the default Mosquitto service (startup set to Manual)." }
Write-Host "Firewall rules added. Your Wi-Fi must be a PRIVATE network:"
Get-NetConnectionProfile | Format-Table Name, InterfaceAlias, NetworkCategory
Write-Host "If it says Public: Set-NetConnectionProfile -InterfaceAlias '<name above>' -NetworkCategory Private"

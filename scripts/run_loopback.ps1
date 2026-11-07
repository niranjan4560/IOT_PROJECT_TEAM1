# Loopback mode: server AND node on ONE laptop (development / rehearsal). SC_MQTT_HOST must be 127.0.0.1 in .env.
#   powershell -ExecutionPolicy Bypass -File scripts\run_loopback.ps1 -Date 2021-09-20
param([string]$Room = "room1", [string]$Date = "", [double]$Speed = 1)
& "$PSScriptRoot\start_server.ps1"
& "$PSScriptRoot\start_node.ps1" -Room $Room -Date $Date -Speed $Speed

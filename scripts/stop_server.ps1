# Laptop 1: stops the ML service, Node-RED and Mosquitto started by start_server.ps1 (reverse order).
#   powershell -ExecutionPolicy Bypass -File scripts\stop_server.ps1
. "$PSScriptRoot\common.ps1"
Stop-FromPidFile (Join-Path $Root "logs\server.pids")

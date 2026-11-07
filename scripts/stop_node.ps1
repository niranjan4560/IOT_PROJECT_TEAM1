# Laptop 2: stops the actuator windows started by start_node.ps1.
#   powershell -ExecutionPolicy Bypass -File scripts\stop_node.ps1
. "$PSScriptRoot\common.ps1"
Stop-FromPidFile (Join-Path $Root "logs\node.pids")

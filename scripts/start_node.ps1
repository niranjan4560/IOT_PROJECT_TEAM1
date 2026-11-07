# Laptop 2 (IoT NODE): starts the light+AC actuator nodes (one window per room), then replays ROBOD here.
#   powershell -ExecutionPolicy Bypass -File scripts\start_node.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start_node.ps1 -Room room1 -Date 2021-09-20 -Speed 0.5
# Stop the actuators: scripts\stop_node.ps1   (the replay stops by itself or with Ctrl+C)
param([string]$Room = "room1", [string]$Date = "", [double]$Speed = 1)
. "$PSScriptRoot\common.ps1"
if (-not (Test-Path $VenvPy)) { Fail "Run scripts\setup_node.ps1 first." }
$server = Get-EnvValue "SC_MQTT_HOST"
if (-not $server) { Fail "SC_MQTT_HOST missing in .env - run scripts\setup_node.ps1 -ServerIp <Laptop 1 IP>" }
if ($server -ne "127.0.0.1") {
    $t = Test-NetConnection -ComputerName $server -Port 1883 -WarningAction SilentlyContinue
    if (-not $t.TcpTestSucceeded) { Fail "Cannot reach ${server}:1883 (ping: $($t.PingSucceeded)). Start Laptop 1 first; check firewall / Private network / same Wi-Fi." }
    Ok "Laptop 1 broker reachable at ${server}:1883"
}
& $VenvPy tools\check_setup.py --role node
if ($LASTEXITCODE -ne 0) { Fail "Fix the FAIL lines above first (wrong password? run setup_node.ps1 again)." }
$pidFile = Join-Path $Root "logs\node.pids"
if (Test-Path $pidFile) { Fail "Actuators seem to be running already (logs\node.pids exists). Run scripts\stop_node.ps1 first." }
foreach ($r in @("room1", "room2")) {
    $p = Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$Root'; .\.venv\Scripts\python actuator.py --room $r" -PassThru
    Save-Pid $pidFile $p "actuator_$r"
}
Start-Sleep -Seconds 4
$simArgs = @("run_simulator.py", "--room", $Room, "--speed", $Speed)
if ($Date) { $simArgs += @("--date", $Date) }
& $VenvPy @simArgs

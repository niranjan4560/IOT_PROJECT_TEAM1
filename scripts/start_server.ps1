# Laptop 1 (SERVER): starts Mosquitto, Node-RED and the ML service, each in its own window.
#   powershell -ExecutionPolicy Bypass -File scripts\start_server.ps1
# Stop all three: powershell -ExecutionPolicy Bypass -File scripts\stop_server.ps1
. "$PSScriptRoot\common.ps1"
if (-not (Test-Path $VenvPy)) { Fail "Run scripts\setup_server.ps1 first." }
$mosq = Find-Mosquitto
& $VenvPy tools\check_setup.py --role server --no-broker
if ($LASTEXITCODE -ne 0) { Fail "Fix the FAIL lines above first (usually: run scripts\setup_server.ps1 again)." }
$uiPort = Get-EnvValue "SC_NODERED_PORT"; if (-not $uiPort) { $uiPort = 1880 }
Assert-PortFree 1883 "MQTT" "Run scripts\stop_server.ps1, or stop the default Mosquitto service: scripts\open_firewall.ps1 as Administrator."
Assert-PortFree $uiPort "Node-RED" "Run scripts\stop_server.ps1, or set SC_NODERED_PORT in .env."
$pidFile = Join-Path $Root "logs\server.pids"
if (Test-Path $pidFile) { Remove-Item $pidFile }
& $VenvPy init_db.py > logs\init_db.log 2>&1
if ($LASTEXITCODE) { Fail "init_db.py failed - see logs\init_db.log" }
Ok "SQLite ready (model metrics imported for the dashboard)"
$p = Start-Process $mosq -ArgumentList "-c", "config/mosquitto/mosquitto.conf", "-v" -WorkingDirectory $Root -PassThru
Save-Pid $pidFile $p "mosquitto"
Wait-Port 1883 15 "Mosquitto"
$p = Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$Root\nodered'; npm.cmd start" -PassThru
Save-Pid $pidFile $p "node-red"
Wait-Port $uiPort 90 "Node-RED"
$p = Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$Root'; .\.venv\Scripts\python ml_service.py" -PassThru
Save-Pid $pidFile $p "ml_service"
Start-Sleep -Seconds 10
& $VenvPy tools\check_setup.py --role server
& $VenvPy tools\show_ip.py
Write-Host "Dashboard: http://localhost:$uiPort/dashboard    Editor: http://localhost:$uiPort (login: admin / SC_EDITOR_PASSWORD in .env)"

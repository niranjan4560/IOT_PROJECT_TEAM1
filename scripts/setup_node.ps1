# Laptop 2 (IoT NODE) one-time setup. In PowerShell, from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_node.ps1 -ServerIp 192.168.1.50
# (-ServerIp = the "Laptop 1 LAN IP" printed by start_server.ps1; you will be asked for the node password it showed.)
param([string]$ServerIp = "")
. "$PSScriptRoot\common.ps1"
$py = Find-Python
if (-not (Test-Path $VenvPy)) { & $py[0] @($py | Select-Object -Skip 1) -m venv .venv; if ($LASTEXITCODE) { Fail "could not create .venv" } }
& $VenvPy -m pip install -r requirements-node.txt;    if ($LASTEXITCODE) { Fail "pip install failed (see above)" }
$initArgs = @("tools\init_env.py", "--role", "node"); if ($ServerIp) { $initArgs += @("--host", $ServerIp) }
& $VenvPy @initArgs;                                   if ($LASTEXITCODE) { Fail "init_env.py failed" }
& $VenvPy download_data.py;                            if ($LASTEXITCODE) { Fail "dataset download/verification failed (see above)" }
$server = Get-EnvValue "SC_MQTT_HOST"
if ($server -and $server -ne "127.0.0.1") {
    $t = Test-NetConnection -ComputerName $server -Port 1883 -WarningAction SilentlyContinue
    if ($t.TcpTestSucceeded) { Ok "Laptop 1 broker reachable at ${server}:1883" }
    else { Write-Warning "Cannot reach ${server}:1883. Is start_server.ps1 running on Laptop 1? Did you run open_firewall.ps1 there? Same Wi-Fi, Private network?" }
}
& $VenvPy tools\check_setup.py --role node
Write-Host "`nNext: scripts\start_node.ps1   (Laptop 1 must already be running scripts\start_server.ps1)"

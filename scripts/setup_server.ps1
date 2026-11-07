# Laptop 1 (SERVER) one-time setup. In PowerShell, from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_server.ps1
. "$PSScriptRoot\common.ps1"
$py = Find-Python
Find-Node
$null = Find-Mosquitto
if (-not (Test-Path $VenvPy)) { & $py[0] @($py | Select-Object -Skip 1) -m venv .venv; if ($LASTEXITCODE) { Fail "could not create .venv" } }
& $VenvPy -m pip install -r requirements.txt;          if ($LASTEXITCODE) { Fail "pip install failed (see above)" }
& $VenvPy tools\init_env.py --role server;             if ($LASTEXITCODE) { Fail "init_env.py failed" }
& $VenvPy download_data.py;                            if ($LASTEXITCODE) { Fail "dataset download/verification failed (see above)" }
if (-not (Test-Path models\final\manifest.json)) { & $VenvPy train_models.py; if ($LASTEXITCODE) { Fail "training failed" } }
Push-Location nodered; npm.cmd install --no-audit --no-fund; $rc = $LASTEXITCODE; Pop-Location
if ($rc) { Fail "npm install failed (see above)" }
& $VenvPy tools\make_broker_users.py;                 if ($LASTEXITCODE) { Fail "make_broker_users.py failed" }
& $VenvPy init_db.py;                                  if ($LASTEXITCODE) { Fail "init_db.py failed" }
& $VenvPy tools\check_setup.py --role server --no-broker
& $VenvPy tools\show_ip.py
Write-Host "`nNext: once, in an ADMINISTRATOR PowerShell: scripts\open_firewall.ps1 ; then: scripts\start_server.ps1"

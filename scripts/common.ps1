# Shared helpers for the Windows scripts (dot-sourced:  . "$PSScriptRoot\common.ps1").
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs"), (Join-Path $Root "storage") | Out-Null
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"

function Fail([string]$Message) { Write-Host "ERROR: $Message" -ForegroundColor Red; exit 1 }
function Ok([string]$Message) { Write-Host "OK    $Message" -ForegroundColor Green }

function Find-Python {
    # Returns the command (array) that runs Python >= 3.10, or fails with an install hint.
    foreach ($cand in @(@("py", "-3"), @("python"), @("python3"))) {
        if (-not (Get-Command $cand[0] -ErrorAction SilentlyContinue)) { continue }
        $exe = $cand[0]; $pre = @($cand | Select-Object -Skip 1)
        $v = & $exe @pre -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -and [version]$v -ge [version]"3.10") { Ok "Python $v ($($cand -join ' '))"; return ,$cand }
    }
    Fail "Python 3.10+ not found. Install from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'."
}

function Find-Node {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "Node.js not found. Install Node.js 22 LTS from https://nodejs.org/" }
    $v = (node --version).TrimStart("v")
    if ([version]$v -lt [version]"20.17") { Fail "Node.js $v is too old (need 20.17+, recommended 22 LTS)." }
    Ok "Node.js $v"
}

function Find-Mosquitto {
    $cmd = Get-Command mosquitto -ErrorAction SilentlyContinue
    $path = if ($cmd) { $cmd.Source } else { "C:\Program Files\mosquitto\mosquitto.exe" }
    if (-not (Test-Path $path)) { Fail "Mosquitto not found. Install: winget install EclipseFoundation.Mosquitto" }
    Ok "Mosquitto $path"
    return $path
}

function Assert-PortFree([int]$Port, [string]$What, [string]$Hint) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) {
        $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        Fail "Port $Port ($What) is already used by $($p.ProcessName) (PID $($c.OwningProcess)). $Hint"
    }
}

function Wait-Port([int]$Port, [int]$Seconds, [string]$What) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { Ok "$What listening on $Port"; return }
        Start-Sleep -Seconds 1
    }
    Fail "$What did not start listening on port $Port within $Seconds s - read its window for the error."
}

function Save-Pid([string]$File, $Process, [string]$Name) {
    Add-Content -Path $File -Value "$($Process.Id) $Name"
}

function Stop-FromPidFile([string]$File) {
    if (-not (Test-Path $File)) { Write-Host "Nothing to stop ($File not found)."; return }
    $lines = @(Get-Content $File); [array]::Reverse($lines)
    foreach ($line in $lines) {
        $procId, $name = $line -split " ", 2
        if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
            taskkill /PID $procId /T /F | Out-Null       # /T also stops the child process (python, node, mosquitto)
            Write-Host "stopped $name (PID $procId)"
        } else { Write-Host "$name (PID $procId) was not running" }
    }
    Remove-Item $File
}

function Get-EnvValue([string]$Key) {
    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) { return "" }
    $line = Get-Content $envFile | Where-Object { $_ -match "^\s*$Key\s*=" } | Select-Object -First 1
    if ($line) { return ($line -split "=", 2)[1].Trim() } else { return "" }
}

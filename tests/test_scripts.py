"""Deployment scripts: every Windows .ps1 parses with the real PowerShell parser, every .sh passes `bash -n`,
and each role has setup / start / stop scripts. PowerShell is optional (set SC_PWSH or put pwsh on PATH).
Windows-only cmdlets (Get-NetTCPConnection, Test-NetConnection, taskkill) are NOT executed here."""
import os
import shutil
import subprocess

import pytest

from conftest import ROOT

SCRIPTS = ROOT / "scripts"
PWSH = os.environ.get("SC_PWSH") or shutil.which("pwsh")
PARSE = r"""$bad = 0
foreach ($f in Get-ChildItem $args[0] -Filter *.ps1) {
  $t = $null; $e = $null
  [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$t, [ref]$e) | Out-Null
  foreach ($x in $e) { $bad++; "FAIL $($f.Name):$($x.Extent.StartLineNumber) $($x.Message)" }
}
exit $bad"""


def test_every_role_has_setup_start_stop_scripts():
    for role in ("server", "node"):
        for action in ("setup", "start", "stop"):
            for ext in ("ps1", "sh"):
                assert (SCRIPTS / f"{action}_{role}.{ext}").exists(), f"{action}_{role}.{ext} missing"
    assert (SCRIPTS / "open_firewall.ps1").exists()


@pytest.mark.parametrize("script", sorted(p.name for p in SCRIPTS.glob("*.sh")))
def test_shell_scripts_parse(script):
    done = subprocess.run(["bash", "-n", str(SCRIPTS / script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.skipif(PWSH is None, reason="PowerShell (pwsh) not available")
def test_powershell_scripts_parse(tmp_path):
    parser = tmp_path / "parse.ps1"
    parser.write_text(PARSE)
    done = subprocess.run([PWSH, "-NoProfile", "-File", str(parser), str(SCRIPTS)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.skipif(PWSH is None, reason="PowerShell (pwsh) not available")
def test_powershell_helpers_detect_tools_and_read_env():
    cmd = (f". '{SCRIPTS / 'common.ps1'}'; $py = Find-Python; Find-Node; "
           "'HOST=' + (Get-EnvValue 'SC_MQTT_HOST'); 'MISSING=' + (Get-EnvValue 'NO_SUCH_KEY')")
    done = subprocess.run([PWSH, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "OK    Python" in done.stdout and "OK    Node.js" in done.stdout and "MISSING=\n" in done.stdout + "\n"
    fail = subprocess.run([PWSH, "-NoProfile", "-Command", f". '{SCRIPTS / 'common.ps1'}'; Fail 'demo'"], capture_output=True, text=True)
    assert fail.returncode == 1 and "ERROR: demo" in fail.stdout


def test_firewall_rules_are_private_lan_only():
    text = (SCRIPTS / "open_firewall.ps1").read_text()
    assert text.count("-Profile Private -RemoteAddress LocalSubnet") == 2 and "Public" not in text.split("NetworkCategory")[0]

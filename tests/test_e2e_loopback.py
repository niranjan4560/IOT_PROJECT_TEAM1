"""Area 12: end-to-end loopback run of the real system (Mosquitto + Node-RED + ML service + actuators + replay).

Needs Mosquitto, Node.js, `cd nodered && npm install`, data and trained models. Opt-in because it starts servers:
    SC_E2E=1 python -m pytest -q tests/test_e2e_loopback.py
It uses temporary credentials, a temporary database and ports 18830/18800, so it never touches your demo setup.
"""
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time

import pytest

from conftest import ROOT

pytestmark = pytest.mark.skipif(os.environ.get("SC_E2E") != "1", reason="set SC_E2E=1 to run the end-to-end test")


def wait_for(path, text, seconds):
    for _ in range(seconds * 2):
        if path.exists() and text in path.read_text(errors="ignore"):
            return
        time.sleep(0.5)
    raise AssertionError(f"{path.name} never showed {text!r}:\n{path.read_text(errors='ignore')[-2000:] if path.exists() else ''}")


def test_full_loop(tmp_path):
    mosquitto, passwd_tool = shutil.which("mosquitto"), shutil.which("mosquitto_passwd")
    assert mosquitto and passwd_tool, "Mosquitto is not installed"
    passwd, acl = tmp_path / "passwd", tmp_path / "acl"
    passwd.write_text("")
    for user, pw in (("e2e_server", "s3rver"), ("e2e_node", "n0de")):
        subprocess.run([passwd_tool, "-b", str(passwd), user, pw], check=True)
    sys.path.insert(0, str(ROOT))
    from tools.make_broker_users import ACL
    acl.write_text(ACL.format(server="e2e_server", node="e2e_node"))
    os.chmod(passwd, 0o600)
    os.chmod(acl, 0o600)
    # Test-only config. When the test runs as root, keep Mosquitto as root so it can read the private temp folder
    # (a root-started Mosquitto otherwise drops to the 'mosquitto' user).
    as_root = "user root\n" if hasattr(os, "geteuid") and os.geteuid() == 0 else ""
    conf = tmp_path / "mosquitto.conf"
    conf.write_text(f"{as_root}listener 18830 127.0.0.1\nallow_anonymous false\npassword_file {passwd}\nacl_file {acl}\npersistence false\n")
    db = tmp_path / "e2e.db"
    env = {**os.environ, "SC_MQTT_HOST": "127.0.0.1", "SC_MQTT_PORT": "18830", "SC_SERVER_USERNAME": "e2e_server",
           "SC_SERVER_PASSWORD": "s3rver", "SC_NODE_USERNAME": "e2e_node", "SC_NODE_PASSWORD": "n0de",
           "SC_DB_PATH": str(db), "SC_NODERED_PORT": "18800", "SC_NODERED_BIND": "127.0.0.1"}
    logs = {name: tmp_path / f"{name}.log" for name in ("broker", "nodered", "ml", "act1", "sim")}
    procs = []
    try:
        procs.append(subprocess.Popen([mosquitto, "-c", str(conf), "-v"], stdout=open(logs["broker"], "w"), stderr=subprocess.STDOUT))
        time.sleep(1)
        procs.append(subprocess.Popen([str(ROOT / "nodered/node_modules/.bin/node-red"), "--userDir", ".", "--settings", "settings.js"],
                                      cwd=ROOT / "nodered", env=env, stdout=open(logs["nodered"], "w"), stderr=subprocess.STDOUT))
        wait_for(logs["nodered"], "Connected to broker", 90)
        wait_for(logs["nodered"], "opened", 30)
        procs.append(subprocess.Popen([sys.executable, "ml_service.py"], cwd=ROOT, env=env, stdout=open(logs["ml"], "w"), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([sys.executable, "actuator.py", "--room", "room1"], cwd=ROOT, env=env, stdout=open(logs["act1"], "w"), stderr=subprocess.STDOUT))
        wait_for(logs["ml"], "listening on", 120)
        wait_for(logs["act1"], "waiting for commands", 30)
        time.sleep(3)  # let Node-RED finish creating the tables
        sim = subprocess.run([sys.executable, "run_simulator.py", "--room", "room1", "--date", "2021-09-20", "--start-row", "80",
                              "--max-rows", "60", "--speed", "0.1"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        assert "Finished after publishing 60 readings" in sim.stdout, sim.stdout + sim.stderr
        con = sqlite3.connect(db)
        count = lambda sql: con.execute(sql).fetchone()[0]
        for _ in range(120):  # wait (max 60 s) until every reading has been decided and every command acknowledged
            if count("SELECT COUNT(*) FROM decisions") == 60 and count("SELECT COUNT(*) FROM commands WHERE status = 'SENT'") == 0:
                break
            time.sleep(0.5)
        assert count("SELECT COUNT(*) FROM telemetry") == 60
        assert count("SELECT COUNT(*) FROM decisions") == 60
        assert count("SELECT COUNT(DISTINCT model) FROM predictions") == 6
        sent = count("SELECT COUNT(*) FROM commands")
        assert sent > 0 and count("SELECT COUNT(*) FROM commands WHERE status = 'ACKED'") == sent
        assert count("SELECT COUNT(*) FROM commands WHERE loop_latency_ms IS NULL OR roundtrip_ms IS NULL") == 0
        assert count("SELECT MAX(loop_latency_ms) FROM commands") < 5000
        assert "not authorised" not in logs["broker"].read_text()
    finally:
        for p in reversed(procs):
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()

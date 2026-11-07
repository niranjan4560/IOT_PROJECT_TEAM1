"""Areas 10-11: Node-RED flow/dashboard configuration and server/node configuration + start-up checks."""
import json
import os
import re
import subprocess
import sys

from conftest import FLOWS, ROOT
from smartclass import config
from smartclass.db import schema_statements

flows = json.loads(FLOWS.read_text(encoding="utf-8"))
by_id = {n["id"]: n for n in flows}


def test_flows_json_is_valid_and_fully_wired():
    assert len(by_id) == len(flows)
    for node in flows:
        for out in node.get("wires", []):
            for target in out:
                assert target in by_id, f"{node['id']} -> missing {target}"
        if node["type"] == "function":
            assert len(node["wires"]) == node["outputs"], node["name"]
            compile_check = subprocess.run(["node", "-e", "new Function('msg','node','context','flow','global','env', process.argv[1])",
                                            node["func"]], capture_output=True, text=True)
            assert compile_check.returncode == 0, f"{node['name']}: {compile_check.stderr[:300]}"


def test_mqtt_topics_match_the_documented_design():
    subs = sorted(n["topic"] for n in flows if n["type"] == "mqtt in")
    assert subs == sorted(["smartclass/+/telemetry", "smartclass/+/analytics", "smartclass/+/actuator/+",
                           "smartclass/+/status", "smartclass/+/actuator_status"])
    code = " ".join(n.get("func", "") for n in flows if n["type"] == "function")
    for topic in ("/validated", "/control/", "/alert"):
        assert topic in code


def test_dashboard_widgets_present():
    types = {n["type"] for n in flows}
    assert {"ui-base", "ui-page", "ui-group", "ui-text", "ui-gauge", "ui-chart", "ui-table", "ui-switch", "ui-dropdown",
            "ui-button", "ui-notification"} <= types
    labels = " ".join(str(n.get("label", "")) + str(n.get("title", "")) + str(n.get("name", "")) for n in flows)
    for needed in ("Occupancy", "Temperature", "Illuminance", "Light command", "AC command", "Reason", "Manual override",
                   "Camera presence", "model comparison", "Command delivery", "Devices"):
        assert needed.lower() in labels.lower(), needed


def test_flow_schema_matches_schema_sql():
    init = next(n for n in flows if n.get("name") == "SQL: create tables")
    embedded = json.loads(re.search(r"const sql = (\[.*?\]);", init["func"], re.S).group(1))
    assert embedded == schema_statements()


def test_no_credentials_ip_or_machine_paths_in_flows():
    text = FLOWS.read_text(encoding="utf-8")
    broker = by_id["sc_broker"]
    assert "credentials" not in broker and broker["broker"] == "${SC_NODERED_MQTT_HOST}"
    assert by_id["sc_db"]["db"] == "${SC_DB_PATH}"
    assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text.replace("127.0.0.1", "")), "hard-coded IP address"
    assert "C:\\\\" not in text and "/home/" not in text and "/Users/" not in text


def test_nodered_package_is_pinned_and_settings_load_env():
    pkg = json.loads((ROOT / "nodered/package.json").read_text())
    assert all(re.match(r"^\d+\.\d+\.\d+$", v) for v in pkg["dependencies"].values())
    settings = (ROOT / "nodered/settings.js").read_text()
    assert ".env" in settings and "flows_cred.json" in settings and "SC_DB_PATH" in settings


def test_python_requirements_are_pinned():
    for name in ("requirements.txt", "requirements-node.txt"):
        for line in (ROOT / name).read_text().splitlines():
            line = line.split("#")[0].strip()
            if line and not line.startswith("-r"):
                assert re.match(r"^[A-Za-z0-9_.\-]+==[0-9.]+$", line), line


def test_broker_is_not_anonymous_and_acl_limits_the_node():
    conf = (ROOT / "config/mosquitto/mosquitto.conf").read_text()
    assert "allow_anonymous false" in conf and "password_file" in conf and "acl_file" in conf
    from tools.make_broker_users import ACL
    acl = ACL.format(server="srv", node="nd")
    node_part = acl.split("user nd", 1)[1]
    assert "topic read smartclass/+/control/+" in node_part and "readwrite" not in node_part


def test_env_example_has_every_setting():
    text = (ROOT / ".env.example").read_text()
    for key in ("SC_MQTT_HOST", "SC_MQTT_PORT", "SC_NODE_USERNAME", "SC_NODE_PASSWORD", "SC_SERVER_USERNAME", "SC_SERVER_PASSWORD"):
        assert key in text


def test_env_precedence(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SC_TEST_A=from_file\nSC_TEST_B='quoted'\n# SC_TEST_C=comment\n")
    monkeypatch.setenv("SC_TEST_A", "from_environment")
    monkeypatch.delenv("SC_TEST_B", raising=False)
    config.load_env_file(env)
    assert os.environ["SC_TEST_A"] == "from_environment" and os.environ["SC_TEST_B"] == "quoted"
    assert "SC_TEST_C" not in os.environ


def test_clients_use_role_credentials(monkeypatch):
    monkeypatch.setenv("SC_NODE_USERNAME", "nodeuser")
    monkeypatch.setenv("SC_NODE_PASSWORD", "pw")
    client = config.make_client("x", "node", "smartclass/room1/status")
    assert client._username == b"nodeuser"


def test_check_setup_offline_runs():
    done = subprocess.run([sys.executable, str(ROOT / "tools/check_setup.py"), "--role", "node", "--no-broker"],
                          capture_output=True, text=True)
    assert "PASS  Python >= 3.10" in done.stdout and "import paho.mqtt.client" in done.stdout


def test_launch_scripts_exist_for_both_os():
    for role in ("setup_server", "start_server", "setup_node", "start_node", "run_loopback"):
        assert (ROOT / f"scripts/{role}.ps1").exists() and (ROOT / f"scripts/{role}.sh").exists(), role
    for sh in (ROOT / "scripts").glob("*.sh"):
        assert subprocess.run(["bash", "-n", str(sh)]).returncode == 0, sh.name

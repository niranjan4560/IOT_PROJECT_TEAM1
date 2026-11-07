"""Failure scenarios: broker down, wrong credentials, ACL, reconnection, ML service crash, missing model files,
missing sensor values, database locked, late / unknown acknowledgements, credential and dataset checks.

Broker tests start a private Mosquitto on 127.0.0.1:18831 with temporary users (never the demo broker) and are
skipped only when Mosquitto is not installed.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import pytest

from conftest import ROOT, needs_node, run_function_node

sys.path.insert(0, str(ROOT))
PORT = 18831
SERVER, NODE = ("t_server", "srv-Pass-123456"), ("t_node", "node-Pass-123456")
needs_mosquitto = pytest.mark.skipif(not (shutil.which("mosquitto") and shutil.which("mosquitto_passwd")),
                                     reason="Mosquitto not installed")


# ---------------------------------------------------------------------------------------------- helpers
def free_port(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


class Broker:
    def __init__(self, folder: Path):
        from tools.make_broker_users import ACL
        self.folder = folder
        passwd, acl = folder / "passwd", folder / "acl"
        passwd.write_text("")
        for user, pw in (SERVER, NODE):
            subprocess.run([shutil.which("mosquitto_passwd"), "-b", str(passwd), user, pw], check=True, capture_output=True)
        acl.write_text(ACL.format(server=SERVER[0], node=NODE[0]))
        os.chmod(passwd, 0o600)
        os.chmod(acl, 0o600)
        as_root = "user root\n" if hasattr(os, "geteuid") and os.geteuid() == 0 else ""
        self.conf = folder / "mosquitto.conf"
        self.conf.write_text(f"{as_root}listener {PORT} 127.0.0.1\nallow_anonymous false\npassword_file {passwd}\n"
                             f"acl_file {acl}\npersistence false\n")
        self.proc = None

    def start(self):
        assert free_port(PORT), f"port {PORT} busy"
        self.proc = subprocess.Popen([shutil.which("mosquitto"), "-c", str(self.conf)], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        for _ in range(50):
            if not free_port(PORT):
                return self
            time.sleep(0.1)
        raise AssertionError("test broker did not start")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(5)
        for _ in range(50):
            if free_port(PORT):
                return
            time.sleep(0.1)


@pytest.fixture
def broker(tmp_path):
    b = Broker(tmp_path).start()
    yield b
    b.stop()


def client(user_pw, client_id):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)
    c.username_pw_set(*user_pw)
    return c


def connack(user_pw) -> mqtt.ReasonCode:
    done, out = threading.Event(), {}
    c = client(user_pw, f"t-{time.time_ns()}")
    c.on_connect = lambda cl, u, f, rc, p: (out.setdefault("rc", rc), done.set())
    c.connect("127.0.0.1", PORT, 10)
    c.loop_start()
    done.wait(5)
    c.loop_stop()
    c.disconnect()
    return out.get("rc")


def service_env(**extra):
    return {**os.environ, "SC_MQTT_HOST": "127.0.0.1", "SC_MQTT_PORT": str(PORT), "SC_SERVER_USERNAME": SERVER[0],
            "SC_SERVER_PASSWORD": SERVER[1], "SC_NODE_USERNAME": NODE[0], "SC_NODE_PASSWORD": NODE[1], **extra}


class Listener:
    """Server-role subscriber that records every message."""

    def __init__(self, topics):
        self.messages, self.ready = [], threading.Event()
        self.c = client(SERVER, f"listener-{time.time_ns()}")
        self.c.on_connect = lambda cl, u, f, rc, p: ([cl.subscribe(t, qos=1) for t in topics], self.ready.set())
        self.c.on_message = lambda cl, u, m: self.messages.append((m.topic, m.payload.decode(errors="replace")))
        self.c.connect("127.0.0.1", PORT, 10)
        self.c.loop_start()
        assert self.ready.wait(5)
        time.sleep(0.3)

    def wait_for(self, predicate, seconds):
        for _ in range(int(seconds * 10)):
            if any(predicate(t, p) for t, p in self.messages):
                return True
            time.sleep(0.1)
        return False

    def close(self):
        self.c.loop_stop()
        self.c.disconnect()


def wait_log(proc_log: Path, text: str, seconds: float) -> None:
    for _ in range(int(seconds * 10)):
        if proc_log.exists() and text in proc_log.read_text(errors="ignore"):
            return
        time.sleep(0.1)
    raise AssertionError(f"{proc_log.name} never showed {text!r}: {proc_log.read_text(errors='ignore')[-1500:] if proc_log.exists() else ''}")


# ---------------------------------------------------------------------------------------------- broker / network
def test_broker_unavailable_gives_clear_message():
    from tools.check_setup import broker_login
    ok, detail = broker_login("node", "127.0.0.1", 18839)          # nothing listens there
    assert not ok and "unreachable" in detail and "SC_MQTT_HOST" in detail


def test_simulator_exits_cleanly_when_broker_down():
    done = subprocess.run([sys.executable, "run_simulator.py", "--room", "room1", "--date", "2021-09-20", "--max-rows", "1"],
                          cwd=ROOT, env=service_env(SC_MQTT_PORT="18839"), capture_output=True, text=True, timeout=60)
    assert done.returncode != 0
    assert "Cannot reach the MQTT broker at 127.0.0.1:18839" in done.stderr
    assert "Traceback" not in done.stderr


@needs_mosquitto
def test_wrong_password_and_unknown_user_are_refused(broker):
    assert not connack(SERVER).is_failure
    assert not connack(NODE).is_failure
    assert connack((NODE[0], "wrong-password")).is_failure
    assert connack(("intruder", "whatever")).is_failure


@needs_mosquitto
def test_wrong_password_service_logs_explanation(broker, tmp_path):
    log = tmp_path / "act.log"
    proc = subprocess.Popen([sys.executable, "actuator.py", "--room", "room1"], cwd=ROOT,
                            env=service_env(SC_NODE_PASSWORD="wrong-password"), stdout=open(log, "w"), stderr=subprocess.STDOUT)
    try:
        wait_log(log, "wrong SC_*_USERNAME / SC_*_PASSWORD", 15)
    finally:
        proc.terminate()
        proc.wait(10)


@needs_mosquitto
def test_acl_node_cannot_send_control_commands(broker):
    listen = Listener(["smartclass/room1/control/#", "smartclass/room1/telemetry"])
    try:
        node = client(NODE, "t-node-acl")
        node.connect("127.0.0.1", PORT, 10)
        node.loop_start()
        node.publish("smartclass/room1/control/ac", json.dumps({"cmd": "OFF"}), qos=1).wait_for_publish(5)
        node.publish("smartclass/room1/telemetry", json.dumps({"x": 1}), qos=1).wait_for_publish(5)
        assert listen.wait_for(lambda t, p: t == "smartclass/room1/telemetry", 3)          # allowed topic arrives
        assert not listen.wait_for(lambda t, p: t.startswith("smartclass/room1/control"), 1.5)  # forbidden: dropped
        node.loop_stop()
        node.disconnect()
    finally:
        listen.close()


@needs_mosquitto
def test_actuator_reconnects_after_broker_restart_and_executes_command(broker, tmp_path):
    log = tmp_path / "act.log"
    proc = subprocess.Popen([sys.executable, "actuator.py", "--room", "room1"], cwd=ROOT, env=service_env(),
                            stdout=open(log, "w"), stderr=subprocess.STDOUT)
    try:
        wait_log(log, "waiting for commands", 20)
        broker.stop()                                     # broker outage
        wait_log(log, "Disconnected", 10)
        time.sleep(1)
        broker.start()                                    # broker back (empty: persistence off)
        for _ in range(60):                               # paho reconnects with 1 s -> 30 s back-off
            if log.read_text(errors="ignore").count("waiting for commands") >= 2:
                break
            time.sleep(0.5)
        assert log.read_text(errors="ignore").count("waiting for commands") >= 2, log.read_text()
        listen = Listener(["smartclass/room1/actuator/light"])
        try:
            cmd = {"cmd": "ON", "command_id": "room1/light/test/1", "ts": "2021-09-20T10:00:00+08:00", "telemetry_sent_at_ms": None}
            listen.c.publish("smartclass/room1/control/light", json.dumps(cmd), qos=1, retain=False).wait_for_publish(5)
            assert listen.wait_for(lambda t, p: json.loads(p).get("command_id") == "room1/light/test/1" and json.loads(p)["state"] == "ON", 10)
        finally:
            listen.close()
    finally:
        proc.terminate()
        proc.wait(10)


@needs_mosquitto
def test_ml_service_crash_is_reported_by_last_will(broker, tmp_path):
    log = tmp_path / "ml.log"
    listen = Listener(["smartclass/ml_service/status"])
    proc = subprocess.Popen([sys.executable, "ml_service.py"], cwd=ROOT, env=service_env(), stdout=open(log, "w"),
                            stderr=subprocess.STDOUT)
    try:
        wait_log(log, "listening on", 120)
        assert listen.wait_for(lambda t, p: p == "online", 5)
        proc.send_signal(signal.SIGKILL)                 # crash: no clean disconnect
        proc.wait(10)
        assert listen.wait_for(lambda t, p: p == "offline", 60), listen.messages  # keepalive 30 s -> broker sends the Will
    finally:
        listen.close()
        if proc.poll() is None:
            proc.kill()


# ---------------------------------------------------------------------------------------------- models / features
def test_missing_model_file_is_skipped_and_others_load(tmp_path):
    from smartclass.registry import load_bundle
    folder = tmp_path / "final"
    shutil.copytree(ROOT / "models/final", folder)
    shutil.copy(ROOT / "models/dqn_controller.pt", tmp_path / "dqn_controller.pt")
    (folder / "occupancy_random_forest.joblib").unlink()
    bundle = load_bundle(folder)
    assert "random_forest" in bundle["load_errors"]
    assert set(bundle["occupancy"]) == {"logistic_regression", "decision_tree", "gradient_boosting", "lstm", "mamba"}


def test_primary_model_missing_falls_back_and_is_flagged(tmp_path):
    from smartclass.predictor import LivePredictor
    folder = tmp_path / "final"
    shutil.copytree(ROOT / "models/final", folder)
    shutil.copy(ROOT / "models/dqn_controller.pt", tmp_path / "dqn_controller.pt")
    (folder / "occupancy_random_forest.joblib").unlink()
    (tmp_path / "dqn_controller.pt").unlink()                       # DQN missing too -> rules decide the AC
    predictor = LivePredictor(folder, primary="random_forest")
    reading = {"timestamp": "2021-09-20T10:00:00+08:00", "wifi_devices": 20, "co2_ppm": 700, "sound_db": 55,
               "humidity_pct": 60, "temperature_c": 24.5, "illuminance_lux": 300, "outdoor_temp_c": 30,
               "lighting_kwh": 0.1, "chilled_water_kwh": 1.0, "fcu_fan_kwh": 0.01, "plug_kwh": 0.02, "solar_wm2": 300}
    out = predictor.predict("room1", reading)
    assert out["primary_model"] == "gradient_boosting" and out["primary_fallback"] is True
    assert out["occupancy_probability"] is not None and out["dqn_ac_action"] is None
    assert "dueling_dqn" in out["unavailable"]


def test_missing_sensor_value_produces_no_probability():
    from smartclass.predictor import LivePredictor
    predictor = LivePredictor(ROOT / "models/final")
    reading = {"timestamp": "2021-09-20T10:00:00+08:00", "wifi_devices": None, "co2_ppm": 700, "sound_db": 55,
               "humidity_pct": 60, "temperature_c": 24.5, "illuminance_lux": 300, "outdoor_temp_c": 30}
    out = predictor.predict("room1", reading)
    assert out["occupancy_probability"] is None and "all" in out["unavailable"]


@needs_node
def test_no_probability_triggers_timetable_fallback_and_alert():
    from smartclass.rules_runner import run_rules
    rec = {"room_id": "room1", "timestamp": "2021-09-20T10:00:00+08:00", "occupancy_probability": None, "primary_model": None,
           "p_arrival_30min": 0, "dqn_ac_action": None, "models": {}, "reading": {"temperature_c": 25, "illuminance_lux": 10}}
    d = run_rules([rec])[0]
    assert (d["light"], d["ac"]) == ("ON", "COMFORT") and d["ac_source"] == "missing-model fallback"


# ---------------------------------------------------------------------------------------------- database
def test_database_locked_briefly_write_waits_and_succeeds(tmp_path):
    from smartclass.db import init_db, write_rows
    db = tmp_path / "locked.db"
    init_db(db)
    holder = sqlite3.connect(db, check_same_thread=False)
    holder.execute("BEGIN EXCLUSIVE")
    threading.Timer(1.5, holder.rollback).start()        # another writer holds the lock for 1.5 s
    start = time.perf_counter()
    n = write_rows("alerts", [{"ts": "2021-09-20T10:00:00+08:00", "room_id": "room1", "type": "TEST", "message": "locked"}], db)
    assert n == 1 and time.perf_counter() - start >= 1.0   # waited for the lock instead of failing or losing the row
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1


def test_database_locked_too_long_raises_not_silently_drops(tmp_path, monkeypatch):
    import smartclass.db as dbmod
    db = tmp_path / "locked.db"
    dbmod.init_db(db)
    holder = sqlite3.connect(db)
    holder.execute("BEGIN EXCLUSIVE")
    real_connect = sqlite3.connect
    monkeypatch.setattr(dbmod.sqlite3, "connect", lambda p, timeout=15: real_connect(p, timeout=0.3))
    monkeypatch.setattr(dbmod, "connect", lambda p=db: real_connect(p, timeout=0.3))
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        dbmod.write_rows("alerts", [{"ts": "t", "room_id": "room1", "type": "TEST", "message": "x"}], db)
    holder.rollback()


# ---------------------------------------------------------------------------------------------- acknowledgements
@needs_node
def test_late_ack_after_no_ack_is_recorded_as_acked_late():
    old = {"room1/ac/t/1-1": {"sent_ms": int(time.time() * 1000) - 10_000, "room": "room1", "load": "ac", "cmd": "ECO",
                              "reason": "r", "data_ts": "t", "sent_at": "x", "tel_ms": None}}
    wd = run_function_node("Watchdog (stale data, NO_ACK)", [{}], flow={"pending": old, "cmd_stats": {"no_ack": 0}})
    timed_out = wd["flow"]["timed_out"]
    assert "room1/ac/t/1-1" in timed_out and wd["flow"]["pending"] == {}
    ack = {"topic": "smartclass/room1/actuator/ac", "payload": json.dumps(
        {"state": "ECO", "previous": "COMFORT", "accepted": True, "command_id": "room1/ac/t/1-1", "loop_latency_ms": 9000})}
    out = run_function_node("Check acknowledgement", [ack], flow={"pending": {}, "timed_out": timed_out, "db_ready": True,
                                                                  "cmd_stats": {"sent": 1, "acked": 0, "rejected": 0, "no_ack": 1,
                                                                                "rtt_sum": 0, "rtt_n": 0, "loop_sum": 0, "loop_n": 0}})
    log, update, show, alert, health, chart = out["outputs"][0]
    assert update["params"]["$status"] == "ACKED_LATE" and update["params"]["$rtt"] >= 10_000
    assert alert["payload"]["type"] == "LATE_ACK" and "late ack 1" in health["payload"]
    assert out["flow"]["timed_out"] == {}


@needs_node
def test_unknown_or_retained_old_ack_does_not_change_commands():
    ack = {"topic": "smartclass/room1/actuator/light", "payload": json.dumps(
        {"state": "OFF", "previous": "ON", "accepted": True, "command_id": "room1/light/previous-run/7"})}
    log, update, show, alert, health, chart = run_function_node("Check acknowledgement", [ack], flow={"db_ready": True})["outputs"][0]
    assert update is None and alert is None and log is not None    # logged, but no command record is touched


@needs_node
def test_unreadable_ack_raises_bad_ack():
    out = run_function_node("Check acknowledgement", [{"topic": "smartclass/room1/actuator/ac", "payload": "{not json"}])
    assert out["outputs"][0][3]["payload"]["type"] == "BAD_ACK" and len(out["outputs"][0]) == 6


# ---------------------------------------------------------------------------------------------- credentials / dataset
def test_init_env_generates_strong_unique_passwords(tmp_path):
    from tools.init_env import main
    env = tmp_path / ".env"
    assert main(["--role", "server", "--env", str(env)]) == 0
    text = env.read_text()
    values = {k: v for k, v in (l.split("=", 1) for l in text.splitlines() if "=" in l and not l.startswith("#"))}
    pws = [values[k] for k in ("SC_SERVER_PASSWORD", "SC_NODE_PASSWORD", "SC_EDITOR_PASSWORD")]
    assert all(len(p) >= 24 and not p.startswith("change-me") for p in pws) and len(set(pws)) == 3
    assert main(["--role", "server", "--env", str(env)]) == 0 and env.read_text() == text   # idempotent: keeps them


def test_init_env_node_rejects_bad_host_and_short_password(tmp_path):
    from tools.init_env import main
    env = tmp_path / ".env"
    assert main(["--role", "node", "--env", str(env), "--host", "laptop-one", "--node-password", "x" * 20]) == 2
    assert main(["--role", "node", "--env", str(env), "--host", "192.168.1.50", "--node-password", "short"]) == 2
    assert main(["--role", "node", "--env", str(env), "--host", "192.168.1.50", "--node-password", "y" * 20]) == 0
    assert "SC_MQTT_HOST=192.168.1.50" in env.read_text()


def test_dataset_integrity_detects_tampering_and_schema_errors(tmp_path):
    from download_data import verify
    for name in ("combined_Room1.csv", "combined_Room2.csv"):
        shutil.copy(ROOT / "data" / name, tmp_path / name)
    assert verify(tmp_path, allow_changed=False)
    with (tmp_path / "combined_Room2.csv").open("a") as f:
        f.write("2022-01-01 00:00 +08:00" + ",0" * 27 + "\n")                 # one extra row
    assert not verify(tmp_path, allow_changed=False)
    first = (tmp_path / "combined_Room1.csv").read_text().splitlines()
    (tmp_path / "combined_Room1.csv").write_text("\n".join([first[0].replace("indoor_co2", "co2")] + first[1:]) + "\n")
    assert not verify(tmp_path, allow_changed=True)                             # schema errors are never allowed
    manifest = json.loads((tmp_path / "dataset_manifest.json").read_text())
    assert manifest["files"]["combined_Room1.csv"]["schema_ok"] is False

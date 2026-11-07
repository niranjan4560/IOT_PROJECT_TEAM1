"""Areas 6, 7(delivery) and 9: Node-RED validation, duplicates, stale data, command gate, acks and NO_ACK,
using the function-node code shipped in nodered/flows.json (tests/js_harness.js)."""
import json
import sqlite3
import time

import pytest

from conftest import ROOT, needs_node, run_function_node

pytestmark = needs_node

GOOD = {"room_id": "room1", "timestamp": "2021-09-20T10:00:00+08:00", "source": "robod_replay", "wifi_devices": 20,
        "co2_ppm": 450, "sound_db": 50, "humidity_pct": 70, "temperature_c": 26, "illuminance_lux": 30, "setpoint_c": 24,
        "outdoor_temp_c": 30, "lighting_kwh": 0.1, "fcu_fan_kwh": 0.02, "plug_kwh": 0.01, "chilled_water_kwh": 1,
        "occupant_presence": 1, "occupant_count": 12, "sent_at_ms": 1700000000000}


def tel(payload, room="room1"):
    return {"topic": f"smartclass/{room}/telemetry", "payload": payload if isinstance(payload, str) else json.dumps(payload)}


def validate(*payloads, **kw):
    return run_function_node("Validate reading", [tel(p, **kw) for p in payloads])


def test_valid_reading_passes():
    out = validate(GOOD)["outputs"][0]
    assert out[0]["payload"]["temperature_c"] == 26 and out[1] is None


@pytest.mark.parametrize("change,expected", [
    ({"timestamp": "2021-09-20 10:00"}, "timestamp must look like"),
    ({"co2_ppm": None}, "co2_ppm is missing"),
    ({"temperature_c": 80}, "temperature_c=80 is outside"),
    ({"wifi_devices": "many"}, "wifi_devices=many is outside"),
])
def test_invalid_or_missing_values_raise_alerts(change, expected):
    out = validate({**GOOD, **change})["outputs"][0]
    assert out[0] is None and out[1]["payload"]["type"] == "INVALID_READING" and expected in out[1]["payload"]["message"]


def test_non_json_and_unknown_room():
    assert validate("not json")["outputs"][0][1]["payload"]["message"] == "payload is not valid JSON"
    assert "unknown room" in validate(GOOD, room="room9")["outputs"][0][1]["payload"]["message"]


def test_optional_fields_may_be_null():
    out = validate({**GOOD, "chilled_water_kwh": None, "occupant_count": None})["outputs"][0]
    assert out[0]["payload"]["chilled_water_kwh"] is None


def test_duplicates_are_dropped():
    result = validate(GOOD, GOOD, {**GOOD, "timestamp": "2021-09-20T10:05:00+08:00"})
    assert result["outputs"][0][0] is not None and result["outputs"][1] is None and result["outputs"][2][0] is not None
    assert result["flow"]["duplicates"] == 1


def test_stale_telemetry_alert_and_recovery():
    old = int(time.time() * 1000) - 60_000
    out = run_function_node("Watchdog (stale data, NO_ACK)", [{}], flow={"lastSeen_room1": old})
    alerts = out["outputs"][0][0]
    assert [a["payload"]["type"] for a in alerts] == ["STALE_TELEMETRY"]
    out = run_function_node("Watchdog (stale data, NO_ACK)", [{}], flow={"lastSeen_room1": int(time.time() * 1000), "stale_room1": True})
    assert [a["payload"]["type"] for a in out["outputs"][0][0]] == ["TELEMETRY_RESUMED"]


def decision(**kw):
    base = {"room_id": "room1", "ts": "2021-09-20T10:00:00+08:00", "light": "ON", "ac": "COMFORT", "reason": "test",
            "telemetry_sent_at_ms": 1700000000000}
    return {"payload": {**base, **kw}}


def test_gate_publishes_only_changes_with_command_ids():
    out = run_function_node("Change-only gate", [decision(), decision(ts="2021-09-20T10:05:00+08:00"), decision(ac="ECO")])
    first, second, third = out["outputs"]
    assert len(first[0]) == 2 and second[0] == [] and len(third[0]) == 1
    cmd = json.loads(first[0][0]["payload"])
    assert first[0][0]["retain"] is True and first[0][0]["topic"] == "smartclass/room1/control/light"
    assert cmd["command_id"].startswith("room1/light/2021-09-20T10:00:00+08:00/") and cmd["telemetry_sent_at_ms"] == 1700000000000
    assert len(out["flow"]["pending"]) == 3 and out["flow"]["cmd_stats"]["sent"] == 3


def test_ack_closes_pending_command_and_records_latency():
    now = int(time.time() * 1000)
    pending = {"room1/light/t/1": {"sent_ms": now - 40, "room": "room1", "load": "light", "cmd": "ON", "reason": "r",
                                   "data_ts": "t", "sent_at": "x", "tel_ms": now - 90}}
    ack = {"topic": "smartclass/room1/actuator/light", "payload": json.dumps(
        {"state": "ON", "previous": "OFF", "accepted": True, "command_id": "room1/light/t/1", "loop_latency_ms": 90})}
    out = run_function_node("Check acknowledgement", [ack], flow={"pending": pending, "db_ready": True})
    log, update, show, alert, health, chart = out["outputs"][0]
    assert update["params"]["$status"] == "ACKED" and update["params"]["$loop"] == 90 and update["params"]["$rtt"] >= 40
    assert out["flow"]["pending"] == {} and out["flow"]["cmd_stats"]["acked"] == 1 and alert is None
    assert "delivery rate 1/1 = 100.0%" in health["payload"]
    assert [c["topic"] for c in chart] == ["Command round trip, server clock (ms)", "Telemetry → actuator loop, node clock (ms)"]
    assert chart[0]["payload"] >= 40 and chart[1]["payload"] == 90


def test_ack_for_rejected_command_raises_alert():
    ack = {"topic": "smartclass/room1/actuator/ac", "payload": json.dumps({"state": "ECO", "previous": "ECO", "accepted": False, "requested": "FLY"})}
    out = run_function_node("Check acknowledgement", [ack], flow={"db_ready": True})
    assert out["outputs"][0][3]["payload"]["type"] == "ACTUATOR_REJECTED"


def test_missing_ack_becomes_no_ack():
    pending = {"room1/ac/t/1": {"sent_ms": int(time.time() * 1000) - 10_000, "room": "room1", "load": "ac", "cmd": "ECO"}}
    out = run_function_node("Watchdog (stale data, NO_ACK)", [{}], flow={"pending": pending, "cmd_stats": {"no_ack": 0}})
    alerts, updates = out["outputs"][0]
    assert alerts[0]["payload"]["type"] == "NO_ACK" and updates[0]["params"]["$id"] == "room1/ac/t/1"
    assert out["flow"]["pending"] == {} and out["flow"]["cmd_stats"]["no_ack"] == 1


def test_schema_creates_tables_and_unique_constraint(tmp_path):
    from smartclass.db import init_db
    path = init_db(tmp_path / "t.db")
    db = sqlite3.connect(path)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"telemetry", "predictions", "decisions", "commands", "actuator_log", "alerts", "model_metrics", "experiment_results"} <= tables
    insert = "INSERT OR IGNORE INTO telemetry (room_id, ts, received_at) VALUES ('room1', '2021-09-20T10:00:00+08:00', 'x')"
    db.execute(insert)
    db.execute(insert)
    assert db.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0] == 1
    init_db(path)  # idempotent


def _decided(light="ON", ac="COMFORT", presence=1, lk=0.1, ck=1.0, ts="2021-09-20T10:00:00+08:00"):
    return {"payload": {"room_id": "room1", "ts": ts, "light": light, "ac": ac,
                        "reading": {"lighting_kwh": lk, "chilled_water_kwh": ck, "occupant_presence": presence}}}


def test_savings_never_shows_misleading_zero_percent():
    out = run_function_node("Baseline vs controlled + comfort", [_decided(lk=0, ck=0, presence=0)])
    light, cool, text, comfort = out["outputs"][0]
    assert "n/a (no recorded energy yet)" in text["payload"] and "0.0%" not in text["payload"]
    assert "n/a (no occupied readings yet)" in comfort["payload"]


def test_savings_and_comfort_counters():
    msgs = [_decided(), _decided(light="OFF", ac="ECO", ts="2021-09-20T10:05:00+08:00"),
            _decided(light="OFF", ac="OFF", presence=0, ts="2021-09-20T10:10:00+08:00")]
    out = run_function_node("Baseline vs controlled + comfort", msgs)
    light, cool, text, comfort = out["outputs"][-1]
    assert light[0]["payload"] == 0.3 and light[1]["payload"] == 0.1          # baseline [M] vs controlled [S]
    assert "Lighting (electrical): 66.7%" in text["payload"] and "3 readings" in text["payload"]
    assert "light OFF while occupied: 1 of 2 (50.0%)" in comfort["payload"]
    assert "AC ECO/OFF while occupied: 1 of 2 (50.0%)" in comfort["payload"]


def test_model_comparison_reads_sqlite_rows_and_marks_validation_choice():
    rows = [{"model": "mamba", "category": "deep", "val_f1": 0.80, "test_f1": 0.65, "test_precision": 0.6, "test_recall": 0.7,
             "cv_f1_mean": None, "cv_f1_std": None, "latency_ms": 2.0, "run_id": "r1"},
            {"model": "random_forest", "category": "ensemble", "val_f1": 0.85, "test_f1": 0.56, "test_precision": 0.5,
             "test_recall": 0.6, "cv_f1_mean": 0.73, "cv_f1_std": 0.11, "latency_ms": 1.0, "run_id": "r1"},
            {"model": "majority", "category": "baseline", "val_f1": 0.9, "test_f1": 0.0, "test_precision": 0, "test_recall": 0,
             "cv_f1_mean": None, "cv_f1_std": None, "latency_ms": 0, "run_id": "r1"}]
    table, note = run_function_node("Format model comparison", [{"payload": rows}])["outputs"][0]
    names = [r["model"] for r in table["payload"]]
    assert "random_forest  ★ selected" in names and "mamba" in names       # chosen by validation F1, not test F1
    assert "majority" in names                                                # baselines shown but never selectable
    assert "VALIDATION F1" in note["payload"] and "never used for selection" in note["payload"]


def test_model_comparison_empty_state_explains_how_to_fill_it():
    table, note = run_function_node("Format model comparison", [{"payload": []}])["outputs"][0]
    assert "python init_db.py" in table["payload"][0]["fix"]


def test_offline_results_panel_uses_sqlite_rows_and_empty_state(tmp_path):
    import sqlite3
    from smartclass.db import import_experiment_results
    db = tmp_path / "x.db"
    assert import_experiment_results(ROOT / "results", db) > 0
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT experiment, scenario, metric, value, unit, run_id FROM experiment_results")]
    cf, cl, note = run_function_node("Format experiment results", [{"payload": rows}])["outputs"][0]
    rf = next(r for r in cf["payload"] if r["occupancy input"].startswith("random_forest"))
    assert rf["lighting saved [S]"] == "38.7 %" and rf["chilled water saved [S] (thermal)"] == "39.5 %"   # = results/savings_results.csv
    assert rf["light OFF while occupied"] == "27.9 %"                                                 # 96 / 344
    always = next(r for r in cl["payload"] if r["controller"] == "always_comfort")
    assert always["cooling [S] kWh thermal"] == 850.61 and "Neither is a measured real-world saving" in note["payload"]
    empty_cf, empty_cl, empty_note = run_function_node("Format experiment results", [{"payload": []}])["outputs"][0]
    assert "python init_db.py" in empty_cf["payload"][0]["fix"] and empty_cl["payload"] == []

"""Areas 5 and 8: MQTT payload serialisation/parsing and actuator command handling + acknowledgements."""
import json
import math
import time

import pandas as pd

from actuator import ClassroomActuatorNode
from conftest import needs_data
from run_simulator import GROUND_TRUTH, SENSOR_FIELDS, build_reading


@needs_data
def test_telemetry_payload_is_strict_json(room1):
    row = room1[room1["illuminance_lux"].isna()].iloc[0]  # a row with a missing sensor
    reading = build_reading(row, "room1")
    text = json.dumps(reading, allow_nan=False)            # would raise if a NaN slipped through
    parsed = json.loads(text)
    assert parsed["illuminance_lux"] is None
    assert parsed["timestamp"].endswith("+08:00") and parsed["source"] == "robod_replay"
    assert set(SENSOR_FIELDS + GROUND_TRUTH) <= set(parsed)
    assert abs(parsed["sent_at_ms"] - time.time() * 1000) < 5000


def node():
    return ClassroomActuatorNode("room1", "127.0.0.1", 1883)  # no connection is made in these tests


def test_actuator_accepts_valid_command_and_measures_loop_latency():
    n = node()
    sent = int(time.time() * 1000) - 120
    ack = n.handle("light", json.dumps({"cmd": "on", "command_id": "room1/light/x/1", "ts": "2021-09-20T10:00:00+08:00",
                                        "telemetry_sent_at_ms": sent}).encode())
    assert ack["accepted"] and ack["state"] == "ON" and ack["previous"] == "UNKNOWN"
    assert ack["command_id"] == "room1/light/x/1" and 100 <= ack["loop_latency_ms"] < 5000
    assert json.loads(json.dumps(ack)) == ack


def test_actuator_rejects_invalid_and_garbage_commands():
    n = node()
    n.handle("ac", json.dumps({"cmd": "ECO"}).encode())
    bad = n.handle("ac", json.dumps({"cmd": "FLY"}).encode())
    assert not bad["accepted"] and bad["state"] == "ECO" and bad["previous"] == "ECO"
    garbage = n.handle("ac", b"\xff not json")
    assert not garbage["accepted"] and garbage["requested"] is None and garbage["state"] == "ECO"
    assert n.handle("heater", b'{"cmd":"ON"}') is None


def test_light_and_ac_are_separate_devices():
    n = node()
    n.handle("light", b'{"cmd":"OFF"}')
    n.handle("ac", b'{"cmd":"BOOST"}')
    assert n.devices["light"].state == "OFF" and n.devices["ac"].state == "BOOST"
    assert n.handle("light", b'{"cmd":"BOOST"}')["accepted"] is False  # an AC mode is not a light state

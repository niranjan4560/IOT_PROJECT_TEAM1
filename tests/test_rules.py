"""Area 7: decision rules and safety conditions (runs the Decision rules node from nodered/flows.json)."""
from datetime import datetime, timedelta

import pytest

from conftest import needs_node
from smartclass.rules_runner import run_rules

pytestmark = needs_node
START = datetime.fromisoformat("2021-09-20T07:00:00+08:00")


def step(i, p, room="room1", temp=24.5, lux=10.0, arrival=0.0, co2=500, dqn=None):
    ts = (START + timedelta(minutes=5 * i)).isoformat(timespec="seconds")
    return {"room_id": room, "timestamp": ts, "occupancy_probability": p, "primary_model": "random_forest",
            "p_arrival_30min": arrival, "dqn_ac_action": dqn, "models": {},
            "reading": {"temperature_c": temp, "illuminance_lux": lux, "co2_ppm": co2, "setpoint_c": 24,
                        "lighting_kwh": 0.1, "chilled_water_kwh": 1.0, "sent_at_ms": 1}}


def cmds(records, config=None):
    return [(d["light"], d["ac"]) for d in run_rules(records, config)]


def test_startup_empty_room_is_not_switched_on():
    assert cmds([step(0, 0.05)])[0] == ("OFF", "ECO")


def test_ac_off_after_30_min_empty():
    out = cmds([step(i, 0.05) for i in range(5)])
    assert out[0] == ("OFF", "ECO") and out[3] == ("OFF", "OFF")


def test_occupied_room_gets_light_and_comfort_or_boost():
    assert cmds([step(0, 0.9)])[0] == ("ON", "COMFORT")
    assert cmds([step(0, 0.9, temp=26.0)])[0] == ("ON", "BOOST")


def test_hysteresis_and_grace_period():   # occupied until p < 0.15, then 15 min grace
    out = cmds([step(0, 0.9), step(1, 0.2), step(2, 0.1), step(3, 0.1), step(4, 0.1), step(5, 0.1)])
    assert out[1] == ("ON", "COMFORT") and out[2] == ("ON", "COMFORT") and out[5] == ("OFF", "ECO")


def test_empty_room_needs_0_25_to_become_occupied():
    out = cmds([step(0, 0.1), step(1, 0.2), step(2, 0.3)])
    assert out[1][0] == "OFF" and out[2] == ("ON", "COMFORT")


def test_precool_only_when_warm():
    assert cmds([step(0, 0.05, temp=26.0, arrival=0.5)])[0] == ("OFF", "PRECOOL")
    assert cmds([step(0, 0.05, temp=24.2, arrival=0.5)])[0] == ("OFF", "ECO")


def test_daylight_dimming_room2_only():
    assert cmds([step(0, 0.9, room="room2", lux=400)])[0][0] == "DIM"
    assert cmds([step(0, 0.9, room="room1", lux=400)])[0][0] == "ON"


def test_minimum_hold_time():
    out = cmds([step(0, 0.9, temp=26.0), step(1, 0.9, temp=24.5), step(2, 0.9, temp=24.5)])
    assert [o[1] for o in out] == ["BOOST", "BOOST", "COMFORT"]


def test_manual_override_wins():
    override = {"_override": {"room": "room1", "enabled": True, "light": "ON", "ac": "BOOST"}}
    assert cmds([override, step(0, 0.05)])[0] == ("ON", "BOOST")


def test_missing_model_output_uses_safe_timetable_then_holds():
    out = cmds([step(0, None), step(1, None)])          # 07:00 is outside the 08:00-20:00 timetable
    assert out == [("OFF", "ECO"), ("OFF", "ECO")]
    late = [step(i, None) for i in range(14, 16)]       # 08:10 inside the timetable
    assert cmds(late)[0] == ("ON", "COMFORT")
    out = cmds([step(0, 0.9), step(1, None)])          # with history: hold the last commands
    assert out[1] == out[0]


def test_dqn_mode_uses_recommendation_but_keeps_safety():
    dqn = {"ac_controller": "dqn"}
    assert cmds([step(0, 0.05, dqn="OFF")], dqn)[0] == ("OFF", "OFF")
    assert cmds([step(0, 0.9, temp=24.5, dqn="ECO")], dqn)[0] == ("ON", "ECO")        # mild: DQN may save
    assert cmds([step(0, 0.9, temp=26.5, dqn="OFF")], dqn)[0] == ("ON", "COMFORT")    # hot + occupied: guard
    assert cmds([step(0, 0.9, dqn=None)], dqn)[0] == ("ON", "COMFORT")                # no DQN: rules
    override = {"_override": {"room": "room1", "enabled": True, "light": "OFF", "ac": "OFF"}}
    assert cmds([override, step(0, 0.9, temp=27, dqn="BOOST")], dqn)[0] == ("OFF", "OFF")


@pytest.mark.parametrize("controller", ["rules", "dqn"])
def test_decisions_are_deterministic(controller):
    seq = [step(i, p, temp=24 + i * 0.3, dqn="ECO") for i, p in enumerate([0.1, 0.7, 0.9, 0.1, 0.05, 0.05, 0.8])]
    assert run_rules(seq, {"ac_controller": controller}) == run_rules(seq, {"ac_controller": controller})


def test_displayed_ac_source_matches_the_decision():
    """Regression for 'AC BOOST while DQN says OFF': the payload must say which layer set the AC command."""
    rules_mode = run_rules([step(0, 0.9, temp=26.0, dqn="OFF")])[0]
    assert rules_mode["ac"] == "BOOST" and rules_mode["ac_source"] == "rules"
    assert rules_mode["dqn_status"].startswith("advisory only")
    dqn = {"ac_controller": "dqn"}
    guarded = run_rules([step(0, 0.9, temp=26.5, dqn="OFF")], dqn)[0]
    assert guarded["ac"] == "COMFORT" and guarded["ac_source"] == "comfort safety guard"
    assert guarded["dqn_status"] == "overridden by comfort guard (DQN wanted OFF)"
    applied = run_rules([step(0, 0.9, temp=24.5, dqn="ECO")], dqn)[0]
    assert applied["ac"] == "ECO" and applied["ac_source"] == "DQN" and applied["dqn_status"] == "applied"
    override = {"_override": {"room": "room1", "enabled": True, "light": "OFF", "ac": "OFF"}}
    ov = run_rules([override, step(0, 0.9, temp=27, dqn="BOOST")], dqn)[0]
    assert ov["ac_source"] == "manual override" and ov["dqn_status"] == "ignored (manual override)"
    fallback = run_rules([step(0, None, dqn="OFF")])[0]
    assert fallback["ac_source"] == "missing-model fallback"

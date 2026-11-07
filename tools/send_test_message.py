"""Live-demo helper (exercise D): publish one deliberately INVALID (or one valid) telemetry message as the IoT node.

  python tools/send_test_message.py valid          a correct reading (accepted, decided, acknowledged)
  python tools/send_test_message.py bad_json       not JSON                      -> alert INVALID_JSON
  python tools/send_test_message.py out_of_range   co2_ppm = 99999               -> alert, reading rejected
  python tools/send_test_message.py missing_field  no temperature_c              -> alert, reading rejected
  python tools/send_test_message.py unknown_room   topic smartclass/room9/...    -> alert UNKNOWN_ROOM
  python tools/send_test_message.py duplicate      the same reading twice        -> second one dropped
Uses the node account from .env, so it also works from Laptop 2. Watch the dashboard Alerts table, or on Laptop 1:
  python -c "import sqlite3;print(*sqlite3.connect('storage/smartclass.db').execute('SELECT ts,room_id,type,message FROM alerts ORDER BY id DESC LIMIT 5'),sep='\\n')"
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from smartclass.config import make_client, mqtt_host, mqtt_port  # noqa: E402
from smartclass.features import SGT  # noqa: E402


def reading(room="room1") -> dict:
    now = datetime.now(SGT)  # a dataset Monday at the current clock time keeps every message unique
    ts = datetime(2021, 12, 13, 10, now.minute, now.second, tzinfo=SGT).isoformat(timespec="seconds")
    return {"room_id": room, "timestamp": ts, "source": "demo_test_message", "sent_at_ms": int(time.time() * 1000),
            "wifi_devices": 25, "co2_ppm": 750, "sound_db": 52.0, "humidity_pct": 62.0, "temperature_c": 25.0,
            "illuminance_lux": 40.0, "setpoint_c": 24.0, "outdoor_temp_c": 29.0, "outdoor_co2_ppm": 420,
            "solar_wm2": 300.0, "fcu_fan_speed": 50, "lighting_kwh": 0.1, "fcu_fan_kwh": 0.01, "plug_kwh": 0.02,
            "chilled_water_kwh": 1.0, "occupant_presence": 1, "occupant_count": 20}


def main() -> None:
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    r = reading()
    messages = {
        "valid": [("smartclass/room1/telemetry", json.dumps(r))],
        "bad_json": [("smartclass/room1/telemetry", "{this is not json")],
        "out_of_range": [("smartclass/room1/telemetry", json.dumps({**r, "co2_ppm": 99999}))],
        "missing_field": [("smartclass/room1/telemetry", json.dumps({k: v for k, v in r.items() if k != "temperature_c"}))],
        "unknown_room": [("smartclass/room9/telemetry", json.dumps(reading("room9")))],
        "duplicate": [("smartclass/room1/telemetry", json.dumps(r))] * 2,
    }
    if kind not in messages:
        raise SystemExit(__doc__)
    client = make_client(f"smartclass-demo-{int(time.time())}", "node")
    client.connect(mqtt_host(), mqtt_port(), keepalive=10)
    client.loop_start()
    for topic, payload in messages[kind]:
        client.publish(topic, payload, qos=1).wait_for_publish(5)
        print(f"published to {topic}: {payload[:110]}{'…' if len(payload) > 110 else ''}")
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()

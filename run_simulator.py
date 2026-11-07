"""IoT sensor node (Laptop 2, Stage 1): replays ROBOD rows in time order to smartclass/{room}/telemetry.

All sensor/meter values are MEASURED (ROBOD). The only SIMULATED parts are the replay timing and
`sent_at_ms` (this laptop's clock when the message was published; used for end-to-end latency).
One CSV row is one five-minute interval; --speed is the number of real seconds per row.
Missing values in the CSV are sent as JSON null (never NaN), so Node-RED can reject them visibly.

Run:  python run_simulator.py --room room1 --speed 1                      (broker from .env SC_MQTT_HOST)
      python run_simulator.py --room room1 --date 2021-09-20 --broker-host 192.168.1.50
"""
from __future__ import annotations

import argparse
import json
import math
import time

from smartclass.config import connect, make_client, mqtt_host, mqtt_port
from smartclass.dataset import read_room_csv
from smartclass.features import to_sgt_iso

SENSOR_FIELDS = ["wifi_devices", "co2_ppm", "sound_db", "humidity_pct", "temperature_c", "illuminance_lux",
                 "setpoint_c", "outdoor_temp_c", "lighting_kwh", "fcu_fan_kwh", "plug_kwh", "chilled_water_kwh"]
GROUND_TRUTH = ["occupant_presence", "occupant_count"]  # camera labels: logged and plotted only, never model inputs


def clean(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else round(number, 6)


def build_reading(row, room: str) -> dict:
    reading = {"room_id": room, "timestamp": to_sgt_iso(row["timestamp"]), "source": "robod_replay"}
    reading.update({name: clean(row[name]) for name in SENSOR_FIELDS + GROUND_TRUTH})
    reading["sent_at_ms"] = int(time.time() * 1000)
    return reading


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay ROBOD readings over MQTT")
    parser.add_argument("--broker-host", default=mqtt_host())
    parser.add_argument("--broker-port", type=int, default=mqtt_port())
    parser.add_argument("--room", default="room1", choices=["room1", "room2"])
    parser.add_argument("--csv", default=None, help="defaults to data/combined_Room1.csv or Room2")
    parser.add_argument("--speed", type=float, default=1.0, help="real seconds between rows (0 = as fast as possible)")
    parser.add_argument("--start-row", type=int, default=0)
    parser.add_argument("--date", default=None, help="replay only this date, e.g. 2021-09-20")
    parser.add_argument("--max-rows", type=int, default=0, help="0 = all rows")
    parser.add_argument("--repeat", action="store_true")
    args = parser.parse_args()
    if args.speed < 0:
        parser.error("--speed must be zero or greater")

    csv_path = args.csv or f"data/combined_{args.room.capitalize()}.csv"
    frame = read_room_csv(csv_path, args.room)
    if args.date:
        frame = frame[frame["date"] == args.date]
        if frame.empty:
            raise SystemExit(f"No rows for date {args.date} in {csv_path}")
    selected = frame.iloc[args.start_row:]
    if args.max_rows:
        selected = selected.iloc[: args.max_rows]

    status = f"smartclass/{args.room}/status"
    client = make_client(f"smartclass-sensor-{args.room}", "node", status)
    connect(client, args.broker_host, args.broker_port)
    client.loop_start()
    client.publish(status, "online", qos=1, retain=True).wait_for_publish(timeout=5)
    print(f"Replaying {len(selected)} rows of {csv_path} as {args.room} to {args.broker_host}:{args.broker_port}")

    sent = 0
    try:
        while True:
            for _, row in selected.iterrows():
                reading = build_reading(row, args.room)
                info = client.publish(f"smartclass/{args.room}/telemetry", json.dumps(reading), qos=1)
                info.wait_for_publish(timeout=10)  # QoS 1: paho re-sends automatically after a reconnect
                sent += 1
                if sent % 100 == 0:
                    print(f"Published {sent} rows; latest {reading['timestamp']}")
                if args.speed:
                    time.sleep(args.speed)
            if not args.repeat:
                break
    except KeyboardInterrupt:
        print("Replay stopped by user")
    finally:
        client.publish(status, "offline", qos=1, retain=True).wait_for_publish(timeout=5)
        client.loop_stop()
        client.disconnect()
    print(f"Finished after publishing {sent} readings")


if __name__ == "__main__":
    main()

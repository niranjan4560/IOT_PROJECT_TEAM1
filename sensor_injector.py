"""Optional sensor-injector panel (Streamlit): type in one sensor reading and publish it over MQTT.

It is NOT the project dashboard - the dashboard is Node-RED Dashboard 2.0 at http://<laptop-A>:1880/dashboard.
The reading goes to smartclass/{room}/telemetry exactly like the replay simulator, so it passes through
Node-RED validation, SQLite, the ML service, the decision rules and the actuator.

Weekday fix: the models only ever saw Monday-Friday of 2021. You choose a weekday and a time; the panel
stamps the reading on that weekday of a real dataset week (13-17 Dec 2021, +08:00), never on today's date.

Run:  streamlit run sensor_injector.py      (broker address and node login come from .env)
"""
from __future__ import annotations

import json
from datetime import date, datetime, time

import time

import paho.mqtt.client as mqtt
import streamlit as st

from smartclass.config import make_client, mqtt_host, mqtt_port
from smartclass.features import SGT

DATASET_WEEK = {  # a real Monday-Friday week inside ROBOD
    "Monday": date(2021, 12, 13), "Tuesday": date(2021, 12, 14), "Wednesday": date(2021, 12, 15),
    "Thursday": date(2021, 12, 16), "Friday": date(2021, 12, 17),
}


def injected_timestamp(weekday: str, clock: time) -> str:
    """Dataset-valid weekday + chosen time; the current seconds keep each injection unique (no duplicate drop)."""
    stamp = datetime.combine(DATASET_WEEK[weekday], clock.replace(second=datetime.now().second), tzinfo=SGT)
    return stamp.isoformat(timespec="seconds")


@st.cache_resource(show_spinner=False)
def mqtt_client(host: str, port: int) -> mqtt.Client:
    client = make_client("smartclass-injector", "node")  # uses SC_NODE_USERNAME / SC_NODE_PASSWORD from .env
    client.connect_async(host, port, keepalive=30)
    client.loop_start()
    return client


def main() -> None:
    st.set_page_config(page_title="Sensor injector", page_icon="🧪")
    st.title("Smart classroom - sensor injector")
    st.caption("Publishes one reading to MQTT. Watch the result on the Node-RED dashboard (Stage 4).")
    host = st.sidebar.text_input("Broker host (Laptop 1)", mqtt_host())
    port = int(st.sidebar.number_input("Broker port", 1, 65535, mqtt_port()))
    client = mqtt_client(host.strip(), port)
    st.sidebar.write("MQTT:", "connected" if client.is_connected() else "connecting...")

    with st.form("reading"):
        c1, c2 = st.columns(2)
        room = c1.selectbox("Room", ["room1", "room2"])
        weekday = c1.selectbox("Day of week (dataset has Mon-Fri only)", list(DATASET_WEEK))
        clock = c1.time_input("Time of day (+08:00)", time(10, 0), step=300)
        wifi = c1.slider("Wi-Fi devices", 0, 60, 15)
        co2 = c1.slider("CO2 (ppm)", 400, 2000, 480, 10)
        sound = c1.slider("Sound (dB)", 40.0, 80.0, 50.0, 0.5)
        temperature = c2.slider("Temperature (°C)", 18.0, 34.0, 26.0, 0.1)
        humidity = c2.slider("Humidity (%RH)", 30.0, 95.0, 70.0, 1.0)
        outdoor = c2.slider("Outdoor temperature (°C)", 20.0, 36.0, 30.0, 0.5)
        lux = c2.slider("Illuminance (lux)", 0.0, 2500.0, 40.0, 10.0)
        setpoint = c2.slider("Recorded BMS setpoint (°C)", 18.0, 31.0, 24.0, 0.5)
        lighting = c2.number_input("Lighting energy (kWh / 5 min)", 0.0, 1.0, 0.10, 0.01, format="%.3f")
        cooling = c2.number_input("Chilled water (THERMAL kWh / 5 min)", 0.0, 12.0, 1.0, 0.1, format="%.2f")
        submitted = st.form_submit_button("Publish reading", type="primary")
    st.info("Tip: inject into a room that is not being replayed at the same time - the rules reset their timers "
            "when the data time jumps backwards or by more than an hour.")

    if submitted:
        reading = {"room_id": room, "timestamp": injected_timestamp(weekday, clock), "source": "injector",
                   "wifi_devices": wifi, "co2_ppm": co2, "sound_db": sound, "humidity_pct": humidity,
                   "temperature_c": temperature, "illuminance_lux": lux, "setpoint_c": setpoint, "outdoor_temp_c": outdoor,
                   "lighting_kwh": lighting, "fcu_fan_kwh": None, "plug_kwh": None, "chilled_water_kwh": cooling,
                   "occupant_presence": None, "occupant_count": None, "sent_at_ms": int(time.time() * 1000)}
        if not client.is_connected():
            st.error(f"Not connected to the broker at {host}:{port}.")
        else:
            client.publish(f"smartclass/{room}/telemetry", json.dumps(reading), qos=1)
            st.success(f"Published to smartclass/{room}/telemetry at {reading['timestamp']}")
            st.json(reading)


if __name__ == "__main__":
    main()

"""Configuration for every Python program: environment variables, optionally loaded from a .env file.

Laptop 1 (server) and Laptop 2 (node) each keep their own .env (copy .env.example). Precedence:
command-line option > real environment variable > .env file > default. Nothing machine-specific is hard-coded.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parent.parent
LOG = logging.getLogger("smartclass.config")


def load_env_file(path: str | Path = ROOT / ".env") -> None:
    """Minimal KEY=VALUE parser (no extra dependency). Existing environment variables win."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()


def setting(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def mqtt_host() -> str:
    return setting("SC_MQTT_HOST", "127.0.0.1")


def mqtt_port() -> int:
    return int(setting("SC_MQTT_PORT", "1883"))


def credentials(role: str) -> tuple[str | None, str | None]:
    """role 'server' (ML service, tools) or 'node' (sensor replay, actuators, injector)."""
    prefix = "SC_SERVER" if role == "server" else "SC_NODE"
    return setting(f"{prefix}_USERNAME"), setting(f"{prefix}_PASSWORD")


def rooms() -> list[str]:
    return [r.strip() for r in setting("SC_ROOMS", "room1,room2").split(",") if r.strip()]


def make_client(client_id: str, role: str, status_topic: str | None = None) -> mqtt.Client:
    """MQTT 3.1.1 client with credentials, Last Will and automatic reconnect (1 s doubling to 30 s)."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)
    user, password = credentials(role)
    if user:
        client.username_pw_set(user, password)
    if status_topic:
        client.will_set(status_topic, "offline", qos=1, retain=True)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def connect(client: mqtt.Client, host: str, port: int) -> None:
    """Connect, with a clear message for the two most common mistakes (wrong IP, wrong password)."""
    try:
        client.connect(host, port, keepalive=30)
    except OSError as exc:
        raise SystemExit(f"Cannot reach the MQTT broker at {host}:{port} ({exc}). Check SC_MQTT_HOST, that the "
                         f"server laptop is running Mosquitto, and the firewall rule for TCP {port}.") from exc


def describe_connect_failure(reason_code) -> str:
    text = str(reason_code)
    if "not authorized" in text.lower() or "bad user" in text.lower():
        return f"{text}: wrong SC_*_USERNAME / SC_*_PASSWORD, or the user is missing from the broker password file"
    return text

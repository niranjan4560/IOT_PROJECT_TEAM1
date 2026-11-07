"""Simulated actuators on the IoT node (Laptop 2, Stage 8): one LIGHT device and one AC device per room.

Each device keeps its own SIMULATED state, applies commands from the server and acknowledges them.

  subscribes   smartclass/{room}/control/light   {"cmd": "ON|DIM|OFF", "command_id", "ts", "reason", "telemetry_sent_at_ms"}
               smartclass/{room}/control/ac      {"cmd": "COMFORT|BOOST|PRECOOL|ECO|OFF", ...}
  publishes    smartclass/{room}/actuator/{load} {"state", "previous", "accepted", "command_id", "ts",
                                                  "acted_at_ms", "loop_latency_ms"}            (retained)
  last will    smartclass/{room}/actuator_status  "offline" (retained)

loop_latency_ms = acted_at_ms - telemetry_sent_at_ms. Both clocks are THIS laptop's (the sensor replay runs
here too), so the end-to-end loop telemetry -> server -> decision -> command -> actuator has no clock skew.

Run:  python actuator.py --room room1          (broker from .env SC_MQTT_HOST)
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import threading
import time
from datetime import datetime

from smartclass.config import connect, describe_connect_failure, make_client, mqtt_host, mqtt_port
from smartclass.features import SGT

LOG = logging.getLogger("actuator")


class SimulatedDevice:
    def __init__(self, load: str, allowed: set[str]):
        self.load, self.allowed, self.state = load, allowed, "UNKNOWN"  # nothing assumed until a command arrives

    def apply(self, requested: str | None) -> tuple[bool, str]:
        previous = self.state
        accepted = requested in self.allowed
        if accepted:
            self.state = requested  # the simulated relay / thermostat mode change
        return accepted, previous


class ClassroomActuatorNode:
    def __init__(self, room: str, host: str, port: int):
        self.room, self.host, self.port = room, host, port
        self.devices = {"light": SimulatedDevice("light", {"ON", "DIM", "OFF"}),
                        "ac": SimulatedDevice("ac", {"COMFORT", "BOOST", "PRECOOL", "ECO", "OFF"})}
        self.status_topic = f"smartclass/{room}/actuator_status"
        self.client = make_client(f"smartclass-actuator-{room}", "node", self.status_topic)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = lambda c, u, f, rc, p: LOG.warning("Disconnected (%s); reconnecting", rc)

    def on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            LOG.error("MQTT connection refused: %s", describe_connect_failure(reason_code))
            return
        client.publish(self.status_topic, "online", qos=1, retain=True)
        client.subscribe(f"smartclass/{self.room}/control/+", qos=1)
        LOG.info("Actuator node for %s connected to %s:%s; waiting for commands", self.room, self.host, self.port)

    def handle(self, load: str, payload: bytes) -> dict | None:
        device = self.devices.get(load)
        if device is None:
            LOG.warning("Ignoring unknown load %s", load)
            return None
        try:
            command = json.loads(payload.decode("utf-8"))
            requested = str(command["cmd"]).upper()
        except (ValueError, KeyError, UnicodeDecodeError, AttributeError, TypeError):
            requested, command = None, {}
        accepted, previous = device.apply(requested)
        acted_ms = int(time.time() * 1000)
        sent_ms = command.get("telemetry_sent_at_ms")
        return {
            "room_id": self.room, "load": load, "state": device.state, "previous": previous, "accepted": accepted,
            "requested": requested, "command_id": command.get("command_id"), "command_ts": command.get("ts"),
            "reason": command.get("reason", ""), "ts": datetime.now(SGT).isoformat(timespec="seconds"),
            "acted_at_ms": acted_ms,
            "loop_latency_ms": (acted_ms - int(sent_ms)) if isinstance(sent_ms, (int, float)) else None,
        }

    def on_message(self, client, userdata, message) -> None:
        load = message.topic.rsplit("/", 1)[-1]
        ack = self.handle(load, message.payload)
        if ack is None:
            return
        client.publish(f"smartclass/{self.room}/actuator/{load}", json.dumps(ack), qos=1, retain=True)
        LOG.info("%s %s: %s -> %s (%s)%s", self.room, load, ack["previous"], ack["state"],
                 "accepted" if ack["accepted"] else f"REJECTED {ack['requested']!r}",
                 f" loop {ack['loop_latency_ms']} ms" if ack["loop_latency_ms"] is not None else "")

    def run(self) -> None:
        stopped = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stopped.set())
        signal.signal(signal.SIGTERM, lambda *_: stopped.set())
        connect(self.client, self.host, self.port)
        self.client.loop_start()
        while not stopped.wait(1):
            pass
        self.client.publish(self.status_topic, "offline", qos=1, retain=True).wait_for_publish(timeout=3)
        self.client.loop_stop()
        self.client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulated light + AC actuators for one classroom")
    parser.add_argument("--room", default="room1")
    parser.add_argument("--broker-host", default=mqtt_host())
    parser.add_argument("--broker-port", type=int, default=mqtt_port())
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ClassroomActuatorNode(args.room, args.broker_host, args.broker_port).run()


if __name__ == "__main__":
    main()

"""ML service (Laptop 1, Stage 5): predictions only - no rules, no database writes, no acknowledgements.

Subscribes : smartclass/{room}/validated     (readings Node-RED has validated and stored)
Publishes  : smartclass/{room}/analytics     (every model's occupancy probability, the primary model,
                                              arrival profile, next-step energy, Dueling-DQN AC recommendation)
             smartclass/ml_service/status     online/offline (retained, Last Will)
             smartclass/ml_service/info       loaded models, load errors, primary model (retained)

Run:  python ml_service.py                    (uses .env; see .env.example)
      python ml_service.py --primary-model mamba
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import threading

from smartclass.config import connect, describe_connect_failure, make_client, mqtt_host, mqtt_port, setting
from smartclass.features import to_sgt_iso
from smartclass.predictor import LivePredictor

LOG = logging.getLogger("ml_service")
STATUS_TOPIC = "smartclass/ml_service/status"


class MLService:
    def __init__(self, host: str, port: int, models: str, primary: str | None):
        self.host, self.port = host, port
        self.predictor = LivePredictor(models, primary)
        self.client = make_client("smartclass-ml-service", "server", STATUS_TOPIC)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = lambda c, u, f, rc, p: LOG.warning("Disconnected (%s); reconnecting", rc)

    def on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            LOG.error("MQTT connection refused: %s", describe_connect_failure(reason_code))
            return
        client.publish(STATUS_TOPIC, "online", qos=1, retain=True)
        info = {"models": sorted(self.predictor.models), "primary_model": self.predictor.primary,
                "dqn_loaded": self.predictor.dqn is not None, "load_errors": self.predictor.load_errors}
        client.publish("smartclass/ml_service/info", json.dumps(info), qos=1, retain=True)
        client.subscribe("smartclass/+/validated", qos=1)
        LOG.info("Connected to %s:%s, listening on smartclass/+/validated (models: %s; primary: %s; DQN: %s)",
                 self.host, self.port, ", ".join(info["models"]), info["primary_model"], info["dqn_loaded"])
        if self.predictor.load_errors:
            LOG.warning("Not loaded: %s", self.predictor.load_errors)

    def on_message(self, client, userdata, message) -> None:
        try:
            reading = json.loads(message.payload.decode("utf-8"))
            room = message.topic.split("/")[1]
            reading["timestamp"] = to_sgt_iso(reading["timestamp"])
            analytics = {"room_id": room, "timestamp": reading["timestamp"], **self.predictor.predict(room, reading),
                         "reading": reading}
            client.publish(f"smartclass/{room}/analytics", json.dumps(analytics), qos=1)
            LOG.info("%s %s primary=%s p_occ=%s dqn=%s %.1f ms%s", room, reading["timestamp"], analytics["primary_model"],
                     analytics["occupancy_probability"], analytics["dqn_ac_action"], analytics["ml_latency_ms"],
                     " (warming up)" if analytics["warming_up"] else "")
        except Exception:  # one bad message must never stop the service
            LOG.exception("Could not process message on %s", message.topic)

    def run(self) -> None:
        stopped = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stopped.set())
        signal.signal(signal.SIGTERM, lambda *_: stopped.set())
        connect(self.client, self.host, self.port)
        self.client.loop_start()
        while not stopped.wait(1):
            pass
        self.client.publish(STATUS_TOPIC, "offline", qos=1, retain=True).wait_for_publish(timeout=3)
        self.client.loop_stop()
        self.client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart classroom ML prediction service")
    parser.add_argument("--broker-host", default=mqtt_host())
    parser.add_argument("--broker-port", type=int, default=mqtt_port())
    parser.add_argument("--models", default=setting("SC_MODELS_DIR", "models/final"))
    parser.add_argument("--primary-model", default=setting("SC_PRIMARY_MODEL"),
                        help="override the primary occupancy model chosen by validation F1")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    MLService(args.broker_host, args.broker_port, args.models, args.primary_model).run()


if __name__ == "__main__":
    main()

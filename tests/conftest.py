"""Shared fixtures. Run all tests from the project folder:  python -m pytest -q
End-to-end test (needs Mosquitto + Node-RED installed):  SC_E2E=1 python -m pytest -q tests/test_e2e_loopback.py
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FLOWS = ROOT / "nodered" / "flows.json"

needs_data = pytest.mark.skipif(not (ROOT / "data/combined_Room1.csv").exists(), reason="run download_data.py first")
needs_models = pytest.mark.skipif(not (ROOT / "models/final/manifest.json").exists(), reason="run train_models.py first")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")


def run_function_node(name: str, messages: list, flow: dict | None = None, global_: dict | None = None, config: dict | None = None) -> dict:
    payload = {"node": name, "messages": messages, "flow": flow or {}, "global": global_ or {}, "config": config}
    done = subprocess.run(["node", str(ROOT / "tests" / "js_harness.js"), str(FLOWS)], input=json.dumps(payload),
                          capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


@pytest.fixture(scope="session")
def room1():
    from smartclass.dataset import add_targets, read_room_csv
    return add_targets(read_room_csv(ROOT / "data/combined_Room1.csv", "room1"))


@pytest.fixture(scope="session")
def room1_features(room1):
    from smartclass.features import add_history_features
    return add_history_features(room1)

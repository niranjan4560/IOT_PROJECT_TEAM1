"""Start-up checks for Laptop 1 (server) or Laptop 2 (node). Prints PASS/FAIL per item; exit code 1 on any FAIL.

Run:  python tools/check_setup.py --role server
      python tools/check_setup.py --role node            (also tests the broker login with the node account)
      python tools/check_setup.py --role node --no-broker  (offline checks only)
"""
from __future__ import annotations

import argparse
import importlib
import os
import shutil
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from smartclass.config import ROOT, credentials, make_client, mqtt_host, mqtt_port  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def env_value(key: str) -> str:
    env = ROOT / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


def dataset_ok() -> bool:
    import contextlib
    import io
    sys.path.insert(0, str(ROOT))
    from download_data import verify
    with contextlib.redirect_stdout(io.StringIO()):
        return verify(ROOT / "data", allow_changed=False)


def broker_login(role: str, host: str, port: int) -> tuple[bool, str]:
    try:
        socket.create_connection((host, port), timeout=3).close()
    except OSError as exc:
        return False, f"TCP {host}:{port} unreachable ({exc}) - is Mosquitto running? firewall? correct SC_MQTT_HOST?"
    done, outcome = threading.Event(), {}
    client = make_client(f"smartclass-check-{role}", role)
    client.on_connect = lambda c, u, f, rc, p: (outcome.setdefault("rc", rc), done.set())
    client.connect(host, port, keepalive=10)
    client.loop_start()
    done.wait(5)
    client.loop_stop()
    client.disconnect()
    rc = outcome.get("rc")
    if rc is None:
        return False, "no CONNACK within 5 s"
    return (not rc.is_failure), f"broker answered: {rc}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["server", "node"], required=True)
    parser.add_argument("--no-broker", action="store_true")
    args = parser.parse_args()

    check("Python >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0])
    modules = ["numpy", "pandas", "paho.mqtt.client"] + (["sklearn", "torch", "joblib", "psutil"] if args.role == "server" else [])
    for module in modules:
        try:
            importlib.import_module(module)
            check(f"import {module}", True)
        except Exception as exc:
            check(f"import {module}", False, f"{exc} -> pip install -r {'requirements.txt' if args.role == 'server' else 'requirements-node.txt'}")
    check(".env present", (ROOT / ".env").exists(), "copy .env.example to .env and edit it")
    user, password = credentials(args.role)
    check(f"{args.role} credentials in .env", bool(user and password), f"SC_{args.role.upper()}_USERNAME/PASSWORD")
    check(f"{args.role} password is not a placeholder", bool(password) and not password.startswith("change-me") and len(password) >= 12,
          f"python tools/init_env.py --role {args.role}")
    for room in ("Room1", "Room2"):
        check(f"data/combined_{room}.csv", (ROOT / f"data/combined_{room}.csv").exists(), "python download_data.py")
    if args.role == "server":
        check("models/final/manifest.json", (ROOT / "models/final/manifest.json").exists(), "python train_models.py")
        check("models/dqn_controller.pt", (ROOT / "models/dqn_controller.pt").exists(), "python train_models.py")
        check("Node.js on PATH", shutil.which("node") is not None, "install Node.js 22 LTS")
        check("Node-RED installed", (ROOT / "nodered/node_modules/node-red").exists(), "cd nodered && npm install")
        check("sqlite3 native module", (ROOT / "nodered/node_modules/sqlite3/build/Release/node_sqlite3.node").exists()
              or (ROOT / "nodered/node_modules/sqlite3/lib/binding").exists(),
              "cd nodered && npm rebuild sqlite3 (npm 11+: npm approve-scripts sqlite3 first)")
        editor = os.environ.get("SC_EDITOR_PASSWORD") or env_value("SC_EDITOR_PASSWORD")
        check("Node-RED editor password set", bool(editor) and not editor.startswith("change-me") and len(editor) >= 8,
              "python tools/init_env.py --role server (without it the editor only accepts localhost)")
        check("dataset SHA-256 matches registered files", dataset_ok(), "python download_data.py --verify")
        check("broker password file", (ROOT / "config/mosquitto/passwd").exists(), "python tools/make_broker_users.py")
    if not args.no_broker:
        ok, detail = broker_login(args.role, mqtt_host(), mqtt_port())
        check(f"MQTT login as {user} at {mqtt_host()}:{mqtt_port()}", ok, detail)
    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {'' if ok else detail}")
    failed = sum(not ok for _, ok, _ in results)
    print(f"{len(results) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

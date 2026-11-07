#!/usr/bin/env bash
# Laptop 2 (IoT NODE) one-time setup:  bash scripts/setup_node.sh <Laptop 1 IP>
set -euo pipefail
source "$(dirname "$0")/lib.sh"
command -v python3 >/dev/null || { echo "python3 not found (need 3.10+)"; exit 1; }
[ -x "$PY" ] || python3 -m venv .venv
"$PY" -m pip install -r requirements-node.txt
"$PY" tools/init_env.py --role node ${1:+--host "$1"}   # asks for the node password shown on Laptop 1
"$PY" download_data.py
"$PY" tools/check_setup.py --role node || echo "Broker check failed: is Laptop 1 running start_server.sh? firewall? IP?"
echo "Next: bash scripts/start_node.sh --date 2021-09-20"

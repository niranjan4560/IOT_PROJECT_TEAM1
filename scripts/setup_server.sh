#!/usr/bin/env bash
# Laptop 1 (SERVER) one-time setup:  bash scripts/setup_server.sh
set -euo pipefail
source "$(dirname "$0")/lib.sh"
command -v python3 >/dev/null || { echo "python3 not found (need 3.10+)"; exit 1; }
command -v node >/dev/null || { echo "node not found (need Node.js 20.17+ / 22 LTS)"; exit 1; }
command -v mosquitto >/dev/null || { echo "mosquitto not found (apt install mosquitto / brew install mosquitto)"; exit 1; }
[ -x "$PY" ] || python3 -m venv .venv
"$PY" -m pip install -r requirements.txt
"$PY" tools/init_env.py --role server          # creates .env with random passwords if needed
"$PY" download_data.py                          # downloads + verifies SHA-256 and schema
[ -f models/final/manifest.json ] || "$PY" train_models.py
(cd nodered && npm install --no-audit --no-fund)
"$PY" tools/make_broker_users.py
"$PY" init_db.py
"$PY" tools/check_setup.py --role server --no-broker
"$PY" tools/show_ip.py
echo "Next: bash scripts/start_server.sh"

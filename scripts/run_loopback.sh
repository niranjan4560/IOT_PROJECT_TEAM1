#!/usr/bin/env bash
# Loopback mode: server AND node on ONE laptop (SC_MQTT_HOST=127.0.0.1 in .env). Ctrl+C stops everything.
#   bash scripts/run_loopback.sh --date 2021-09-20 --speed 0.5
set -euo pipefail
source "$(dirname "$0")/lib.sh"
trap cleanup EXIT INT TERM
start_server_components
start_node_components
"$PY" run_simulator.py --speed 1 "$@"
echo "Replay finished; everything is still running - Ctrl+C to stop."
wait

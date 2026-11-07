#!/usr/bin/env bash
# Laptop 2 (IoT NODE): actuator nodes for room1+room2, then replays ROBOD. Extra arguments go to run_simulator.py.
#   bash scripts/start_node.sh --room room1 --date 2021-09-20 --speed 0.5
set -euo pipefail
source "$(dirname "$0")/lib.sh"
trap cleanup EXIT INT TERM
start_node_components
"$PY" run_simulator.py --speed 1 "$@"
echo "Replay finished; actuators still running - Ctrl+C to stop."
wait

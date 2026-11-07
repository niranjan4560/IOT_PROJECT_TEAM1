#!/usr/bin/env bash
# Laptop 1 (SERVER): Mosquitto + Node-RED + ML service. Ctrl+C stops all three.  bash scripts/start_server.sh
set -euo pipefail
source "$(dirname "$0")/lib.sh"
trap cleanup EXIT INT TERM
start_server_components
echo "Press Ctrl+C to stop the server."
wait

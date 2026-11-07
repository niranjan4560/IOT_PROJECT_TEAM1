#!/usr/bin/env bash
# Stops what scripts/start_server.sh started (ML service, Node-RED, Mosquitto), e.g. from another terminal.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
stop_from_pidfile logs/server.pids

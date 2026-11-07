#!/usr/bin/env bash
# Stops what scripts/start_node.sh started (actuator nodes; the replay stops with its own terminal).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
stop_from_pidfile logs/node.pids

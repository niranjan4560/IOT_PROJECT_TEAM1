# Shared functions for the Linux/macOS scripts (sourced, not run directly).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
mkdir -p logs storage
PIDS=()
PIDFILE=""

record_pid() {  # record_pid <pid> <name>   (also written to $PIDFILE so stop_*.sh works from another terminal)
  PIDS+=("$1"); [ -n "$PIDFILE" ] && echo "$1 $2" >> "$PIDFILE"; return 0
}

cleanup() {  # stop in reverse start-up order so the broker goes last
  trap - EXIT INT TERM
  echo; echo "Stopping..."
  for (( i=${#PIDS[@]}-1; i>=0; i-- )); do kill "${PIDS[i]}" 2>/dev/null || true; wait "${PIDS[i]}" 2>/dev/null || true; done
  [ -n "$PIDFILE" ] && rm -f "$PIDFILE"; return 0
}

wait_for_log() {  # wait_for_log <file> <text> <seconds>
  for _ in $(seq "${3:-60}"); do grep -a -q "$2" "$1" 2>/dev/null && return 0; sleep 1; done
  echo "$1 never showed '$2' - see the log"; exit 1
}

port_in_use() { (echo > "/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

require_free_port() {  # require_free_port <port> <what> <hint>
  if port_in_use "$1"; then echo "Port $1 ($2) is already in use. $3"; exit 1; fi
}

start_server_components() {
  [ -x "$PY" ] || { echo "Run scripts/setup_server.sh first"; exit 1; }
  "$PY" tools/check_setup.py --role server --no-broker || { echo "Fix the FAIL lines above first."; exit 1; }
  local ui_port="${SC_NODERED_PORT:-$(grep -E '^SC_NODERED_PORT=' .env 2>/dev/null | cut -d= -f2)}"; ui_port="${ui_port:-1880}"
  require_free_port 1883 "MQTT" "A system Mosquitto service? sudo systemctl stop mosquitto  - or an earlier run: bash scripts/stop_server.sh"
  require_free_port "$ui_port" "Node-RED" "An earlier Node-RED? bash scripts/stop_server.sh  - or set SC_NODERED_PORT in .env"
  PIDFILE="$ROOT/logs/server.pids"; : > "$PIDFILE"
  "$PY" init_db.py > logs/init_db.log 2>&1 || { echo "init_db.py failed - see logs/init_db.log"; exit 1; }
  mosquitto -c config/mosquitto/mosquitto.conf -v > logs/mosquitto.log 2>&1 & record_pid $! mosquitto
  sleep 1
  (cd nodered && exec ./node_modules/.bin/node-red --userDir . --settings settings.js) > logs/nodered.log 2>&1 & record_pid $! node-red
  wait_for_log logs/nodered.log "Connected to broker" 90
  "$PY" ml_service.py > logs/ml_service.log 2>&1 & record_pid $! ml_service
  wait_for_log logs/ml_service.log "listening on" 120
  echo "Server running. Dashboard: http://localhost:$ui_port/dashboard  Editor: http://localhost:$ui_port  (logs in logs/)"
  "$PY" tools/show_ip.py
}

start_node_components() {
  [ -x "$PY" ] || { echo "Run scripts/setup_node.sh first"; exit 1; }
  "$PY" tools/check_setup.py --role node || { echo "Fix the FAIL lines above first."; exit 1; }
  PIDFILE="$ROOT/logs/node.pids"; : > "$PIDFILE"
  for room in room1 room2; do
    "$PY" actuator.py --room "$room" > "logs/actuator_$room.log" 2>&1 & record_pid $! "actuator_$room"
    wait_for_log "logs/actuator_$room.log" "waiting for commands" 30
  done
}

stop_from_pidfile() {  # stop_from_pidfile <file>
  [ -f "$1" ] || { echo "Nothing to stop ($1 not found)."; return 0; }
  tac "$1" | while read -r pid name; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      for _ in $(seq 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done   # wait up to 20 s (Node-RED closes MQTT)
      if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid"; echo "force-stopped $name (pid $pid)"; else echo "stopped $name (pid $pid)"; fi
    else echo "$name (pid $pid) was not running"; fi
  done
  rm -f "$1"
}

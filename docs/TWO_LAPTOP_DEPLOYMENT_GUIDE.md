# Two-laptop deployment guide (Windows)

**Laptop 1 = SERVER:** Mosquitto broker, Node-RED (flow, decision engine, SQLite, Dashboard 2.0), ML service.
**Laptop 2 = IoT NODE:** ROBOD replay (sensor publisher), Room 1 and Room 2 actuators (light + AC), acknowledgements.

> **Verification status.**
> - The scripts were parse-checked with the real PowerShell 7.4 parser, and their helper functions were executed
>   under PowerShell on Linux (`tests/test_scripts.py`).
> - The Linux equivalents (`scripts/*.sh`) ran the full system end to end.
> - Windows-only cmdlets (`Get-NetTCPConnection`, `Test-NetConnection`, `taskkill`, `New-NetFirewallRule`) have
>   **not been executed by us**.
> - **Communication between two separate physical machines is NOT YET VERIFIED.** Run the checklist in section 6 and
>   record the result before claiming it.

## 0. What you need

| | Laptop 1 (server) | Laptop 2 (node) |
|---|---|---|
| Windows | 10 or 11 | 10 or 11 |
| Python | 3.11–3.13 ("Add python.exe to PATH" ticked) | 3.11–3.13 |
| Node.js | 22 LTS (20.17 minimum) | – |
| Mosquitto | 2.x: `winget install EclipseFoundation.Mosquitto` | – |
| Network | the same Wi-Fi/LAN as Laptop 2, set to **Private** | the same Wi-Fi/LAN |
| Disk / RAM | about 3 GB (PyTorch) / 8 GB | about 300 MB / 4 GB |

Copy the project folder to both laptops (USB stick or `git clone`). All commands below run in **PowerShell, inside
the project folder**.

Campus Wi-Fi often blocks laptop-to-laptop traffic ("client isolation"). If check 6.3 fails on campus Wi-Fi, use a
phone hotspot or a small router. **Never** use port forwarding or a public address to make MQTT work.

## 1. Laptop 1 — one-time setup

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_server.ps1
```

What it does, in order:

1. Detects Python (≥ 3.10), Node.js (≥ 20.17) and Mosquitto, and stops with an install hint if one is missing.
2. Creates `.venv` and installs `requirements.txt`.
3. Runs `tools\init_env.py --role server`, which creates `.env` with **random** passwords from Python's `secrets`
   module (`SC_SERVER_PASSWORD`, `SC_NODE_PASSWORD`, `SC_EDITOR_PASSWORD`).
4. Downloads ROBOD and verifies its SHA-256 and schema.
5. Trains the models if `models\final` is missing (about 10 minutes).
6. Runs `npm install` for Node-RED.
7. Writes the broker password file and ACL.
8. Creates the SQLite database and imports the registered model metrics and experiment results.

Expected output (abridged):

```text
OK    Python 3.13 (py -3)
OK    Node.js 22.x
OK    Mosquitto C:\Program Files\mosquitto\mosquitto.exe
...
.env: updated SC_SERVER_PASSWORD, SC_NODE_PASSWORD, SC_EDITOR_PASSWORD
Type this node password on Laptop 2 when init_env.py asks for it (shown once):
    <24 random characters>                       <- write it down for Laptop 2, do not photograph or email it
...
PASS  combined_Room1.csv: sha256 matches, 8352 rows, schema ok
PASS  combined_Room2.csv: sha256 matches, 8352 rows, schema ok
...
Imported 183 model-metric rows from training_report.json (0 = already present)
Imported 154 experiment-result rows from results/ (0 = already present or not found)
...
21 passed, 0 failed
Laptop 1 LAN IP: 192.168.x.y
Next: once, in an ADMINISTRATOR PowerShell: scripts\open_firewall.ps1 ; then: scripts\start_server.ps1
```

Then, **once**, in an **Administrator** PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\open_firewall.ps1
```

This allows TCP 1883 (MQTT) and 1880 (dashboard) **only on the Private profile and only from the local subnet**. It
also stops the default Mosquitto Windows service (which would occupy port 1883) and sets it to Manual. It prints the
network category; if that says `Public`, run the `Set-NetConnectionProfile` command it shows.

## 2. Laptop 1 — start

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_server.ps1
```

The script:

1. Re-checks the setup (fails on placeholder passwords or a dataset hash mismatch).
2. **Refuses to start** if port 1883 or 1880 is already in use, and names the owning process.
3. Runs `init_db.py`.
4. Opens three windows (Mosquitto, Node-RED, ML service) and records their PIDs in `logs\server.pids`.
5. Waits for each port, tests the MQTT login, and prints the LAN IP.

Expected output (end):

```text
OK    SQLite ready (model metrics imported for the dashboard)
OK    Mosquitto listening on 1883
OK    Node-RED listening on 1880
PASS  MQTT login as sc_server at 127.0.0.1:1883
22 passed, 0 failed
Laptop 1 LAN IP: 192.168.x.y
  On Laptop 2 run: python tools/init_env.py --role node --host 192.168.x.y   (or setup_node.ps1 -ServerIp 192.168.x.y)
  Dashboard from any laptop on this Wi-Fi: http://192.168.x.y:1880/dashboard
Dashboard: http://localhost:1880/dashboard    Editor: http://localhost:1880 (login: admin / SC_EDITOR_PASSWORD in .env)
```

If a port is busy you get, for example:
`ERROR: Port 1883 (MQTT) is already used by mosquitto (PID 4321). Run scripts\stop_server.ps1, or stop the default Mosquitto service ...`

## 3. Laptop 2 — one-time setup

Use the IP and the node password printed on Laptop 1:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_node.ps1 -ServerIp 192.168.x.y
```

What it does:

1. Detects Python and creates `.venv` with `requirements-node.txt` (no ML libraries).
2. Writes `.env` with `SC_MQTT_HOST=192.168.x.y` and asks for the node password. Input is hidden; anything
   shorter than 12 characters is refused.
3. Downloads and verifies ROBOD.
4. Tests TCP to `192.168.x.y:1883`, then the MQTT login as `sc_node`.

Expected output (end):

```text
Node password shown on Laptop 1 (hidden):
.env: updated SC_MQTT_HOST, SC_NODE_PASSWORD
...
OK    Laptop 1 broker reachable at 192.168.x.y:1883
PASS  MQTT login as sc_node at 192.168.x.y:1883
10 passed, 0 failed
```

## 4. Laptop 2 — start

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_node.ps1 -Room room1 -Date 2021-09-20 -Speed 1
```

1. Checks TCP connectivity to Laptop 1 and the MQTT login, and fails with a reason if either is missing.
2. Opens one actuator window per room (PIDs in `logs\node.pids`).
3. Replays one ROBOD day: 288 readings, 1 per second at `-Speed 1`; `-Speed 0.25` is 4 per second.

Expected output:

```text
OK    Laptop 1 broker reachable at 192.168.x.y:1883
...
Replaying 288 rows of data/combined_Room1.csv as room1 to 192.168.x.y:1883
Published 100 rows; latest 2021-09-20T08:15:00+08:00
Published 200 rows; latest 2021-09-20T16:35:00+08:00
Finished after publishing 288 readings
```

Each actuator window shows lines such as `room1 light: OFF -> ON (accepted) loop 95 ms`.

## 5. Shutdown (either order is safe)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop_node.ps1     # Laptop 2: stops both actuator windows
powershell -ExecutionPolicy Bypass -File scripts\stop_server.ps1   # Laptop 1: ML service, Node-RED, Mosquitto
```

Expected: `stopped actuator_room2 (PID ...)`, `stopped actuator_room1 (PID ...)`, and on Laptop 1 `stopped ml_service`,
`stopped node-red`, `stopped mosquitto`.

If the actuators stop first, Laptop 1 raises `DEVICE_OFFLINE` (MQTT Last Will) and `NO_ACK` for any later command.
If the server stops first, the actuators log `Disconnected ... reconnecting` and reconnect automatically (1–30 s
back-off) when it comes back. They receive the last retained command; this is tested in
`tests/test_failures.py::test_actuator_reconnects_after_broker_restart_and_executes_command`.

## 6. Two-machine verification checklist (requires BOTH laptops)

Record the date, both IP addresses and the result of each check. Physical status today: **PENDING**.

| # | Check | How | Pass criterion | Result |
|---|---|---|---|---|
| 6.1 | Same network | `ipconfig` on both | same subnet (e.g. 192.168.1.x) | ☐ |
| 6.2 | Private profile | `Get-NetConnectionProfile` on Laptop 1 | `NetworkCategory : Private` | ☐ |
| 6.3 | TCP reachability | Laptop 2: `Test-NetConnection 192.168.x.y -Port 1883` | `TcpTestSucceeded : True` | ☐ |
| 6.4 | Authenticated login | Laptop 2: `.\.venv\Scripts\python tools\check_setup.py --role node` | `PASS MQTT login as sc_node at 192.168.x.y:1883` | ☐ |
| 6.5 | Wrong password refused | Laptop 2: temporarily change `SC_NODE_PASSWORD`, run 6.4 again, restore it | `FAIL  MQTT login … broker answered: Not authorized` | ☐ |
| 6.6 | ACL | Laptop 2 cannot command actuators: `python -c "from smartclass.config import *; c=make_client('x','node'); c.connect(mqtt_host(),1883); c.loop_start(); c.publish('smartclass/room1/control/ac','{\"cmd\":\"OFF\"}',qos=1).wait_for_publish(); print('sent')"` | nothing happens in the actuator window; Mosquitto window on Laptop 1 shows `Denied PUBLISH from x (… 'smartclass/room1/control/ac' …)` | ☐ |
| 6.7 | Telemetry crosses machines | start the replay (section 4) | dashboard on Laptop 1 shows "source: robod_replay via MQTT → Node-RED → SQLite" and the reading time advancing | ☐ |
| 6.8 | Commands cross back | actuator windows on Laptop 2 | `room1 light: OFF -> ON (accepted) loop … ms` lines appear; dashboard "Light actuator ack [S]" matches the command | ☐ |
| 6.9 | Delivery rate | dashboard System health | `delivery rate N/N = 100.0%`, no-ack 0 | ☐ |
| 6.10 | Latency | dashboard latency chart, or `python tools\closed_loop_report.py --out logs\two_laptop_report.json` on Laptop 1 | round trip and loop medians recorded (expect tens to a few hundred ms on Wi-Fi) | ☐ |
| 6.11 | Dashboard from Laptop 2 | browser on Laptop 2: `http://192.168.x.y:1880/dashboard` | page loads | ☐ |
| 6.12 | Editor protected | browser on Laptop 2: `http://192.168.x.y:1880/` | login prompt; wrong password refused | ☐ |
| 6.13 | Node outage | run `stop_node.ps1` on Laptop 2 | dashboard: actuators offline, `DEVICE_OFFLINE` alert | ☐ |
| 6.14 | Broker outage and recovery | `stop_server.ps1` then `start_server.ps1` on Laptop 1, leave Laptop 2 running | actuator windows reconnect (`waiting for commands` appears again) | ☐ |
| 6.15 | Clean shutdown | sections 5 on both | all `stopped ...`; ports 1883/1880 free (`Get-NetTCPConnection -LocalPort 1883` empty) | ☐ |

Only when 6.1–6.12 pass may the report say "two-laptop operation verified on <date>". Attach a photo of both screens
and the `two_laptop_report.json` from 6.10 as evidence.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Port 1883 (MQTT) is already used by mosquitto` | the Mosquitto Windows service, or a previous run | `scripts\stop_server.ps1`, or run `open_firewall.ps1` as Administrator once (stops the service) |
| `Cannot reach 192.168.x.y:1883` on Laptop 2 | firewall, Public profile, client isolation, or a changed IP | 6.2 / 6.3; re-run `open_firewall.ps1`; try a hotspot; check `ipconfig` again (DHCP may change the IP) |
| `FAIL MQTT login ... Not authorized` | the node password differs from Laptop 1 | on Laptop 1 the password is in `.env` (`SC_NODE_PASSWORD`); on Laptop 2 run `python tools\init_env.py --role node --rotate` and type it again |
| Dashboard "No training metrics in SQLite yet" | the database was deleted after start | `python init_db.py`, then press **Reload from SQLite** |
| Node-RED window: `sqlite3` error | native module not built (npm 11 blocks install scripts) | `cd nodered; npm approve-scripts sqlite3; npm rebuild sqlite3` |
| Editor says "set SC_EDITOR_PASSWORD" (HTTP 403) | no editor password, so the editor is localhost-only | `python tools\init_env.py --role server`, then restart the server |
| `Actuators seem to be running already` | `logs\node.pids` exists from an earlier run | `scripts\stop_node.ps1` |

## 8. Security notes

- **MQTT:** anonymous access is disabled, and each laptop role has its own account. The ACL limits the node account
  to telemetry/status/acknowledgement writes and control-topic reads. There is no TLS: this is a LAN prototype, so
  use it only on a private network.
- **Node-RED editor:** it requires a login when `SC_EDITOR_PASSWORD` is set (bcrypt hash computed at start). Without
  a password, it only answers requests from Laptop 1 itself. The dashboard is read-only, apart from the override and
  reset controls, and is reachable on the LAN.
- **Secrets:** `.env`, `config/mosquitto/passwd` and `nodered/flows_cred.json` are git-ignored and excluded from the
  project ZIP. Passwords never appear in logs: `init_env.py` shows the node password once, only on Laptop 1's
  screen.
- **Firewall:** rules apply to the Private profile and the local subnet only.

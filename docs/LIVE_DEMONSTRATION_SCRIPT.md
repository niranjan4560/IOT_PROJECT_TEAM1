# Live demonstration script (about 15 minutes + modification exercises)

Roles are suggestions: **P1** presents, **P2** drives Laptop 1, **P3** drives Laptop 2. Swap them as the team
prefers. Everything below was rehearsed on the project build; the outputs quoted come from those rehearsals
(`FINAL_DELIVERY/EVIDENCE/terminal/`). The rehearsals ran on one machine through its network interface; the
two-machine version is still pending (`TWO_LAPTOP_DEPLOYMENT_GUIDE.md` §6).

**Before the examiners arrive (10 min):**

- both laptops on the same private Wi-Fi or hotspot;
- Laptop 1: `scripts\start_server.ps1`;
- Laptop 2: `python tools\check_setup.py --role node` → all PASS;
- open the dashboard (`http://localhost:1880/dashboard`) and the editor (logged in) in two browser tabs on Laptop 1;
- open a third tab with `docs/architecture.png`.

Keep a terminal open in the project folder on each laptop with `.venv` activated (`.\.venv\Scripts\Activate.ps1`).

---

## Part 1 — Feature demonstration

| # | Step | Who / where | Say | Show / expected |
|---|---|---|---|---|
| 1 | Architecture | P1, architecture tab | "Eight stages exactly as the reference: dataset node → MQTT → Node-RED → SQLite + dashboard → ML → decision → MQTT control → actuators with acknowledgements. Laptop 1 is the server; Laptop 2 is the IoT node." | `docs/architecture.png` |
| 2 | Laptop 1 startup | P2 | "One script; it checks ports, passwords and the dataset hash before starting anything." | three windows; `22 passed, 0 failed`; LAN IP printed |
| 3 | Laptop 2 startup | P3 | "The node only knows the server IP and its own restricted account." | `start_node.ps1 -Room room1 -Date 2021-09-20 -Speed 1`; `OK Laptop 1 broker reachable`; two actuator windows |
| 4 | Dataset replay | P3 | "Real ROBOD lecture-room data, 5-minute rows, sent as JSON with QoS 1; times stay in +08:00." | `Replaying 288 rows ...`; dashboard "Showing" line: room1, data time, `source: robod_replay via MQTT → Node-RED → SQLite` |
| 5 | Dashboard tour | P1 | "[M] measured, [P] predicted, [S] simulated: every panel says which. Lighting is electrical kWh; chilled water is THERMAL kWh and never added to it." | gauge, sensor values, occupancy chart (probability vs camera), the two energy charts |
| 6 | Model predictions | P1 | "Six models predict every reading; the random forest is primary because it had the best validation F1. Test F1 is shown but was never used for selection." | live predictions table; model-performance table (from SQLite) with ★ selected and the selection rule |
| 7 | Decision engine | P2, editor | "One function node; the priority is manual override > minimum hold > comfort guard > controller > fallback. The panel says which layer set each command." | open the **Decision rules** node; dashboard "AC command [S]: … — set by rules" and the "Dueling-DQN … advisory only" line |
| 8 | MQTT commands | P2 | "Commands go only on change, retained, with a command_id; the ACL stops the node account from sending commands." | Mosquitto window: `smartclass/room1/control/light`; optionally checklist 6.6 (`Denied PUBLISH`) |
| 9 | Acknowledgement | P3 | "The actuator applies the command and acknowledges with the loop latency measured on its own clock." | actuator window `room1 light: OFF -> ON (accepted) loop … ms`; dashboard "Light actuator ack [S]" |
| 10 | Energy evaluation | P1 | "Live savings are a counterfactual on recorded energy; the offline table is the registered experiment on 6 held-out days. Rules + random forest: 38.7% lighting, 39.5% chilled water, but the lights were wrongly OFF in 27.9% of occupied intervals. That is the honest trade-off." | savings charts + offline evaluation table |
| 11 | System health | P2 | "Last Will shows each device; delivery rate, round trip and loop latency per command." | `delivery rate N/N = 100.0%`; latency chart (about 90 ms here) |
| 12 | Manual override | P2, dashboard | "Override always wins and is logged." | choose Light ON, AC BOOST, enable → next reading: `BOOST — set by manual override`, acknowledged; disable it again |
| 13 | Shutdown | P3 then P2 | "Clean stop by PID; the server raises DEVICE_OFFLINE when the node goes away." | `stop_node.ps1` → alert; `stop_server.ps1` → `stopped …` ×3 |

Fallback if Wi-Fi fails in the room: run both roles on Laptop 1 (`scripts\run_loopback.ps1 -Date 2021-09-20`) and
say so openly. It is the same code, but not the two-machine setup.

---

## Part 2 — Live modification exercises

**General rules:**

- Thresholds live in one place: the **CONFIG (all thresholds)** function node, **On Start** tab.
- To change one: Node-RED editor → double-click CONFIG → On Start → edit → **Done** → **Deploy**. Node-RED rewrites
  `nodered/flows.json`, and the change takes effect on the next reading.
- **Verify** with `python tools\demo_check.py <scenario>`. It runs a fixed scenario through the deployed Decision rules
  code, so no replay is needed.
- **Global rollback** for every flow exercise: edit the value back and Deploy. Or on Laptop 1, stop the server, run
  `git checkout nodered/flows.json` (or restore it from the ZIP), and start the server again.

### Exercise A — occupancy threshold

- **Location:** CONFIG node, On Start (source of the shipped value: `nodered/flows.json`, node "CONFIG (all
  thresholds)").
- **Original:**
  ```js
  occupancy_on_above: 0.25,
  occupancy_off_below: 0.15,
  ```
- **Change:** `occupancy_on_above: 0.50,` (Deploy).
- **Expected result:** a room now needs p ≥ 0.50 to count as occupied. Fewer false ON, more missed occupancy.
  Rehearsed output of `python tools\demo_check.py occupancy`:

  | time | p | before (0.25) | after (0.50) |
  |---|---|---|---|
  | 09:10 | 0.30 | light ON, AC COMFORT | light OFF, AC ECO |
  | 09:15 | 0.45 | ON / COMFORT | OFF / OFF (empty 30 min) |
  | 09:20 | 0.55 | ON / COMFORT | ON / COMFORT |

- **Verification:**
  1. `python tools\demo_check.py occupancy`: the CONFIG line prints `occupancy_on_above: 0.50`.
  2. `python -m pytest -q tests\test_rules.py` now shows **1 failed**:
     `test_empty_room_needs_0_25_to_become_occupied`. That is expected, because the test pins the validated value.
     It shows the tests protect the tuned threshold.
- **Explain:** 0.25/0.15 were chosen on the **validation** dates (`results/threshold_tuning_validation.csv`), never
  on test.
- **Rollback:** set `0.25` again, Deploy, then confirm with `pytest tests\test_rules.py` → all pass. Rehearsed:
  `14 passed`.

### Exercise B — AC comfort threshold

- **Location:** CONFIG node, On Start.
- **Original:**
  ```js
  comfort_setpoint_c: 24.0,
  boost_above_comfort_c: 1.5,
  ```
- **Change:** `boost_above_comfort_c: 0.5,` (Deploy).
- **Expected result:** BOOST starts at 24.5 °C instead of 25.5 °C, which means more cooling energy and fewer warm
  occupied intervals. Rehearsed `python tools\demo_check.py comfort`:

  | temp | before (1.5) | after (0.5) |
  |---|---|---|
  | 24.8 °C | COMFORT | BOOST, reason "24.8 C > comfort+0.5" |
  | 25.2 °C | COMFORT | BOOST |
  | 25.6 °C | BOOST | BOOST |

- **Verification:** the `demo_check comfort` output; on the dashboard, the next warm occupied reading shows
  `BOOST — set by rules`.
- **Rollback:** set `1.5` again, Deploy.

### Exercise C — hysteresis grace period / minimum hold

- **Location:** CONFIG node, On Start.
- **Original:**
  ```js
  light_off_after_min: 15,      // grace period before lights go OFF and AC goes to ECO
  min_hold_min: 10,
  ```
- **Change:** `light_off_after_min: 5,` and `min_hold_min: 20,` (Deploy).
- **Expected result** (rehearsed `python tools\demo_check.py hold`):

  | scenario | default (grace 15, hold 10) | changed (grace 5, hold 20) |
  |---|---|---|
  | Part 1, rules: room empties at 09:10, light/AC last switched at 09:00 | lights OFF + AC ECO at 09:25 | the 5-min grace wants OFF at 09:15, but the 20-min hold delays it (`[light held: min time]`): OFF at **09:20** |
  | Part 2, DQN flips COMFORT/OFF in an occupied 24.5 °C room | OFF held at 09:05, applied at 09:10 | OFF held at 09:05 and 09:10, applied at **09:20** |

  Switching **up** for an occupied room is never delayed (09:15 COMFORT in Part 2).
- **Explain:** with the default values, the 15-minute grace period is longer than the 10-minute hold, so under the
  rules the hold never binds; it protects against a flip-flopping DQN. It binds in the rules only when the grace
  period is shorter than the hold, which is exactly what this change shows. We found this while rehearsing.
- **Rollback:** set `15` and `10` again, Deploy, then run `pytest tests\test_rules.py tests\test_flow_functions.py`.
  Rehearsed: `32 passed`.

### Exercise D — invalid MQTT message is rejected

- **Location:** validation code in the **Validate reading** function node. Ranges are in CONFIG `ranges`, for
  example `co2_ppm: [300, 5000, true]`. The test publisher is `tools/send_test_message.py`.
- **Original:** no change to code; we inject bad input. An optional code variant is shown at the end.
- **Run** (on Laptop 2, which uses the node account):
  ```powershell
  python tools\send_test_message.py bad_json
  python tools\send_test_message.py out_of_range
  python tools\send_test_message.py missing_field
  python tools\send_test_message.py unknown_room
  python tools\send_test_message.py duplicate
  python tools\send_test_message.py valid
  ```
- **Expected result** (rehearsed, alerts table / SQLite `alerts`):
  ```text
  INVALID_READING  payload is not valid JSON
  INVALID_READING  2021-12-13T10:58:41+08:00: co2_ppm=99999 is outside 300..5000
  INVALID_READING  2021-12-13T10:58:44+08:00: temperature_c is missing
  INVALID_READING  unknown room "room9"
  ```
  The duplicate pair stores **one** row only. The valid message is stored, predicted, decided and acknowledged.
- **Verification:** the dashboard Alerts table and pop-up. On Laptop 1:
  `python -c "import sqlite3;print(*sqlite3.connect('storage/smartclass.db').execute('SELECT ts,room_id,type,message FROM alerts ORDER BY id DESC LIMIT 5'),sep='\n')"`
- **Code variant (rehearsed, `EVIDENCE/terminal/exercise_D_code_variant.txt`):** in CONFIG `ranges`, change `co2_ppm: [300, 5000, true]` to
  `co2_ppm: [300, 700, true]` and Deploy. `send_test_message.py valid` sends 750 ppm, so it is now rejected
  with `co2_ppm=750 is outside 300..700`. Rollback: restore `5000`, Deploy.
- **Rollback:** nothing to undo. The test rows use dataset dates (13 Dec 2021) and are marked
  `source = demo_test_message`.

### Exercise E — DQN reward weight (comfort vs energy)

- **Location:** `smartclass/room_env.py`
  ```python
  @dataclass
  class RewardWeights:
      cop: float = 3.5            # converts thermal cooling kWh to electrical-equivalent kWh FOR THE REWARD ONLY
      comfort_per_k: float = 0.5  # penalty per K outside the comfort band per occupied step
      co2_per_100ppm: float = 0.3
  ```
  The reward per 5-minute step is −(cooling kWh / COP + fan kWh) − comfort_per_k × K outside 23–26 °C −
  co2_per_100ppm × (CO₂ − 1000)/100. The comfort and CO₂ terms apply only while occupied.
- **Change:** the comfort weight 0.5 → 2.0. Live, use the command-line flag; it does not edit the file and does not
  touch the deployed `models/dqn_controller.pt`:
  ```powershell
  python tools\dqn_reward_experiment.py --comfort-per-k 0.5
  python tools\dqn_reward_experiment.py --comfort-per-k 2.0
  ```
  Each run takes about 80 s on a laptop CPU. To change the default in the file instead, edit `comfort_per_k: float = 2.0`.
- **Expected result** (rehearsed; same shortened protocol for both: 150 episodes, camera-label occupancy, raw policy
  without safety layer, 6 test dates):

  | comfort_per_k | cooling kWh thermal | occupied steps outside 23–26 °C | K·h | AC switches/day |
  |---|---|---|---|---|
  | 0.5 | 115.7 | 26.5 % | 1.30 | 30.8 |
  | 2.0 | 121.6 | 1.7 % | 0.43 | 24.5 |

  A 4× comfort weight costs about 5% more cooling and almost removes the comfort violations. That is the trade-off
  the registered DQN (weight 0.5) got wrong, and it is why `rules` remains the default controller.
- **Verification:** each run appends one row to `results/supplementary/dqn_reward_sweep.csv`. Repeating a weight
  gives the same numbers, because the seeds are fixed.
- **Rollback:** nothing deployed changed. Delete `models/experiments/` and the extra CSV rows if desired. If you
  edited `room_env.py`, run `git checkout smartclass/room_env.py`.
- **Explain honestly:** these numbers come from the simulator with assumed parameters and cannot be compared with
  `results/closed_loop_results.csv`, which uses 400 episodes and out-of-fold LSTM occupancy.

---

## Debugging tips if something goes wrong live

| Symptom on the dashboard | First check |
|---|---|
| nothing updates | Laptop 2 terminal: replay still running? Dashboard "Devices": sensor online? `STALE_TELEMETRY` alert? |
| AC/light commands but no acks | actuator windows open? `NO_ACK` alerts? `stop_node.ps1` + `start_node.ps1` |
| "no model output (fallback active)" | ML service window: error? Restart it with `.\.venv\Scripts\python ml_service.py`; the rules use the timetable meanwhile |
| a Deploy broke the flow | Node-RED debug sidebar (the "any node error" catch node); roll back with `git checkout nodered/flows.json` + restart |

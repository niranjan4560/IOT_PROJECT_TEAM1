# Viva preparation — Smart Classroom Energy Management (Team 1)

Every answer below matches the delivered code and result files. File paths are given so you can open the evidence
during the viva. Numbers come from `models/training_report.json`, `results/*.csv` and
`results/supplementary/*.csv`. If the examiner asks something not covered here, answer from the code and say what
you have *not* verified: that is better than guessing.

**Golden rules for answers:**

1. Say whether a number is **measured** (ROBOD), **predicted** (model), or **simulated** (our simulator or
   counterfactual).
2. Never say "we saved X% energy in the classroom". Say "in simulation" or "on recorded data re-scaled by our
   commands".
3. Two-laptop operation is verified only if the team has run checklist §6 of the deployment guide on two machines.
   Say the date if you did; say "pending" if not.

---

## A. Problem definition and dataset

**1. What problem does the project solve?**
Lights and AC run in empty lecture rooms. We monitor occupancy, temperature, light and energy. We estimate
occupancy with ML and switch lighting and AC accordingly, with pre-cooling when an arrival is likely. The aim is to
cut energy in unoccupied periods without making occupied rooms uncomfortable.

**2. Why ROBOD?**
It is a real, published dataset (Tekler et al., *Building Simulation* 2022) from NUS lecture rooms. It has exactly the
signals the brief asks for: Wi-Fi devices, CO₂, sound, humidity, temperature, illuminance, lighting / plug / fan
electrical energy and chilled-water thermal energy. It also has camera-based occupancy labels as ground truth.

**3. Describe the data.**
Rooms 1 and 2, 8,352 rows × 28 columns each, 5-minute resolution, 29 weekdays (7 Sep–1 Oct and 9–23 Dec 2021).
Timestamps are kept in +08:00. Room 1 is used for training and testing; Room 2 only for cross-room evaluation.

**4. What is the dataset licence?**
We could not verify it: no licence is stated where we obtained the files. So we do **not** redistribute the CSVs.
`download_data.py` downloads them from the official repository and checks the SHA-256 (the exact files our results
come from), the row count and the required columns.

**5. Which fields are measured, and which do you create?**
All sensor and energy columns and the camera labels are measured. Light and AC states do not exist in ROBOD, so all
actuator states are **simulated**. "Controlled energy" is simulated. Predictions are model outputs. See
`docs/DATA_DICTIONARY.md` and the [M]/[P]/[S] tags on the dashboard.

**6. How do you handle missing values?**
Live: a reading with a missing required field is rejected by Node-RED, alerted, and never filled. Offline: features
forward-fill only from the past within a contiguous segment, and those rows are flagged and excluded from training
and scoring.

**7. Why is chilled-water energy never added to electrical energy?**
It is **thermal** kWh (heat removed), not electricity. Adding them would mix units. Converting it would need the
plant's COP, which ROBOD does not provide. We report the two separately everywhere. The DQN reward uses an assumed
COP of 3.5 for the reward only.

## B. Architecture, MQTT, Mosquitto

**8. Walk through the architecture.**
Stage 1 is the IoT node (`run_simulator.py`). Stage 2 is the Mosquitto broker. Stage 3 is the Node-RED flow
(validation, duplicates, watchdog). Stage 4 is SQLite plus Dashboard 2.0. Stage 5 is `ml_service.py` (6 models,
arrival profile, energy forecaster, DQN). Stage 6 is the Node-RED Decision rules node. Stage 7 is
`control/{light,ac}` over MQTT. Stage 8 is `actuator.py`, which applies the command and acknowledges it.

**9. Why MQTT rather than HTTP?**
Publish/subscribe decouples the node and the server. The broker buffers QoS 1 messages, retained messages give a
reconnecting actuator its last command, and the Last Will reports crashed devices. It is lightweight for constrained
IoT nodes.

**10. Which QoS do you use and why?**
QoS 1 (at-least-once) everywhere. A lost command or reading is worse than a duplicate, and duplicates are handled:
telemetry has a UNIQUE(room_id, ts) constraint plus an in-memory duplicate drop, and actuators are idempotent.

**11. Which messages are retained?**
Control commands, acknowledgements and status messages. A restarted actuator immediately gets its last command, and
the dashboard shows the last known actuator state. Telemetry is not retained, because a stale reading must not be
replayed.

**12. What is a Last Will and where is it used?**
A message the broker publishes if a client disconnects without saying goodbye. The ML service, actuators and replay
set `status = offline` (retained). Node-RED turns it into a `DEVICE_OFFLINE` alert.
`test_ml_service_crash_is_reported_by_last_will` kills the ML service with SIGKILL and checks for it.

**13. How is the broker secured?**
- `allow_anonymous false`, with a password file holding salted PBKDF2-SHA512 hashes (`$7$`, written by `mosquitto_passwd`).
- Two roles: `sc_server` (read/write `smartclass/#`) and `sc_node`.
- The ACL lets the node account write only telemetry, status and acknowledgements, and read only control topics. So
  a compromised node cannot command actuators.
- Tested: a wrong password is refused and the node's control publish is dropped (`Denied PUBLISH` in the Mosquitto
  log).

**14. Is MQTT encrypted?**
No: no TLS. It is a LAN prototype. Mitigations: private-profile firewall rules limited to the local subnet, per-role
accounts and ACL. For production we would add TLS on 8883 with certificates.

**15. What happens if the broker goes down?**
Clients reconnect with exponential back-off (1–30 s). The simulator exits with a clear "Cannot reach the MQTT
broker" message if the broker is down at start. The actuator reconnects and executes the next command; this is
tested by restarting the broker in `test_actuator_reconnects_after_broker_restart_and_executes_command`.

**16. How is a wrong IP or password reported?**
`tools/check_setup.py` first tests TCP (it says "unreachable … firewall? correct SC_MQTT_HOST?"), then the MQTT
login (it says "broker answered: Not authorized"). The services log "wrong SC_*_USERNAME / SC_*_PASSWORD".

## C. Node-RED, SQLite, dashboard

**17. What does the Node-RED flow do?**
- 118 nodes, 22 function nodes.
- CONFIG (all thresholds), table creation from `db/schema.sql`, then telemetry validation → SQLite → forward to the
  ML service.
- Analytics → predictions stored → Decision rules → change-only gate → MQTT control + commands table.
- Acknowledgements → actuator_log and command UPSERT.
- Device status, watchdog (stale data, NO_ACK), alerts.
- Model-performance and offline-experiment tables loaded from SQLite.

**18. What does validation check?**
JSON parse; the room must be in `allowed_rooms`; a valid timestamp; every field in CONFIG `ranges` within
[min, max]; required fields present; and duplicate (room, ts) dropped. Each rejection creates an `INVALID_READING`
alert and nothing downstream runs.

**19. Why SQLite?**
The brief allows SQLite or MySQL. SQLite needs no server, is a single file, and suits one writer (Node-RED) plus
occasional readers. It has 8 tables: telemetry, predictions, decisions, commands, actuator_log, alerts,
model_metrics, experiment_results.

**20. What happens if the database is locked?**
Python writers use `busy_timeout = 15 s`, so they wait. The test holds an exclusive lock for 1.5 s and checks that the
write waits and succeeds. If the lock lasts longer than the timeout, an `OperationalError` is raised, so the failure
is visible rather than a silently dropped row. That is also tested.

**21. Why was the model-comparison panel empty before, and how did you fix it?**
Metrics reached SQLite only when `train_models.py` or `init_db.py` ran, and the start scripts ran neither. Now:
- the start scripts run `init_db.py`, which imports `models/training_report.json` and the registered `results/*.csv`
  once per run id;
- the panel reads `model_metrics` with SQL and formats it;
- if the table is empty, it says "run python init_db.py, then press Reload" instead of showing blank or zero values.

Nothing is hard-coded; a test feeds the formatter real SQLite rows.

**22. How does the dashboard separate measured, predicted and simulated values?**
Every title and label carries [M], [P] or [S]. Units are in the titles (kWh electrical vs kWh THERMAL, ms, 0–1). A
"Showing" line gives the room, data time and source. The savings text states the data window and number of readings,
and says "n/a" instead of 0% when there is no baseline yet.

**23. The dashboard showed "AC BOOST" while the DQN said "OFF". Was that a bug?**
No. The display was ambiguous. In the default `ac_controller: 'rules'` mode the DQN is **advisory only**, and the
rules chose BOOST because the room was occupied and warmer than 25.5 °C. The decision priority is: manual override >
minimum hold > comfort safety guard > selected controller > missing-model fallback. The payload now carries
`ac_source` and `dqn_status`, so the panel reads "BOOST — set by rules" and "DQN: OFF — advisory only".
`test_displayed_ac_source_matches_the_decision` checks every case.

## D. Python architecture and features

**24. How is the Python code organised?**
`smartclass/` is the library: config, dataset, features, models, DQN, room simulator, registry, predictor, db.
The scripts are `train_models.py`, `run_experiments.py`, `ml_service.py`, `actuator.py`, `run_simulator.py` and
`init_db.py`. `tools/` holds setup, diagnostics and demo helpers. The control logic is **not** duplicated in Python:
`tools/run_rules.js` executes the Decision rules code from `flows.json` for tests and experiments.

**25. Which features do you use?**
- Six sensors (Wi-Fi, CO₂, sound, humidity, temperature, lux) and sine/cosine time of day plus weekday.
- Tabular models also get the Wi-Fi 30-minute mean, CO₂ change over 15 and 55 minutes, the 30-minute maximum sound
  and the 15-minute temperature change.
- Sequence models get the last 12 readings (1 hour) of 9 features.

**26. How do you prevent temporal leakage?**
- Every feature uses only time t or earlier; a test changes future values and checks the features at t are
  unchanged.
- Splits are by whole date, so no day is split between train and test.
- Scalers are fitted on training dates only.
- Camera labels are never inputs.
- The DQN is trained on out-of-fold LSTM probabilities.
- Thresholds were tuned on validation dates.

**27. Why split by date and not randomly by row?**
Consecutive 5-minute rows are almost identical. A random split would put near-copies in train and test and inflate
the scores.

**28. Does the live service compute the same features as training?**
Yes. `LivePredictor` builds the window from the incoming readings with the same functions, and a test compares live
and offline feature values.

## E. Models and evaluation

**29. Which models did you compare?**
- Baseline: majority class.
- Traditional: logistic regression, decision tree (depth 5).
- Ensemble: random forest (200 trees), histogram gradient boosting.
- Deep: LSTM (paper B) and Mamba (paper A adaptation).
- Energy: linear regression, random forest and gradient boosting, against mean and persistence baselines.

**30. Give the main test results.**

| model | test F1 | validation F1 |
|---|---|---|
| Mamba | 0.651 | 0.757 |
| logistic regression | 0.646 | 0.731 |
| LSTM | 0.593 | 0.714 |
| random forest | 0.559 | 0.848 |
| gradient boosting | 0.556 | 0.819 |
| decision tree | 0.544 | 0.760 |
| majority class | 0.000 | 0.000 |

**31. Why is the random forest primary if Mamba is better on test?** (expect this one)
We selected the model by **validation** F1 before looking at test. The random forest had the highest validation F1
(0.848) and the best 5-fold-by-date CV F1 (0.73 ± 0.11). Choosing by test F1 afterwards would be test-set selection
and would make the test score optimistic.

We also checked whether the test difference is real. A date-cluster bootstrap on the 6 test dates
(`results/supplementary/bootstrap_ci_paired_vs_primary.csv`) gives Mamba − RF = +0.093 F1, 95% CI [−0.18, +0.38].
Every model's CI against RF includes 0. With 6 test dates, no model is significantly better.

**32. Why a cluster bootstrap over dates?**
Rows within a day are strongly correlated. Resampling rows would pretend we have 1,717 independent samples and give
CIs that are far too narrow. Resampling the 6 dates (2,000 repetitions, seed 42) respects that structure.

**33. Why are some per-date F1 values 0?**
On 2021-09-24 and 2021-12-22, F1 is 0 for every model. Those days have 0 and 1 occupied intervals (out of 288), so
F1 is 0 or undefined; any false ON gives F1 = 0. Two of the six test days therefore carry almost no information about
recall, which is one reason the test F1 values are low and unstable.

**34. Why F1 and not accuracy?**
The room is empty about 80% of the time, so "always empty" gets 0.80 accuracy and is useless. F1 balances precision
(no false ON) and recall (no missed occupancy) on the occupied class.

**35. How do the energy forecasters do?**
For next-5-minute lighting, nothing beats persistence (MAE 0.0022 kWh), because lights rarely change. For chilled
water, gradient boosting and random forest (MAE 0.243 / 0.244 kWh thermal) halve the error of both baselines.

**36. What are the computational costs?**
- Per-reading latency is ≤ ≈ 13 ms for every model on one CPU thread; the random forest is the slowest.
- The random forest is the largest file (4.2 MB); the deep models are 26–77 kB.
- In the live run, all 6 models together took about 38–54 ms per reading.

## F. LSTM, Mamba, research adaptations

**37. What does the LSTM do?**
One LSTM layer with 32 units over a 1-hour window of 9 features; the last hidden state goes to a logit. Trained with
Adam and class-weighted BCE, with early stopping on validation F1. 5,537 parameters.

**38. What did you take from paper B (Hou et al. 2025), and what did you change?**
Taken: an LSTM occupancy estimator feeding a Dueling DQN HVAC controller that saves energy while protecting comfort
and IAQ. Changed:
- our labels come from ROBOD's camera instead of CO₂ change-point labels;
- the input is six sensors instead of CO₂ only;
- the state, actions and reward are our own design, because the paper's exact definitions were not accessible to us;
- the plant is our grey-box simulator.

It is "inspired by", not a reproduction.

**39. What is Mamba?**
A selective state-space model (Gu & Dao 2023). The SSM parameters Δ, B and C depend on the input, so the recurrence
can decide per step what to keep and what to forget. It runs in linear time in the sequence length.

**40. What exactly is your Mamba implementation?**
- A linear embedding to 32 dimensions, then two pre-norm residual Mamba blocks.
- Each block: expand ×2, causal depth-wise convolution (kernel 4), SiLU, input-dependent Δ/B/C (state 8),
  zero-order-hold discretisation, a sequential selective scan, a D skip connection and SiLU gating.
- RMSNorm, then the last step goes to a logit. 17,217 parameters.
- Pure PyTorch, with no CUDA kernel.

**41. Is it OCC-Mamba?**
No. We verified the OCC-Mamba paper record (Qaisar et al., *Building and Environment*, article 114085), but could not
access its full text or code. So we implemented the Mamba mechanism the title names, and do not claim OCC-Mamba's
architecture or results.

**42. Which of A and B worked better here?**
On test F1, A (Mamba, 0.651) beat B's LSTM (0.593). Both deep models are the most precise (Mamba 0.819, LSTM 0.816) but miss about half the occupied intervals. In
the closed loop, the rules performed similarly with either. As question 31 shows, the differences are within the
date-to-date variance.

## G. Decision engine and DQN

**43. Describe the rule-based decision logic.**
- **Occupancy hysteresis:** occupied at p ≥ 0.25, empty only at p < 0.15.
- **Occupied:** light ON (or DIM in Room 2 above 300 lux), AC COMFORT, or BOOST when temp > comfort + 1.5 °C.
- **Empty, first 15 minutes:** keep the last commands.
- **Empty after 15 minutes:** light OFF, AC ECO.
- **Empty after 30 minutes with no arrival expected:** AC OFF.
- **PRECOOL:** when P(arrival in 30 min) ≥ 0.2 and the room is more than 0.5 °C above comfort.
- **Minimum hold:** 10 minutes between downward switches.
- **Start-up:** never switches an empty room ON.
- **Missing model:** hold the last commands, or use the 08–20 timetable.

**44. How were 0.25 / 0.15 chosen?**
On the 4 validation dates (`results/threshold_tuning_validation.csv`): the most comfort-protective pair that still
saves ≥ 30% of lighting. 0.6/0.4 switched lights off in 22.5% of occupied validation intervals; 0.25/0.15 in 13.7%.
The test dates were not used.

**45. What is a Dueling DQN?**
A DQN whose network splits into a state value V(s) and action advantages A(s,a), combined as
Q = V + A − mean(A). It learns which states are valuable even when the action matters little. We use 2×64 ReLU
layers, experience replay (50k), a target network (sync every 1,000 steps), ε-greedy exploration from 1 to 0.05,
γ = 0.97 and Huber loss, over 400 one-day episodes.

**46. What are the state, actions and reward?**
- **State:** LSTM occupancy probability, arrival probability, temperature, CO₂, outdoor temperature, time of day.
- **Actions:** OFF, ECO, COMFORT, BOOST.
- **Reward:** −(cooling kWh / 3.5 + fan kWh) − 0.5 × K outside 23–26 °C − 0.3 × (CO₂ − 1000)/100. The last two
  terms apply only while occupied.

**47. Where does the DQN train? Isn't that unrealistic?**
In a grey-box RC thermal + CO₂ model (`smartclass/room_env.py`) driven by ROBOD's weather and occupant counts. We
first tried to identify the plant from ROBOD, but linear models explained R² ≤ 0.044 of temperature change (cooling is
metered in coarse steps). So the parameters are **assumed** and declared; they were calibrated only to plausible peak
temperature and daily cooling. Absolute energy is indicative; we compare controllers with each other only.

**48. How good is the DQN?**
In simulation over 6 test days:

| controller | cooling (kWh thermal) | occupied steps outside comfort |
|---|---|---|
| always-on | 850.6 | 0% |
| rules + random forest | 405.5 | 0.6% |
| raw DQN + LSTM | 128.5 | 24.1% |
| DQN + safety layer + LSTM | 150.9 | 7.0% |

It saves more but tolerates warm rooms, so `rules` is the default and the DQN is optional behind the safety layer.

**49. What is the safety layer?**
Rules that apply even in DQN mode:
- occupied and more than 2 °C above comfort means at least COMFORT;
- manual override always wins;
- the minimum hold time applies;
- stale data means hold;
- no DQN output means rules.

The dashboard shows when the guard overrode the DQN ("overridden by comfort guard (DQN wanted OFF)").

**50. How would you fix the DQN's comfort problem?**
Raise the comfort weight, choosing it on validation dates. With `tools/dqn_reward_experiment.py`, weight 2.0 instead
of 0.5 cut test comfort violations from 26.5% to 1.7% for about 5% more cooling (shortened protocol, simulation).
We would also add a switching penalty and the previous action to the state.

**51. Why not just always use the DQN since it saves more energy?**
Because the saving comes largely from leaving occupied rooms warm. Energy is only half of the objective; the brief
asks to reduce energy **in unoccupied periods**. A controller that violates comfort 24% of the time fails the
problem, so it does not count as an optimisation.

## H. Energy evaluation

**52. How do you compute energy savings?**
Two separate ways, both simulated:
1. **Recorded-energy counterfactual:** the recorded ROBOD energy is scaled by our command (light OFF 0, DIM 0.5;
   AC OFF 0, ECO 0.75).
2. **Closed-loop simulation:** the controller drives the grey-box room.

Neither is a measured saving in a real building.

**53. What are the headline numbers?**
Room 1 test dates, rules + random forest: lighting 38.7% and chilled water 39.5% less than recorded, but lights were
wrongly OFF in 96 of 344 occupied intervals (27.9%). With the camera labels (upper bound): 33.0% and 43.1% with 0
wrong OFFs. Closed loop: 405.5 vs 850.6 kWh thermal for always-on (−52%) with 0.6% comfort violations.

**54. How can the predicted-occupancy saving (38.7%) be larger than the oracle's (33.0%)?**
Because part of it comes from switching off **occupied** rooms (the 27.9% wrong OFFs). Savings above the oracle bound
are a comfort cost, not a real saving. We report saving and comfort cost together.

**55. Is the ECO factor 0.75 justified?**
It is an assumption. The sensitivity analysis shows chilled-water savings change by less than 1.5 points for ECO
between 0.5 and 0.9, because most of the saving comes from AC OFF.

**56. Does pre-cooling work?**
Weakly. The weekday × half-hour arrival profile caught 7 of 47 arrivals on test dates with 158 false alarms. The
feature works as designed, but arrivals in these rooms are not predictable from the timetable alone.

## I. Actuators, acknowledgements, latency

**57. What does the actuator do?**
`actuator.py` (Laptop 2, one process per room) subscribes to `control/{light,ac}`. It validates the command,
simulates the state change and publishes a retained acknowledgement containing state, previous state, accepted,
command_id and `loop_latency_ms`. An unknown command is rejected with `accepted: false`, and Node-RED raises
`ACTUATOR_REJECTED`.

**58. How do you know a command was executed?**
- Each command has a `command_id` and is stored as SENT.
- The matching acknowledgement upserts ACKED or REJECTED with the round-trip time.
- No acknowledgement within 5 s gives NO_ACK and an alert.
- An acknowledgement after the timeout is recorded as ACKED_LATE with a `LATE_ACK` alert (added in this version and
  tested).

**59. How do you measure latency without clock-sync errors?**
Two measures, each on a single clock:
- **Round trip:** command published → acknowledgement received, on the server clock.
- **Loop latency:** telemetry sent → actuator applied, on the node clock (the reading carries `sent_at_ms`).

Neither subtracts timestamps from two machines.

**60. What latency did you measure?**
Live run (v4, same machine via the network interface): 29 commands, 100% acknowledged, round trip median 88 ms
(p95 92), loop median 94 ms (p95 159). On two laptops over Wi-Fi this will be higher; it must be measured with
checklist item 6.10.

## J. Security, deployment, failure handling, limitations

**61. Is the Node-RED editor secure?**
With `SC_EDITOR_PASSWORD` set (generated by `tools/init_env.py`), the editor and admin API require a login; the
bcrypt hash is computed at start, and an unauthenticated request gets HTTP 401. Without a password, the editor only
answers localhost. Session tokens (`.sessions.json`) are git-ignored and excluded from the ZIP.

**62. How are passwords generated and stored?**
`tools/init_env.py` uses `secrets.token_urlsafe(18)` (24 characters, about 144 bits) for the server, node and editor
passwords. It replaces the `change-me` placeholders, writes `.env` with mode 600 where supported, and shows the node
password once on screen for typing on Laptop 2. Mosquitto stores only hashes. `check_setup.py` fails on placeholder
or short passwords.

**63. How does the two-laptop setup work, and what if the Wi-Fi blocks it?**
- Laptop 1 runs the broker, Node-RED and ML; Laptop 2 runs the replay and actuators.
- Laptop 2's `.env` points `SC_MQTT_HOST` at Laptop 1's LAN IP.
- The scripts detect tools, generate credentials, check ports and connectivity, and record PIDs for the stop
  scripts.
- If campus Wi-Fi isolates clients, use a phone hotspot. Never use port forwarding or public exposure.
- Physical two-machine status: pending until checklist §6 is run (state the date if your team did it).

**64. Which failure scenarios are tested?**
Broker unavailable; wrong password; unknown user; ACL violation; broker restart with actuator reconnection; ML
service crash (Last Will); missing model file (fallback to the next model, flagged); DQN missing; missing sensor value
(no probability → timetable fallback); database locked (wait / visible error); invalid JSON, out-of-range values,
missing fields, unknown room; duplicates; stale data; NO_ACK; late acknowledgement; unknown or old acknowledgement;
manual override; dataset tampering; weak credentials. 97 automated tests plus 1 opt-in end-to-end test, all passing
(`FINAL_DELIVERY/TEST_RESULTS/TEST_SUMMARY.md`).

**65. What are the main limitations?**
- 29 dates (6 test), so model rankings are not statistically separable.
- OCC-Mamba is followed only at the model-family level.
- The grey-box plant uses assumed parameters.
- Savings are counterfactual or simulated.
- Wrong lights-OFF while occupied reaches 27.9% on the test dates with the deployed model; a real deployment needs a
  motion sensor or a minimum-lighting fallback.
- No TLS.
- Dataset licence unverified.
- Windows scripts only parse-checked, and two physical laptops not yet verified by us.

**66. What would you do with more time?**
A PIR or motion sensor for the lighting fallback; tuning the DQN reward and switching penalty on validation dates;
more dates or rooms for stable model selection; TLS for MQTT; obtaining the OCC-Mamba full text to align the
architecture; and a real pilot with metered energy.

---

## K. Per-member subsystem sections

> Team allocation. The decision engine, Dueling DQN and energy evaluation (the largest ML-algorithm part) was shared by
> Niranjan N S and Sivadev Smijith. Each member should be able to answer every question in their section *and* open
> the listed files live.

### YALAMARTHI JYOTHI SRI KRISHNA CHAITANYA (AM.SC.U4CSE23370) — IoT node, MQTT broker, two-laptop deployment

- **Owns:** `run_simulator.py`, `actuator.py`, `smartclass/config.py`, `config/mosquitto/*`,
  `tools/make_broker_users.py`, `tools/init_env.py`, `tools/check_setup.py`, `scripts/*.ps1|*.sh`,
  `docs/TWO_LAPTOP_DEPLOYMENT_GUIDE.md`.
- **Must explain:** topics and payloads, QoS 1, retained messages, Last Will, ACL roles, reconnect back-off, the
  firewall rule scope, PID-based stop, port-conflict detection.
- **Likely live task:** show `Denied PUBLISH` for the node account (checklist 6.6); recover from a broker restart.
- **Questions:** 8–16, 57, 59, 62–63.

### SIVADEV SMIJITH (AM.SC.U4CSE23359) — Node-RED integration, SQLite, dashboard

- **Owns:** `nodered/flows.json` (validation, gate, ACK, watchdog, dashboard nodes), `nodered/settings.js`,
  `db/schema.sql`, `init_db.py`, `smartclass/db.py`.
- **Must explain:** the validation rules, the duplicate drop, the change-only gate and command_id, the ACK UPSERT race
  fix, `db_ready`, NO_ACK / LATE_ACK, how panels read SQLite, empty-state handling, the [M]/[P]/[S] tags.
- **Likely live task:** exercise D (invalid message) and the Alerts table; reload the model-performance panel after
  `init_db.py`.
- **Questions:** 17–23, 58, 61.

### PENUMALLU RAM DINESH REDDY (AM.SC.U4CSE23341) — Data, features, traditional and ensemble ML, evaluation

- **Owns:** `smartclass/dataset.py`, `smartclass/features.py`, `smartclass/registry.py`, `train_models.py`,
  `tools/bootstrap_ci.py`, `download_data.py`, `docs/DATA_DICTIONARY.md`.
- **Must explain:** date splits, leakage controls, features, why F1, model selection by validation, bootstrap CIs,
  per-date F1 zeros, energy forecasting versus persistence.
- **Likely live task:** open `results/model_comparison.csv` and `bootstrap_ci_test_f1.csv`; explain why the random
  forest is primary.
- **Questions:** 1–7, 24–36.

### MANISH SHISHIRCHANDRA DORA ALURI (AM.SC.U4CSE23333) — Deep learning and research adaptations (LSTM, Mamba)

- **Owns:** `smartclass/deep_models.py`, `ml_service.py`, `smartclass/predictor.py`.
- **Must explain:** the LSTM and Mamba architectures, the selective scan, parameter counts, early stopping on
  validation, what was adapted versus taken from papers A and B, live inference and the fallback order.
- **Likely live task:** stop the ML service and show the timetable fallback plus the `DEVICE_OFFLINE` alert; restart
  it.
- **Questions:** 37–42.

### NIRANJAN N S (AM.SC.U4CSE23338) and SIVADEV SMIJITH (AM.SC.U4CSE23359) — Decision engine, Dueling DQN, energy and comfort evaluation (shared)

- **Owns:** the Decision rules / CONFIG nodes, `smartclass/dqn.py`, `smartclass/room_env.py`, `run_experiments.py`,
  `tools/run_rules.js`, `tools/demo_check.py`, `tools/dqn_reward_experiment.py`.
- **Must explain:** the priority order, hysteresis tuning, the safety layer, the DQN state/action/reward, the
  grey-box simulator assumptions, counterfactual versus closed loop, savings versus comfort cost.
- **Likely live task:** exercises A, B, C (CONFIG + `demo_check.py`) and E (reward weight).
- **Questions:** 43–56.

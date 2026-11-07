# Changelog

## v4.0 — final completion and evaluator readiness (Nov 2026)

Baseline: v3 delivery, git commit `862406d` and backup `baseline_v3.zip` (SHA-256 `24ee374b…a046`). **No registered
result was changed.** `results/*.csv`, `results/figures/`, `models/` and `models/training_report.json` (runs
`train-20261027-143655` / `exp-20261027-150655`) are byte-identical to v3, except `results/dashboard_screenshot.png`,
which is a new screenshot. New analyses write new files under `results/supplementary/`.

| # | Files changed | Reason | Test(s) | Result |
|---|---|---|---|---|
| 1 | `nodered/flows.json` (Decision rules) | the AC panel showed "BOOST (rules, DQN says OFF)" with no explanation. Every decision now carries `light_source`, `ac_source`, `dqn_status`; the priority order is documented in the node | `test_rules.py::test_displayed_ac_source_matches_the_decision` | pass |
| 2 | `flows.json` (dashboard) | the model-comparison panel was empty on a fresh DB. It now reads `model_metrics` through a format function with an empty state and separates validation (selection) from test; new groups for occupancy, recorded energy, comfort, latency, offline results; every title has units, [M]/[P]/[S], room/time/source | `test_flow_functions.py::test_model_comparison_*`, `test_offline_results_panel_*` | pass |
| 3 | `flows.json` (savings) | "0.0%" was shown with no baseline. Now `n/a (…)`; live comfort counters (light OFF / AC ECO-OFF while camera says occupied) | `test_savings_never_shows_misleading_zero_percent`, `test_savings_and_comfort_counters` | pass |
| 4 | `flows.json` (ACK, watchdog) | latency chart output; delivery rate as N/N; **late acknowledgements after NO_ACK were ignored** and are now `ACKED_LATE` + `LATE_ACK` alert; `db/schema.sql` comment | `test_late_ack_after_no_ack_is_recorded_as_acked_late`, `test_ack_closes_pending_command_and_records_latency` | pass |
| 5 | `flows.json` (gate) | **bug:** two decisions in the same millisecond produced the same `command_id` (an intermittent test failure exposed it); a sequence suffix was added | `test_gate_publishes_only_changes_with_command_ids` (3 repeated runs) | pass |
| 6 | `smartclass/db.py`, `init_db.py`, `run_experiments.py` | `init_db.py` also imports the registered `results/*.csv` (read-only, once per run id) into `experiment_results`; shared `experiment_rows()` | `test_offline_results_panel_*` | pass |
| 7 | `nodered/settings.js`, `.env.example` | Node-RED editor had no login. Now `adminAuth` from `SC_EDITOR_PASSWORD` (bcrypt at start); without a password, editor/admin API answer localhost only | manual: `curl /flows` → 401; editor screenshot after login | manually verified |
| 8 | `tools/init_env.py` (new), setup scripts | credentials were `change-me` placeholders. Now generated with `secrets` (24 chars); `check_setup.py` fails on placeholders/short passwords and checks editor password + dataset hash | `test_init_env_*` | pass |
| 9 | `scripts/stop_server.*`, `stop_node.*`, `common.ps1` (new); `lib.sh`, `setup_*`, `start_*` | no stop scripts; no 1880 check; no tool detection. Now PID files, port-conflict detection naming the process, Python/Node/Mosquitto detection, TCP check from the node, `init_db.py` before Node-RED; stop waits for exit (**bug:** a quick restart hit the port check) | `test_scripts.py` (bash -n, PowerShell 7.4 parser, helpers), manual stop/start | pass |
| 10 | `download_data.py` | no integrity check. SHA-256 + row count + 18 required columns + manifest; `--verify`, `--allow-changed-data` | `test_dataset_integrity_detects_tampering_and_schema_errors` | pass |
| 11 | `tests/test_failures.py` (new, 19 tests) | missing failure scenarios: broker down, wrong credentials, ACL, broker restart + actuator reconnect, ML crash (Last Will), missing model / DQN / sensor, DB locked, late / unknown / bad ACK, credentials, dataset | the file itself | 19 pass |
| 12 | `tools/bootstrap_ci.py`, `tools/plot_bootstrap_ci.py` (new) | test metrics had no uncertainty. Date-cluster bootstrap (2,000×, seed 42); recomputes and asserts the registered test F1 first | run output | written to `results/supplementary/` |
| 13 | `tools/dqn_reward_experiment.py` (new) | live exercise E. Retrains a DQN with a chosen comfort weight in a separate file; never touches `models/dqn_controller.pt` | run twice for 0.5 → identical | deterministic |
| 14 | `tools/demo_check.py`, `tools/send_test_message.py` (new) | live exercises A–D verification | rehearsed via an authenticated Deploy | outputs in `EVIDENCE/terminal/` |
| 15 | `tools/closed_loop_report.py` | `--out` so a new live report does not overwrite the registered one | manual | ok |
| 16 | `.gitignore` | `nodered/.sessions.json` (editor tokens, created once the login was enabled) had been committed in a v4 working commit; untracked, ignored, never shipped | `git ls-files nodered` | ok |
| 17 | `docs/FINAL_PROJECT_REPORT.md/.pdf`, `TWO_LAPTOP_DEPLOYMENT_GUIDE.md`, `LIVE_DEMONSTRATION_SCRIPT.md`, `VIVA_PREPARATION.md`, `docs/images/`, README | final documentation; v3 report and matrix moved to `docs/archive/` | content checked against result files | – |

**Not done / not verifiable here:**

- two physical laptops;
- Windows-only cmdlets (`Get-NetTCPConnection`, `Test-NetConnection`, `taskkill`, firewall);
- the dataset licence;
- physical actuators.

## v3.0 — final submission (27 Oct 2026)

Compared with v2 (`Smart-Classroom-Energy-Management-fixed.zip`). Everything that still worked was kept: the
ROBOD replay, the Node-RED validation/rules/gate, SQLite, Dashboard 2.0, the separate actuator, the arrival
profile and the rule-runner idea.

### Architecture and deployment
- **Two-laptop layout.** Laptop 1 runs broker, Node-RED, SQLite, ML service and dashboard; Laptop 2 runs the replay
  and actuators. New `.env` configuration (`.env.example`), with no hard-coded IPs, paths or credentials.
- **Secured broker** (`config/mosquitto/`): `allow_anonymous false`, a password per role and an ACL. The node account
  can only publish telemetry, status and acks, and read control topics.
- **Node-RED** reads broker credentials and the DB path from `.env` (`settings.js` writes the git-ignored
  `flows_cred.json`).
- **Launch scripts** for Windows (`scripts/*.ps1`) and Linux/macOS (`scripts/*.sh`): setup, start server, start node,
  loopback, and firewall rules (Private profile, local subnet).
- **Tools:** `tools/check_setup.py` (start-up checks, including the broker login), `tools/show_ip.py`,
  `tools/make_broker_users.py`, `tools/closed_loop_report.py`.
- **MQTT clients** reconnect automatically (1–30 s back-off) and give clear errors for a wrong IP or password.
- Removed `run_demo.*` (replaced by `scripts/`) and the root `mosquitto.conf` (now `config/mosquitto/mosquitto.conf`).

### Stage 5 — analytics and ML
- **Three model categories:**
  - traditional: logistic regression, decision tree, linear regression;
  - ensemble: random forest, histogram gradient boosting;
  - deep learning: LSTM, Mamba, Dueling DQN.
- **Research algorithm A:** Mamba selective-SSM occupancy model (OCC-Mamba family) in plain PyTorch
  (`smartclass/deep_models.py`).
- **Research algorithm B:** LSTM occupancy estimator plus Dueling DQN HVAC controller (`smartclass/dqn.py`), trained
  in a documented grey-box room simulator (`smartclass/room_env.py`). ROBOD cannot identify a room model
  (R² ≤ 0.044, wrong-signed cooling); this is reported.
- **New measured inputs:** CO₂, sound and humidity, plus past-only derived features over a 1-hour window. Camera
  labels are never inputs.
- **Splits:** train 19 / validation 4 / test 6 dates; preprocessing fitted on training data only; fixed seeds;
  identical results across runs.
- **Evaluation:** accuracy/precision/recall/F1/confusion matrix, 5-fold-by-date CV, Room 2 cross-room,
  MAE/RMSE/R², baselines, training time, single-reading latency, peak memory, size, parameters.
- **Live service** (`ml_service.py`, `smartclass/predictor.py`): runs all models on every reading. Missing-sensor
  handling, model-load failures and primary-model fallback are all recoverable; a warm-up flag is sent. Inference is
  single-threaded (126 ms → 1–16 ms per model).

### Stages 6–8 — decisions, commands, feedback
- **AC control** by rules (default) or by the Dueling DQN behind a safety layer: comfort guard, override, minimum
  hold, missing-model timetable fallback.
- **Occupancy thresholds** were tuned on the **validation** dates (0.6/0.4 → 0.25/0.15) to reduce wrongly-off lights.
- **Command delivery:** command IDs, a `commands` table (SENT/ACKED/REJECTED/NO_ACK), round-trip (server clock) and
  loop latency (node clock), and a NO_ACK watchdog.
- **Actuator node:** separate simulated light and AC devices, echoing `command_id` and measuring the loop latency.
- **Fixed in testing:**
  - a SQLite INSERT/UPDATE race (acknowledgements now UPSERT);
  - retained acks arriving before the tables exist (`db_ready` flag);
  - the start-up occupancy threshold.

### Database and dashboard
- `db/schema.sql` is the single schema (8 tables: + predictions, commands, model_metrics, experiment_results). The
  Node-RED create-tables node is generated from it, a test checks they match, and `init_db.py` applies it and imports
  training metrics.
- **Dashboard:** live predictions of all models, a model-comparison table from SQLite, CO₂/sound/humidity, camera
  count, command-delivery health, ML latency, and [M]/[D]/[P]/[S] labels on every panel.

### Experiments, tests, documentation
- `run_experiments.py` replaces `savings_experiment.py`. It contains:
  - validation threshold tuning;
  - the recorded-energy counterfactual (7 occupancy sources × 2 controllers × ECO/DIM sensitivity × 3 loads);
  - the closed-loop simulation (14 controllers);
  - figures;
  - SQLite rows.
- **61 automated tests** (pytest) across 12 areas, including a real end-to-end loopback test.
- **Documentation:** `docs/TECHNICAL_REPORT.md/.pdf`, `docs/architecture.svg/.png`, `docs/DATA_DICTIONARY.md`,
  `docs/ACCEPTANCE_MATRIX.md`, and a rewritten README.
- **Requirements** split into `requirements.txt` (server) and `requirements-node.txt` (node, no ML libraries), with
  every version pinned. SciPy is pinned to remove the `OptimizeWarning` seen with scikit-learn 1.6.1.

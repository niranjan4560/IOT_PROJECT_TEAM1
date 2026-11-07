# Acceptance matrix

Environment of the runs below: Linux, 2 vCPU, Python 3.13.17, Node.js 22.23, Node-RED 4.1.17, Mosquitto 2.0.18
(27 Oct 2026). **PASS** = executed and checked; **NOT VERIFIED** = could not be executed here (reason and manual
procedure given). "pytest" refers to `python -m pytest -q`: 60 passed, plus 1 end-to-end test with `SC_E2E=1`.

| # | Requirement | Implementation | Test performed | Result | Evidence / reason |
|---|---|---|---|---|---|
| 1 | Stage 1: ROBOD replay, timestamped JSON telemetry | `run_simulator.py` | `test_telemetry_payload_is_strict_json`; live replays | PASS | 288 rows/day stored; nulls instead of NaN; `sent_at_ms` present |
| 2 | Measured vs simulated labelled | `docs/DATA_DICTIONARY.md`, `db/schema.sql`, dashboard [M]/[D]/[P]/[S] | `test_every_field_has_unit_and_kind`; dashboard screenshot | PASS | every ROBOD field has unit + kind |
| 3 | Stage 2: Mosquitto, auth, ACL, QoS, retained, Last Will | `config/mosquitto/*`, `tools/make_broker_users.py`, `smartclass/config.py` | manual ACL test; `test_broker_is_not_anonymous_and_acl_limits_the_node`; e2e | PASS | node publish to control dropped; wrong password and anonymous refused |
| 4 | Reconnection | `make_client` (1–30 s back-off), retained commands | code review; restarts during testing | PARTIAL | clients reconnected after Node-RED/broker restarts in our runs; no scripted network-drop test |
| 5 | Stage 3: Node-RED parse, validate, duplicates, errors | `nodered/flows.json` | `test_flow_functions.py` (9 tests); catch node | PASS | invalid JSON, timestamp, range, missing field, unknown room, duplicate |
| 6 | Stage 4: SQLite schema + init + persistence | `db/schema.sql`, `init_db.py`, flow | `test_schema_creates_tables_and_unique_constraint`; `test_flow_schema_matches_schema_sql`; e2e | PASS | 8 tables; UNIQUE(room, ts); idempotent |
| 7 | Stage 4: Dashboard (occupancy, count, temp, lux, energy, predictions, comparison, states, trends, alerts, reasons, override, health) | Dashboard 2.0 in `flows.json` | `test_dashboard_widgets_present`; headless-browser render; override clicked in the browser | PASS | `results/dashboard_screenshot.png`, 0 page errors; override: 15 decisions `MANUAL OVERRIDE`, actuators ON/BOOST then back to OFF/OFF |
| 8 | Stage 5: traditional, ensemble and deep models | `smartclass/registry.py`, `deep_models.py` | `test_every_category_trains_and_predicts` | PASS | all 4 categories (incl. baseline) train and predict |
| 9 | Research algorithm A implemented and integrated | `MambaOccupancy`; live in `ml_service.py` | save/load and seeding tests; live predictions table | PASS (adaptation) | OCC-Mamba internals not accessible; Mamba family per Gu & Dao |
| 10 | Research algorithm B implemented and integrated | `LSTMOccupancy`, `dqn.py`, `room_env.py`; DQN recommendation in analytics; `ac_controller: 'dqn'` | `test_dueling_head_and_environment`; `test_dqn_mode_uses_recommendation_but_keeps_safety`; closed-loop experiment | PASS (adaptation) | state/action/reward and simulator are ours |
| 11 | Predictive metrics + baselines | `train_models.py` | `test_training_report_complete_and_consistent` | PASS | `models/training_report.json`, `results/model_comparison.csv` |
| 12 | Computational metrics | `smartclass/perf.py` | same test | PASS | train s, median/p95 ms, peak MB, kB, params |
| 13 | Closed-loop metrics (latency, ack rate, switching, energy, comfort) | `tools/closed_loop_report.py`, `run_experiments.py` | live run + e2e assertions | PASS | 46/46 acked; round trip median 88 ms; loop median 96 ms |
| 14 | No temporal leakage; whole-day splits; seeds | `features.py`, `dataset.split_dates` | `test_features_use_no_future_information`; `test_split_is_by_whole_date_and_reproducible`; `test_deep_training_is_seeded` | PASS | two full runs gave identical reports and results |
| 15 | Missing values not silently valid | `features.py`, flow validation | `test_missing_values_are_not_silently_filled`; validation tests | PASS | flagged rows excluded; INVALID_READING alerts |
| 16 | Stage 6: hysteresis, minimum hold, temperature constraints, missing-data safeguard, override, stale-data hold | "Decision rules" + watchdog | `tests/test_rules.py` (13); stale test | PASS | |
| 17 | Deterministic and safe when models fail | `predictor.py` fallback, decision fallback | `test_live_predictor_runs_all_models_and_falls_back`; `test_missing_model_output_uses_safe_timetable_then_holds` | PASS | |
| 18 | Stage 7: commands with IDs, timestamps, reasons, delivery status, latency | gate/ack/watchdog nodes, `commands` table | gate/ack/NO_ACK tests; e2e | PASS | |
| 19 | Stage 8: actuators change state and acknowledge | `actuator.py` | `test_messages_actuator.py` (4); e2e | PASS | light and AC are separate devices; invalid commands rejected |
| 20 | Energy experiment: per-load, valid denominators, comfort, sensitivity, simulated label | `run_experiments.py` | executed (deterministic, run twice) | PASS | `results/savings_*.csv`, `closed_loop_results.csv`, figures |
| 21 | Server/node configuration and start-up checks | `.env.example`, `tools/check_setup.py`, scripts | `test_config_flows.py` (13); check_setup against LAN IP | PASS | `PASS MQTT login as sc_node at 192.0.2.2:1883` |
| 22 | Node via LAN IP (not localhost) | `.env` `SC_MQTT_HOST` | node clients run against eth0 192.0.2.2 | PASS | broker log: `New client connected from 192.0.2.2 … u'sc_node'`; dashboard HTTP 200 on LAN IP |
| 23 | Real two-physical-laptop run | scripts + README §2 | — | **NOT VERIFIED** | one machine only; follow README §2 and check the four "proof" points |
| 24 | Windows PowerShell scripts | `scripts/*.ps1` | static review only | **NOT VERIFIED** | no Windows here; run `setup_server.ps1` / `start_server.ps1` / `start_node.ps1` |
| 25 | Linux scripts | `scripts/*.sh` | `bash -n` (test); `run_loopback.sh` start/stop run (see changelog verification) | PASS | |
| 26 | macOS | `scripts/*.sh` | — | NOT VERIFIED | expected to work like Linux (Homebrew Mosquitto) |
| 27 | End-to-end loopback simulation | `tests/test_e2e_loopback.py` | `SC_E2E=1 pytest` | PASS | 60/60 stored and decided; 6 models; 100% ack; latencies recorded |
| 28 | References real; DOIs | `docs/TECHNICAL_REPORT.md` §15 | web lookup (HKUST portal, publisher listing, author homepage, arXiv) | PASS with caveat | OCC-Mamba DOI not resolvable from here; record verified; volume not verified |
| 29 | Dataset licence | README §9 | — | NOT VERIFIED | not stated by ROBOD; ask the faculty |
| 30 | Python 3.11/3.12, Windows wheels | `requirements*.txt` | `pip --dry-run --platform win_amd64` for 3.11–3.13 | PARTIAL | wheels exist; executed only on Linux 3.13 |

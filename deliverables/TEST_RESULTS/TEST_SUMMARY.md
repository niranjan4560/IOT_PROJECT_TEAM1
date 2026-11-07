# Test summary — v4 final

## Result

| Run | Exact command | Passed | Failed | Skipped | Log |
|---|---|---|---|---|---|
| Baseline v3 (before any change) | `.venv/bin/python -m pytest -q` | 60 | 0 | 1 (opt-in e2e) | `test_logs/00_baseline_pytest.log` |
| Baseline v3 end-to-end | `SC_E2E=1 .venv/bin/python -m pytest -q tests/test_e2e_loopback.py` | 1 | 0 | 0 | `test_logs/00_baseline_e2e.log` |
| **Final v4 full suite** | `SC_PWSH=<pwsh 7.4.6> .venv/bin/python -m pytest -v -rs` | **97** | **0** | **1** (opt-in e2e) | `test_logs/40_final_pytest.log` |
| **Final v4 end-to-end** | `SC_E2E=1 .venv/bin/python -m pytest -v tests/test_e2e_loopback.py` | **1** | 0 | 0 | `test_logs/41_final_e2e.log` |
| **Clean room** (unzip of the delivered project ZIP into an empty folder, official dataset download, generated credentials) | see `test_logs/30_cleanroom.log` | 97 + 1 e2e | 0 | 1 | `test_logs/30_cleanroom.log` |

The single skip is `tests/test_e2e_loopback.py` in the plain run: it starts servers, so it is opt-in (`SC_E2E=1`), and
it was run and passed separately. No test was disabled, weakened, or marked passed without being run.

## Environment

| | |
|---|---|
| OS | Linux 6.18 (container), 2 vCPU, CPU only |
| Python | 3.13.17 — numpy 2.2.6, pandas 2.2.3, scikit-learn 1.6.1, torch 2.14.1, paho-mqtt 2.1.0, pytest 8.4.2 |
| Node.js | 22.23.4; node-red 4.1.17, @flowfuse/node-red-dashboard 1.34.0, node-red-node-sqlite 2.0.1 |
| Mosquitto | 2.0.18 |
| PowerShell | 7.4.6 (Linux build), used only to parse `.ps1` files and run their portable helper functions |
| Dataset | ROBOD Room 1/2, SHA-256 verified (`download_data.py --verify` → PASS ×2; clean room downloaded fresh copies, same hashes) |

## Coverage by area (98 collected)

| File | Tests | What is verified |
|---|---|---|
| `test_data_features.py` | 9 | raw schema/size, unit + kind for every field, ordered unique weekday timestamps, missing values not silently filled, whole-date reproducible split, no future information in features, live = offline features, window shape, timestamp rule |
| `test_models_eval.py` | 7 | every model category trains and predicts, deep model save/load, seeded deep training, dueling head + environment, training report complete and consistent, live predictor runs all models and falls back |
| `test_messages_actuator.py` | 4 | strict JSON telemetry, actuator accepts/measures loop latency, rejects invalid commands, light and AC are separate devices |
| `test_flow_functions.py` | 19 | Node-RED validation (valid, invalid/missing values, non-JSON, unknown room, nullable optional fields), duplicates, stale data + recovery, change-only gate with unique command ids, ACK + latency chart, rejected ACK, NO_ACK, schema UNIQUE, **savings never shows a misleading 0%**, **savings + comfort counters**, **model comparison from SQLite rows + selection by validation F1**, **empty state**, **offline experiments panel from SQLite** |
| `test_rules.py` | 14 | start-up safety, AC off after 30 min, COMFORT/BOOST, hysteresis + grace, 0.25 threshold, pre-cool, minimum hold, manual override, missing-model timetable, DQN mode + safety, rules vs DQN parameterised, **displayed ac_source / dqn_status match the decision** |
| `test_config_flows.py` | 13 | flows.json valid and fully wired, topics match the design, dashboard widgets present, flow schema = `db/schema.sql`, no credentials/IPs/paths in flows, pinned packages, settings load `.env`, broker not anonymous + ACL limits the node, `.env` handling, role credentials, start-up checks, launch scripts |
| `test_failures.py` | 19 | see the failure-scenario table below |
| `test_scripts.py` | 12 | setup/start/stop scripts exist for both roles and OSs; `bash -n` for every `.sh`; **real PowerShell parser on every `.ps1`**; PowerShell helpers detect Python/Node, read `.env`, fail with exit 1; firewall rules Private + LocalSubnet only |
| `test_e2e_loopback.py` | 1 (opt-in) | real Mosquitto (auth + ACL) + Node-RED + ML service + actuator + replay of 60 readings: 60 stored and decided, 6 models predicting, 100% of commands ACKED, latencies recorded, loop < 5 s |

## Failure scenarios required by the brief

| Scenario | Test (all in `tests/` unless stated) | Status |
|---|---|---|
| MQTT broker unavailable | `test_failures.py::test_broker_unavailable_gives_clear_message`, `::test_simulator_exits_cleanly_when_broker_down` | AUTOMATED TEST PASSED |
| Wrong credentials | `::test_wrong_password_and_unknown_user_are_refused`, `::test_wrong_password_service_logs_explanation` | AUTOMATED TEST PASSED |
| (extra) ACL violation | `::test_acl_node_cannot_send_control_commands` | AUTOMATED TEST PASSED |
| Invalid telemetry | `test_flow_functions.py::test_invalid_or_missing_values_raise_alerts`, `::test_non_json_and_unknown_room`; live: exercise D (`EVIDENCE/terminal/exercise_D_invalid_messages.txt`) | AUTOMATED TEST PASSED + MANUALLY VERIFIED |
| Missing features | `test_failures.py::test_missing_sensor_value_produces_no_probability`, `::test_no_probability_triggers_timetable_fallback_and_alert` | AUTOMATED TEST PASSED |
| Missing model | `::test_missing_model_file_is_skipped_and_others_load`, `::test_primary_model_missing_falls_back_and_is_flagged` (also DQN missing) | AUTOMATED TEST PASSED |
| ML service unavailable | `::test_ml_service_crash_is_reported_by_last_will` (SIGKILL → retained `offline`); rules fall back (`test_rules.py` missing-model test) | AUTOMATED TEST PASSED |
| Database locked | `::test_database_locked_briefly_write_waits_and_succeeds`, `::test_database_locked_too_long_raises_not_silently_drops` | AUTOMATED TEST PASSED |
| Duplicate messages | `test_flow_functions.py::test_duplicates_are_dropped`, schema UNIQUE test; live: `send_test_message.py duplicate` stored once | AUTOMATED TEST PASSED + MANUALLY VERIFIED |
| Stale readings | `test_flow_functions.py::test_stale_telemetry_alert_and_recovery`; live: STALE_TELEMETRY / TELEMETRY_RESUMED alerts | AUTOMATED TEST PASSED + MANUALLY VERIFIED |
| Actuator disconnected | `test_flow_functions.py::test_missing_ack_becomes_no_ack`; `test_failures.py::test_actuator_reconnects_after_broker_restart_and_executes_command` | AUTOMATED TEST PASSED |
| Delayed acknowledgement | `test_failures.py::test_late_ack_after_no_ack_is_recorded_as_acked_late`; `::test_unknown_or_retained_old_ack_does_not_change_commands`; `::test_unreadable_ack_raises_bad_ack` | AUTOMATED TEST PASSED |
| Manual override enabled | `test_rules.py` override test + `::test_displayed_ac_source_matches_the_decision`; live: dashboard override → BOOST acknowledged in 87 ms (`EVIDENCE/dashboard/manual_override.png`) | AUTOMATED TEST PASSED + MANUALLY VERIFIED |
| (extra) weak / placeholder credentials | `::test_init_env_generates_strong_unique_passwords`, `::test_init_env_node_rejects_bad_host_and_short_password` | AUTOMATED TEST PASSED |
| (extra) dataset tampering / schema change | `::test_dataset_integrity_detects_tampering_and_schema_errors` | AUTOMATED TEST PASSED |

## Failures found during v4 and the fixes applied

| Failure | Cause | Fix | Now |
|---|---|---|---|
| `test_ack_closes_pending_command_and_records_latency`: unpack of 5 outputs | the ACK node gained a 6th output (latency chart) | the test now unpacks 6 outputs and **additionally** asserts the chart topics and values | pass |
| `test_gate_publishes_only_changes_with_command_ids`: intermittent, `2 == 3` pending commands | **product bug**: two decisions in the same millisecond produced the same `command_id` | sequence suffix in the gate; the test was left unchanged and passed 3 consecutive runs | pass |
| `test_database_locked_briefly_…`: thread error | test bug: the SQLite connection was used across threads | `check_same_thread=False` in the test's lock-holder connection only | pass |
| `test_offline_results_panel_…`: `NameError ROOT` | missing import in the test | import added | pass |
| restart after `stop_server.sh` → "Port 1880 already in use" (manual) | **product bug**: the stop script returned before Node-RED had exited (MQTT close takes about 15 s) | stop waits up to 20 s per process, then forces | verified manually (`EVIDENCE/terminal/stop_server.txt`) |
| exercise A: `test_empty_room_needs_0_25_to_become_occupied` fails after setting 0.50 | **expected**: the test pins the validated threshold | rollback restores it; documented in the demo script | pass after rollback |

## Remaining limitations of the testing

- **Windows:** the `.ps1` scripts were parsed with the real PowerShell 7.4 parser, and their portable helper
  functions were executed. Windows-only cmdlets (`Get-NetTCPConnection`, `Test-NetConnection`, `taskkill`,
  `New-NetFirewallRule`, `Get-NetConnectionProfile`) were **not executed**.
- **Two physical laptops: NOT VERIFIED.** All network tests used one machine (loopback, and in v3 also the machine's
  own network interface). The 15-item two-machine checklist is in `DOCUMENTATION/TWO_LAPTOP_DEPLOYMENT_GUIDE.md` §6.
- **Physical actuators:** none; actuators are simulated.
- **Python 3.11/3.12 and macOS:** not executed.
- The e2e test replays 60 readings, not a full day. The full-day replay was run manually
  (`EVIDENCE/energy_results/live_run_v4_report.json`).
- **Dashboard rendering:** checked by screenshots (`EVIDENCE/dashboard/`); there is no automated browser test. The
  data functions behind the panels are unit-tested.

# Initial audit — Smart Classroom Energy Management (baseline v3)

**Audited:** `Smart-Classroom-Energy-Management-final.zip`, as delivered on 27 Oct 2026. The "(2)" copies named in
the brief were not attached to this session. The last delivered ZIP is the same project and was used as the baseline.
**Instructor document:** `Projects_v4.docx` (original upload).

**Backup:** `backup/baseline_v3.zip` (SHA-256 `24ee374b…a046`) and git commit `862406d` ("Baseline: v3 final delivery
(unchanged)").

**Environment:** Linux, 2 vCPU, Python 3.13.17, Node.js 22.23.4, Mosquitto 2.0.18. No Windows, no second machine.

**Baseline tests (`TEST_RESULTS/test_logs/00_baseline_*.log`):** `pytest` gave 60 passed, 1 skipped (the opt-in e2e
test); `SC_E2E=1 pytest tests/test_e2e_loopback.py` gave 1 passed.

## 1. Existing architecture

Stage 1, Laptop 2: `run_simulator.py` (ROBOD replay) and `actuator.py` (light + AC simulated devices) →
Stage 2: Mosquitto with password file + ACL →
Stage 3: Node-RED `flows.json` (validation, duplicates, watchdog) →
Stage 4: SQLite (`db/schema.sql`, 8 tables) + Node-RED Dashboard 2.0 →
Stage 5: `ml_service.py` (6 occupancy models, arrival profile, energy forecaster, DQN recommendation) →
Stage 6: Node-RED "Decision rules" (rules or DQN + safety layer) →
Stage 7: `control/{light,ac}` with command IDs →
Stage 8: actuator acknowledgements with latency.

This matches the instructor's chain: dataset → MQTT → Node-RED → DB → Dashboard → ML → Decision → MQTT → actuators.

## 2. Requirement compliance matrix (instructor document)

| Requirement (Projects_v4.docx) | Implementation location | Initial status | Required action | Verification evidence |
|---|---|---|---|---|
| IoT node generating data (real-world dataset / Python simulator) | `run_simulator.py`, `download_data.py` | Working | Add dataset integrity check (SHA-256, schema) | test_data_features (9 tests) |
| MQTT for communication | `config/mosquitto/`, `smartclass/config.py` | Working | Add failure tests (broker down, wrong password, reconnect) | e2e test; manual ACL test (v3) |
| Node-RED for integration and automation | `nodered/flows.json` | Working | Clearer AC decision display; label groups | flow tests (11) |
| Database: SQLite or MySQL | `db/schema.sql`, Node-RED sqlite nodes, `smartclass/db.py` | Working | Add indexes; test DB-locked behaviour | schema test |
| Node-RED Dashboard for visualisation | Dashboard 2.0 in `flows.json` | Partly: comparison panel empty in the shipped screenshot; no comfort-violation panel; no latency chart; time range / room / source not stated | Fix comparison (auto-import + empty-state message); add missing panels | screenshot |
| Machine-learning analytics | `train_models.py`, `smartclass/*` | Working | Add confidence intervals; document primary-model selection | report, tests |
| Decision and automation → MQTT → actuators | Decision rules, gate, `actuator.py` | Working; ambiguous display | Make the applied controller and priority explicit | rule tests (12) |
| Team 1: monitor occupancy, temperature, ambient light, electrical power | telemetry + dashboard | Working | — | screenshot |
| Team 1: estimate occupancy / unoccupied periods and energy demand | occupancy models; energy forecaster | Working | — | training report |
| Team 1: control lighting and AC from analytics; reduce energy when unoccupied; prepare before occupancy | rules (OFF/ECO/OFF-after-30, PRECOOL) | Working; pre-cool weak (documented) | Keep; explain honestly | experiments |
| Evaluation: individual viva | — | Missing preparation material | VIVA_PREPARATION.md (≥ 60 Q&A, per member) | — |
| Evaluation: live modification / debugging | CONFIG node, tests | Partly (README only) | LIVE_DEMONSTRATION_SCRIPT.md with ≥ 5 rehearsed exercises; DQN reward-weight tool | — |
| Evaluation: meaningful advanced features | 2 research methods, DQN safety layer, delivery tracking, experiments | Present | Make visible in dashboard / report / PPT | — |
| Dataset confirmed with faculty by 9 Oct 2026 | proposal PDF | Unknown (team action) | Record in the report | — |
| Report and PPT (from this brief, not the docx) | `docs/TECHNICAL_REPORT.*` | Report has 15 sections; no PPT | 34-section final report + PDF; 15–18 slide PPTX | — |

## 3. Working features (verified by baseline tests)

Replay; validation (invalid JSON, timestamps, ranges, missing fields, unknown room); duplicate drop (memory + UNIQUE);
the stale-data watchdog; six models live with fallback; the DQN recommendation; rules with hysteresis, minimum hold,
pre-cool, AC-off, start-up safety, manual override and missing-model timetable; command IDs; ACK upsert; NO_ACK;
latency measurement; Dashboard 2.0; the experiments; the e2e loop with 100% acknowledgements.

## 4. Incomplete features

1. No `stop_server` / `stop_node` scripts (Windows or Linux), and no PID tracking.
2. No credential generation: `.env.example` ships `change-me-*`; the setup scripts only warn.
3. Port-conflict detection covers 1883 only, not 1880.
4. The dataset downloader has no integrity check or schema verification.
5. Dashboard gaps:
   - no live comfort-violation panel;
   - no end-to-end latency trend;
   - delivery rate is text only;
   - no room / time-range / data-source header;
   - validation vs test metrics not separated in the comparison table;
   - the savings text shows "0.0%" when the baseline is 0 (misleading zero).
6. Test metrics have no confidence intervals.
7. No tool to retrain the DQN with a different reward weight for live-modification demos.
8. Missing failure-scenario tests: broker unavailable, wrong credentials, missing model file, database locked,
   delayed acknowledgement, actuator disconnected with reconnection.

## 5. Broken / misleading features

1. **Model comparison panel empty** in the shipped screenshot. Cause: metrics only reach SQLite through
   `train_models.py` or `init_db.py`, and the start scripts call neither. A fresh or deleted database shows a blank
   table with no explanation.
2. **AC display ambiguity.** The panel shows "AC command: BOOST (rules, DQN says OFF)". In the default
   `ac_controller: 'rules'` mode, the DQN is advisory only, but the panel reads as if the DQN was overridden by error.
   The actual priority (override > safety/min-hold > selected controller) is not shown.

## 6. Security issues

- The Node-RED editor has no login, and it listens on 0.0.0.0, so anyone on the LAN can edit the flow.
- No TLS on MQTT (LAN prototype; documented).
- Default example passwords are not forced to change.
- **Good:** password + ACL on the broker; `.env`, passwd and `flows_cred.json` are git-ignored; firewall rules limited
  to the Private profile and the local subnet.

## 7. Dependency and environment issues

- All Python and Node versions are pinned.
- Linux PyPI torch pulls about 3 GB of CUDA libraries (documented; CPU index alternative given).
- The Windows `.ps1` scripts have never been executed: no PowerShell in the v3 environment.
- Mosquitto 2.0.18 here vs 2.1.2 on the team laptop.

## 8. Test coverage

61 tests, covering the dataset, features, models, payloads, actuators, flow functions, rules, configuration and e2e.
Not covered: broker-down / wrong-credential client behaviour, reconnection, missing model files, the SQLite busy
path, delayed ACK after NO_ACK, PowerShell syntax.

## 9. Experimental validity

- Whole-date splits; preprocessing fitted on the training dates only; test dates never used for selection or tuning.
  Thresholds were tuned on the validation dates.
- Two runs and a from-scratch retrain gave identical results.
- **Risks:**
  - The primary model (random forest) was chosen by validation F1 but scores lower on test than Mamba. This must be
    explained, not changed retrospectively.
  - Only 6 test dates, so there is high variance; confidence intervals are needed.
  - Closed-loop energy comes from an assumed grey-box plant.
  - Counterfactual savings with predicted occupancy include wrongly switched-off occupied rooms.

## 10. Documentation gaps

No two-laptop guide separate from the README; no live demonstration script; no viva preparation; no PPT; the report
lacks title page, scope, hardware/software requirements, testing, team contributions and reproduction sections.

## 11. Deployment gaps

Two physical laptops: never executed. Windows scripts: never executed. There are no stop scripts, and nothing
generates node/server credentials.

## 12. Mark-deduction risks (highest first)

1. An empty dashboard panel during the demo (§5.1).
2. Examiner asks "why does AC say BOOST when the DQN says OFF?" (§5.2).
3. Two-laptop demo failure on venue Wi-Fi (client isolation, firewall, wrong IP).
4. "Why is your primary model not the best on test?" asked without a prepared answer.
5. Claiming energy savings without simulation caveats.
6. The editor being modifiable by anyone on the LAN.
7. No PPT, no viva preparation.

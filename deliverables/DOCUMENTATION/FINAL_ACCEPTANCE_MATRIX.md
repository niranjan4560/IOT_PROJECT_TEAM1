# Final acceptance matrix — v4

**Status words:**

- IMPLEMENTED — the code exists.
- TEST PASSED — automated test passing.
- MANUALLY VERIFIED — run and inspected by us.
- PHYSICALLY VERIFIED — two machines or real hardware.
- NOT VERIFIED.
- NOT APPLICABLE.

All evidence paths are relative to `FINAL_DELIVERY/` or to the project root. Test status refers to the final run:
97 passed, 0 failed, 1 opt-in skipped, plus 1 end-to-end passed, repeated in a clean room.

## A. Instructor requirements (Projects_v4.docx)

| Requirement | Implementation | Evidence | Test status | Remaining issue |
|---|---|---|---|---|
| IoT node generating data (real dataset / simulator) | `run_simulator.py` replays ROBOD; `download_data.py` with SHA-256 + schema | `EVIDENCE/terminal/start_node.txt`; `test_logs/30_cleanroom.log` (fresh download, hashes match) | TEST PASSED, MANUALLY VERIFIED | licence unverified, so the CSVs are not shipped |
| MQTT communication | Mosquitto with passwords + ACL, QoS 1, retained commands/acks, Last Will | `test_failures.py` (8 broker tests), e2e | TEST PASSED | no TLS (LAN prototype) |
| Node-RED integration and automation | `nodered/flows.json` (118 nodes) | `EVIDENCE/node_red/editor_flow*.png`; `test_flow_functions.py`, `test_config_flows.py` | TEST PASSED | – |
| Database (SQLite/MySQL) | SQLite, 8 tables, `db/schema.sql` | `test_config_flows.py::test_flow_schema_matches_schema_sql`, DB-locked tests | TEST PASSED | – |
| Node-RED Dashboard | Dashboard 2.0; all 20 required panels; data from runtime and SQLite | `EVIDENCE/dashboard/dashboard_full.png`, `manual_override.png`; report §13 | TEST PASSED (panel data functions), MANUALLY VERIFIED (render) | no automated browser test |
| Machine-learning analytics | 7 occupancy models (3 categories + baseline), energy forecaster, arrival profile, DQN | `results/model_comparison.csv`, `results/supplementary/bootstrap_ci_*.csv` | TEST PASSED | small test set (6 dates) |
| Decision → MQTT → actuators | Decision rules (+ DQN behind a safety layer), gate, `actuator.py`, acknowledgements | `live_run_v4_report.json` (29/29 ACKED); e2e | TEST PASSED, MANUALLY VERIFIED | actuators simulated (no physical relay) |
| Team 1: monitor occupancy, temperature, light, electrical power | telemetry → dashboard [M] | dashboard screenshot | MANUALLY VERIFIED | – |
| Team 1: estimate occupied/unoccupied periods and energy demand | occupancy models; energy forecasting vs baselines | report §23 | TEST PASSED | pre-cooling arrival profile weak (F1 0.066), reported |
| Team 1: control lighting and AC; reduce energy when unoccupied; prepare before occupancy | rules (OFF/ECO/OFF-30/PRECOOL), DQN option | `results/closed_loop_results.csv`, `savings_*.csv` | TEST PASSED (rules) | savings simulated only |

## B. Six evaluation categories

| # | Category | Implementation | Evidence | Test status | Remaining issue | Readiness |
|---|---|---|---|---|---|---|
| 1 | Individual viva | `DOCUMENTATION/VIVA_PREPARATION.md`: 66 Q&A checked against the code and results, including hard questions (RF vs Mamba, leakage, DQN comfort, savings above the oracle); per-member sections with files and live tasks | the document | NOT APPLICABLE | names and the team's actual work split are filled in; each member must study their section | **85%** |
| 2 | Live feature demonstration | `LIVE_DEMONSTRATION_SCRIPT.md` part 1 (13 steps), start/stop scripts, dashboard | rehearsed full-day replay, override, shutdown (`EVIDENCE/terminal/`, `EVIDENCE/dashboard/`) | MANUALLY VERIFIED (one machine) | **not yet run on two laptops**; venue Wi-Fi may isolate clients (hotspot fallback documented) | **75%** |
| 3 | Live modification / debugging | 5 exercises A–E with file location, original code, change, expected result, verification, rollback; `tools/demo_check.py`, `send_test_message.py`, `dqn_reward_experiment.py` | `EVIDENCE/terminal/exercises_A_B_C_rehearsal.txt`, `exercise_D_*.txt`, `exercise_E_repeat_0.5.txt`; deployed through the authenticated admin API | MANUALLY VERIFIED | rehearsed through the admin API, not by clicking in the editor UI | **90%** |
| 4 | Advanced features and innovation | Mamba (A) and LSTM + Dueling DQN (B) adaptations; DQN safety layer with visible decision source; delivery tracking with late acks; date-cluster bootstrap CIs; reward-weight study | report §17–20, §23–25 | TEST PASSED | adaptations, not reproductions (documented) | **85%** |
| 5 | Project report | `REPORT/Smart_Classroom_Final_Report.pdf`: 44-page Amrita-format report with title page, Certificate, Declaration, Acknowledgement, six chapters, technical architecture, ML/DQN methodology, experimental results, limitations, references and reproduction appendix | The final 44-page PDF; figures and numerical results cross-checked against the project result files | MANUALLY VERIFIED | This is the final Amrita-format report; the older 29-page report is not the submission version | **93%** |
| 6 | PPT / presentation | `PRESENTATION/…pptx`: 18 slides, native charts from result files, real screenshots, speaker notes | `validate.py`: all validations passed; LibreOffice render inspected | MANUALLY VERIFIED | not opened in Microsoft PowerPoint by us | **85%** |

## C. Cross-cutting assessment

| Area | Implementation | Evidence | Test status | Remaining issue | Readiness |
|---|---|---|---|---|---|---|
| Architecture compliance | all 8 reference stages; control logic once (Node-RED), executed by tests and experiments | report §8; `test_config_flows.py` | TEST PASSED | – | **95%** |
| Code quality | small modules, pinned dependencies, single sources of truth, 97 tests, CHANGELOG with file/reason/test | `CHANGELOG.md` | TEST PASSED | `flows.json` is large; it is generated by a builder that is not shipped (`flows.json` is the source of truth) | **85%** |
| Security | broker auth + ACL; random credentials; editor login (401) or localhost-only; secrets git-ignored and absent from the ZIP (scanned); firewall Private + LocalSubnet | `test_failures.py`, `test_scripts.py`, secret scan in `FINAL_AUDIT.md` | TEST PASSED, MANUALLY VERIFIED | no TLS; dashboard override/reset open on the LAN; one shared editor account | **75%** |
| Model validity | whole-date splits, leakage tests, selection on validation only, test reported once; registered results unchanged; CIs added in new files | `results/`, `results/supplementary/`, `git diff 862406d -- results models` (only additions + new screenshot) | TEST PASSED | 6 test dates (2 nearly empty), so rankings are not separable | **85%** |
| Energy evaluation | counterfactual + closed-loop simulation, comfort cost reported with every saving, [M]/[P]/[S] labelling | report §24–25 | TEST PASSED (code paths) | simulated only; plant parameters assumed; no metered savings | **70%** |
| Two-laptop deployment | Windows setup/start/stop/firewall scripts with detection, credential generation, port checks, connectivity checks, PID stop; 15-item checklist | `docs/TWO_LAPTOP_DEPLOYMENT_GUIDE.md`; `test_scripts.py` (PowerShell parser) | TEST PASSED (parse + helpers), MANUALLY VERIFIED (Linux equivalents) | **NOT PHYSICALLY VERIFIED**; Windows-only cmdlets not executed | **55%** |
| Reproducibility | dataset SHA-256 + schema; seeds 42; pinned versions; model manifest; clean room from the ZIP | `test_logs/30_cleanroom.log` | TEST PASSED | retraining creates new run ids (documented); Python 3.11/3.12 not executed | **90%** |

## D. Overall readiness

The overall readiness is the mean of the 13 scores in B and C: **(85+75+90+85+85+85+95+85+75+85+70+55+90)/13 =
81.5%, about 82%**. It is not 100% because:

1. Two-laptop operation has not been physically verified, and that is the configuration the evaluation expects.
2. All energy savings are simulated.
3. The Head-of-Department name and the submission date in the Amrita report should be confirmed by the team.
4. There is no TLS, and the dashboard controls have no login.

**Verdict: READY WITH MINOR LIMITATIONS.** Before the evaluation, the team must:

- run checklist §6 of the deployment guide on the two real laptops and record the result;
- confirm the HoD name and date in the Amrita-format report;
- rehearse exercises A–E once on those laptops.

If the two-laptop checklist fails and cannot be fixed (for example, Wi-Fi isolation with no hotspot available), the
demonstration falls back to loopback mode on one laptop. That fallback must be stated openly. In that case,
categories 2 and the two-laptop score drop and the verdict becomes NOT READY for the two-laptop requirement.

# Final audit — Smart Classroom Energy Management v4

**Audited:** the project at git commit `2697d38` and above (working repository), and the delivered
`FINAL_PROJECT.zip` contents.
**Compared with:** the v3 baseline (`862406d`, `INITIAL_AUDIT.md`).
**Environment:** Linux, 2 vCPU, Python 3.13.17, Node.js 22.23.4, Mosquitto 2.0.18, PowerShell 7.4.6 (parser only).

## 1. Resolution of the initial findings

| Initial finding (INITIAL_AUDIT §) | Status in v4 | Evidence |
|---|---|---|
| §5.1 Model-comparison panel empty | **Fixed.** `init_db.py` (run by the start scripts) imports the training report and registered results; the panel reads SQLite through a formatter with an empty-state instruction; selection vs test columns are separated | `test_model_comparison_*`; `EVIDENCE/dashboard/dashboard_full.png` |
| §5.2 "AC BOOST while DQN says OFF" ambiguity | **Fixed and explained.** Priority order documented in the node; `ac_source` / `dqn_status` shown on the dashboard; the safety layer is never bypassed for the DQN | `test_displayed_ac_source_matches_the_decision` |
| §4.1 No stop scripts / PID tracking | **Fixed.** `stop_server` / `stop_node` (`.ps1` + `.sh`), PID files; stop waits for exit | `test_scripts.py`; `EVIDENCE/terminal/stop_server.txt` |
| §4.2 No credential generation | **Fixed.** `tools/init_env.py` (`secrets`, 24 characters); placeholders fail `check_setup` | `test_init_env_*` |
| §4.3 Port 1880 not checked | **Fixed.** 1883 and 1880 checked; the owning process is named | manual: the port check fired correctly during a too-fast restart |
| §4.4 No dataset integrity check | **Fixed.** SHA-256 + row count + 18 columns + manifest | `test_dataset_integrity_*`; clean-room download PASS |
| §4.5 Dashboard gaps (comfort, latency trend, delivery rate, header, val/test, misleading 0%) | **Fixed.** All 20 required panels; `n/a (…)` instead of 0% | report §13; `test_savings_*` |
| §4.6 No confidence intervals | **Added** as supplementary files (date-cluster bootstrap); registered results untouched | `results/supplementary/bootstrap_ci_*` |
| §4.7 No DQN reward-weight tool | **Added** (`tools/dqn_reward_experiment.py`, deterministic, separate output) | `dqn_reward_sweep.csv` (repeat run identical) |
| §4.8 Missing failure tests | **Added:** 19 tests in `test_failures.py` | `TEST_SUMMARY.md` |
| §6 Node-RED editor without login | **Fixed.** Login from `SC_EDITOR_PASSWORD`, else localhost-only | `curl /flows` → 401; `EVIDENCE/node_red/editor_login_required.png` |
| §6 Default passwords not forced to change | **Fixed** (generation + check) | as above |
| §7 Windows scripts never executed | **Partly.** Parsed by the real PowerShell parser; helpers executed; Windows-only cmdlets still unexecuted | `test_scripts.py` |
| §10 Missing docs (guide, demo script, viva, PPT, report sections) | **Done.** All present | `DOCUMENTATION/`, `REPORT/`, `PRESENTATION/` |
| §11 Two physical laptops never executed | **Still pending** (cannot be done here). A 15-item checklist is provided | `TWO_LAPTOP_DEPLOYMENT_GUIDE.md` §6 |

## 2. New problems found during v4 and fixed

1. **Command-id collision** within one millisecond: two commands could share an id, and the pending map lost one,
   which would turn a delivered command into a false NO_ACK. Fixed with a sequence suffix.
2. **Late acknowledgements** after the NO_ACK timeout were ignored, so the command stayed NO_ACK forever. They are
   now `ACKED_LATE` with a `LATE_ACK` alert.
3. **Stop/restart race:** Node-RED takes about 15 s to close its MQTT connection. The stop script now waits.
4. **Node-RED `.sessions.json`** (editor tokens) appeared once the login was enabled and was committed in a v4
   working commit. It is now untracked and ignored, and was never in any ZIP. The tokens belonged to this test
   instance only.
5. **Rehearsal finding:** with the default values, the 10-minute minimum hold never binds under the rules, because
   the 15-minute grace period is longer. It only protects DQN mode. This is documented, and exercise C shows it.

## 3. Integrity of registered results

- `git diff --stat 862406d -- results models` shows only additions under `results/supplementary/` and a new
  `results/dashboard_screenshot.png`.
- `diff -rq` of `models/` against the v3 copy shows no differences, ignoring the new `models/experiments/`, which is
  excluded from the ZIP.
- `tools/bootstrap_ci.py` re-predicts the test dates with the saved evaluation models. It stops if any test F1 differs
  from the registered value; all 6 matched.
- No model was re-selected; the primary model remains the random forest (highest validation F1).
- Test dates were not used for any v4 tuning. The reward-weight study is labelled as a separate shortened protocol;
  it reports test numbers and selects nothing.

## 4. Security audit

| Item | Finding | Status |
|---|---|---|
| MQTT authentication | `allow_anonymous false`; PBKDF2-SHA512 password file | OK (tested) |
| MQTT ACL | node: write telemetry/status/acks, read control; server: `smartclass/#` | OK (tested: `Denied PUBLISH`) |
| Passwords | generated with `secrets`; `.env` mode 600 where supported; node password shown once on screen | OK |
| Environment files | `.env.example` contains only placeholders; `.env` is git-ignored and absent from the ZIP | OK |
| Git exclusions | `.env`, `passwd`, `flows_cred.json`, `.sessions.json`, `.config.runtime.json`, data CSVs, DB, logs, venv, node_modules, `models/experiments/` | OK |
| **Secret scan** | each real password from this environment's `.env` was searched in the staged ZIP content and in `FINAL_DELIVERY/`: no match | OK |
| Node-RED editor | login required (401, tested with curl) when a password is set; otherwise localhost-only (HTTP 403 middleware, implemented, not exercised from another machine) | OK |
| Network binding | Mosquitto `listener 1883` (all interfaces, needed for Laptop 2); Node-RED `0.0.0.0:1880`; Windows firewall rules Private + LocalSubnet; no port forwarding | acceptable for a LAN |
| Error logging | services log connection failures with causes; Node-RED catch node; no passwords in logs (`init_env` prints only a masked value after first creation) | OK |
| Input validation | Node-RED validation + actuator command validation | OK (tested) |
| Database access | single local file; busy timeout; no remote access | OK |
| Service failure handling | reconnect back-off, Last Will, missing-model fallback, NO_ACK / late ACK, stale-data hold | OK (tested) |
| **Open risks** | no TLS; dashboard override/reset have no login; one shared editor account | documented |

## 5. Dataset and reproducibility

- **Licence:** still unverified. Nothing has been invented: the CSVs are not shipped and `download_data.py` fetches
  them from the official repository.
- **Integrity:** verified in a clean room. A fresh download matched both SHA-256 values.
- **Versions:** Python 3.13.17, Node.js 22.23.4, Mosquitto 2.0.18; packages pinned in `requirements*.txt` and
  `nodered/package.json`.
- **Seeds and configuration:** seeds 42; split, features and simulator parameters in
  `models/training_report.json`; model manifest in `models/final/manifest.json`.
- **Clean room:** unzip → download → `init_env` → broker users → `init_db` → `check_setup` (21/21) → pytest (97
  passed) → e2e (passed). Logged in `TEST_RESULTS/test_logs/30_cleanroom.log`.
- **Clean-room caveat:** the clean room reused the pinned virtual environment and `node_modules` rather than
  re-installing them. A from-scratch install of the same pins was done in v3.

## 6. Residual risks for the evaluation (highest first)

1. Two-laptop operation is not physically verified, and venue Wi-Fi may isolate clients. Mitigation: run checklist
   §6 beforehand; bring a phone hotspot; loopback fallback, stated openly.
2. Windows-only cmdlets in the scripts are unexecuted. Mitigation: the setup rehearsal on the real laptops will
   exercise them.
3. Examiner asks why Mamba is not primary. Prepared answer: viva Q31 and report §23, with the bootstrap figure.
4. Savings being mistaken for real-world savings. Every slide, table and panel says simulated.
5. Team names and contributions are now filled in (report §33 / Amrita report §6.4, slide 18, viva §K) as given by the team.

**Verdict (see FINAL_ACCEPTANCE_MATRIX.md): READY WITH MINOR LIMITATIONS, readiness about 82%.**

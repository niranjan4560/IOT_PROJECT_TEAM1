---
title: "Smart Classroom Energy Management — Technical Report"
subtitle: "Team 1 · B.Tech CSE Semester 7 IoT mini-project · two-laptop MQTT / Node-RED / ML implementation on the ROBOD dataset"
date: "October 2026"
---

# 1. Abstract

We built an end-to-end IoT system that monitors lecture rooms and controls their lighting and air-conditioning (AC)
from occupancy analytics. The system follows the faculty reference architecture (stages 1–8):

- An IoT node replays the real ROBOD dataset (two NUS lecture rooms, 5-minute data, 29 weekdays) to an
  authenticated Mosquitto broker.
- Node-RED validates, stores (SQLite) and visualises (Node-RED Dashboard 2.0) each reading.
- A Python ML service runs traditional, ensemble and deep-learning occupancy models.
- A Node-RED decision engine sends commands to simulated light and AC actuators, which acknowledge them.

Two recent research methods are integrated. (A) A Mamba selective-state-space occupancy model, from the model family
of OCC-Mamba (Qaisar et al., *Building and Environment*, 2025/26). (B) The LSTM occupancy estimator and Dueling Deep
Q-Network (DQN) HVAC controller of Hou et al. (*Building and Environment* 284, 2025).

On six held-out test dates, the best occupancy F1 was 0.651 (Mamba), against 0.000 for the majority-class baseline.
The random forest, chosen on validation data, scored 0.559 on test but had the best 5-fold-by-date F1 (0.73 ± 0.11).

In a closed-loop grey-box simulation, rule-based control driven by predicted occupancy used 52% less cooling energy
than always-on operation (405 vs 851 kWh thermal over six days), with 0.6% of occupied intervals outside the comfort
band. The Dueling DQN saved more cooling energy (129 kWh thermal) but violated comfort in 24% of occupied intervals.
Behind our safety layer it reached 151 kWh thermal and 7.0% violations, so rules remain the default.

The live two-node loop acknowledged 100% of 46 commands, with a median telemetry-to-actuator latency of 96 ms. All
savings are simulated counterfactuals, not measurements.

# 2. Problem statement and objectives

Lighting and AC often run in empty classrooms. The faculty problem statement (Team 1) asks us to:

- monitor occupancy, temperature, ambient light and electrical power;
- estimate occupied and unoccupied periods and energy demand with analytical or ML methods;
- use the analytics to control lighting and AC, reducing energy in expected unoccupied periods and/or preparing the
  room before expected occupancy.

The common architecture prescribes MQTT, Node-RED for integration and automation, SQLite or MySQL, and the Node-RED
Dashboard.

Our objectives:

- O1: reproduce the reference architecture on two physical laptops;
- O2: compare traditional, ensemble and deep models fairly, including predictive, computational and closed-loop
  performance;
- O3: implement and evaluate two 2024–2026 research algorithms;
- O4: control both loads safely, with complete MQTT command and acknowledgement feedback;
- O5: report energy and comfort honestly, separating measured, derived, predicted and simulated quantities.

# 3. Literature review of the two selected papers

## 3.1 Paper A — OCC-Mamba

I. Qaisar, K. Sun, D. Zhong, X. Yang, X. Miao, Q. Zhao. *OCC-Mamba: A Mamba-based deep learning approach for indoor
occupancy prediction.* Building and Environment, article 114085 (ScienceDirect PII S0360132325015513). The
corresponding author's homepage reports it as accepted in late 2025. DOI (as given in our brief, consistent with the
article number): 10.1016/j.buildenv.2025.114085. The authors' earlier work includes a Transformer for building
occupancy-number prediction (Building and Environment 244, 2023, 110807) and multi-sensor occupancy prediction
(Buildings 13(8), 2023, 2002).

**What we could verify.** We verified the title, authors, journal and article number. We could **not** access the
abstract, full text or code: the publisher page blocks automated access, and no repository is listed by the authors.
Therefore we do not claim OCC-Mamba's layer configuration, inputs, horizon or results.

**What it is built on.** As the title states, it uses the Mamba selective state-space model (A. Gu, T. Dao, *Mamba:
Linear-Time Sequence Modeling with Selective State Spaces*, arXiv:2312.00752, v2 May 2024). Mamba makes the SSM
parameters (step size Δ and matrices B, C) functions of the input, so the recurrence can keep or forget information
per time step. It computes this with a linear-time scan.

**Mapping.** Stage 5 (deep-learning occupancy prediction).

## 3.2 Paper B — LSTM + Dueling DQN

F. Hou, J. C. P. Cheng, J. Ma, H. H. L. Kwok, C. Huang, Z. Wu. *Occupancy-driven HVAC control optimization via LSTM
and deep reinforcement learning for enhanced indoor air quality, thermal comfort and energy efficiency.* Building and
Environment 284 (2025) 113501, published online 29 July 2025 (HKUST). DOI 10.1016/j.buildenv.2025.113501.

**Problem and method (from the published abstract and record).** The framework, OccD-LSTM-DDQN, estimates occupancy
from indoor CO₂ fluctuations using an LSTM, with labels derived by change-point analysis. A Dueling DQN uses this
estimate to reduce HVAC operation in unoccupied periods while maintaining thermal comfort and indoor air quality. It
adds a dynamic hyper-parameter adjustment strategy for robust deployment.

**Reported results (published, NOT ours).** Across three rooms: occupancy estimation precision ≈ 0.7 and recall ≈ 0.6;
9.5–14.6% fewer temperature violations; 12.2–17.4% fewer CO₂ violations; 10.9–30.4% less HVAC operation time. The
exact state, action and reward definitions and the simulation platform were not accessible to us.

**Mapping.** Stage 5 (LSTM occupancy estimator) and Stage 6 (Dueling DQN in the decision engine).

## 3.3 Why these two

They are complementary: A is a modern sequence model for the prediction step, and B closes the loop from prediction
to HVAC action. Both run on a laptop CPU (17k and 5.5k parameters; DQN 24 kB). Both fit ROBOD, which provides
Wi-Fi, CO₂, sound, humidity, temperature, light and camera occupancy labels.

# 4. Reference architecture and implementation mapping

![Implemented architecture (docs/architecture.png)](architecture.png)

| Stage | Reference block | Implementation | Laptop |
|---|---|---|---|
| 1 | IoT devices / dataset replay | `run_simulator.py` (ROBOD rows, `sent_at_ms`); `actuator.py` (light + AC devices) | 2 |
| 2 | MQTT broker | Mosquitto 2.x, `allow_anonymous false`, password file, ACL per role, QoS 1, retained commands/acks, Last Will | 1 |
| 3 | Node-RED flow processing | `nodered/flows.json`: JSON parse, range + required-field validation, duplicate drop, stale-data watchdog, alerts, health | 1 |
| 4 | Dashboard + database | Node-RED Dashboard 2.0 (`/dashboard`); SQLite from `db/schema.sql` (8 tables) | 1 |
| 5 | Analytics & ML | `ml_service.py` + `smartclass/predictor.py`: 6 occupancy models, arrival profile, energy forecaster, DQN recommendation; evaluation in `train_models.py`, `run_experiments.py` | 1 |
| 6 | Decision engine | Node-RED "Decision rules": rules or Dueling-DQN AC + safety layer; change-only gate | 1 |
| 7 | Control command via MQTT | `smartclass/{room}/control/{light,ac}`; `command_id`; SQLite `commands` (SENT/ACKED/REJECTED/NO_ACK) | 1→2 |
| 8 | Command to actuators + feedback | simulated state change; `smartclass/{room}/actuator/{load}` ack with `loop_latency_ms` | 2→1 |

**Single sources of truth.**

- The control logic exists once, in the Node-RED "Decision rules" node. Experiments and tests execute that exact code
  through `tools/run_rules.js`.
- The database schema exists once, in `db/schema.sql`. The Node-RED create-tables node is generated from it, and a
  test checks they match.
- All thresholds are in the Node-RED CONFIG node.

# 5. Dataset and preprocessing

**Source.** ROBOD (Tekler et al., Building Simulation 15(12), 2022), downloaded unmodified from the official
repository. Room 1 is the primary room (training and test) and Room 2 is secondary (cross-room evaluation only).
Each room has 8,352 rows × 28 columns, at 5-minute resolution, over 29 weekdays (7 Sep–1 Oct and 9–23 Dec 2021).
Timestamps are kept in their recorded form, `YYYY-MM-DD HH:MM +08:00`, converted to ISO 8601 +08:00. Rows are
sorted and de-duplicated, and a new contiguous **segment** starts at every gap. Licence: unverified.

**Field kinds and units.** These are listed in `docs/DATA_DICTIONARY.md`. Lighting, FCU-fan and plug energy are
electrical kWh per 5 minutes. Chilled-water energy is **thermal** kWh and is never added to electrical energy. Light
and AC states do not exist in ROBOD, so all actuator states are simulated.

**Missing values.** Room 1 has 14 rows without indoor sensors and 10 without chilled-water/fan energy; Room 2 has 30.
They are sent as JSON null, rejected by Node-RED (alerted) and never silently filled. Offline, features forward-fill
from the past only within a segment and flag the row; flagged rows are excluded from training and scoring.

**Features.** All features use only data at time t or earlier.

- Sensors: Wi-Fi devices, CO₂, sound, humidity, temperature, illuminance.
- Time: sine/cosine of time of day, and weekday.
- Tabular models also get: Wi-Fi 30-minute mean, CO₂ change over 15 and 55 minutes, 30-minute maximum sound,
  15-minute temperature change.
- Sequence models get the last 12 readings (1 hour) of the 9 sensor and time features.

Camera labels are **never** inputs. A test changes future values and checks that features at t are unchanged.
Another test checks that the live service computes exactly the offline features. A cross-validation ablation on the
training and validation dates only showed that the extra sensors help: random-forest F1 0.733 vs 0.630 with the
earlier Wi-Fi/temperature/light/time set.

**Splits.** By whole date, with seed 42:

- 19 training dates;
- 4 validation dates (2021-09-08, 09-27, 12-09, 12-13): model selection, early stopping, threshold tuning;
- 6 test dates (2021-09-20, 09-21, 09-24, 09-30, 12-15, 12-22): reported only.

Rows: 5,414 / 1,119 / 1,717 (a row needs a full 1-hour window and valid sensors). Scalers are fitted on training data
only. A 5-fold GroupKFold by date on training + validation measures ranking stability.

# 6. Algorithms and adaptations

**Traditional:** logistic regression (standardised, class-balanced); decision tree (depth 5, balanced); linear
regression for energy.

**Ensemble:** random forest (200 trees, minimum leaf 5, balanced); histogram gradient boosting (200 iterations,
learning rate 0.05).

**Deep learning (paper B, LSTM):** one LSTM layer, 32 units, last hidden state → logit. Trained with Adam (learning
rate 1e-3), class-weighted BCE and early stopping on validation F1 (best epoch 13). Change from the paper: labels come
from ROBOD's camera rather than CO₂ change-point labels, because ground truth exists. The input is a 1-hour window of
six sensors, of which CO₂ is one.

**Deep learning (paper A, Mamba):** a linear embedding to d = 32, then two pre-norm residual Mamba blocks. Each block
has: expand 2, causal depth-wise convolution (kernel 4), SiLU, input-dependent Δ/B/C (state size 8), zero-order-hold
discretisation, a recurrent selective scan, a skip connection D and SiLU(z) gating. RMSNorm, then the last time step
goes to a logit. 17,217 parameters; plain PyTorch, no CUDA kernel. What is preserved is the Mamba mechanism; OCC-Mamba's
own configuration is not known to us (Section 3.1).

**Arrival profile (pre-cooling):** P(arrival within 30 min | empty) per weekday × half-hour, from training dates. The
threshold 0.2 was chosen by 5-fold CV on training dates.

**Dueling DQN (paper B):**

- Q(s,a) = V(s) + A(s,a) − mean A, with 2×64 ReLU hidden layers.
- State: LSTM probability, arrival probability, temperature, CO₂, outdoor temperature, time of day.
- Actions: OFF / ECO / COMFORT / BOOST.
- Reward: −(cooling kWh / COP 3.5 + fan kWh) − 0.5 × K outside 23–26 °C − 0.3 × (CO₂ − 1000 ppm)/100, the last two
  only while occupied.
- Training: experience replay (50k), target network (sync every 1,000 steps), ε-greedy (1 → 0.05), γ = 0.97,
  Huber loss, 400 one-day episodes on training + validation dates. The occupancy input during training is
  **out-of-fold** LSTM predictions, to avoid in-sample optimism.

**Grey-box simulator** (`smartclass/room_env.py`). We first tried to identify the room from ROBOD. Linear models of
the 5/30/60-minute temperature change explained R² ≤ 0.044, and gave cooling the wrong sign, because cooling is
metered in 1-kWh steps and runs in the hottest hours. ROBOD therefore cannot identify the plant, so we use a
first-order RC model with an ideal thermostat per mode (ECO 26, COMFORT 24, BOOST 23 °C) and a CO₂ mass balance. All
parameters are declared and assumed. They were calibrated on training dates so that the free-running room peaks
around 30 °C and 24/7 COMFORT uses 140 kWh thermal per day (ROBOD median 132). ROBOD supplies the outdoor
temperature, solar radiation, outdoor CO₂ and real occupant counts.

**Decision engine (Node-RED):**

- Lights are always rule-based: ON (or DIM above the per-room lux threshold, which is disabled in Room 1) when
  occupied; OFF after 15 minutes empty.
- AC by rules: COMFORT, or BOOST when hot, while occupied; ECO after 15 minutes empty; OFF after 30 minutes if no
  arrival is expected; PRECOOL when an arrival is likely and the room is warm.
- AC by the DQN (optional): the recommendation passes a **safety layer**: occupied and more than 2 °C above comfort
  means at least COMFORT; manual override wins; minimum 10-minute hold; holding on stale data.
- Occupancy hysteresis: on at ≥ 0.25, off below 0.15. These were tuned on the validation dates: the most
  comfort-protective pair with ≥ 30% lighting saving.
- Missing model output: hold the last commands, or use the 08:00–20:00 timetable if there are none.
- Start-up: an empty room is never switched on.

# 7. Two-laptop deployment

**Laptop 1 (server):** Mosquitto, Node-RED + Dashboard + SQLite, ML service.
**Laptop 2 (node):** ROBOD replay and the light + AC actuators (one process per room).

Each laptop has its own `.env`: broker address (Laptop 1's LAN IP on Laptop 2) and role credentials. There are
separate PowerShell and bash scripts for setup and start-up, Windows firewall rules limited to the Private profile
and local subnet, a LAN-IP helper, start-up checks (`tools/check_setup.py`), and a loopback mode for one laptop. The
startup order, shutdown, reconnect behaviour (exponential back-off 1–30 s; retained commands and acknowledgements)
and troubleshooting are in the README.

**Verification in our environment.** The node clients connected through the machine's network interface
(192.0.2.2, not loopback) as `sc_node`. The dashboard answered on that address. All commands were acknowledged.
A run on **two physical laptops** could not be performed here; Section 13 lists it as a manual step.

# 8. MQTT and Node-RED integration

Topics and payloads are tabulated in the README (§7). QoS 1 everywhere. Commands and acknowledgements are retained,
so a restarted actuator gets its last command. Every client has a Last Will on its status topic.

The broker ACL allows the node account to write only telemetry, status and acknowledgements, and to read only
control topics. We tested this: a control publish by the node account was dropped; a wrong password and anonymous
clients were refused.

Node-RED gets its credentials from `.env` through `settings.js`, which writes the git-ignored `flows_cred.json`. The
flow is numbered by stage and contains 97 nodes; it imports into any Node-RED 4.x with the three pinned packages.

**Delivery tracking.** The change-only gate assigns a `command_id`, stores SENT and keeps it pending. An
acknowledgement upserts ACKED/REJECTED, with the round trip (server clock) and loop latency (node clock). Neither
measure crosses clocks. The watchdog marks NO_ACK after 5 s.

Two integration bugs were found and fixed during testing: an INSERT/UPDATE race between two SQLite nodes, and
retained acknowledgements arriving before the tables existed.

# 9. Database and dashboard

**SQLite tables:**

- `telemetry` (UNIQUE room/ts), `predictions` (per model), `decisions`, `commands`, `actuator_log`, `alerts`;
- `model_metrics` (training results);
- `experiment_results`.

Units and kinds are in the schema comments.

**Dashboard panels:**

- occupancy probability and primary model; arrival probability;
- light and AC commands and actuator acknowledgements; reason;
- temperature gauge; lux, CO₂, Wi-Fi, sound, humidity; camera presence and count (labelled as not a model input);
- live predictions of all six models with latency; model comparison (SQLite);
- energy vs occupancy chart; separate electrical and thermal cumulative baseline-vs-controlled charts;
- alert table and pop-ups; device status; command-delivery health (sent, acknowledged %, NO_ACK, round trip, loop);
- manual override; reset.

![Dashboard during a replay (results/dashboard_screenshot.png)](../results/dashboard_screenshot.png)

# 10. Experimental methodology and metrics

**Predictive.** Occupancy: accuracy, precision, recall, F1, confusion matrix on test dates, with the majority-class
baseline; 5-fold-by-date F1; Room 2 cross-room F1. Energy: MAE, RMSE, R², against mean and persistence baselines.

**Computational.**

- Training time (wall clock).
- Inference latency: median and p95 over 200 single-reading calls, one thread, exactly as the live service runs.
- Peak resident memory above the start (sampled every 10 ms; the deep-model value includes PyTorch's first-use
  allocations).
- Model size on disk and parameter count.

Hardware: 2-vCPU Intel Xeon 2.8 GHz, CPU only; Python 3.13, PyTorch 2.14.1, scikit-learn 1.6.1.

**Closed-loop (live).**

- Acknowledgement rate = ACKED / decided commands.
- Round trip = command published → ack received (server clock).
- Loop latency = telemetry published → actuator applied (node clock).
- Switches per data day.

`tools/closed_loop_report.py` computes these from SQLite.

**Closed-loop (simulation).** Six test days in the grey-box room. Controllers: always COMFORT; timetable 07–20; rules;
raw DQN; DQN + safety layer. Occupancy input: camera, LSTM, Mamba or random forest. Measured: cooling kWh thermal;
fan kWh electrical; occupied steps outside 23–26 °C (count and K·h); CO₂ > 1000 ppm occupied steps; switches per day.

**Recorded-energy counterfactual.** The baseline is the recorded energy. The controlled energy is the same, scaled by
our command (lighting OFF 0, DIM 0.5, ON 1; chilled water OFF 0, ECO 0.75, otherwise 1; fan OFF 0, otherwise 1).
Reported per load, controller and occupancy source; sensitivity for ECO ∈ {0.5, 0.6, 0.75, 0.9} and
DIM ∈ {0.3, 0.5, 0.7}.

Comfort proxies: lights OFF while occupied (incorrect OFF) and AC ECO/OFF while occupied. The denominator of every
percentage is the recorded baseline of that load. Every decision passes through the live code path: the
`LivePredictor` with the eval models, then the Node-RED rule code.

# 11. Results

## 11.1 Occupancy

![Model comparison (results/figures/model_comparison.png)](../results/figures/model_comparison.png)

| Model | Category | Val F1 | Test acc. | Test P / R | **Test F1** | CV F1 (5 folds) | Room 2 F1 | Train (s) | Latency median (ms) | Size (kB) | Params |
|---|---|---|---|---|---|---|---|---|---|---|---|
| majority class | baseline | 0.000 | 0.800 | 0 / 0 | 0.000 | 0.00 | 0.000 | 0.0 | 0.02 | 1 | – |
| logistic regression | traditional | 0.731 | 0.859 | 0.65 / 0.65 | 0.646 | 0.66 ± 0.15 | 0.679 | 0.02 | 0.88 | 2 | – |
| decision tree | traditional | 0.760 | 0.818 | 0.55 / 0.54 | 0.544 | 0.62 ± 0.16 | 0.657 | 0.04 | 0.86 | 6 | – |
| random forest | ensemble | **0.848** | 0.838 | 0.61 / 0.51 | 0.559 | **0.73 ± 0.11** | 0.667 | 1.0 | 10.1 | 4,235 | – |
| gradient boosting | ensemble | 0.819 | 0.846 | 0.66 / 0.48 | 0.556 | 0.68 ± 0.15 | 0.635 | 0.7 | 2.52 | 729 | – |
| LSTM (B) | deep | 0.714 | 0.872 | 0.82 / 0.47 | 0.593 | 0.61 ± 0.14 | 0.637 | 4.9 | 0.40 | 26 | 5,537 |
| Mamba (A) | deep | 0.757 | **0.884** | 0.82 / 0.54 | **0.651** | 0.67 ± 0.12 | 0.570 | 24.9 | 2.21 | 77 | 17,217 |

All models beat the majority baseline by a wide margin. The deep models are the most precise (0.82) but miss about
half of the occupied intervals. Mamba has the best test F1, and A vs B favours A on this data (0.651 vs 0.593).

The ranking is unstable across splits: the random forest leads validation and 5-fold CV but not the test dates. The
standard deviations (0.11–0.16) are as large as the gaps between models, so no model is clearly superior with
29 dates.

Computationally, every model runs in ≤ 10 ms per reading on a laptop CPU. The random forest is the largest (4.2 MB)
and slowest. The deep models are small (26–77 kB), but their training needs PyTorch (about 160–180 MB extra peak
memory). The six models together averaged 1–16 ms each in the live service.

## 11.2 Energy forecasting (next 5 minutes, test dates)

| Model | Lighting MAE | Lighting R² | Chilled water MAE | Chilled water R² |
|---|---|---|---|---|
| mean baseline | 0.0539 | −0.00 | 0.669 | −0.02 |
| persistence | **0.0022** | 0.965 | 0.450 | −0.09 |
| linear regression | 0.0028 | **0.966** | 0.466 | 0.32 |
| random forest | 0.0144 | 0.836 | 0.244 | 0.66 |
| gradient boosting | 0.0040 | **0.966** | **0.243** | **0.70** |

For lighting, nothing beats persistence: the lights rarely change between 5-minute steps. For chilled water, the
ensembles halve the error of both baselines.

## 11.3 Pre-cooling profile

On test dates, the arrival profile caught 7 of 47 arrivals and raised 158 false alarms (F1 0.066), against 0 for
the never-pre-cool baseline. Arrivals in these rooms are not well predicted by the weekday-and-time timetable. The
feature works as designed, but it is weak.

## 11.4 Dueling DQN training

![DQN training (results/figures/dqn_training.png)](../results/figures/dqn_training.png)

400 episodes took 219 s on CPU. The episode return improved from −40 to −8. The policy is 24 kB and takes 0.12 ms
per decision.

# 12. Energy and comfort analysis

## 12.1 Closed-loop simulation (6 test days, AC only; `results/closed_loop_results.csv`)

![Energy vs comfort (results/figures/closed_loop_tradeoff.png)](../results/figures/closed_loop_tradeoff.png)

| Controller | Cooling kWh_th | Fan kWh_e | Outside 23–26 °C (occupied) | K·h | CO₂ viol. | AC switches/day |
|---|---|---|---|---|---|---|
| always COMFORT | 850.6 | 37.5 | 0.0% | 0.00 | 0 | 0.0 |
| timetable 07–20 | 509.5 | 20.3 | 0.0% | 0.00 | 0 | 2.0 |
| rules + camera (upper bound) | 366.7 | 12.3 | 0.3% | 0.01 | 0 | 14.7 |
| rules + LSTM | 361.7 | 12.3 | 0.6% | 0.07 | 0 | 17.0 |
| rules + Mamba | 422.9 | 15.1 | 1.2% | 0.08 | 0 | 14.0 |
| **rules + random forest (default)** | **405.5** | 14.2 | **0.6%** | 0.07 | 0 | 16.5 |
| DQN raw + camera | 127.5 | 2.2 | 22.4% | 2.53 | 0 | 23.5 |
| DQN raw + LSTM (paper B pairing) | 128.5 | 2.3 | 24.1% | 3.13 | 0 | 25.3 |
| DQN + safety + LSTM | 150.9 | 2.8 | 7.0% | 0.59 | 0 | 17.7 |
| DQN + safety + Mamba | 156.1 | 2.8 | 9.9% | 1.29 | 0 | 17.2 |
| DQN + safety + random forest | 152.8 | 2.7 | 12.2% | 1.20 | 0 | 17.3 |

Rule-based control with predicted occupancy reached 52% less cooling than always-on and 20% less than the timetable,
at 0.6% comfort violations, which is close to the camera-oracle bound.

The DQN learned a much leaner policy (−85% vs always-on), but it tolerates warm rooms: a mean occupied temperature of
25.7 °C and 21–26% violations. The safety layer cuts violations to 7–12% at a small energy cost, but that is still
not acceptable, so the default stays `rules`.

A better comfort/energy balance would need a larger comfort weight, chosen on validation dates. CO₂ never exceeded
1,000 ppm in any scenario, so the IAQ term of the paper-B reward was never binding here. AC switching (14–25 per day)
reflects many short BOOST/COMFORT changes and is a known limitation.

![One simulated test day (results/figures/closed_loop_day.png)](../results/figures/closed_loop_day.png)

## 12.2 Recorded-energy counterfactual (`results/savings_results.csv`, ECO 0.75, DIM 0.5)

![Savings by occupancy source (results/figures/savings_by_source.png)](../results/figures/savings_by_source.png)

| Room 1 test dates, rules | Lighting | Chilled water (thermal) | FCU fan | Lights OFF while occupied |
|---|---|---|---|---|
| camera label (upper bound) | 33.0% | 43.1% | 44.7% | 0 / 344 |
| random forest (deployed) | 38.7% | 39.5% | 38.4% | 96 / 344 (27.9%) |
| logistic regression | 26.1% | 23.9% | 23.0% | 36 / 344 (10.5%) |
| Mamba | 32.6% | 33.4% | 33.3% | 64 / 344 (18.6%) |
| LSTM | 57.7% | 41.2% | 41.8% | 133 / 344 (38.7%) |

Lighting savings above the camera bound are not real savings: they come from switching off occupied rooms. The
honest comparison is "saving per comfort cost". On Room 1 test dates, logistic regression and Mamba switch off far
fewer occupied intervals than the random forest. On Room 2 (never trained on), the random forest has the fewest
wrong OFFs (8.1%).

Validation tuning of the hysteresis reduced wrong OFFs from 22.5% to 13.7% on validation. On the harder test dates
they were still 27.9%.

**Sensitivity.** Chilled-water savings change by less than 1.5 points across ECO factors 0.5–0.9 (most of the saving
comes from AC OFF, not ECO). DIM has no effect in Room 1, where dimming is disabled because lux ≤ 92.

With the DQN controlling AC (still behind the safety layer), recorded-energy cooling savings rise to 48–71% in
Room 1, but with 65–194 occupied intervals in ECO/OFF (65 even with the camera label). This matches the closed-loop finding.

## 12.3 Live closed loop (`results/live_closed_loop_report.json`)

Run over the network interface, with 518 readings and 46 commands:

- acknowledgement rate 100%;
- round trip median 88 ms (p95 112, max 139 ms);
- telemetry-to-actuator loop median 96 ms (p95 153, max 474 ms, measured while experiments shared the CPU);
- per-model inference 1–16 ms;
- 0 NO_ACK; stale-data and recovery alerts raised as designed.

The automated end-to-end test, a separate run, repeats this with 60 readings and asserts 100% acknowledgement.

# 13. Limitations, risks and future work

1. **Small data.** 29 dates (6 test) make model rankings unstable (CV standard deviation 0.11–0.16). Report ranges,
   not winners.
2. **OCC-Mamba** could only be followed at the model-family level (Section 3.1). Obtain the full text through the
   library to align the architecture.
3. **Grey-box plant with assumed parameters.** Absolute closed-loop energy is indicative only; compare controllers
   with each other, not with the building.
4. **Counterfactual energy** assumes recorded energy scales with our command. It cannot add energy when we would
   switch something on, so savings are optimistic. Pre-cooling energy is not added.
5. **Comfort.** With predicted occupancy, lights are wrongly OFF in 8–28% of occupied intervals (by room). Before any
   real deployment, add a motion sensor or a minimum-lighting fallback.
6. **DQN** comfort weight and switching cost should be tuned on validation dates. Add a switching penalty and a
   previous-action input.
7. **Security.** Passwords and ACL, but no TLS; the Node-RED editor has no login. Fine for a classroom LAN only.
8. **Not verified by us:** a run on two physical laptops on a real Wi-Fi; Windows PowerShell scripts; macOS; Python
   3.11/3.12 (wheels verified to exist, not executed); dataset licence.

# 14. Conclusion

The project implements every stage of the faculty reference architecture on two laptops, with authenticated MQTT,
Node-RED integration, SQLite, a Node-RED dashboard, and a complete command and acknowledgement loop. Delivery is
measured: 100% acknowledged, about 0.1 s loop latency.

The three model categories and the two research methods are compared fairly on held-out dates, with baselines and
computational costs. Mamba (A) gave the best test F1 (0.651) and the LSTM (B) the highest precision. All models were
far above the majority baseline, but differences between them are within the date-to-date variance.

Occupancy-driven rules cut simulated cooling energy by about half at under 1% comfort violations. The paper-B Dueling
DQN saves more but needs comfort tuning, so it remains an option behind a safety layer rather than the default. Every
claimed number is traceable to an output file, and every saving is a simulation result.

# 15. References

1. Z. D. Tekler, Y. Lei, Y. Peng, C. Miller, A. Chong. ROBOD, room-level occupancy and building operation dataset.
   *Building Simulation* 15(12), 2022. https://doi.org/10.1007/s12273-022-0925-9 · data: https://github.com/ideas-lab-nus/robod
2. I. Qaisar, K. Sun, D. Zhong, X. Yang, X. Miao, Q. Zhao. OCC-Mamba: A Mamba-based deep learning approach for indoor
   occupancy prediction. *Building and Environment*, article 114085. https://doi.org/10.1016/j.buildenv.2025.114085 ·
   https://www.sciencedirect.com/science/article/abs/pii/S0360132325015513 (record verified via the publisher listing
   and the corresponding author's homepage https://kailaisun.github.io/; full text not accessed).
3. F. Hou, J. C. P. Cheng, J. Ma, H. H. L. Kwok, C. Huang, Z. Wu. Occupancy-driven HVAC control optimization via LSTM
   and deep reinforcement learning for enhanced indoor air quality, thermal comfort and energy efficiency. *Building and
   Environment* 284 (2025) 113501. https://doi.org/10.1016/j.buildenv.2025.113501 ·
   https://researchportal.hkust.edu.hk/en/publications/occupancy-driven-hvac-control-optimization-via-lstm-and-deep-rein/
4. A. Gu, T. Dao. Mamba: Linear-Time Sequence Modeling with Selective State Spaces. arXiv:2312.00752 (v2, 31 May 2024).
   https://arxiv.org/abs/2312.00752
5. K. Sun, I. Qaisar, M. A. Khan, T. Xing, Q. Zhao. Building occupancy number prediction: A Transformer approach.
   *Building and Environment* 244 (2023) 110807. https://doi.org/10.1016/j.buildenv.2023.110807
6. I. Qaisar, K. Sun, Q. Zhao, T. Xing, H. Yan. Multi-Sensor-Based Occupancy Prediction in a Multi-Zone Office Building
   with Transformer. *Buildings* 13(8) (2023) 2002. https://doi.org/10.3390/buildings13082002
7. Z. Wang, T. Schaul, M. Hessel, H. van Hasselt, M. Lanctot, N. de Freitas. Dueling Network Architectures for Deep
   Reinforcement Learning. *ICML* 2016, arXiv:1511.06581. https://arxiv.org/abs/1511.06581 (background for the dueling head).

# Data dictionary

Kinds: **[M] measured** (ROBOD sensor/meter) · **[D] derived** (computed from past/current measured values only) ·
**[P] predicted** (model output) · **[S] simulated** (our simulator: replay timing, actuator states, controlled energy,
the grey-box room).

Timestamps: `timestamp`/`ts` = data time, ISO 8601 with `+08:00` (Singapore, ROBOD's own clock). `*_at` = wall-clock
time ISO 8601 `+08:00`. `*_ms` = Unix epoch milliseconds.

## Telemetry (`smartclass/{room}/telemetry`, SQLite `telemetry`)

| Field | Kind | Unit | ROBOD column | Notes |
|---|---|---|---|---|
| timestamp | M | ISO 8601 +08:00 | timestamp | 5-minute steps, 29 weekdays (7 Sep–1 Oct, 9–23 Dec 2021) |
| wifi_devices | M | count | wifi_connected_devices | occupancy proxy |
| co2_ppm | M | ppm | indoor_co2 | |
| sound_db | M | dB | sound_pressure_level | |
| humidity_pct | M | %RH | indoor_relative_humidity | |
| temperature_c | M | °C | air_temperature | |
| illuminance_lux | M | lux | illuminance | Room 1 never exceeds 92 lux → daylight dimming disabled there |
| setpoint_c | M | °C | temp_setpoint | BMS setpoint, up to 31 °C at night; rules use their own 24 °C comfort setpoint |
| outdoor_temp_c | M | °C | dry_bulb_temp | |
| lighting_kwh | M | kWh **electrical** / 5 min | lighting_energy | |
| fcu_fan_kwh | M | kWh **electrical** / 5 min | fcu_fan_energy | |
| plug_kwh | M | kWh **electrical** / 5 min | plug_load_energy | stored, not controlled |
| chilled_water_kwh | M | kWh **THERMAL** / 5 min | chilled_water_energy | never added to electrical energy |
| occupant_presence, occupant_count | M | 0/1, people | occupant_presence, occupant_count | camera ground truth; evaluation only, **never a model input** |
| source | S | text | – | `robod_replay` or `injector` |
| sent_at_ms | S | epoch ms (node clock) | – | used for end-to-end latency |

Missing values in ROBOD (Room 1: 14 rows without indoor sensors, 10 without chilled-water/fan energy; Room 2: 30)
are sent as JSON `null`. Node-RED rejects a reading with a missing **required** sensor (`INVALID_READING` alert) and the
last commands are held; optional energy values may be `null` and are stored as SQL NULL. Nothing is filled silently:
offline feature engineering forward-fills from the past only and flags the row (`sensor_missing`); flagged rows are
excluded from training and scoring.

## Derived features (`smartclass/features.py`)

| Feature | Kind | Definition (all use readings at t or earlier, inside one contiguous segment) |
|---|---|---|
| hour_sin, hour_cos | D | time of day on the unit circle |
| day_of_week | D | Monday = 0 … Friday = 4 |
| wifi_mean_30min | D | mean Wi-Fi count of the last 6 readings |
| co2_delta_15min | D | CO₂ now − CO₂ 15 min ago |
| co2_delta_window | D | CO₂ now − CO₂ at the start of the 1-hour window (55 min) |
| sound_max_30min | D | max sound level of the last 6 readings |
| temp_delta_15min | D | temperature now − 15 min ago |
| 1-hour window | D | last 12 readings of the 6 sensors + 3 time features (LSTM / Mamba input) |

## Predictions (`smartclass/{room}/analytics`, SQLite `predictions`, `decisions`)

| Field | Kind | Meaning |
|---|---|---|
| models.{name}.p | P | P(occupied now) from each deployable model |
| primary_model, occupancy_probability | P | the model used for control (best validation F1; fallback order if it fails) |
| p_arrival_30min | P | P(someone arrives within 30 min \| empty), weekday × half-hour profile |
| predicted_next_lighting_kwh | P | next 5-min lighting energy (electrical) |
| predicted_next_chilled_water_kwh_thermal | P | next 5-min chilled-water energy (thermal) |
| dqn_ac_action | P | Dueling-DQN AC recommendation before the safety layer |
| warming_up | D | fewer than 12 consecutive readings so far (window padded) |

## Commands and actuators

| Field | Kind | Meaning |
|---|---|---|
| light_cmd ∈ {ON, DIM, OFF}, ac_cmd ∈ {COMFORT, BOOST, PRECOOL, ECO, OFF} | S | commands from the decision engine |
| state, previous | S | simulated actuator state after/before the command |
| command_id | S | `room/load/data-ts/sent-ms` |
| roundtrip_ms | D | server clock: command published → acknowledgement received |
| loop_latency_ms | D | node clock: telemetry published → actuator applied the resulting command |
| status | D | SENT / ACKED / REJECTED / NO_ACK (no ack within 5 s) |

## Experiment outputs (`results/`)

| File | Kind | Content |
|---|---|---|
| model_comparison.csv, energy_comparison.csv | D | predictive + computational metrics per model |
| savings_results.csv, savings_comfort.csv | S | recorded-energy counterfactual, per load, controller, occupancy source, sensitivity |
| closed_loop_results.csv | S | grey-box room simulation: energy, comfort, CO₂, switching per controller |
| figures/*.png | – | plots of the above |

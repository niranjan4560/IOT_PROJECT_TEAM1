-- Smart Classroom SQLite schema (single source of truth).
-- Applied by Node-RED at start-up (the "SQL: create tables" node is generated from this file) and by
-- `python init_db.py`. Every statement is idempotent (CREATE ... IF NOT EXISTS).
-- Time columns: `ts` = data time, ISO 8601 text with +08:00 (text order = time order);
--               `*_at` = wall-clock time, ISO 8601 +08:00;  `*_ms` = Unix epoch milliseconds.
-- Kinds: [M] measured (ROBOD)  [D] derived  [P] predicted  [S] simulated.

CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT NOT NULL, ts TEXT NOT NULL, source TEXT,
  sent_at_ms INTEGER,                 -- [S] when the IoT node published (node clock)
  wifi_devices REAL,                  -- [M] count
  co2_ppm REAL,                       -- [M] ppm
  sound_db REAL,                      -- [M] dB
  humidity_pct REAL,                  -- [M] %RH
  temperature_c REAL,                 -- [M] degC
  illuminance_lux REAL,               -- [M] lux
  setpoint_c REAL,                    -- [M] degC (recorded BMS setpoint)
  outdoor_temp_c REAL,                -- [M] degC
  lighting_kwh REAL,                  -- [M] kWh electrical per 5 min
  fcu_fan_kwh REAL,                   -- [M] kWh electrical per 5 min
  plug_kwh REAL,                      -- [M] kWh electrical per 5 min
  chilled_water_kwh_thermal REAL,     -- [M] kWh THERMAL per 5 min (never added to electrical energy)
  occupant_presence INTEGER,          -- [M] camera ground truth, never a model input
  occupant_count REAL,                -- [M] camera ground truth, never a model input
  received_at TEXT NOT NULL,
  UNIQUE(room_id, ts)
);

CREATE TABLE IF NOT EXISTS predictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT NOT NULL, ts TEXT NOT NULL,
  model TEXT NOT NULL, category TEXT,  -- traditional / ensemble / deep_learning
  probability REAL,                   -- [P] P(occupied now)
  latency_ms REAL,                    -- inference time inside the ML service
  UNIQUE(room_id, ts, model)
);

CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT NOT NULL, ts TEXT NOT NULL,
  primary_model TEXT, occupancy_probability REAL, occupied INTEGER,
  p_arrival_30min REAL,               -- [P]
  predicted_next_lighting_kwh REAL,   -- [P] electrical
  predicted_next_chilled_water_kwh_thermal REAL,  -- [P] thermal
  ac_controller TEXT,                 -- rules / dqn
  dqn_ac_action TEXT,                 -- [P] Dueling-DQN recommendation before the safety layer
  light_cmd TEXT NOT NULL, ac_cmd TEXT NOT NULL,  -- [S] commands
  reason TEXT NOT NULL,
  UNIQUE(room_id, ts)
);

CREATE TABLE IF NOT EXISTS commands (
  command_id TEXT PRIMARY KEY,        -- room/load/data-ts
  room_id TEXT NOT NULL, load TEXT NOT NULL, cmd TEXT NOT NULL, reason TEXT,
  data_ts TEXT,                       -- data time of the reading that caused the command
  sent_at TEXT NOT NULL, sent_at_ms INTEGER NOT NULL,          -- server clock
  telemetry_sent_at_ms INTEGER,       -- node clock (copied from the telemetry)
  status TEXT NOT NULL,               -- SENT / ACKED / REJECTED / NO_ACK / ACKED_LATE (ack after the NO_ACK timeout)
  ack_state TEXT, ack_received_at TEXT,
  roundtrip_ms REAL,                  -- server clock: command published -> acknowledgement received
  loop_latency_ms REAL                -- node clock: telemetry published -> actuator applied the command
);

CREATE TABLE IF NOT EXISTS actuator_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT NOT NULL, load TEXT NOT NULL,
  state TEXT, previous TEXT, accepted INTEGER,   -- [S] simulated actuator state
  command_id TEXT, command_ts TEXT, ack_ts TEXT, received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT, type TEXT NOT NULL, message TEXT, ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL, created_at TEXT NOT NULL,
  task TEXT NOT NULL,                 -- occupancy / energy / arrival / dqn
  model TEXT NOT NULL, category TEXT,
  split TEXT NOT NULL,                -- validation / test / room2 / compute
  metric TEXT NOT NULL, value REAL
);

CREATE TABLE IF NOT EXISTS experiment_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL, created_at TEXT NOT NULL,
  experiment TEXT NOT NULL, scenario TEXT NOT NULL,
  metric TEXT NOT NULL, value REAL, unit TEXT
);

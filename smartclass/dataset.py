"""Read ROBOD lecture-room CSVs, label every field, and build leak-free features and splits.

Field kinds used throughout the project:
  MEASURED  - recorded by a ROBOD sensor or meter
  DERIVED   - computed from measured values (only past/current values; never future ones)
  PREDICTED - produced by a model
  SIMULATED - produced by our simulator (actuator states, controlled energy, room model)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from smartclass.features import SGT

# ROBOD column -> project name, with unit and kind.
FIELDS = {
    "wifi_connected_devices": ("wifi_devices", "count", "MEASURED"),
    "indoor_co2": ("co2_ppm", "ppm", "MEASURED"),
    "sound_pressure_level": ("sound_db", "dB", "MEASURED"),
    "indoor_relative_humidity": ("humidity_pct", "%RH", "MEASURED"),
    "air_temperature": ("temperature_c", "degC", "MEASURED"),
    "illuminance": ("illuminance_lux", "lux", "MEASURED"),
    "temp_setpoint": ("setpoint_c", "degC", "MEASURED"),
    "dry_bulb_temp": ("outdoor_temp_c", "degC", "MEASURED"),
    "outdoor_co2": ("outdoor_co2_ppm", "ppm", "MEASURED"),
    "global_horizontal_solar_radiation": ("solar_wm2", "W/m2", "MEASURED"),
    "fcu_fan_speed": ("fcu_fan_speed", "% (raw BMS value)", "MEASURED"),
    "lighting_energy": ("lighting_kwh", "kWh electrical per 5 min", "MEASURED"),
    "fcu_fan_energy": ("fcu_fan_kwh", "kWh electrical per 5 min", "MEASURED"),
    "plug_load_energy": ("plug_kwh", "kWh electrical per 5 min", "MEASURED"),
    "chilled_water_energy": ("chilled_water_kwh", "kWh THERMAL per 5 min", "MEASURED"),
    "occupant_presence": ("occupant_presence", "0/1 camera label", "MEASURED"),
    "occupant_count": ("occupant_count", "people, camera label", "MEASURED"),
}
RAW_TO_APP = {raw: name for raw, (name, _, _) in FIELDS.items()}

STEP_MINUTES = 5
STEPS_IN_30_MIN = 6
TEST_DATES_SEED = 42


def read_room_csv(path: str | Path, room_id: str = "room1") -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = {"timestamp", *RAW_TO_APP} - set(frame.columns)
    if missing:
        raise ValueError(f"ROBOD CSV is missing columns: {', '.join(sorted(missing))}")
    frame = frame[["timestamp", *RAW_TO_APP]].rename(columns=RAW_TO_APP)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], format="%Y-%m-%d %H:%M %z").dt.tz_convert(SGT)
    if not frame["timestamp"].is_monotonic_increasing:
        frame = frame.sort_values("timestamp")
    frame = frame.drop_duplicates("timestamp").reset_index(drop=True)
    frame["room_id"] = room_id
    frame["date"] = frame["timestamp"].dt.date.astype(str)
    frame["hour"] = frame["timestamp"].dt.hour
    frame["minute_of_day"] = frame["hour"] * 60 + frame["timestamp"].dt.minute
    frame["day_of_week"] = frame["timestamp"].dt.weekday  # Monday = 0 ... Friday = 4
    frame["slot"] = frame["hour"] * 2 + frame["timestamp"].dt.minute // 30
    # A new segment starts whenever the 5-minute sequence is broken (weekends, the Oct-Dec gap).
    gap = frame["timestamp"].diff() != pd.Timedelta(minutes=STEP_MINUTES)
    frame["segment"] = gap.cumsum()
    return frame


def add_targets(frame: pd.DataFrame) -> pd.DataFrame:
    """Targets only (never used as inputs): next-step energy and 'occupied within the next 30 min'."""
    frame = frame.copy()
    by_day = frame.groupby("date")
    frame["next_lighting_kwh"] = by_day["lighting_kwh"].shift(-1)
    frame["next_chilled_water_kwh"] = by_day["chilled_water_kwh"].shift(-1)
    future = pd.concat([by_day["occupant_presence"].shift(-k) for k in range(1, STEPS_IN_30_MIN + 1)], axis=1)
    frame["occupied_next_30min"] = future.max(axis=1).where(future.notna().all(axis=1))
    return frame


def split_dates(frame: pd.DataFrame, test_size: float = 0.2, val_days: int = 4, seed: int = TEST_DATES_SEED):
    """Whole-day split: test dates (same 6 as earlier versions), then validation dates from the rest."""
    from sklearn.model_selection import GroupShuffleSplit

    dates = np.array(sorted(frame["date"].unique()))
    train_idx, test_idx = next(GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
                               .split(dates, groups=dates))
    rest = dates[train_idx]
    rng = np.random.default_rng(seed)
    val = sorted(rng.choice(rest, size=val_days, replace=False).tolist())
    train = sorted(d for d in rest.tolist() if d not in val)
    return train, val, sorted(dates[test_idx].tolist())

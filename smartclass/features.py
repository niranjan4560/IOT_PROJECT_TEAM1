"""Feature definitions and the single timestamp rule used by every Python component.

Timestamp rule: ISO 8601 in Singapore time, e.g. "2021-09-07T09:10:00+08:00" (ROBOD's own clock).

Leakage rule: every feature at time t uses readings at t or earlier only. Rolling statistics are
computed inside one contiguous 5-minute segment, so they never reach across a weekend gap.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

SGT = timezone(timedelta(hours=8))

# Raw sensors every occupancy model may use (camera labels are NEVER inputs).
SENSORS = ["wifi_devices", "co2_ppm", "sound_db", "humidity_pct", "temperature_c", "illuminance_lux"]
TIME = ["hour_sin", "hour_cos", "day_of_week"]

# Sequence models (LSTM, Mamba) see the last SEQ_LEN readings of SENSORS + TIME.
SEQ_LEN = 12  # 12 x 5 min = 1 hour
SEQUENCE_FEATURES = SENSORS + TIME

# Tabular models see the current reading plus past-only summaries of the same window.
TABULAR_FEATURES = SENSORS + TIME + [
    "wifi_mean_30min", "co2_delta_15min", "co2_delta_window", "sound_max_30min", "temp_delta_15min",
]

# Energy forecasting inputs (current energy is included so the model is compared fairly with persistence).
ENERGY_FEATURES = ["wifi_devices", "co2_ppm", "temperature_c", "illuminance_lux", "outdoor_temp_c",
                   "setpoint_c", "hour_sin", "hour_cos", "day_of_week", "lighting_kwh", "chilled_water_kwh"]
ENERGY_TARGETS = ["next_lighting_kwh", "next_chilled_water_kwh"]


def to_sgt(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace(" +", "+")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SGT)
    return parsed.astimezone(SGT)


def to_sgt_iso(value: Any) -> str:
    return to_sgt(value).isoformat(timespec="seconds")


def finite_number(value: Any, default: float | None = 0.0) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if np.isfinite(number) else default


def add_time_features(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    minutes = frame["timestamp"].dt.hour * 60 + frame["timestamp"].dt.minute
    frame["hour_sin"] = np.sin(2 * np.pi * minutes / 1440)
    frame["hour_cos"] = np.cos(2 * np.pi * minutes / 1440)
    frame["day_of_week"] = frame["timestamp"].dt.weekday
    return frame


def add_history_features(frame: pd.DataFrame) -> pd.DataFrame:
    """DERIVED features from past readings only (within one contiguous segment).

    Missing sensor values are forward-filled from the PAST only (never back-filled); a row whose
    sensors are still missing after that is marked invalid and is not used for training or scoring.
    """
    frame = add_time_features(frame)
    seg = frame.groupby("segment")
    filled = seg[SENSORS].ffill()
    frame["sensor_missing"] = frame[SENSORS].isna().any(axis=1)  # raw reading had a gap (flag only)
    for col in SENSORS:
        frame[col + "_filled"] = filled[col]
    g = frame.groupby("segment")
    frame["wifi_mean_30min"] = g["wifi_devices_filled"].transform(lambda s: s.rolling(6, min_periods=1).mean())
    frame["co2_delta_15min"] = frame["co2_ppm_filled"] - g["co2_ppm_filled"].shift(3)
    frame["co2_delta_window"] = frame["co2_ppm_filled"] - g["co2_ppm_filled"].shift(SEQ_LEN - 1)  # first-to-last of the 1 h window
    frame["sound_max_30min"] = g["sound_db_filled"].transform(lambda s: s.rolling(6, min_periods=1).max())
    frame["temp_delta_15min"] = frame["temperature_c_filled"] - g["temperature_c_filled"].shift(3)
    position = g.cumcount()
    frame["has_full_window"] = position >= SEQ_LEN - 1
    for col in SENSORS:
        frame[col] = frame[col + "_filled"]
    frame = frame.drop(columns=[c + "_filled" for c in SENSORS])
    frame["features_valid"] = frame[TABULAR_FEATURES].notna().all(axis=1) & frame["has_full_window"]
    return frame


def build_windows(frame: pd.DataFrame, rows: np.ndarray) -> np.ndarray:
    """Return (len(rows), SEQ_LEN, n_features) windows ending at each row (rows must have full windows)."""
    values = frame[SEQUENCE_FEATURES].to_numpy(dtype=np.float32)
    offsets = np.arange(-SEQ_LEN + 1, 1)
    return values[rows[:, None] + offsets[None, :]]


def tabular_from_window(window: pd.DataFrame) -> dict[str, float]:
    """Live version of the DERIVED features: same definitions as add_history_features, computed from
    the last SEQ_LEN readings held by the ML service (oldest first, newest last)."""
    last = window.iloc[-1]
    row = {name: float(last[name]) for name in SENSORS + TIME}
    row["wifi_mean_30min"] = float(window["wifi_devices"].iloc[-6:].mean())
    row["co2_delta_15min"] = float(last["co2_ppm"] - window["co2_ppm"].iloc[-4])
    row["co2_delta_window"] = float(last["co2_ppm"] - window["co2_ppm"].iloc[0])
    row["sound_max_30min"] = float(window["sound_db"].iloc[-6:].max())
    row["temp_delta_15min"] = float(last["temperature_c"] - window["temperature_c"].iloc[-4])
    return row


def reading_time_features(timestamp: Any) -> dict[str, float]:
    ts = to_sgt(timestamp)
    minutes = ts.hour * 60 + ts.minute
    return {"hour_sin": float(np.sin(2 * np.pi * minutes / 1440)),
            "hour_cos": float(np.cos(2 * np.pi * minutes / 1440)),
            "day_of_week": float(ts.weekday())}

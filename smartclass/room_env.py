"""SIMULATED classroom: grey-box thermal + CO2 model used to train and evaluate HVAC controllers.

Why a grey-box model: we tried to identify the room's temperature and CO2 dynamics from ROBOD itself
(linear regression of the 5/30/60-minute change on outdoor-indoor difference, metered cooling, occupants and
solar radiation). It explained almost nothing (R^2 = 0.004 at 5 min, <= 0.044 at 60 min) and the cooling
coefficient had the wrong sign, because cooling is metered in 1-kWh steps and runs mostly in the hottest hours.
ROBOD therefore cannot support a learned plant model, so the plant below uses DECLARED, ASSUMED parameters.
Real ROBOD rows supply the exogenous inputs (outdoor temperature, solar radiation, outdoor CO2, the camera
occupant count) and the starting temperature/CO2 of each day. All outputs of this module are SIMULATED.

Calibration of the ASSUMED parameters (training dates only): the free-running (AC OFF) room should stay
physically plausible (median daily maximum ~30 C) and 24/7 COMFORT should need cooling energy of the same order
as ROBOD's recorded chilled-water energy (~130 kWh thermal per day), which requires the outdoor-air load term.

Thermal model (first-order RC, 5-minute step, ideal thermostat per AC mode):
  T_free = T + dt/C * [UA (T_out - T) + q_person * n + a_solar * G_solar + q_light]
  if mode != OFF and T_free > T_set(mode): cooling Q = min(Q_max, (T_free - T_set) * C / dt), T = T_free - Q dt / C
  cooling energy (thermal) = (Q + outdoor-air load while the fan runs) * dt
CO2 model (well-mixed mass balance):
  C_next = C + dt * [n * g_person * 1e6 / V - (Q_vent / V) * (C - C_out)],  Q_vent = fan-on or infiltration
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

AC_ACTIONS = ["OFF", "ECO", "COMFORT", "BOOST"]


@dataclass
class RoomParams:  # assumed values for a ~150 m2 tropical lecture room; change here and re-run experiments
    dt_s: float = 300.0
    capacitance_j_per_k: float = 8.0e6      # effective (air + furniture + structure)
    ua_w_per_k: float = 200.0               # envelope + infiltration conductance
    q_person_w: float = 75.0                # sensible heat per occupant
    solar_aperture_m2: float = 0.5          # effective solar gain area (W per W/m2), shaded windows
    q_light_w: float = 800.0                # lighting heat while occupied
    cooling_max_w: float = 15000.0          # fan-coil capacity (~1.25 kWh thermal per 5 min)
    outdoor_air_load_w: float = 4500.0      # sensible+latent load of humid outdoor air while the fan runs
    setpoints_c: tuple = (26.0, 24.0, 23.0)  # ECO, COMFORT, BOOST
    volume_m3: float = 500.0
    co2_per_person_m3_s: float = 5.2e-6     # ~0.31 L/min per seated adult
    vent_fan_m3_s: float = 0.5              # outdoor-air supply while the fan coil runs
    vent_infiltration_m3_s: float = 0.05
    fan_kwh_per_step: float = 0.0217        # MEASURED median ROBOD FCU fan energy per 5 min when running
    comfort_low_c: float = 23.0
    comfort_high_c: float = 26.0
    co2_limit_ppm: float = 1000.0


@dataclass
class RewardWeights:
    cop: float = 3.5            # converts thermal cooling kWh to electrical-equivalent kWh FOR THE REWARD ONLY
    comfort_per_k: float = 0.5  # penalty per K outside the comfort band per occupied step
    co2_per_100ppm: float = 0.3


class ClassroomEnv:
    """One episode = one recorded day (288 five-minute steps)."""

    def __init__(self, day: pd.DataFrame, occupancy_prob: np.ndarray, arrival_prob: np.ndarray,
                 params: RoomParams | None = None, weights: RewardWeights | None = None):
        self.day = day.reset_index(drop=True)
        self.occupancy_prob = np.nan_to_num(np.asarray(occupancy_prob, dtype=float), nan=0.0)
        self.arrival_prob = np.nan_to_num(np.asarray(arrival_prob, dtype=float), nan=0.0)
        self.p = params or RoomParams()
        self.w = weights or RewardWeights()
        self.reset()

    def reset(self) -> np.ndarray:
        self.t = 0
        first = self.day.iloc[0]
        self.temp = float(first["temperature_c"]) if pd.notna(first["temperature_c"]) else 26.0
        self.co2 = float(first["co2_ppm"]) if pd.notna(first["co2_ppm"]) else 450.0
        return self.observation()

    @property
    def done(self) -> bool:
        return self.t >= len(self.day)

    def observation(self) -> np.ndarray:
        """What a controller may see: PREDICTED occupancy, arrival profile, measured-style T/CO2, time."""
        row = self.day.iloc[min(self.t, len(self.day) - 1)]
        minutes = row["hour"] * 60 + row["timestamp"].minute
        return np.array([
            self.occupancy_prob[min(self.t, len(self.day) - 1)],
            self.arrival_prob[min(self.t, len(self.day) - 1)],
            (self.temp - 24.0) / 3.0,
            (self.co2 - 600.0) / 400.0,
            (float(row["outdoor_temp_c"]) - 28.0) / 4.0,
            np.sin(2 * np.pi * minutes / 1440),
            np.cos(2 * np.pi * minutes / 1440),
        ], dtype=np.float32)

    def step(self, action: str) -> tuple[np.ndarray, float, dict]:
        p, row = self.p, self.day.iloc[self.t]
        people = float(row["occupant_count"]) if pd.notna(row["occupant_count"]) else 0.0
        occupied = people > 0
        solar = float(row["solar_wm2"]) if pd.notna(row["solar_wm2"]) else 0.0
        gains = p.ua_w_per_k * (float(row["outdoor_temp_c"]) - self.temp) + p.q_person_w * people \
            + p.solar_aperture_m2 * solar + (p.q_light_w if occupied else 0.0)
        t_free = self.temp + p.dt_s / p.capacitance_j_per_k * gains
        cooling_w = 0.0
        if action != "OFF":
            setpoint = p.setpoints_c[AC_ACTIONS.index(action) - 1]
            if t_free > setpoint:
                cooling_w = min(p.cooling_max_w, (t_free - setpoint) * p.capacitance_j_per_k / p.dt_s)
        self.temp = t_free - cooling_w * p.dt_s / p.capacitance_j_per_k
        vent = p.vent_fan_m3_s if action != "OFF" else p.vent_infiltration_m3_s
        c_out = float(row["outdoor_co2_ppm"]) if pd.notna(row["outdoor_co2_ppm"]) else 450.0
        self.co2 += p.dt_s * (people * p.co2_per_person_m3_s * 1e6 / p.volume_m3 - vent / p.volume_m3 * (self.co2 - c_out))
        cooling_kwh = (cooling_w + (p.outdoor_air_load_w if action != "OFF" else 0.0)) * p.dt_s / 3.6e6
        fan_kwh = p.fan_kwh_per_step if action != "OFF" else 0.0
        too_hot = max(0.0, self.temp - p.comfort_high_c)
        too_cold = max(0.0, p.comfort_low_c - self.temp)
        co2_excess = max(0.0, self.co2 - p.co2_limit_ppm)
        reward = -(cooling_kwh / self.w.cop + fan_kwh)
        if occupied:
            reward -= self.w.comfort_per_k * (too_hot + too_cold) + self.w.co2_per_100ppm * co2_excess / 100.0
        info = {"cooling_kwh_thermal": cooling_kwh, "fan_kwh": fan_kwh, "temp_c": self.temp, "co2_ppm": self.co2,
                "occupied": occupied, "comfort_violation_k": (too_hot + too_cold) if occupied else 0.0,
                "co2_violation": occupied and co2_excess > 0}
        self.t += 1
        return self.observation(), reward, info


def params_dict() -> dict:
    return {"room": asdict(RoomParams()), "reward": asdict(RewardWeights())}

"""Live inference: keeps a 1-hour window per room and runs every model on each validated reading.

Safety behaviour (Stage 6 relies on it):
  * a model that fails to load or to predict is skipped and listed under "unavailable";
  * the primary model falls back to the next model in FALLBACK_ORDER, so a probability is almost always sent;
  * until a room has SEQ_LEN consecutive readings the window is padded with the oldest reading and
    "warming_up" is true (the decision engine can see this);
  * a gap in the 5-minute sequence (new replay, injector reading) restarts the window.
"""
from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from smartclass.dqn import DuelingDQNController, dqn_observation
from smartclass.features import (ENERGY_FEATURES, SENSORS, SEQ_LEN, SEQUENCE_FEATURES, TABULAR_FEATURES,
                                 finite_number, reading_time_features, tabular_from_window, to_sgt)
from smartclass.registry import load_bundle

FALLBACK_ORDER = ["random_forest", "gradient_boosting", "logistic_regression", "decision_tree", "lstm", "mamba"]


class LivePredictor:
    def __init__(self, folder: str | Path = "models/final", primary: str | None = None):
        import torch
        torch.set_num_threads(1)  # one reading at a time: extra threads only add contention on a laptop
        folder = Path(folder)
        bundle = load_bundle(folder)
        self.manifest = bundle["manifest"]
        self.models = bundle["occupancy"]
        self.load_errors = bundle["load_errors"]
        self.energy = bundle["energy"]
        self.profile = bundle["profile"]
        self.primary = primary or self.manifest["primary_model"]
        self.dqn = None
        dqn_path = (folder / self.manifest["dqn_file"]).resolve()
        try:
            self.dqn = DuelingDQNController.load(dqn_path)
        except Exception as exc:  # recoverable: Node-RED then uses its rule-based AC logic
            self.load_errors["dueling_dqn"] = repr(exc)
        self.windows: dict[str, deque] = {}

    # ------------------------------------------------------------------ window handling
    def _push(self, room: str, reading: dict) -> tuple[pd.DataFrame, bool]:
        ts = to_sgt(reading["timestamp"])
        window = self.windows.setdefault(room, deque(maxlen=SEQ_LEN))
        if window and (ts - window[-1]["_ts"]).total_seconds() != 300:
            window.clear()  # not the next 5-minute step: start a new window
        row = {name: finite_number(reading.get(name), None) for name in SENSORS}
        row.update(reading_time_features(ts))
        row["_ts"] = ts
        window.append(row)
        rows = list(window)
        warming_up = len(rows) < SEQ_LEN
        if warming_up:
            rows = [rows[0]] * (SEQ_LEN - len(rows)) + rows
        return pd.DataFrame(rows), warming_up

    # ------------------------------------------------------------------ prediction
    def predict(self, room: str, reading: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        frame, warming_up = self._push(room, reading)
        out: dict[str, Any] = {"models": {}, "unavailable": dict(self.load_errors), "warming_up": warming_up}
        if frame[SENSORS].iloc[-1].isna().any():
            out["unavailable"]["all"] = "current reading has a missing sensor value"
        else:
            tab = pd.DataFrame([tabular_from_window(frame)], columns=TABULAR_FEATURES).astype("float32")
            seq = frame[SEQUENCE_FEATURES].to_numpy(dtype=np.float32)[None, :, :]
            for name, model in self.models.items():
                info = self.manifest["occupancy_models"][name]
                t0 = time.perf_counter()
                try:
                    p = float(model.predict_proba(seq if info["kind"] == "sequence" else tab)[0, 1])
                    out["models"][name] = {"p": round(p, 4), "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                                           "category": info["category"]}
                except Exception as exc:
                    out["unavailable"][name] = repr(exc)
        chosen = next((m for m in [self.primary] + FALLBACK_ORDER if m in out["models"]), None)
        out["primary_model"] = chosen
        out["primary_fallback"] = chosen is not None and chosen != self.primary
        out["occupancy_probability"] = out["models"][chosen]["p"] if chosen else None
        out["predicted_occupancy"] = None if chosen is None else int(out["occupancy_probability"] >= 0.5)

        ts = to_sgt(reading["timestamp"])
        cell = self.profile.get(f"{ts.weekday()}-{ts.hour * 2 + ts.minute // 30}")
        out["p_arrival_30min"] = float(cell["p"]) if cell else 0.0

        energy_row = {**{n: finite_number(reading.get(n), None) for n in ENERGY_FEATURES}, **reading_time_features(ts)}
        if all(energy_row[n] is not None for n in ENERGY_FEATURES):
            light, cool = self.energy.predict(pd.DataFrame([energy_row], columns=ENERGY_FEATURES))[0]
            out["predicted_next_lighting_kwh"] = round(max(0.0, float(light)), 5)
            out["predicted_next_chilled_water_kwh_thermal"] = round(max(0.0, float(cool)), 5)
        else:
            out["predicted_next_lighting_kwh"] = out["predicted_next_chilled_water_kwh_thermal"] = None

        # Dueling DQN (algorithm B) observes the LSTM occupancy probability, as in Hou et al.
        dqn_input = "lstm" if "lstm" in out["models"] else chosen
        out["dqn_input_model"] = dqn_input
        out["dqn_ac_action"] = None
        temp, co2, t_out = (finite_number(reading.get(k), None) for k in ("temperature_c", "co2_ppm", "outdoor_temp_c"))
        if self.dqn is not None and dqn_input is not None and None not in (temp, co2, t_out):
            obs = dqn_observation(out["models"][dqn_input]["p"], out["p_arrival_30min"], temp, co2, t_out,
                                  ts.hour * 60 + ts.minute)
            out["dqn_ac_action"] = self.dqn.act(obs)
        out["ml_latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
        return out

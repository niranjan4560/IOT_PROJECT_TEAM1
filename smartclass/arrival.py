"""Arrival profile for pre-cooling: P(someone arrives within 30 min | room empty now), weekday x half-hour."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupKFold

THRESHOLD_CANDIDATES = [0.2, 0.3, 0.4, 0.5]


def build_profile(frame: pd.DataFrame) -> dict:
    rows = frame.dropna(subset=["occupied_next_30min"])
    rows = rows[rows["occupant_presence"] == 0]
    table = rows.groupby(["day_of_week", "slot"])["occupied_next_30min"].agg(["mean", "count"])
    return {f"{int(d)}-{int(s)}": {"p": round(float(r["mean"]), 4), "n": int(r["count"])} for (d, s), r in table.iterrows()}


def lookup(profile: dict, day_of_week: int, slot: int) -> float:
    cell = profile.get(f"{int(day_of_week)}-{int(slot)}")
    return cell["p"] if cell else 0.0  # weekends / unseen slots: no evidence of arrivals


def lookup_frame(profile: dict, frame: pd.DataFrame) -> np.ndarray:
    return np.array([lookup(profile, d, s) for d, s in zip(frame["day_of_week"], frame["slot"])])


def choose_threshold(train_frame: pd.DataFrame) -> dict:
    """5-fold cross-validation by date on TRAINING dates only."""
    empty = train_frame.dropna(subset=["occupied_next_30min"])
    empty = empty[empty["occupant_presence"] == 0].reset_index(drop=True)
    scores = {}
    for threshold in THRESHOLD_CANDIDATES:
        f1s = []
        for tr, te in GroupKFold(n_splits=5).split(empty, groups=empty["date"]):
            p = lookup_frame(build_profile(empty.loc[tr]), empty.loc[te])
            f1s.append(f1_score(empty.loc[te, "occupied_next_30min"].astype(int), p >= threshold, zero_division=0))
        scores[str(threshold)] = round(float(np.mean(f1s)), 4)
    return {"inner_cv_f1_by_threshold": scores, "chosen_threshold": float(max(scores, key=scores.get))}

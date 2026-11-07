"""Areas 3-4: model training/inference (all three categories + both research methods), reproducible evaluation."""
import json

import numpy as np
import pandas as pd
import pytest

from conftest import ROOT, needs_data, needs_models
from smartclass.deep_models import SequenceClassifier, TrainConfig
from smartclass.dqn import DuelingDQNController, DuelingQNet, dqn_observation
from smartclass.features import SEQUENCE_FEATURES, TABULAR_FEATURES, build_windows
from smartclass.registry import DEPLOYABLE, OCCUPANCY_MODELS
from smartclass.room_env import AC_ACTIONS, ClassroomEnv

pytestmark = needs_data


@pytest.fixture(scope="module")
def small(room1_features):
    f = room1_features
    rows = np.where(f["features_valid"] & ~f["sensor_missing"])[0]
    return f, rows[:1500], rows[1500:2000]


def test_every_category_trains_and_predicts(small):
    f, tr, te = small
    y = f["occupant_presence"].astype(int).to_numpy()
    categories = set()
    for name, (category, kind, _, factory) in OCCUPANCY_MODELS.items():
        model = factory()
        x_tr = build_windows(f, tr) if kind == "sequence" else f.loc[tr, TABULAR_FEATURES]
        x_te = build_windows(f, te) if kind == "sequence" else f.loc[te, TABULAR_FEATURES]
        model.fit(x_tr, y[tr], epochs=1) if kind == "sequence" else model.fit(x_tr, y[tr])
        p = model.predict_proba(x_te)
        assert p.shape == (len(te), 2) and np.all((p >= 0) & (p <= 1)), name
        categories.add(category)
    assert categories == {"baseline", "traditional", "ensemble", "deep_learning"}


@pytest.mark.parametrize("arch", ["lstm", "mamba"])
def test_sequence_model_save_load_roundtrip(small, tmp_path, arch):
    f, tr, te = small
    y = f["occupant_presence"].astype(int).to_numpy()
    model = SequenceClassifier(len(SEQUENCE_FEATURES), TrainConfig(arch)).fit(build_windows(f, tr), y[tr], epochs=1)
    model.save(tmp_path / "m.pt")
    again = SequenceClassifier.load(tmp_path / "m.pt")
    np.testing.assert_allclose(model.predict_proba(build_windows(f, te)), again.predict_proba(build_windows(f, te)), atol=1e-6)


def test_deep_training_is_seeded(small):
    f, tr, te = small
    y = f["occupant_presence"].astype(int).to_numpy()
    a = SequenceClassifier(len(SEQUENCE_FEATURES), TrainConfig("lstm")).fit(build_windows(f, tr), y[tr], epochs=1)
    b = SequenceClassifier(len(SEQUENCE_FEATURES), TrainConfig("lstm")).fit(build_windows(f, tr), y[tr], epochs=1)
    np.testing.assert_allclose(a.predict_proba(build_windows(f, te)), b.predict_proba(build_windows(f, te)), atol=1e-6)


def test_dueling_head_and_environment(room1):
    q = DuelingQNet()
    import torch
    out = q(torch.zeros(3, 7))
    assert out.shape == (3, len(AC_ACTIONS))
    day = room1[room1["date"] == room1["date"].iloc[0]]
    env = ClassroomEnv(day, np.zeros(len(day)), np.zeros(len(day)))
    obs = env.reset()
    assert obs.shape == (7,)
    _, reward, info = env.step("OFF")
    assert info["cooling_kwh_thermal"] == 0 and info["fan_kwh"] == 0 and reward <= 0
    _, _, info = env.step("COMFORT")
    assert info["cooling_kwh_thermal"] > 0  # outdoor-air load at least
    assert DuelingDQNController().act(dqn_observation(0.9, 0.0, 27, 600, 30, 600)) in AC_ACTIONS


@needs_models
def test_training_report_complete_and_consistent():
    report = json.loads((ROOT / "models/training_report.json").read_text())
    assert set(OCCUPANCY_MODELS) == set(report["occupancy"])
    for name, entry in report["occupancy"].items():
        for split in ("validation", "test"):
            assert {"accuracy", "precision", "recall", "f1", "confusion_matrix_[[TN,FP],[FN,TP]]"} <= set(entry[split])
        assert {"train_seconds", "peak_memory_mb", "model_size_kb", "median_ms"} <= set(entry["compute"])
        cm = np.array(entry["test"]["confusion_matrix_[[TN,FP],[FN,TP]]"])
        assert cm.sum() == report["split"]["rows"]["test"]
    assert report["primary_occupancy_model"]["name"] == max(DEPLOYABLE, key=lambda m: report["occupancy"][m]["validation"]["f1"])
    for target in ("next_lighting_kwh", "next_chilled_water_kwh"):
        assert {"mae", "rmse", "r2"} <= set(report["energy"]["persistence_baseline"][target])
    table = pd.read_csv(ROOT / "results/model_comparison.csv")
    assert len(table) == len(OCCUPANCY_MODELS)


@needs_models
def test_live_predictor_runs_all_models_and_falls_back(room1):
    from smartclass.predictor import LivePredictor
    from smartclass.features import to_sgt_iso
    lp = LivePredictor(ROOT / "models/final")
    assert set(lp.models) == set(DEPLOYABLE) and lp.dqn is not None
    out = None
    for _, row in room1.iloc[100:114].iterrows():
        reading = {k: (None if pd.isna(row[k]) else float(row[k])) for k in
                   ["wifi_devices", "co2_ppm", "sound_db", "humidity_pct", "temperature_c", "illuminance_lux", "setpoint_c",
                    "outdoor_temp_c", "lighting_kwh", "chilled_water_kwh"]}
        reading["timestamp"] = to_sgt_iso(row["timestamp"])
        out = lp.predict("room1", reading)
    assert set(out["models"]) == set(DEPLOYABLE) and not out["warming_up"]
    assert out["dqn_ac_action"] in AC_ACTIONS and out["dqn_input_model"] == "lstm"
    lp.models.pop(lp.primary)  # simulate a broken primary model
    out = lp.predict("room1", {**reading, "timestamp": to_sgt_iso(room1["timestamp"].iloc[114])})
    assert out["primary_fallback"] and out["occupancy_probability"] is not None
    bad = lp.predict("room1", {**reading, "co2_ppm": None, "timestamp": to_sgt_iso(room1["timestamp"].iloc[115])})
    assert bad["occupancy_probability"] is None and "all" in bad["unavailable"]

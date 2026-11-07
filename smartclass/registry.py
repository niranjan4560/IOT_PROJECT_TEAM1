"""Model registry: every occupancy/energy model, its category in the reference architecture, and loading.

Categories (Stage 5 of the reference architecture):
  traditional   - logistic regression, decision tree, linear regression
  ensemble      - random forest, histogram gradient boosting
  deep_learning - LSTM (research algorithm B), Mamba selective SSM (research algorithm A)
  baseline      - majority class / mean / persistence (lower bounds, never deployed)
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.multioutput import MultiOutputRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from smartclass.deep_models import SequenceClassifier, TrainConfig
from smartclass.features import SEQUENCE_FEATURES

SEED = 42

OCCUPANCY_MODELS = {
    # name: (category, input kind, research tag, factory)
    "majority_class": ("baseline", "tabular", "", lambda: DummyClassifier(strategy="most_frequent")),
    "logistic_regression": ("traditional", "tabular", "", lambda: make_pipeline(
        StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced"))),
    "decision_tree": ("traditional", "tabular", "", lambda: DecisionTreeClassifier(
        max_depth=5, class_weight="balanced", random_state=SEED)),
    "random_forest": ("ensemble", "tabular", "", lambda: RandomForestClassifier(
        n_estimators=200, min_samples_leaf=5, class_weight="balanced", random_state=SEED, n_jobs=-1)),
    "gradient_boosting": ("ensemble", "tabular", "", lambda: HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.05, class_weight="balanced", random_state=SEED)),
    "lstm": ("deep_learning", "sequence", "B: Hou et al. 2025 (LSTM occupancy estimator)", lambda: SequenceClassifier(
        len(SEQUENCE_FEATURES), TrainConfig("lstm"), {"hidden": 32})),
    "mamba": ("deep_learning", "sequence", "A: OCC-Mamba family (Mamba selective SSM)", lambda: SequenceClassifier(
        len(SEQUENCE_FEATURES), TrainConfig("mamba"), {"d_model": 32, "layers": 2, "d_state": 8})),
}
DEPLOYABLE = [m for m, spec in OCCUPANCY_MODELS.items() if spec[0] != "baseline"]

ENERGY_MODELS = {
    "linear_regression": ("traditional", lambda: LinearRegression()),
    "random_forest": ("ensemble", lambda: RandomForestRegressor(n_estimators=200, min_samples_leaf=5,
                                                                 random_state=SEED, n_jobs=-1)),
    "gradient_boosting": ("ensemble", lambda: MultiOutputRegressor(HistGradientBoostingRegressor(
        max_iter=200, learning_rate=0.05, random_state=SEED))),
}


def save_model(name: str, model, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    if OCCUPANCY_MODELS.get(name, ("", "tabular"))[1] == "sequence":
        path = folder / f"occupancy_{name}.pt"
        model.save(path)
    else:
        path = folder / f"occupancy_{name}.joblib"
        joblib.dump(model, path)
    return path


def load_bundle(folder: str | Path) -> dict:
    """Load manifest.json and every model it lists. A model that fails to load is skipped and reported."""
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    loaded, errors = {}, {}
    for name, info in manifest["occupancy_models"].items():
        try:
            path = folder / info["file"]
            model = SequenceClassifier.load(path) if info["kind"] == "sequence" else joblib.load(path)
            if hasattr(model, "n_jobs"):
                model.n_jobs = 1  # one reading at a time: a thread pool costs more than it saves
            loaded[name] = model
        except Exception as exc:  # recoverable: the service keeps running with the other models
            errors[name] = repr(exc)
    energy = joblib.load(folder / manifest["energy_model"]["file"])
    if hasattr(energy, "n_jobs"):
        energy.n_jobs = 1
    profile = json.loads((folder / "occupancy_profile.json").read_text(encoding="utf-8"))
    return {"manifest": manifest, "occupancy": loaded, "load_errors": errors, "energy": energy, "profile": profile}

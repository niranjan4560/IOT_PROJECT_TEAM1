"""Train and evaluate every model of the Analytics & ML stage, with baselines and computational metrics.

Run:  python train_models.py            (about 5-10 minutes on a laptop CPU)
      python train_models.py --quick    (tiny settings, for automated tests only)

Splits (whole dates, Room 1): 19 training dates, 4 validation dates (model selection, early stopping),
6 test dates (reported). Preprocessing (scalers) is fitted on training data only.

Writes:
  models/eval/   trained on TRAINING dates only -> used for every reported test metric and experiment
  models/final/  retrained on all 29 dates      -> used by the live ML service
  models/dqn_controller.pt                      -> Dueling-DQN HVAC policy (trained in the simulator)
  models/training_report.json, results/model_comparison.csv, results/energy_comparison.csv
  SQLite table model_metrics (storage/smartclass.db)
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, mean_absolute_error, mean_squared_error,
                             precision_score, r2_score, recall_score)
from sklearn.model_selection import GroupKFold

from smartclass import arrival
from smartclass.dataset import add_targets, read_room_csv, split_dates
from smartclass.db import import_training_report
from smartclass.deep_models import SequenceClassifier, TrainConfig
from smartclass.dqn import DuelingDQNController
from smartclass.features import (ENERGY_FEATURES, ENERGY_TARGETS, SEQ_LEN, SEQUENCE_FEATURES, TABULAR_FEATURES,
                                 add_history_features, build_windows)
from smartclass.perf import PeakMemory, file_size_kb, latency_ms
from smartclass.registry import DEPLOYABLE, ENERGY_MODELS, OCCUPANCY_MODELS, SEED, save_model
from smartclass.room_env import ClassroomEnv, params_dict

ROOT = Path(__file__).resolve().parent
ROOM1, ROOM2 = ROOT / "data/combined_Room1.csv", ROOT / "data/combined_Room2.csv"
MODELS, RESULTS = ROOT / "models", ROOT / "results"


def classification(y, pred) -> dict:
    return {"accuracy": round(float(accuracy_score(y, pred)), 4), "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
            "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
            "confusion_matrix_[[TN,FP],[FN,TP]]": confusion_matrix(y, pred, labels=[0, 1]).tolist()}


def regression(y, pred) -> dict:
    return {"mae": round(float(mean_absolute_error(y, pred)), 5), "rmse": round(float(mean_squared_error(y, pred) ** 0.5), 5),
            "r2": round(float(r2_score(y, pred)), 4)}


def prepare(path: Path, room: str) -> pd.DataFrame:
    return add_history_features(add_targets(read_room_csv(path, room)))


def occupancy_rows(frame: pd.DataFrame, dates: list[str]) -> np.ndarray:
    ok = frame["features_valid"] & ~frame["sensor_missing"] & frame["occupant_presence"].notna()
    return np.where(ok & frame["date"].isin(dates))[0]


def inputs(frame: pd.DataFrame, kind: str, rows: np.ndarray):
    if kind == "sequence":
        return build_windows(frame, rows)
    return frame.loc[rows, TABULAR_FEATURES].astype("float32")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate all models")
    parser.add_argument("--quick", action="store_true", help="tiny settings for automated tests")
    args = parser.parse_args()
    run_id = datetime.now().strftime("train-%Y%m%d-%H%M%S") + ("-quick" if args.quick else "")
    np.random.seed(SEED)
    if not ROOM1.exists():
        raise SystemExit("ROBOD data is missing. Run `python download_data.py` first.")
    for folder in (MODELS / "eval", MODELS / "final", RESULTS):
        folder.mkdir(parents=True, exist_ok=True)

    frame = prepare(ROOM1, "room1")
    train_d, val_d, test_d = split_dates(frame)
    r_tr, r_va, r_te = (occupancy_rows(frame, d) for d in (train_d, val_d, test_d))
    r_all = occupancy_rows(frame, train_d + val_d + test_d)
    y = frame["occupant_presence"].astype(int).to_numpy()
    report: dict = {
        "run_id": run_id, "dataset": "ROBOD Room 1 (Tekler et al., Building Simulation 15(12), 2022)",
        "split": {"train_dates": train_d, "validation_dates": val_d, "test_dates": test_d,
                  "rows": {"train": len(r_tr), "validation": len(r_va), "test": len(r_te)},
                  "row_rule": "rows with a full 1-hour past window inside one contiguous segment and no missing current sensor"},
        "features": {"tabular": TABULAR_FEATURES, "sequence": SEQUENCE_FEATURES, "sequence_length": SEQ_LEN,
                     "energy": ENERGY_FEATURES},
        "occupancy": {}, "energy": {},
    }

    # ------------------------------------------------------------------ 1. occupancy (presence now)
    eval_models, epochs_used = {}, {}
    for name, (category, kind, research, factory) in OCCUPANCY_MODELS.items():
        model = factory()
        if args.quick and kind == "sequence":
            model.config.max_epochs = 2
        with PeakMemory() as mem:
            if kind == "sequence":
                model.fit(inputs(frame, kind, r_tr), y[r_tr], inputs(frame, kind, r_va), y[r_va])
            else:
                model.fit(inputs(frame, kind, r_tr), y[r_tr])
        val_pred = model.predict(inputs(frame, kind, r_va))
        test_pred = model.predict(inputs(frame, kind, r_te))
        path = save_model(name, model, MODELS / "eval")
        one = inputs(frame, kind, r_te[:1])
        if hasattr(model, "n_jobs"):
            model.n_jobs = 1  # latency is measured exactly as the live service predicts: one reading, one thread
        compute = {"train_seconds": round(mem.seconds, 2), "peak_memory_mb": round(mem.peak_mb_above_start, 1),
                   "model_size_kb": file_size_kb(path), **latency_ms(model.predict_proba, one, repeats=50 if args.quick else 200)}
        if kind == "sequence":
            compute["parameters"] = model.parameter_count()
            epochs_used[name] = max(model.best_epoch, 1)
            compute["best_epoch"] = epochs_used[name]
        eval_models[name] = model
        entry = {"category": category, "input": kind, "research": research, "validation": classification(y[r_va], val_pred),
                 "test": classification(y[r_te], test_pred), "compute": compute}
        report["occupancy"][name] = entry
        print(f"occupancy {name:20s} val F1 {entry['validation']['f1']:.3f}  test F1 {entry['test']['f1']:.3f}  "
              f"train {compute['train_seconds']:.1f}s  latency {compute['median_ms']:.2f} ms")
    primary = max(DEPLOYABLE, key=lambda m: report["occupancy"][m]["validation"]["f1"])
    report["primary_occupancy_model"] = {"name": primary, "rule": "highest validation F1 (test dates not used)"}

    # 5-fold-by-date check for every model on train+validation dates (robustness of the ranking)
    r_cv = occupancy_rows(frame, train_d + val_d)
    folds = list(GroupKFold(n_splits=3 if args.quick else 5).split(r_cv, groups=frame["date"].to_numpy()[r_cv]))
    for name, (category, kind, _, factory) in OCCUPANCY_MODELS.items():
        scores = []
        for tr_i, te_i in folds:
            m = factory()
            if kind == "sequence":
                m.fit(inputs(frame, kind, r_cv[tr_i]), y[r_cv[tr_i]], epochs=epochs_used[name])
            else:
                m.fit(inputs(frame, kind, r_cv[tr_i]), y[r_cv[tr_i]])
            scores.append(f1_score(y[r_cv[te_i]], m.predict(inputs(frame, kind, r_cv[te_i])), zero_division=0))
        report["occupancy"][name]["groupkfold_by_date_f1"] = {"mean": round(float(np.mean(scores)), 4),
                                                             "std": round(float(np.std(scores)), 4), "folds": len(folds)}

    # Room 2 (never trained on): cross-room generalisation of the eval models
    if ROOM2.exists():
        f2 = prepare(ROOM2, "room2")
        r2 = occupancy_rows(f2, sorted(f2["date"].unique()))
        y2 = f2["occupant_presence"].astype(int).to_numpy()
        for name, (category, kind, _, _) in OCCUPANCY_MODELS.items():
            res = classification(y2[r2], eval_models[name].predict(inputs(f2, kind, r2)))
            report["occupancy"][name]["room2_cross_room"] = res

    # Final models for the live service: all 29 dates (deep models: fixed epochs from early stopping)
    final_files = {}
    for name in DEPLOYABLE:
        category, kind, research, factory = OCCUPANCY_MODELS[name]
        m = factory()
        if kind == "sequence":
            m.fit(inputs(frame, kind, r_all), y[r_all], epochs=epochs_used[name])
        else:
            m.fit(inputs(frame, kind, r_all), y[r_all])
        final_files[name] = save_model(name, m, MODELS / "final").name

    # ------------------------------------------------------------------ 2. next-step energy
    ok_e = frame[ENERGY_FEATURES + ENERGY_TARGETS].notna().all(axis=1) & ~frame["sensor_missing"]
    e_tr = np.where(ok_e & frame["date"].isin(train_d + val_d))[0]
    e_te = np.where(ok_e & frame["date"].isin(test_d))[0]
    ex_tr, ex_te = frame.loc[e_tr, ENERGY_FEATURES], frame.loc[e_te, ENERGY_FEATURES]
    ey_tr, ey_te = frame.loc[e_tr, ENERGY_TARGETS].to_numpy(), frame.loc[e_te, ENERGY_TARGETS].to_numpy()
    current = frame.loc[e_te, ["lighting_kwh", "chilled_water_kwh"]].to_numpy()
    energy_preds = {"mean_baseline": np.tile(ey_tr.mean(0), (len(e_te), 1)), "persistence_baseline": current}
    energy_compute, energy_fitted = {}, {}
    for name, (category, factory) in ENERGY_MODELS.items():
        model = factory()
        with PeakMemory() as mem:
            model.fit(ex_tr, ey_tr)
        energy_preds[name] = model.predict(ex_te)
        energy_fitted[name] = model
        if hasattr(model, "n_jobs"):
            model.n_jobs = 1
        energy_compute[name] = {"train_seconds": round(mem.seconds, 2), "peak_memory_mb": round(mem.peak_mb_above_start, 1),
                                **latency_ms(model.predict, ex_te.iloc[:1], repeats=50)}
    for name, pred in energy_preds.items():
        category = ENERGY_MODELS.get(name, ("baseline",))[0]
        entry = {"category": category}
        for i, target in enumerate(ENERGY_TARGETS):
            entry[target] = regression(ey_te[:, i], pred[:, i])
        if name in energy_compute:
            entry["compute"] = energy_compute[name]
        report["energy"][name] = entry
    report["energy"]["units"] = "kWh per 5-minute interval; lighting is electrical, chilled water is THERMAL"
    deployed_energy = "random_forest"
    import joblib
    for folder in ("eval", "final"):
        model = energy_fitted[deployed_energy] if folder == "eval" else ENERGY_MODELS[deployed_energy][1]().fit(
            frame.loc[np.where(ok_e)[0], ENERGY_FEATURES], frame.loc[np.where(ok_e)[0], ENERGY_TARGETS].to_numpy())
        joblib.dump(model, MODELS / folder / "energy_random_forest.joblib")

    # ------------------------------------------------------------------ 3. arrival profile (pre-cooling)
    train_frame = frame[frame["date"].isin(train_d + val_d)]
    selection = arrival.choose_threshold(train_frame)
    profile_eval, profile_final = arrival.build_profile(train_frame), arrival.build_profile(frame)
    test_rows = frame[frame["date"].isin(test_d)].dropna(subset=["occupied_next_30min"])
    test_rows = test_rows[test_rows["occupant_presence"] == 0]
    truth = test_rows["occupied_next_30min"].astype(int).to_numpy()
    prob = arrival.lookup_frame(profile_eval, test_rows)
    report["arrival_profile"] = {"threshold_selection": selection,
                                 "test": classification(truth, (prob >= selection["chosen_threshold"]).astype(int)),
                                 "test_empty_rows": int(len(truth)), "test_arrivals": int(truth.sum())}
    for folder, profile in (("eval", profile_eval), ("final", profile_final)):
        (MODELS / folder / "occupancy_profile.json").write_text(json.dumps(profile), encoding="utf-8")

    # ------------------------------------------------------------------ 4. Dueling DQN (research algorithm B)
    # The DQN observes the LSTM occupancy probability, as in Hou et al. To avoid in-sample optimism, the
    # probabilities on the training dates are OUT-OF-FOLD (4-fold by date) LSTM predictions.
    dqn_dates = train_d + val_d
    oof = np.full(len(frame), np.nan)
    r_dqn = occupancy_rows(frame, dqn_dates)
    for tr_i, te_i in GroupKFold(n_splits=2 if args.quick else 4).split(r_dqn, groups=frame["date"].to_numpy()[r_dqn]):
        m = OCCUPANCY_MODELS["lstm"][3]()
        m.fit(inputs(frame, "sequence", r_dqn[tr_i]), y[r_dqn[tr_i]], epochs=epochs_used["lstm"])
        oof[r_dqn[te_i]] = m.predict_proba(inputs(frame, "sequence", r_dqn[te_i]))[:, 1]
    frame["dqn_occ_prob"] = np.nan_to_num(oof, nan=0.0)  # rows without a full window (night start) -> 0
    frame["dqn_arrival"] = arrival.lookup_frame(profile_eval, frame)
    days = [frame[frame["date"] == d] for d in dqn_dates]
    controller = DuelingDQNController(seed=SEED)
    seconds = controller.train(lambda i: ClassroomEnv(days[i], days[i]["dqn_occ_prob"].to_numpy(), days[i]["dqn_arrival"].to_numpy()),
                               len(days), episodes=6 if args.quick else 400)
    controller.save(MODELS / "dqn_controller.pt")
    obs = np.zeros(7, dtype=np.float32)
    report["dqn"] = {"research": "B: Hou et al. 2025 (Dueling DQN HVAC control)", "train_seconds": round(seconds, 1),
                     "episodes": 6 if args.quick else 400, "model_size_kb": file_size_kb(MODELS / "dqn_controller.pt"),
                     **latency_ms(controller.act, obs, repeats=200), "training_log": controller.training_log,
                     "simulator": params_dict()}

    # ------------------------------------------------------------------ 5. manifests, report, tables
    for folder, files in (("eval", {n: f"occupancy_{n}.{'pt' if OCCUPANCY_MODELS[n][1] == 'sequence' else 'joblib'}" for n in DEPLOYABLE}),
                          ("final", final_files)):
        manifest = {"run_id": run_id, "primary_model": primary, "seq_len": SEQ_LEN, "tabular_features": TABULAR_FEATURES,
                    "sequence_features": SEQUENCE_FEATURES, "energy_features": ENERGY_FEATURES,
                    "energy_model": {"name": deployed_energy, "file": "energy_random_forest.joblib"},
                    "precool_threshold": selection["chosen_threshold"], "dqn_file": "../dqn_controller.pt",
                    "trained_on": "training dates only" if folder == "eval" else "all 29 Room 1 dates",
                    "occupancy_models": {n: {"file": files[n], "category": OCCUPANCY_MODELS[n][0], "kind": OCCUPANCY_MODELS[n][1],
                                             "research": OCCUPANCY_MODELS[n][2]} for n in DEPLOYABLE}}
        (MODELS / folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    (MODELS / "training_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    table = pd.DataFrame([{"model": n, "category": e["category"], "research": e["research"], "input": e["input"],
                           "val_f1": e["validation"]["f1"], "test_accuracy": e["test"]["accuracy"], "test_precision": e["test"]["precision"],
                           "test_recall": e["test"]["recall"], "test_f1": e["test"]["f1"],
                           "cv_f1_mean": e["groupkfold_by_date_f1"]["mean"], "cv_f1_std": e["groupkfold_by_date_f1"]["std"],
                           "room2_f1": e.get("room2_cross_room", {}).get("f1"), "train_s": e["compute"]["train_seconds"],
                           "latency_ms": e["compute"]["median_ms"], "peak_mem_mb": e["compute"]["peak_memory_mb"],
                           "size_kb": e["compute"]["model_size_kb"], "parameters": e["compute"].get("parameters")}
                          for n, e in report["occupancy"].items()])
    table.to_csv(RESULTS / "model_comparison.csv", index=False)
    energy_table = pd.DataFrame([{"model": n, "category": e["category"], **{f"{t}_{k}": e[t][k] for t in ENERGY_TARGETS for k in ("mae", "rmse", "r2")}}
                                 for n, e in report["energy"].items() if n != "units"])
    energy_table.to_csv(RESULTS / "energy_comparison.csv", index=False)
    import_training_report(MODELS / "training_report.json")  # model_metrics table (dashboard comparison)
    print(table.to_string(index=False))
    print(energy_table.to_string(index=False))
    print(f"Primary occupancy model (by validation F1): {primary}")
    print(f"Saved models/eval, models/final, models/dqn_controller.pt, models/training_report.json ({run_id})")


if __name__ == "__main__":
    main()

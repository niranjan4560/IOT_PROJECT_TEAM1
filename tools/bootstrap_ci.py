"""Supplementary analysis: 95 % confidence intervals for the registered TEST F1 scores (no retraining, no reselection).

Loads the already-saved evaluation models (models/eval, trained on the 19 training dates only), predicts the same
6 held-out test dates, checks that the F1 reproduces the registered value in models/training_report.json, then runs a
CLUSTER bootstrap over test DATES (rows within one day are strongly correlated, so resampling rows would understate
the uncertainty). With only 6 dates the intervals are wide and approximate - that is the honest finding.

Writes NEW files only:  results/supplementary/bootstrap_ci_test_f1.csv  and  ..._paired_vs_primary.csv
  python tools/bootstrap_ci.py [--reps 2000]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from smartclass.registry import load_bundle  # noqa: E402
from train_models import ROOM1, inputs, occupancy_rows, prepare  # noqa: E402

SEED = 42


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=2000)
    args = parser.parse_args()
    report = json.loads((ROOT / "models/training_report.json").read_text(encoding="utf-8"))
    test_dates = report["split"]["test_dates"]
    primary = report["primary_occupancy_model"]["name"]
    frame = prepare(ROOM1, "room1")
    rows = occupancy_rows(frame, test_dates)
    y = frame["occupant_presence"].astype(int).to_numpy()[rows]
    dates = frame["date"].to_numpy()[rows]
    bundle = load_bundle(ROOT / "models/eval")
    preds = {}
    for name, model in bundle["occupancy"].items():
        kind = bundle["manifest"]["occupancy_models"][name]["kind"]
        preds[name] = np.asarray(model.predict(inputs(frame, kind, rows))).astype(int)
        registered = report["occupancy"][name]["test"]["f1"]
        got = round(float(f1_score(y, preds[name], zero_division=0)), 4)
        if abs(got - registered) > 1e-4:
            raise SystemExit(f"{name}: recomputed test F1 {got} != registered {registered} - stop, do not report CIs")
    print(f"recomputed test F1 matches the registered value for all {len(preds)} models")

    rng = np.random.default_rng(SEED)
    uniq = np.array(sorted(set(dates)))
    idx_by_date = {d: np.where(dates == d)[0] for d in uniq}
    samples = [np.concatenate([idx_by_date[d] for d in rng.choice(uniq, size=len(uniq), replace=True)]) for _ in range(args.reps)]
    rows_out, paired = [], []
    for name, p in preds.items():
        boot = np.array([f1_score(y[s], p[s], zero_division=0) for s in samples])
        per_day = {d: round(float(f1_score(y[i], p[i], zero_division=0)), 3) for d, i in idx_by_date.items()}
        rows_out.append({"model": name, "test_f1_registered": report["occupancy"][name]["test"]["f1"],
                         "ci95_low": round(float(np.percentile(boot, 2.5)), 3), "ci95_high": round(float(np.percentile(boot, 97.5)), 3),
                         "bootstrap_sd": round(float(boot.std()), 3), "validation_f1": report["occupancy"][name]["validation"]["f1"],
                         **{f"f1_{d}": v for d, v in per_day.items()}})
        if name != primary:
            diff = np.array([f1_score(y[s], p[s], zero_division=0) - f1_score(y[s], preds[primary][s], zero_division=0) for s in samples])
            paired.append({"model": name, "vs": primary, "mean_diff_f1": round(float(diff.mean()), 3),
                           "ci95_low": round(float(np.percentile(diff, 2.5)), 3), "ci95_high": round(float(np.percentile(diff, 97.5)), 3),
                           "share_of_resamples_better": round(float((diff > 0).mean()), 3)})
    out = ROOT / "results/supplementary"
    out.mkdir(parents=True, exist_ok=True)
    table = pd.DataFrame(rows_out).sort_values("test_f1_registered", ascending=False)
    table.to_csv(out / "bootstrap_ci_test_f1.csv", index=False)
    pd.DataFrame(paired).to_csv(out / "bootstrap_ci_paired_vs_primary.csv", index=False)
    meta = {"method": "cluster bootstrap over test dates (percentile 95 % CI)", "reps": args.reps, "seed": SEED,
            "test_dates": test_dates, "rows": int(len(rows)), "primary_model": primary, "registered_run": report["run_id"]}
    (out / "bootstrap_ci_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(table[["model", "test_f1_registered", "ci95_low", "ci95_high", "validation_f1"]].to_string(index=False))
    print(pd.DataFrame(paired).to_string(index=False))


if __name__ == "__main__":
    main()

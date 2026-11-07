"""SQLite helpers for the Python side (schema initialisation, metric and experiment storage)."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from smartclass.features import SGT

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "db" / "schema.sql"
DEFAULT_DB = ROOT / "storage" / "smartclass.db"


def schema_statements() -> list[str]:
    """CREATE statements from db/schema.sql with comments removed (also used to build the Node-RED flow)."""
    text = re.sub(r"--[^\n]*", "", SCHEMA.read_text(encoding="utf-8"))
    return [" ".join(s.split()) for s in text.split(";") if s.strip()]


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.execute("PRAGMA busy_timeout = 15000")
    return db


def init_db(path: str | Path = DEFAULT_DB) -> Path:
    with connect(path) as db:
        for statement in schema_statements():
            db.execute(statement)
    return Path(path)


def now_sgt() -> str:
    return datetime.now(SGT).isoformat(timespec="seconds")


def write_rows(table: str, rows: list[dict], path: str | Path = DEFAULT_DB) -> int:
    if not rows:
        return 0
    init_db(path)
    cols = list(rows[0])
    with connect(path) as db:
        db.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                       [tuple(r[c] for c in cols) for r in rows])
    return len(rows)


def report_metric_rows(report: dict) -> list[dict]:
    """Flatten models/training_report.json into model_metrics rows (long format)."""
    rows, run_id, created = [], report["run_id"], now_sgt()

    def add(task, model, category, split, metrics):
        for k, v in (metrics or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                rows.append({"run_id": run_id, "created_at": created, "task": task, "model": model, "category": category,
                             "split": split, "metric": k, "value": float(v)})

    for name, e in report["occupancy"].items():
        for split in ("validation", "test"):
            add("occupancy", name, e["category"], split, e[split])
        add("occupancy", name, e["category"], "compute", e["compute"])
        cv = e.get("groupkfold_by_date_f1", {})
        add("occupancy", name, e["category"], "cv", {"f1_mean": cv.get("mean"), "f1_std": cv.get("std")})
        add("occupancy", name, e["category"], "room2", e.get("room2_cross_room"))
    for name, e in report["energy"].items():
        if name == "units":
            continue
        for target in ("next_lighting_kwh", "next_chilled_water_kwh"):
            add("energy", name, e["category"], f"test:{target}", e[target])
        add("energy", name, e["category"], "compute", e.get("compute"))
    dqn = report.get("dqn", {})
    add("dqn", "dueling_dqn", "deep_learning", "compute", {k: dqn.get(k) for k in ("train_seconds", "model_size_kb", "median_ms", "p95_ms")})
    return rows


def import_training_report(report_path: str | Path, path: str | Path = DEFAULT_DB) -> int:
    """Copy a training report into model_metrics once (skipped if that run_id is already stored)."""
    import json
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    init_db(path)
    with connect(path) as db:
        if db.execute("SELECT 1 FROM model_metrics WHERE run_id = ? LIMIT 1", (report["run_id"],)).fetchone():
            return 0
    return write_rows("model_metrics", report_metric_rows(report), path)


def experiment_rows(savings, closed, run_id: str, comfort=None) -> list[dict]:
    """experiment_results rows from the savings, closed-loop and (optional) comfort tables (pandas DataFrames)."""
    rows, created = [], now_sgt()
    if comfort is not None:
        for _, r in comfort.iterrows():
            rows.append({"run_id": run_id, "created_at": created, "experiment": "recorded_counterfactual",
                         "scenario": f"{r.case}|{r.controller}|{r.source}|comfort", "metric": "light_off_while_occupied_pct",
                         "value": round(100.0 * r.incorrect_light_off / max(r.occupied_rows, 1), 1), "unit": "%"})
    for _, r in savings[(savings.eco_factor == 0.75) & (savings.dim_factor == 0.5)].iterrows():
        rows.append({"run_id": run_id, "created_at": created, "experiment": "recorded_counterfactual",
                     "scenario": f"{r.case}|{r.controller}|{r.source}|{r.load}", "metric": "saved_pct", "value": float(r.saved_pct), "unit": "%"})
    for _, r in closed.iterrows():
        for metric, unit in (("cooling_kwh_thermal", "kWh thermal"), ("comfort_violation_pct", "%"), ("ac_switches_per_day", "1/day")):
            rows.append({"run_id": run_id, "created_at": created, "experiment": "closed_loop_simulation",
                         "scenario": r.controller, "metric": metric, "value": float(r[metric]), "unit": unit})
    return rows


def import_experiment_results(results_dir: str | Path, path: str | Path = DEFAULT_DB) -> int:
    """Copy the REGISTERED result CSVs (written by run_experiments.py) into experiment_results once.
    The CSVs are only read, never changed. The run id is taken from results/experiments_log.txt."""
    import pandas as pd
    results_dir = Path(results_dir)
    needed = [results_dir / n for n in ("savings_results.csv", "closed_loop_results.csv", "experiments_log.txt", "savings_comfort.csv")]
    if not all(p.exists() for p in needed):
        return 0
    found = re.findall(r"exp-\d{8}-\d{6}", needed[2].read_text(encoding="utf-8", errors="ignore"))
    run_id = found[-1] if found else "exp-registered"
    init_db(path)
    with connect(path) as db:
        if db.execute("SELECT 1 FROM experiment_results WHERE run_id = ? LIMIT 1", (run_id,)).fetchone():
            return 0
    return write_rows("experiment_results", experiment_rows(pd.read_csv(needed[0]), pd.read_csv(needed[1]), run_id,
                                                         pd.read_csv(needed[3])), path)

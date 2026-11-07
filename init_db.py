"""Create (or upgrade) the SQLite database from db/schema.sql.

Run:  python init_db.py                 -> storage/smartclass.db
      python init_db.py --db other.db
Node-RED also applies the same schema when it starts. This script additionally copies
models/training_report.json into model_metrics and the registered results/*.csv into experiment_results
(the dashboard's model-performance and offline-experiment tables). Both imports are read-only and run once per run id.
"""
import argparse

from pathlib import Path

from smartclass.db import DEFAULT_DB, import_experiment_results, import_training_report, init_db, schema_statements

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--db", default=str(DEFAULT_DB))
args = parser.parse_args()
path = init_db(args.db)
print(f"Applied {len(schema_statements())} statements to {path}")
report = Path(__file__).resolve().parent / "models" / "training_report.json"
if report.exists():
    print(f"Imported {import_training_report(report, path)} model-metric rows from {report.name} (0 = already present)")
results = Path(__file__).resolve().parent / "results"
print(f"Imported {import_experiment_results(results, path)} experiment-result rows from results/ (0 = already present or not found)")

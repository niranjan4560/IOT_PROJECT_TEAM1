"""Closed-loop metrics of a LIVE run, read from SQLite (Laptop 1). Run after a replay:

    python tools/closed_loop_report.py                 -> prints the report, writes results/live_closed_loop_report.json

Definitions
  acknowledgement rate  = commands with status ACKED / commands sent (SENT still pending are excluded)
  round trip (ms)       = server clock: command published by Node-RED -> acknowledgement received by Node-RED
  loop latency (ms)     = node clock: telemetry published by the replay -> actuator applied the resulting command
  switches per data day = changes of commanded state per room and load, divided by the number of replayed dates
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from smartclass.db import DEFAULT_DB  # noqa: E402


def stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    a = np.array(values, dtype=float)
    return {"n": int(a.size), "mean": round(float(a.mean()), 1), "median": round(float(np.median(a)), 1),
            "p95": round(float(np.percentile(a, 95)), 1), "max": round(float(a.max()), 1)}


def main(db_path: str | Path = DEFAULT_DB, out: str | Path | None = None) -> dict:
    db = sqlite3.connect(db_path)
    q = lambda sql: db.execute(sql).fetchall()
    status = dict(q("SELECT status, COUNT(*) FROM commands GROUP BY status"))
    decided = sum(v for k, v in status.items() if k != "SENT")
    days = dict(q("SELECT room_id, COUNT(DISTINCT substr(ts, 1, 10)) FROM decisions GROUP BY room_id"))
    switches = {f"{room}/{load}": round(n / max(days.get(room, 1), 1), 2)
                for room, load, n in q("SELECT room_id, load, COUNT(*) FROM commands GROUP BY room_id, load")}
    report = {
        "telemetry_rows": q("SELECT COUNT(*) FROM telemetry")[0][0],
        "decisions": q("SELECT COUNT(*) FROM decisions")[0][0],
        "predictions_per_model": dict(q("SELECT model, COUNT(*) FROM predictions GROUP BY model")),
        "ml_latency_ms_per_model": {m: round(v, 2) for m, v in q("SELECT model, AVG(latency_ms) FROM predictions GROUP BY model")},
        "commands_by_status": status,
        "acknowledgement_rate_pct": round(100 * status.get("ACKED", 0) / decided, 2) if decided else None,
        "roundtrip_ms": stats([r[0] for r in q("SELECT roundtrip_ms FROM commands WHERE roundtrip_ms IS NOT NULL")]),
        "loop_latency_ms": stats([r[0] for r in q("SELECT loop_latency_ms FROM commands WHERE loop_latency_ms IS NOT NULL")]),
        "command_switches_per_data_day": switches,
        "alerts_by_type": dict(q("SELECT type, COUNT(*) FROM alerts GROUP BY type")),
    }
    out = Path(out) if out else ROOT / "results" / "live_closed_loop_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    # python tools/closed_loop_report.py [db] [--out file.json]   (--out keeps the registered results/ file unchanged)
    args = sys.argv[1:]
    out = args[args.index("--out") + 1] if "--out" in args else None
    if "--out" in args:
        del args[args.index("--out"):args.index("--out") + 2]
    main(args[0] if args else DEFAULT_DB, out)

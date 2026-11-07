"""Download the two ROBOD lecture-room CSVs and verify them (SHA-256 + schema) before anything uses them.

  python download_data.py            download if missing, then verify
  python download_data.py --verify   verify existing files only (no network)
  python download_data.py --force    download again, then verify

The expected SHA-256 values are the exact files every registered result in results/ and models/ was produced from.
A mismatch means the upstream files changed: the project still runs with --allow-changed-data, but the registered
results are then no longer guaranteed to reproduce. Licence: see docs/DATA_DICTIONARY.md - the licence terms
could not be verified by the team, so the CSVs are NOT redistributed in the project ZIP.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

BASE = "https://raw.githubusercontent.com/ideas-lab-nus/robod/master/Data"
SOURCE_REPO = "https://github.com/ideas-lab-nus/robod"
EXPECTED = {
    "combined_Room1.csv": {"sha256": "34a3d7a1946945c5321f06fbe38639d74e47e40fdd0df086c635d3ed73a63f3d", "rows": 8352},
    "combined_Room2.csv": {"sha256": "ac9a34cd7149814bc31be26c75d0481c6c205e3cc0e0775d42f963b86a90941f", "rows": 8352},
}
# Columns the project reads (smartclass/dataset.py FIELDS) - all must be present.
REQUIRED_COLUMNS = [
    "timestamp", "wifi_connected_devices", "indoor_co2", "sound_pressure_level", "indoor_relative_humidity",
    "air_temperature", "illuminance", "temp_setpoint", "dry_bulb_temp", "outdoor_co2",
    "global_horizontal_solar_radiation", "fcu_fan_speed", "lighting_energy", "fcu_fan_energy", "plug_load_energy",
    "chilled_water_energy", "occupant_presence", "occupant_count",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_schema(path: Path) -> tuple[list[str], int, str]:
    """Return (problems, data_rows, first_timestamp)."""
    problems: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            problems.append(f"missing columns: {', '.join(missing)}")
        rows, first = 0, ""
        ts_index = header.index("timestamp") if "timestamp" in header else None
        for row in reader:
            rows += 1
            if ts_index is not None and rows == 1:
                first = row[ts_index]
                try:
                    datetime.strptime(first, "%Y-%m-%d %H:%M %z")
                except ValueError:
                    problems.append(f"timestamp format not 'YYYY-MM-DD HH:MM +08:00': {first!r}")
    return problems, rows, first


def verify(directory: Path, allow_changed: bool) -> bool:
    manifest, ok = {"verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": SOURCE_REPO,
                    "files": {}}, True
    for name, expected in EXPECTED.items():
        path = directory / name
        if not path.exists():
            print(f"FAIL  {name}: not found (run: python download_data.py)")
            ok = False
            continue
        digest = sha256(path)
        problems, rows, first = check_schema(path)
        if rows != expected["rows"]:
            problems.append(f"{rows} data rows, expected {expected['rows']}")
        hash_ok = digest == expected["sha256"]
        status = "PASS" if hash_ok and not problems else ("WARN" if allow_changed and not problems else "FAIL")
        print(f"{status}  {name}: sha256 {'matches' if hash_ok else 'DIFFERS (' + digest[:12] + '…)'}, {rows} rows, "
              f"schema {'ok' if not problems else '; '.join(problems)}")
        if problems or (not hash_ok and not allow_changed):
            ok = False
        manifest["files"][name] = {"sha256": digest, "expected_sha256": expected["sha256"], "rows": rows,
                                   "first_timestamp": first, "schema_ok": not problems}
    (directory / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not ok:
        print("Dataset verification failed. Registered results were produced from the files with the expected SHA-256.")
        print("If upstream intentionally changed, rerun with --allow-changed-data and retrain (results will differ).")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download and verify the ROBOD lecture-room CSV files")
    parser.add_argument("--force", action="store_true", help="download again even if a CSV already exists")
    parser.add_argument("--verify", action="store_true", help="only verify existing files (no download)")
    parser.add_argument("--allow-changed-data", action="store_true", help="accept files whose SHA-256 differs")
    parser.add_argument("--dir", default="data")
    args = parser.parse_args(argv)
    directory = Path(args.dir)
    directory.mkdir(exist_ok=True)
    if not args.verify:
        for name in EXPECTED:
            destination = directory / name
            if destination.exists() and not args.force:
                print(f"Keeping existing {destination}")
                continue
            url = f"{BASE}/{name}"
            print(f"Downloading {url}")
            partial = destination.with_suffix(".part")
            with urlopen(url, timeout=60) as response, partial.open("wb") as output:
                output.write(response.read())
            partial.replace(destination)
            print(f"Saved {destination}")
    return 0 if verify(directory, args.allow_changed_data) else 1


if __name__ == "__main__":
    sys.exit(main())

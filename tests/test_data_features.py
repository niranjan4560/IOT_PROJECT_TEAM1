"""Areas 1-2: dataset loading/schema, timestamp ordering, feature generation without leakage."""
import numpy as np
import pandas as pd
import pytest

from conftest import ROOT, needs_data
from smartclass.dataset import FIELDS, RAW_TO_APP, read_room_csv, split_dates
from smartclass.features import (SEQ_LEN, SEQUENCE_FEATURES, TABULAR_FEATURES, add_history_features, build_windows,
                                 tabular_from_window, to_sgt_iso)

pytestmark = needs_data


def test_raw_schema_and_size():
    raw = pd.read_csv(ROOT / "data/combined_Room1.csv")
    assert raw.shape == (8352, 28)
    assert set(RAW_TO_APP) <= set(raw.columns)
    assert raw["timestamp"].str.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d \+08:00$").all()


def test_every_field_has_unit_and_kind():
    for raw, (name, unit, kind) in FIELDS.items():
        assert unit and kind == "MEASURED", raw
    assert "THERMAL" in FIELDS["chilled_water_energy"][1] and "electrical" in FIELDS["fcu_fan_energy"][1]


def test_timestamps_ordered_unique_weekdays(room1):
    ts = room1["timestamp"]
    assert ts.is_monotonic_increasing and ts.is_unique
    assert str(ts.dt.tz) == "UTC+08:00"
    assert room1["date"].nunique() == 29
    assert set(room1["day_of_week"]) <= {0, 1, 2, 3, 4}
    steps = ts.diff().dropna()
    assert (steps[room1["segment"].diff().iloc[1:] == 0] == pd.Timedelta(minutes=5)).all()


def test_missing_values_are_not_silently_filled(room1):
    raw = pd.read_csv(ROOT / "data/combined_Room1.csv")
    assert room1["illuminance_lux"].isna().sum() == raw["illuminance"].isna().sum() > 0


def test_split_is_by_whole_date_and_reproducible(room1):
    a, b = split_dates(room1), split_dates(room1)
    assert a == b
    train, val, test = a
    assert len(test) == 6 and len(val) == 4 and len(train) == 19
    assert not (set(train) & set(val) or set(train) & set(test) or set(val) & set(test))


def test_features_use_no_future_information(room1):
    base = add_history_features(room1)
    row = int(np.where(base["features_valid"])[0][500])
    changed = room1.copy()
    changed.loc[row + 1:, ["wifi_devices", "co2_ppm", "sound_db", "temperature_c"]] += 999  # change the future only
    after = add_history_features(changed)
    pd.testing.assert_series_equal(base.loc[row, TABULAR_FEATURES], after.loc[row, TABULAR_FEATURES])
    np.testing.assert_array_equal(build_windows(base, np.array([row])), build_windows(after, np.array([row])))


def test_live_features_equal_offline_features(room1_features):
    f = room1_features
    rows = np.where(f["features_valid"] & ~f["sensor_missing"])[0][::400]
    for row in rows:
        window = f.iloc[row - SEQ_LEN + 1: row + 1]
        live = tabular_from_window(window)
        for name in TABULAR_FEATURES:
            assert live[name] == pytest.approx(float(f.loc[row, name]), abs=1e-6), (row, name)


def test_windows_shape(room1_features):
    rows = np.where(room1_features["features_valid"])[0][:10]
    assert build_windows(room1_features, rows).shape == (10, SEQ_LEN, len(SEQUENCE_FEATURES))


def test_timestamp_rule():
    assert to_sgt_iso("2021-09-07 09:10 +08:00") == "2021-09-07T09:10:00+08:00"
    assert to_sgt_iso("2021-09-07T01:10:00Z") == "2021-09-07T09:10:00+08:00"

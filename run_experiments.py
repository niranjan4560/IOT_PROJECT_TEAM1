"""All experiments in one command (Laptop 1). Run AFTER train_models.py:  python run_experiments.py

Every decision in these experiments goes through the SAME code as the live system:
  ML stage   : smartclass.predictor.LivePredictor (the ML service's class), models/eval (never saw the test dates)
  Decisions  : the "Decision rules" node of nodered/flows.json, executed by tools/run_rules.js
Readings that Node-RED's validator would reject (a missing required sensor) are skipped, exactly as live.

Experiment 0 - occupancy-threshold tuning on the VALIDATION dates (never the test dates)  -> results/threshold_tuning_validation.csv
  For each hysteresis pair (on, off): incorrect light OFF in occupied intervals vs lighting saving, per model.
  The CONFIG values were chosen from this table (most comfort-protective pair with lighting saving >= 30%).

Experiment 1 - recorded-energy counterfactual (open loop)                     -> results/savings_*.csv
  Baseline   = ROBOD's recorded energy. Controlled = the same recorded energy scaled by our command:
               lighting ON 100% / DIM dim_factor / OFF 0%;  chilled water COMFORT/BOOST/PRECOOL 100%, ECO eco_factor,
               OFF 0%;  FCU fan OFF 0%, otherwise 100%.  Loads are reported separately; thermal never added to electrical.
  Sources    : every deployable occupancy model, and the camera label ("oracle", upper bound for the rules).
  Controllers: rules (AC by rules) and dqn (AC by the Dueling DQN behind the safety layer). Lights are always rules.
  Sensitivity: eco_factor in {0.5, 0.6, 0.75, 0.9} and dim_factor in {0.3, 0.5, 0.7}.
  Comfort    : occupied (camera) with light OFF = incorrect OFF; occupied with AC ECO/OFF; command switches per day.
  Validity   : savings are SIMULATED; they assume the recorded energy would scale with our command.

Experiment 2 - closed-loop simulation (smartclass/room_env.py, AC only)          -> results/closed_loop_*.csv
  The simulated room temperature and CO2 respond to the controller, so comfort can be measured.
  Controllers: always COMFORT, timetable 07:00-20:00, rules, Dueling DQN (raw), Dueling DQN + Node-RED safety layer.
  Inputs     : occupancy probability from the camera (oracle), LSTM (paper B pairing), Mamba (paper A) or random forest.
  Validity   : the plant has ASSUMED parameters (ROBOD cannot identify one); compare controllers with each other only.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from smartclass.dataset import add_targets, read_room_csv  # noqa: E402
from smartclass.db import experiment_rows, write_rows  # noqa: E402
from smartclass.dqn import DuelingDQNController  # noqa: E402
from smartclass.features import SENSORS, to_sgt_iso  # noqa: E402
from smartclass.predictor import LivePredictor  # noqa: E402
from smartclass.room_env import AC_ACTIONS, ClassroomEnv  # noqa: E402
from smartclass.rules_runner import RulesSession, run_rules  # noqa: E402

ROOT = Path(__file__).resolve().parent
RESULTS, FIGURES = ROOT / "results", ROOT / "results" / "figures"
REQUIRED = SENSORS + ["setpoint_c"]
READING_FIELDS = REQUIRED + ["outdoor_temp_c", "lighting_kwh", "fcu_fan_kwh", "plug_kwh", "chilled_water_kwh",
                             "occupant_presence", "occupant_count"]
SOURCES = ["oracle", "random_forest", "gradient_boosting", "logistic_regression", "decision_tree", "lstm", "mamba"]
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]  # fixed order
ECO_FACTORS, DIM_FACTORS = [0.5, 0.6, 0.75, 0.9], [0.3, 0.5, 0.7]


def clean(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def live_analytics(frame: pd.DataFrame, predictor: LivePredictor, room: str) -> list[dict | None]:
    """Run the ML service's predictor over the rows, in time order; None = rejected by the Node-RED validator."""
    out = []
    for _, row in frame.iterrows():
        reading = {k: clean(row[k]) for k in READING_FIELDS}
        if any(reading[k] is None for k in REQUIRED):
            out.append(None)
            continue
        reading["timestamp"] = to_sgt_iso(row["timestamp"])
        out.append({"room_id": room, "timestamp": reading["timestamp"], **predictor.predict(room, reading), "reading": reading})
    return out


def with_source(record: dict, source: str) -> dict:
    rec = dict(record)
    if source == "oracle":
        rec["occupancy_probability"] = float(record["reading"]["occupant_presence"])
        rec["primary_model"] = "camera (oracle)"
    else:
        rec["occupancy_probability"] = record["models"][source]["p"]
        rec["primary_model"] = source
    rec["primary_fallback"] = False
    return rec


def decide_open_loop(records: list[dict | None], source: str, controller: str) -> pd.DataFrame:
    valid = [i for i, r in enumerate(records) if r is not None]
    decisions = run_rules([with_source(records[i], source) for i in valid], config={"ac_controller": controller})
    cmds = pd.DataFrame({"light": [d["light"] for d in decisions], "ac": [d["ac"] for d in decisions]}, index=valid)
    return cmds.reindex(range(len(records))).ffill().fillna({"light": "OFF", "ac": "ECO"})  # rejected row: hold


def experiment_recorded(case: str, frame: pd.DataFrame, records: list) -> tuple[list[dict], list[dict]]:
    savings, comfort = [], []
    occupied = (frame["occupant_presence"] == 1).to_numpy()
    light_e = frame["lighting_kwh"].fillna(0).to_numpy()
    fan_e = frame["fcu_fan_kwh"].fillna(0).to_numpy()
    cool_e = frame["chilled_water_kwh"].fillna(0).to_numpy()
    days = frame["date"].nunique()
    for controller in ("rules", "dqn"):
        for source in SOURCES:
            cmds = decide_open_loop(records, source, controller)
            light, ac = cmds["light"].to_numpy(), cmds["ac"].to_numpy()
            for eco in ECO_FACTORS:
                for dim in DIM_FACTORS:
                    lf = np.select([light == "OFF", light == "DIM"], [0.0, dim], 1.0)
                    cf = np.select([ac == "OFF", ac == "ECO"], [0.0, eco], 1.0)
                    ff = np.where(ac == "OFF", 0.0, 1.0)
                    for load, unit, base, factor in (("lighting", "kWh electrical", light_e, lf), ("fcu_fan", "kWh electrical", fan_e, ff),
                                                     ("chilled_water", "kWh THERMAL", cool_e, cf)):
                        b, c = float(base.sum()), float((base * factor).sum())
                        savings.append({"case": case, "controller": controller, "source": source, "eco_factor": eco,
                                        "dim_factor": dim, "load": load, "unit": unit, "days": days, "baseline": round(b, 3),
                                        "controlled": round(c, 3), "saved": round(b - c, 3),
                                        "saved_pct": round(100 * (b - c) / b, 1) if b > 0 else None})
            comfort.append({
                "case": case, "controller": controller, "source": source, "rows": len(frame), "occupied_rows": int(occupied.sum()),
                "incorrect_light_off": int((occupied & (light == "OFF")).sum()),
                "ac_eco_or_off_while_occupied": int((occupied & np.isin(ac, ["ECO", "OFF"])).sum()),
                "precool_rows": int((ac == "PRECOOL").sum()),
                "precool_followed_by_arrival": int(((ac == "PRECOOL") & (frame["occupied_next_30min"] == 1).to_numpy()).sum()),
                "light_switches_per_day": round(float((light[1:] != light[:-1]).sum()) / days, 2),
                "ac_switches_per_day": round(float((ac[1:] != ac[:-1]).sum()) / days, 2),
            })
            print(f"  recorded {case:15s} {controller:5s} {source:20s} done")
    return savings, comfort


def experiment_closed_loop(frame: pd.DataFrame, records: list, dqn: DuelingDQNController) -> tuple[list[dict], dict]:
    rows, traces = [], {}
    probs = {s: np.array([np.nan if r is None else with_source(r, s)["occupancy_probability"] for r in records]) for s in SOURCES}
    arrival = np.array([0.0 if r is None else r["p_arrival_30min"] for r in records])
    for name, kind, source in ([("always_comfort", "fixed", None), ("timetable_07_20", "timetable", None)]
                               + [(f"rules[{s}]", "rules", s) for s in ("oracle", "lstm", "mamba", "random_forest")]
                               + [(f"dqn_raw[{s}]", "dqn_raw", s) for s in ("oracle", "lstm", "mamba", "random_forest")]
                               + [(f"dqn_safe[{s}]", "dqn_safe", s) for s in ("oracle", "lstm", "mamba", "random_forest")]):
        totals = {"cooling_kwh_thermal": 0.0, "fan_kwh": 0.0, "comfort_violation_steps": 0, "comfort_violation_kh": 0.0,
                  "co2_violation_steps": 0, "ac_switches": 0, "reward": 0.0, "occupied_steps": 0, "occupied_temp_sum": 0.0}
        session = RulesSession({"ac_controller": "dqn" if kind == "dqn_safe" else "rules"}) if kind in ("rules", "dqn_safe") else None
        for date, day in frame.groupby("date", sort=True):
            idx = day.index.to_numpy()
            p = np.nan_to_num(probs[source][idx], nan=0.0) if source else np.zeros(len(idx))
            env = ClassroomEnv(day, p, arrival[idx])
            obs, last, trace = env.reset(), None, []
            for k, i in enumerate(idx):
                hour = int(day.loc[i, "hour"])
                if kind == "fixed":
                    action = "COMFORT"
                elif kind == "timetable":
                    action = "COMFORT" if 7 <= hour < 20 else "OFF"
                elif kind == "dqn_raw":
                    action = dqn.act(obs)
                else:
                    rec = records[i]
                    if rec is None:
                        action = last or "ECO"  # rejected reading: the last command is held
                    else:
                        rec = with_source(rec, source)
                        rec["reading"] = {**rec["reading"], "temperature_c": env.temp, "co2_ppm": env.co2}  # simulated room
                        rec["dqn_ac_action"] = dqn.act(obs) if kind == "dqn_safe" else None
                        action = session.decide(rec)["ac"]
                    action = "COMFORT" if action == "PRECOOL" else action  # PRECOOL = comfort setpoint in the plant
                obs, reward, info = env.step(action)
                totals["cooling_kwh_thermal"] += info["cooling_kwh_thermal"]
                totals["fan_kwh"] += info["fan_kwh"]
                totals["reward"] += reward
                if info["occupied"]:
                    totals["occupied_steps"] += 1
                    totals["occupied_temp_sum"] += info["temp_c"]
                    totals["comfort_violation_steps"] += int(info["comfort_violation_k"] > 0)
                    totals["comfort_violation_kh"] += info["comfort_violation_k"] * 5 / 60
                totals["co2_violation_steps"] += int(info["co2_violation"])
                totals["ac_switches"] += int(last is not None and action != last)
                last = action
                trace.append((info["temp_c"], action))
            if date == frame["date"].iloc[0]:
                traces[name] = trace
        if session:
            session.close()
        n_days = frame["date"].nunique()
        rows.append({"controller": name, "kind": kind, "occupancy_input": source or "-", "days": n_days,
                     "cooling_kwh_thermal": round(totals["cooling_kwh_thermal"], 2), "fan_kwh_electrical": round(totals["fan_kwh"], 3),
                     "occupied_steps": totals["occupied_steps"], "comfort_violation_steps": totals["comfort_violation_steps"],
                     "comfort_violation_pct": round(100 * totals["comfort_violation_steps"] / max(totals["occupied_steps"], 1), 1),
                     "comfort_violation_kelvin_hours": round(totals["comfort_violation_kh"], 2),
                     "co2_violation_steps": totals["co2_violation_steps"], "ac_switches_per_day": round(totals["ac_switches"] / n_days, 1),
                     "mean_occupied_temp_c": round(totals["occupied_temp_sum"] / max(totals["occupied_steps"], 1), 2),
                     "reward": round(totals["reward"], 2)})
        print(f"  closed-loop {name:28s} cooling {rows[-1]['cooling_kwh_thermal']:8.1f} kWh_th  "
              f"comfort viol {rows[-1]['comfort_violation_pct']:5.1f}%  switches/day {rows[-1]['ac_switches_per_day']}")
    return rows, traces


def figures(report: dict, savings: pd.DataFrame, closed: pd.DataFrame, traces: dict, frame1: pd.DataFrame) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                         "grid.color": "#e5e5e5", "axes.axisbelow": True})
    occ = report["occupancy"]
    names = [n for n in occ if n != "majority_class"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    x = np.arange(len(names))
    for j, (split, label) in enumerate((("validation", "Validation F1"), ("test", "Test F1"))):
        axes[0].bar(x + (j - 0.5) * 0.38, [occ[n][split]["f1"] for n in names], 0.36, color=COLORS[j], label=label)
    axes[0].errorbar(x + 0.0, [occ[n]["groupkfold_by_date_f1"]["mean"] for n in names],
                     yerr=[occ[n]["groupkfold_by_date_f1"]["std"] for n in names], fmt="o", color="#0b0b0b", ms=4, label="5-fold by date (mean ± sd)")
    axes[0].set_xticks(x, [n.replace("_", "\n") for n in names], fontsize=8)
    axes[0].set_ylim(0, 1.18)
    axes[0].set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    axes[0].set_title("Occupancy F1 (majority-class baseline = 0)")
    axes[0].legend(fontsize=8, loc="upper center", ncol=3, frameon=False)
    axes[1].bar(x, [occ[n]["compute"]["median_ms"] for n in names], color=COLORS[0])
    axes[1].set_xticks(x, [n.replace("_", "\n") for n in names], fontsize=8)
    axes[1].set_title("Inference latency per reading (median ms, CPU)")
    fig.tight_layout()
    fig.savefig(FIGURES / "model_comparison.png", dpi=160)
    plt.close(fig)

    main = savings[(savings.case == "room1_test") & (savings.eco_factor == 0.75) & (savings.dim_factor == 0.5)]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
    for ax, load in zip(axes, ["lighting", "fcu_fan", "chilled_water"]):
        sub = main[main.load == load]
        for j, controller in enumerate(("rules", "dqn")):
            s = sub[sub.controller == controller].set_index("source").reindex(SOURCES)
            ax.bar(np.arange(len(SOURCES)) + (j - 0.5) * 0.38, s["saved_pct"], 0.36, color=COLORS[j], label=f"AC: {controller}")
        ax.set_xticks(np.arange(len(SOURCES)), [s.replace("_", "\n") for s in SOURCES], fontsize=7)
        ax.set_title({"lighting": "Lighting (electrical)", "fcu_fan": "FCU fan (electrical)", "chilled_water": "Chilled water (THERMAL)"}[load])
    axes[0].set_ylabel("Saved vs recorded, % (simulated)")
    axes[0].legend(fontsize=8)
    fig.suptitle("Room 1 test dates: counterfactual savings by occupancy source (ECO 0.75, DIM 0.5)", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGURES / "savings_by_source.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4.4))
    kinds = {"fixed": 0, "timetable": 1, "rules": 2, "dqn_raw": 3, "dqn_safe": 6}
    for kind, ci in kinds.items():
        sub = closed[closed.kind == kind]
        ax.scatter(sub.cooling_kwh_thermal, sub.comfort_violation_pct, s=60, color=COLORS[ci], edgecolor="white", linewidth=1.5, label=kind, zorder=3)
        for j, (_, r) in enumerate(sub.sort_values("cooling_kwh_thermal").iterrows()):
            dy = [8, -14, 20, -26][j % 4] if kind == "rules" else 3   # the rules points sit close together
            ax.annotate(r.occupancy_input if r.occupancy_input != "-" else r.controller, (r.cooling_kwh_thermal, r.comfort_violation_pct),
                        fontsize=7, xytext=(4, dy), textcoords="offset points", color="#52514e",
                        arrowprops={"arrowstyle": "-", "color": "#c3c2b7", "lw": 0.6} if kind == "rules" else None)
    ax.set_xlabel("Cooling energy over the 6 test days, kWh thermal (simulated)")
    ax.set_ylabel("Occupied steps outside 23-26 °C, %")
    ax.set_ylim(-4, max(closed.comfort_violation_pct) + 3)
    ax.set_title("Closed-loop simulation: energy vs comfort (lower-left is better)")
    ax.legend(fontsize=8, title="controller", title_fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "closed_loop_tradeoff.png", dpi=160)
    plt.close(fig)

    log = report["dqn"]["training_log"]
    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.plot([e["episode"] for e in log], [e["return"] for e in log], color=COLORS[0], lw=2)
    ax.set_xlabel("training episode (one simulated day)")
    ax.set_ylabel("episode return")
    ax.set_title("Dueling DQN training (one episode every 20 shown)")
    fig.tight_layout()
    fig.savefig(FIGURES / "dqn_training.png", dpi=160)
    plt.close(fig)

    day = frame1[frame1.date == frame1.date.iloc[0]]
    hours = day["hour"].to_numpy() + day["timestamp"].dt.minute.to_numpy() / 60
    fig, ax = plt.subplots(figsize=(9, 3.8))
    for ci, name in ((1, "timetable_07_20"), (2, "rules[lstm]"), (6, "dqn_safe[lstm]")):
        ax.plot(hours, [t for t, _ in traces[name]], lw=2, color=COLORS[ci], label=name)
    occupied = (day["occupant_count"] > 0).to_numpy()
    ax.fill_between(hours, 22, 30, where=occupied, color="#d9d9e0", alpha=0.6, step="mid", label="occupied (camera)")
    ax.axhspan(23, 26, color=COLORS[2], alpha=0.08)
    ax.set_ylim(22, 30)
    ax.set_xlabel(f"hour of {day.date.iloc[0]} (test date)")
    ax.set_ylabel("simulated room temperature, °C")
    ax.set_title("One test day in the simulator (comfort band 23-26 °C shaded)")
    ax.legend(fontsize=8, ncol=4, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIGURES / "closed_loop_day.png", dpi=160)
    plt.close(fig)


THRESHOLD_PAIRS = [(0.6, 0.4), (0.5, 0.3), (0.4, 0.25), (0.3, 0.2), (0.25, 0.15), (0.2, 0.1)]


def experiment_thresholds(frame: pd.DataFrame, records: list) -> pd.DataFrame:
    occupied = (frame["occupant_presence"] == 1).to_numpy()
    light_e = frame["lighting_kwh"].fillna(0).to_numpy()
    valid = [i for i, r in enumerate(records) if r is not None]
    rows = []
    for source in ("random_forest", "gradient_boosting", "logistic_regression", "lstm", "mamba"):
        for on, off in THRESHOLD_PAIRS:
            d = run_rules([with_source(records[i], source) for i in valid], {"occupancy_on_above": on, "occupancy_off_below": off})
            light = pd.Series([x["light"] for x in d], index=valid).reindex(range(len(records))).ffill().fillna("OFF").to_numpy()
            factor = np.select([light == "OFF", light == "DIM"], [0.0, 0.5], 1.0)
            rows.append({"source": source, "on_above": on, "off_below": off, "occupied_rows": int(occupied.sum()),
                         "incorrect_light_off": int((occupied & (light == "OFF")).sum()),
                         "incorrect_light_off_pct": round(100 * (occupied & (light == "OFF")).sum() / occupied.sum(), 1),
                         "lighting_saved_pct": round(100 * (1 - (light_e * factor).sum() / light_e.sum()), 1)})
    return pd.DataFrame(rows)


def main() -> None:
    run_id = datetime.now().strftime("exp-%Y%m%d-%H%M%S")
    RESULTS.mkdir(exist_ok=True)
    report = json.loads((ROOT / "models/training_report.json").read_text(encoding="utf-8"))
    test_dates = report["split"]["test_dates"]
    started = time.perf_counter()
    f1 = add_targets(read_room_csv(ROOT / "data/combined_Room1.csv", "room1"))
    f1 = f1[f1["date"].isin(test_dates)].reset_index(drop=True)
    f2 = add_targets(read_room_csv(ROOT / "data/combined_Room2.csv", "room2")).reset_index(drop=True)
    fv = add_targets(read_room_csv(ROOT / "data/combined_Room1.csv", "room1"))
    fv = fv[fv["date"].isin(report["split"]["validation_dates"])].reset_index(drop=True)
    tuning = experiment_thresholds(fv, live_analytics(fv, LivePredictor(ROOT / "models/eval"), "room1"))
    tuning.to_csv(RESULTS / "threshold_tuning_validation.csv", index=False)
    print(tuning[tuning.source == "random_forest"].to_string(index=False))
    cases = {}
    for case, frame, room in (("room1_test", f1, "room1"), ("room2_all_days", f2, "room2")):
        predictor = LivePredictor(ROOT / "models/eval")
        cases[case] = (frame, live_analytics(frame, predictor, room))
        print(f"live predictions for {case}: {sum(r is not None for r in cases[case][1])} valid rows")

    savings, comfort = [], []
    for case, (frame, records) in cases.items():
        s, c = experiment_recorded(case, frame, records)
        savings += s
        comfort += c
    savings_df, comfort_df = pd.DataFrame(savings), pd.DataFrame(comfort)
    savings_df.to_csv(RESULTS / "savings_results.csv", index=False)
    comfort_df.to_csv(RESULTS / "savings_comfort.csv", index=False)

    dqn = DuelingDQNController.load(ROOT / "models/dqn_controller.pt")
    closed_rows, traces = experiment_closed_loop(*cases["room1_test"], dqn)
    closed_df = pd.DataFrame(closed_rows)
    closed_df.to_csv(RESULTS / "closed_loop_results.csv", index=False)
    figures(report, savings_df, closed_df, traces, cases["room1_test"][0])

    db_rows = experiment_rows(savings_df, closed_df, run_id, comfort_df)
    write_rows("experiment_results", db_rows)
    print(f"Done in {time.perf_counter() - started:.0f} s. Results in results/ and results/figures/ ({run_id})")


if __name__ == "__main__":
    main()

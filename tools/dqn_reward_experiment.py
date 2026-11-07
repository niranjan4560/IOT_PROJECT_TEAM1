"""Live-modification exercise E: retrain the Dueling DQN with a different COMFORT reward weight and compare.

  python tools/dqn_reward_experiment.py --comfort-per-k 0.5            (the registered default weight)
  python tools/dqn_reward_experiment.py --comfort-per-k 2.0            (comfort matters 4x more)

What it does (kept short enough for a live demo, about 1 minute per run on a laptop CPU):
  * trains a NEW Dueling DQN in the same grey-box room simulator on the 23 training+validation dates;
  * to keep it fast, the DQN observes the CAMERA occupancy label (oracle) instead of the out-of-fold LSTM
    probabilities used by train_models.py, and trains for --episodes (default 150, registered model: 400);
  * evaluates the raw policy (no safety layer) on the 6 held-out TEST dates, also with oracle occupancy;
  * appends one row to results/supplementary/dqn_reward_sweep.csv and saves models/experiments/dqn_comfort_<w>.pt.

It NEVER overwrites models/dqn_controller.pt or any registered result. Numbers from this tool are only comparable
with other rows of dqn_reward_sweep.csv (same shortened protocol), not with results/closed_loop_results.csv.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from smartclass import arrival  # noqa: E402
from smartclass.dataset import split_dates  # noqa: E402
from smartclass.dqn import DuelingDQNController  # noqa: E402
from smartclass.room_env import ClassroomEnv, RewardWeights  # noqa: E402
from train_models import ROOM1, prepare  # noqa: E402

SEED = 42


def evaluate(controller: DuelingDQNController, days: list[pd.DataFrame], profile: dict, weights: RewardWeights) -> dict:
    tot = {"cooling_kwh_thermal": 0.0, "occupied_steps": 0, "violation_steps": 0, "violation_kh": 0.0, "switches": 0, "reward": 0.0}
    for day in days:
        env = ClassroomEnv(day, day["occupant_presence"].fillna(0).to_numpy(float), arrival.lookup_frame(profile, day), weights=weights)
        obs, last = env.reset(), None
        while not env.done:
            action = controller.act(obs)
            obs, reward, info = env.step(action)
            tot["cooling_kwh_thermal"] += info["cooling_kwh_thermal"]
            tot["reward"] += reward
            if info["occupied"]:
                tot["occupied_steps"] += 1
                tot["violation_steps"] += int(info["comfort_violation_k"] > 0)
                tot["violation_kh"] += info["comfort_violation_k"] * 5 / 60
            tot["switches"] += int(last is not None and action != last)
            last = action
    return {"test_cooling_kwh_thermal": round(tot["cooling_kwh_thermal"], 1),
            "test_comfort_violation_pct": round(100 * tot["violation_steps"] / max(tot["occupied_steps"], 1), 1),
            "test_comfort_violation_kelvin_hours": round(tot["violation_kh"], 2),
            "test_ac_switches_per_day": round(tot["switches"] / len(days), 1)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--comfort-per-k", type=float, default=RewardWeights().comfort_per_k)
    parser.add_argument("--co2-per-100ppm", type=float, default=RewardWeights().co2_per_100ppm)
    parser.add_argument("--episodes", type=int, default=150)
    args = parser.parse_args()
    weights = RewardWeights(comfort_per_k=args.comfort_per_k, co2_per_100ppm=args.co2_per_100ppm)
    frame = prepare(ROOM1, "room1")
    train_d, val_d, test_d = split_dates(frame)
    profile = json.loads((ROOT / "models/eval/occupancy_profile.json").read_text(encoding="utf-8"))
    train_days = [frame[frame["date"] == d] for d in train_d + val_d]
    test_days = [frame[frame["date"] == d] for d in test_d]
    controller = DuelingDQNController(seed=SEED)
    start = time.perf_counter()
    controller.train(lambda i: ClassroomEnv(train_days[i], train_days[i]["occupant_presence"].fillna(0).to_numpy(float),
                                            arrival.lookup_frame(profile, train_days[i]), weights=weights),
                     len(train_days), episodes=args.episodes)
    seconds = time.perf_counter() - start
    out_models = ROOT / "models/experiments"
    out_models.mkdir(parents=True, exist_ok=True)
    model_path = out_models / f"dqn_comfort_{args.comfort_per_k:g}.pt"
    controller.save(model_path)
    row = {"run_at": datetime.now().isoformat(timespec="seconds"), **{f"w_{k}": v for k, v in asdict(weights).items()},
           "episodes": args.episodes, "occupancy_input": "camera label (oracle)", "train_seconds": round(seconds, 1),
           **evaluate(controller, test_days, profile, weights), "model_file": str(model_path.relative_to(ROOT))}
    out = ROOT / "results/supplementary/dqn_reward_sweep.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row]).to_csv(out, mode="a", header=not out.exists(), index=False)
    print(json.dumps(row, indent=2))
    print(f"appended to {out.relative_to(ROOT)} - compare with the other rows of that file")


if __name__ == "__main__":
    main()

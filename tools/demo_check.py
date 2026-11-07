"""Live-demo helper: run a fixed scenario through the Decision rules node of the CURRENT nodered/flows.json
(Node-RED rewrites that file when you press Deploy) and print what the rules decide, step by step.

  python tools/demo_check.py occupancy   - exercise A: occupancy probability rises and falls (hysteresis)
  python tools/demo_check.py comfort     - exercise B: occupied room getting warmer (COMFORT vs BOOST)
  python tools/demo_check.py hold        - exercise C: grace period / AC off (rules) and minimum hold (DQN flip-flop)
  python tools/demo_check.py dqn         - DQN mode: recommendation vs comfort guard (shows ac_source)
Times are DATA time (5-minute readings), exactly as in the replay. Nothing is published; no broker needed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from smartclass.rules_runner import run_rules  # noqa: E402

START = datetime.fromisoformat("2021-09-20T09:00:00+08:00")


def rec(i, p, temp=24.5, dqn=None, arrival=0.0):
    return {"room_id": "room1", "timestamp": (START + timedelta(minutes=5 * i)).isoformat(timespec="seconds"),
            "occupancy_probability": p, "primary_model": "random_forest", "p_arrival_30min": arrival, "dqn_ac_action": dqn,
            "models": {}, "reading": {"temperature_c": temp, "illuminance_lux": 10.0, "co2_ppm": 600}}


def config_values(keys):
    flows = json.loads((ROOT / "nodered/flows.json").read_text(encoding="utf-8"))
    code = next(n for n in flows if n.get("type") == "function" and n.get("name") == "CONFIG (all thresholds)")["initialize"]
    out = []
    for k in keys:
        line = next((l.strip() for l in code.splitlines() if l.strip().startswith(k + ":")), f"{k}: ?")
        out.append(line.split("//")[0].strip().rstrip(","))
    return ", ".join(out)


def show(records, config=None, extra=lambda r, d: ""):
    for r, d in zip(records, run_rules(records, config)):
        t = r["timestamp"][11:16]
        p = r["occupancy_probability"]
        print(f"  {t}  p={'-' if p is None else f'{p:.2f}'}  temp={r['reading']['temperature_c']:.1f}  ->  light {d['light']:4s} "
              f"AC {d['ac']:8s} ({d['ac_source']}){extra(r, d)}   {d['reason']}")


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "occupancy"
    if which == "occupancy":
        print("CONFIG:", config_values(["occupancy_on_above", "occupancy_off_below"]))
        ps = [0.05, 0.20, 0.30, 0.45, 0.55, 0.35, 0.20, 0.12, 0.05]
        show([rec(i, p) for i, p in enumerate(ps)])
    elif which == "comfort":
        print("CONFIG:", config_values(["comfort_setpoint_c", "boost_above_comfort_c"]))
        temps = [24.0, 24.8, 25.2, 25.6, 26.0, 26.5]
        show([rec(i, 0.9, temp=t) for i, t in enumerate(temps)])
    elif which == "hold":
        print("CONFIG:", config_values(["light_off_after_min", "ac_off_after_min", "min_hold_min"]))
        print("Part 1 - rules: grace period (light_off_after_min) and AC off (ac_off_after_min)")
        ps = [0.9, 0.9] + [0.05] * 9
        show([rec(i, p) for i, p in enumerate(ps)])
        print("Part 2 - DQN mode, the DQN flips COMFORT/OFF every reading in an occupied 24.5 C room:")
        print("         switching DOWN waits min_hold_min; switching UP for an occupied room is immediate")
        flips = ["COMFORT", "OFF", "OFF", "COMFORT", "OFF", "OFF", "OFF", "COMFORT"]
        show([rec(i, 0.9, dqn=a) for i, a in enumerate(flips)], {"ac_controller": "dqn"},
             extra=lambda r, d: f"  DQN wanted {r['dqn_ac_action']}")
    elif which == "dqn":
        print("CONFIG: ac_controller = 'dqn' (forced for this scenario);", config_values(["dqn_comfort_guard_c", "comfort_setpoint_c"]))
        cases = [(0.9, 24.5, "ECO"), (0.9, 26.5, "OFF"), (0.05, 25.0, "OFF"), (0.9, 25.0, None)]
        show([rec(i * 13, p, temp=t, dqn=a) for i, (p, t, a) in enumerate(cases)], {"ac_controller": "dqn"},
             extra=lambda r, d: f"  DQN: {d['dqn_status']}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()

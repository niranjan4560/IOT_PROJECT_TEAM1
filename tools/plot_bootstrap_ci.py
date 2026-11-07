"""Figure for the supplementary bootstrap CIs: results/supplementary/bootstrap_ci_test_f1.png (reads the CSV only)."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results/supplementary"
t = pd.read_csv(OUT / "bootstrap_ci_test_f1.csv").sort_values("test_f1_registered")
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                     "grid.color": "#e5e5e5", "axes.axisbelow": True})
fig, ax = plt.subplots(figsize=(7.5, 4.1))
y = range(len(t))
ax.hlines(y, t.ci95_low, t.ci95_high, color="#a9c9f1", lw=6, label="test F1, 95% CI (bootstrap over the 6 test dates)")
ax.plot(t.test_f1_registered, y, "o", color="#2a78d6", ms=8, label="test F1 (registered)")
ax.plot(t.validation_f1, y, "D", mfc="white", mec="#eb6834", mew=1.8, ms=7, label="validation F1 (used for selection)")
ax.set_yticks(list(y), [m.replace("_", " ") + ("  ★" if m == "random_forest" else "") for m in t.model])
ax.set_xlim(0, 1)
ax.set_xlabel("F1 (occupied class), Room 1")
ax.set_title("Occupancy models: no model is separable from the primary on 6 test dates", fontsize=10, loc="left")
ax.legend(loc="upper center", bbox_to_anchor=(0.42, -0.2), ncol=2, fontsize=7.5, frameon=False)
fig.tight_layout()
fig.savefig(OUT / "bootstrap_ci_test_f1.png", dpi=160)
print("wrote", OUT / "bootstrap_ci_test_f1.png")

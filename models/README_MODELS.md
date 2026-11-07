# Models in this repository

**Included:** `models/final/` (the deployed models) and `models/dqn_controller.pt`, so the system runs without
retraining.
- They are losslessly compressed with joblib (xz) to keep the repository small.
- They load with the same code, and every tree, coefficient and threshold is identical to the originals.
- `models/training_report.json` holds the registered metrics used in the report.

**Not included:** `models/eval/` (models trained on the training dates only). It is needed only to re-run
`run_experiments.py`, `tools/bootstrap_ci.py` or `tools/dqn_reward_experiment.py`. Recreate it with:

```bash
python train_models.py      # about 10 min on a laptop CPU, seed 42
```

`train_models.py` rewrites `models/final/` and `models/training_report.json` too. On a different CPU or operating
system, the deep-learning numbers can differ slightly from the registered ones; the registered results stay in
`results/`.

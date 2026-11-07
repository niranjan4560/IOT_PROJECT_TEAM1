"""Deep-learning occupancy models (category 3 of the reference architecture).

LSTMOccupancy  - occupancy estimator of research algorithm B (Hou et al., Building and Environment 284,
                 113501, 2025: LSTM occupancy estimation feeding a Dueling-DQN HVAC controller).
MambaOccupancy - research algorithm A: a selective state-space (Mamba) sequence classifier, the model family
                 of OCC-Mamba (Qaisar et al., Building and Environment, article 114085). OCC-Mamba's exact
                 layer configuration was not accessible to us, so the block follows the public Mamba design
                 (Gu & Dao, arXiv:2312.00752): input projection -> causal depth-wise Conv1d -> SiLU ->
                 selective SSM with input-dependent (Delta, B, C) -> gate with SiLU(z) -> output projection.
                 The selective scan is written as a plain PyTorch loop (no CUDA kernel), which is fast enough
                 for 12-step windows on a laptop CPU.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


# ----------------------------------------------------------------------------- models
class LSTMOccupancy(nn.Module):
    def __init__(self, n_features: int, hidden: int = 32, layers: int = 1, dropout: float = 0.1):
        super().__init__()
        self.lstm = nn.LSTM(n_features, hidden, num_layers=layers, batch_first=True)
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # x: (batch, time, features) -> logits (batch,)
        out, _ = self.lstm(x)
        return self.head(self.dropout(out[:, -1])).squeeze(-1)


class RMSNorm(nn.Module):
    def __init__(self, d: int, eps: float = 1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(d))

    def forward(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps) * self.weight


class MambaBlock(nn.Module):
    """One Mamba block (selective SSM), following Gu & Dao's reference design."""

    def __init__(self, d_model: int, d_state: int = 8, d_conv: int = 4, expand: int = 2):
        super().__init__()
        d_inner = expand * d_model
        self.d_inner, self.d_state = d_inner, d_state
        self.dt_rank = math.ceil(d_model / 16)
        self.in_proj = nn.Linear(d_model, 2 * d_inner, bias=False)
        self.conv1d = nn.Conv1d(d_inner, d_inner, kernel_size=d_conv, groups=d_inner, padding=d_conv - 1)
        self.x_proj = nn.Linear(d_inner, self.dt_rank + 2 * d_state, bias=False)
        self.dt_proj = nn.Linear(self.dt_rank, d_inner, bias=True)
        a = torch.arange(1, d_state + 1, dtype=torch.float32).repeat(d_inner, 1)
        self.A_log = nn.Parameter(torch.log(a))          # A = -exp(A_log) keeps the SSM stable
        self.D = nn.Parameter(torch.ones(d_inner))       # skip connection
        self.out_proj = nn.Linear(d_inner, d_model, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # (B, L, d_model)
        length = x.shape[1]
        u, z = self.in_proj(x).chunk(2, dim=-1)
        u = self.conv1d(u.transpose(1, 2))[..., :length].transpose(1, 2)  # causal: drop right padding
        u = F.silu(u)
        y = self.selective_scan(u)
        return self.out_proj(y * F.silu(z))

    def selective_scan(self, u: torch.Tensor) -> torch.Tensor:
        A = -torch.exp(self.A_log)                                    # (d_inner, N)
        delta, B, C = torch.split(self.x_proj(u), [self.dt_rank, self.d_state, self.d_state], dim=-1)
        delta = F.softplus(self.dt_proj(delta))                       # input-dependent step size
        dA = torch.exp(delta.unsqueeze(-1) * A)                       # zero-order-hold discretisation
        dBu = delta.unsqueeze(-1) * B.unsqueeze(2) * u.unsqueeze(-1)  # (B, L, d_inner, N)
        h = torch.zeros(u.shape[0], self.d_inner, self.d_state, device=u.device)
        ys = []
        for t in range(u.shape[1]):                                   # selective scan (recurrent form)
            h = dA[:, t] * h + dBu[:, t]
            ys.append((h * C[:, t].unsqueeze(1)).sum(-1))
        return torch.stack(ys, dim=1) + u * self.D


class MambaOccupancy(nn.Module):
    def __init__(self, n_features: int, d_model: int = 32, layers: int = 2, d_state: int = 8, dropout: float = 0.1):
        super().__init__()
        self.embed = nn.Linear(n_features, d_model)
        self.blocks = nn.ModuleList([MambaBlock(d_model, d_state) for _ in range(layers)])
        self.norms = nn.ModuleList([RMSNorm(d_model) for _ in range(layers)])
        self.final_norm = RMSNorm(d_model)
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(d_model, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.embed(x)
        for norm, block in zip(self.norms, self.blocks):
            h = h + block(norm(h))                                    # pre-norm residual blocks
        return self.head(self.dropout(self.final_norm(h)[:, -1])).squeeze(-1)


ARCHITECTURES = {"lstm": LSTMOccupancy, "mamba": MambaOccupancy}


# ----------------------------------------------------------------------------- training
@dataclass
class TrainConfig:
    architecture: str
    max_epochs: int = 40
    batch_size: int = 128
    lr: float = 1e-3
    patience: int = 6
    seed: int = 42


class SequenceClassifier:
    """Scaler + network + training loop; same interface as a scikit-learn classifier (predict_proba)."""

    def __init__(self, n_features: int, config: TrainConfig, model_kwargs: dict | None = None):
        self.config = config
        self.model_kwargs = model_kwargs or {}
        self.n_features = n_features
        torch.manual_seed(config.seed)
        self.net = ARCHITECTURES[config.architecture](n_features, **self.model_kwargs)
        self.mean = np.zeros(n_features, dtype=np.float32)
        self.scale = np.ones(n_features, dtype=np.float32)
        self.best_epoch = 0
        self.history: list[dict] = []

    def _tensor(self, windows: np.ndarray) -> torch.Tensor:
        return torch.as_tensor((windows - self.mean) / self.scale, dtype=torch.float32)

    def fit(self, x_train, y_train, x_val=None, y_val=None, epochs: int | None = None) -> "SequenceClassifier":
        """Scaler is fitted on the TRAINING windows only. With validation data: early stopping on val F1."""
        from sklearn.metrics import f1_score

        torch.manual_seed(self.config.seed)
        np.random.seed(self.config.seed)
        flat = x_train.reshape(-1, x_train.shape[-1])
        self.mean, self.scale = flat.mean(0), flat.std(0) + 1e-6
        xt, yt = self._tensor(x_train), torch.as_tensor(y_train, dtype=torch.float32)
        pos_weight = torch.tensor(float((len(yt) - yt.sum()) / max(float(yt.sum()), 1.0)))  # balance classes like class_weight
        opt = torch.optim.Adam(self.net.parameters(), lr=self.config.lr)
        generator = torch.Generator().manual_seed(self.config.seed)
        best_state, best_f1, waited = None, -1.0, 0
        for epoch in range(1, (epochs or self.config.max_epochs) + 1):
            self.net.train()
            order = torch.randperm(len(xt), generator=generator)
            for start in range(0, len(xt), self.config.batch_size):
                idx = order[start:start + self.config.batch_size]
                loss = F.binary_cross_entropy_with_logits(self.net(xt[idx]), yt[idx], pos_weight=pos_weight)
                opt.zero_grad()
                loss.backward()
                opt.step()
            if x_val is not None and epochs is None:
                f1 = f1_score(y_val, self.predict_proba(x_val)[:, 1] >= 0.5, zero_division=0)
                self.history.append({"epoch": epoch, "val_f1": round(float(f1), 4)})
                if f1 > best_f1:
                    best_f1, best_state, waited, self.best_epoch = f1, {k: v.clone() for k, v in self.net.state_dict().items()}, 0, epoch
                else:
                    waited += 1
                    if waited >= self.config.patience:
                        break
        if best_state is not None:
            self.net.load_state_dict(best_state)
        elif epochs:
            self.best_epoch = epochs
        self.net.eval()
        return self

    @torch.no_grad()
    def predict_proba(self, windows: np.ndarray) -> np.ndarray:
        self.net.eval()
        p = torch.sigmoid(self.net(self._tensor(windows))).numpy()
        return np.stack([1 - p, p], axis=1)

    def predict(self, windows: np.ndarray) -> np.ndarray:
        return (self.predict_proba(windows)[:, 1] >= 0.5).astype(int)

    def save(self, path: str | Path) -> None:
        torch.save({"state_dict": self.net.state_dict(), "config": asdict(self.config), "model_kwargs": self.model_kwargs,
                    "n_features": self.n_features, "mean": self.mean, "scale": self.scale,
                    "best_epoch": self.best_epoch, "history": self.history}, path)

    @classmethod
    def load(cls, path: str | Path) -> "SequenceClassifier":
        blob = torch.load(path, map_location="cpu", weights_only=False)
        obj = cls(blob["n_features"], TrainConfig(**blob["config"]), blob["model_kwargs"])
        obj.net.load_state_dict(blob["state_dict"])
        obj.mean, obj.scale, obj.best_epoch, obj.history = blob["mean"], blob["scale"], blob["best_epoch"], blob["history"]
        obj.net.eval()
        return obj

    def parameter_count(self) -> int:
        return sum(p.numel() for p in self.net.parameters())


def timed(fn, *args, **kwargs):
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, time.perf_counter() - start

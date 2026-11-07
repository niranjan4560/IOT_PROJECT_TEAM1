"""Dueling Deep Q-Network HVAC controller (control part of research algorithm B, Hou et al. 2025).

Preserved from the paper: occupancy estimated by an LSTM is an input to a Dueling DQN that chooses the HVAC
action, trading energy against thermal comfort and indoor-air-quality (CO2) violations.
Changed (the full text's state/action/reward definitions were not accessible to us): the state, the four
discrete actions (OFF/ECO/COMFORT/BOOST, the same commands our actuator understands) and the reward weights
are our own, documented in smartclass/room_env.py; training uses our grey-box simulator, not the authors'.
Standard DQN machinery is used around the dueling head: experience replay, a target network and
epsilon-greedy exploration.
"""
from __future__ import annotations

import random
import time
from collections import deque
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from smartclass.room_env import AC_ACTIONS, ClassroomEnv

OBS_DIM = 7


class DuelingQNet(nn.Module):
    """Q(s,a) = V(s) + A(s,a) - mean_a A(s,a)  (Wang et al. dueling architecture)."""

    def __init__(self, obs_dim: int = OBS_DIM, n_actions: int = len(AC_ACTIONS), hidden: int = 64):
        super().__init__()
        self.body = nn.Sequential(nn.Linear(obs_dim, hidden), nn.ReLU(), nn.Linear(hidden, hidden), nn.ReLU())
        self.value = nn.Linear(hidden, 1)
        self.advantage = nn.Linear(hidden, n_actions)

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        h = self.body(obs)
        adv = self.advantage(h)
        return self.value(h) + adv - adv.mean(dim=-1, keepdim=True)


class DuelingDQNController:
    def __init__(self, seed: int = 42):
        torch.manual_seed(seed)
        self.net = DuelingQNet()
        self.net.eval()
        self.training_log: list[dict] = []

    @torch.no_grad()
    def act(self, obs: np.ndarray) -> str:
        q = self.net(torch.as_tensor(obs, dtype=torch.float32).unsqueeze(0))[0]
        return AC_ACTIONS[int(q.argmax())]

    def train(self, make_env, n_days: int, episodes: int = 400, gamma: float = 0.97, lr: float = 1e-3,
              batch: int = 64, buffer_size: int = 50_000, target_sync: int = 1000, eps_start: float = 1.0,
              eps_end: float = 0.05, seed: int = 42) -> float:
        """make_env(i) returns the ClassroomEnv for training day i. Returns training time in seconds."""
        rng = random.Random(seed)
        torch.manual_seed(seed)
        target = DuelingQNet()
        target.load_state_dict(self.net.state_dict())
        opt = torch.optim.Adam(self.net.parameters(), lr=lr)
        memory: deque = deque(maxlen=buffer_size)
        steps, start = 0, time.perf_counter()
        for episode in range(episodes):
            env: ClassroomEnv = make_env(rng.randrange(n_days))
            obs = env.reset()
            eps = max(eps_end, eps_start - (eps_start - eps_end) * episode / (0.7 * episodes))
            total = 0.0
            while not env.done:
                self.net.eval()
                action = rng.randrange(len(AC_ACTIONS)) if rng.random() < eps else AC_ACTIONS.index(self.act(obs))
                nxt, reward, _ = env.step(AC_ACTIONS[action])
                memory.append((obs, action, reward, nxt, float(env.done)))
                obs, total, steps = nxt, total + reward, steps + 1
                if len(memory) >= 2000 and steps % 2 == 0:
                    self.net.train()
                    sample = rng.sample(memory, batch)
                    o, a, r, n, d = (torch.as_tensor(np.array(x), dtype=torch.float32) for x in zip(*sample))
                    q = self.net(o).gather(1, a.long().unsqueeze(1)).squeeze(1)
                    with torch.no_grad():
                        y = r + gamma * (1 - d) * target(n).max(1).values
                    loss = F.smooth_l1_loss(q, y)
                    opt.zero_grad()
                    loss.backward()
                    nn.utils.clip_grad_norm_(self.net.parameters(), 10.0)
                    opt.step()
                if steps % target_sync == 0:
                    target.load_state_dict(self.net.state_dict())
            if episode % 20 == 0 or episode == episodes - 1:
                self.training_log.append({"episode": episode, "epsilon": round(eps, 3), "return": round(total, 2)})
        self.net.eval()
        return time.perf_counter() - start

    def save(self, path: str | Path) -> None:
        torch.save({"state_dict": self.net.state_dict(), "actions": AC_ACTIONS, "obs_dim": OBS_DIM,
                    "training_log": self.training_log}, path)

    @classmethod
    def load(cls, path: str | Path) -> "DuelingDQNController":
        blob = torch.load(path, map_location="cpu", weights_only=False)
        obj = cls()
        obj.net.load_state_dict(blob["state_dict"])
        obj.net.eval()
        obj.training_log = blob.get("training_log", [])
        return obj


def dqn_observation(occupancy_prob: float, arrival_prob: float, temp_c: float, co2_ppm: float,
                    outdoor_temp_c: float, timestamp_minutes: int) -> np.ndarray:
    """Live version of ClassroomEnv.observation() (same scaling), used by the ML service."""
    return np.array([occupancy_prob, arrival_prob, (temp_c - 24.0) / 3.0, (co2_ppm - 600.0) / 400.0,
                     (outdoor_temp_c - 28.0) / 4.0, np.sin(2 * np.pi * timestamp_minutes / 1440),
                     np.cos(2 * np.pi * timestamp_minutes / 1440)], dtype=np.float32)

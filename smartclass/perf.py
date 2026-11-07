"""Computational-performance measurements (training time, latency, memory, model size)."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import numpy as np
import psutil


class PeakMemory:
    """Samples this process's resident memory every 10 ms; peak_mb_above_start is the extra memory used."""

    def __enter__(self):
        self.process = psutil.Process(os.getpid())
        self.start = self.peak = self.process.memory_info().rss
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        self.t0 = time.perf_counter()
        return self

    def _sample(self):
        while not self._stop.is_set():
            self.peak = max(self.peak, self.process.memory_info().rss)
            time.sleep(0.01)

    def __exit__(self, *exc):
        self.seconds = time.perf_counter() - self.t0
        self._stop.set()
        self._thread.join()
        self.peak = max(self.peak, self.process.memory_info().rss)
        self.peak_mb_above_start = (self.peak - self.start) / 2**20
        return False


def latency_ms(predict_one, sample, repeats: int = 200) -> dict:
    """Median and 95th-percentile wall-clock latency of ONE prediction (what the live service does)."""
    for _ in range(10):
        predict_one(sample)  # warm-up
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        predict_one(sample)
        times.append((time.perf_counter() - start) * 1000)
    return {"median_ms": round(float(np.median(times)), 3), "p95_ms": round(float(np.percentile(times, 95)), 3)}


def file_size_kb(path: str | Path) -> float:
    return round(Path(path).stat().st_size / 1024, 1)

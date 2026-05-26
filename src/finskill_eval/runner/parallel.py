"""Parallel grid execution with rate limiting and resumability (M5).

Runs the grid under a concurrency cap and a global request-rate limit (so
parallel FMP calls stay within limits). Resumable: a sample whose result JSON
already exists is loaded from disk and its scorer is not re-run.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from finskill_eval.runner.grid import GridSample, SampleRecord


class RateLimiter:
    """Spaces calls to at most `rps` per second across threads."""

    def __init__(self, rps: float):
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval


def _result_path(results_dir: Path, sample: GridSample) -> Path:
    return Path(results_dir) / f"{sample.sample_id}.json"


def _load(path: Path) -> SampleRecord:
    return SampleRecord(**json.loads(path.read_text(encoding="utf-8")))


def _persist(path: Path, rec: SampleRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(rec), indent=2), encoding="utf-8")


def run_grid(
    samples: list[GridSample],
    score_fn: Callable[[GridSample], SampleRecord],
    *,
    concurrency: int,
    global_rps: float,
    resume: bool,
    results_dir: Path,
) -> list[SampleRecord]:
    results_dir = Path(results_dir)
    limiter = RateLimiter(global_rps)
    results: dict[str, SampleRecord] = {}

    pending: list[GridSample] = []
    for s in samples:
        path = _result_path(results_dir, s)
        if resume and path.exists():
            results[s.sample_id] = _load(path)
        else:
            pending.append(s)

    def _work(sample: GridSample) -> tuple[str, SampleRecord]:
        limiter.acquire()
        rec = score_fn(sample)
        _persist(_result_path(results_dir, sample), rec)
        return sample.sample_id, rec

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            for sid, rec in pool.map(_work, pending):
                results[sid] = rec

    # preserve input order
    return [results[s.sample_id] for s in samples]

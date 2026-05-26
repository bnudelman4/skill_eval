"""Frozen point-in-time snapshots (M4).

Every ground-truth pull is written under data/snapshots/<source>/<pull_date>/,
and re-reads come from the frozen snapshot — so a run is reproducible even as
live vendor data changes. The snapshot key is source + ticker + period + label
(+ pull_date in the path).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from finskill_eval.groundtruth.base import Value


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s)


class SnapshotStore:
    def __init__(self, *, root: Path | str, pull_date: str):
        self.root = Path(root)
        self.pull_date = pull_date

    def _path(self, source: str, ticker: str, period: str, label: str) -> Path:
        fname = f"{_safe(ticker)}_{_safe(period)}_{_safe(label)}.json"
        return self.root / source / self.pull_date / fname

    def write(self, source: str, ticker: str, period: str, label: str, value: Value) -> Path:
        path = self._path(source, ticker, period, label)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value.model_dump_json(), encoding="utf-8")
        return path

    def read(self, source: str, ticker: str, period: str, label: str) -> Optional[Value]:
        path = self._path(source, ticker, period, label)
        if not path.exists():
            return None
        return Value.model_validate_json(path.read_text(encoding="utf-8"))

    def get_or_fetch(
        self,
        source: str,
        ticker: str,
        period: str,
        label: str,
        fetch: Callable[[], Optional[Value]],
    ) -> Optional[Value]:
        cached = self.read(source, ticker, period, label)
        if cached is not None:
            return cached
        fresh = fetch()
        if fresh is not None:
            self.write(source, ticker, period, label, fresh)
        return fresh

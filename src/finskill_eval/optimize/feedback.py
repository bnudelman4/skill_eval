"""User-feedback capture off the FLAG/PASS mechanism (M7.6).

Analysts override the verifier on specific cells: "correct despite FLAG" or
"wrong despite PASS". These judgments are append-only labeled data that refine
the JUDGE (tolerance bands) and the TEST SET — never silently edit a skill body.

  - FLAG/WARN overturned to correct  -> bands may be too tight
  - PASS overturned to wrong         -> bands may be too loose (more serious)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

HumanLabel = Literal["correct", "wrong"]


@dataclass
class FeedbackEntry:
    skill: str
    ticker: str
    period: str
    canonical_label: str
    verifier_status: str       # PASS / WARN / FLAG / FAIL as scored
    human_label: HumanLabel    # analyst's verdict
    note: str = ""

    @property
    def disagrees(self) -> bool:
        verifier_pass = self.verifier_status == "PASS"
        human_pass = self.human_label == "correct"
        return verifier_pass != human_pass


def append_feedback(path: Path, entry: FeedbackEntry) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry)) + "\n")


def load_feedback(path: Path) -> list[FeedbackEntry]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(FeedbackEntry(**json.loads(line)))
    return out


@dataclass
class FeedbackSummary:
    total: int
    agreements: int
    flag_overturned_correct: int   # verifier flagged/failed, human says correct
    pass_overturned_wrong: int     # verifier passed, human says wrong
    suggestions: list[str]


def summarize_feedback(entries: list[FeedbackEntry]) -> FeedbackSummary:
    flag_overturned = sum(
        1 for e in entries
        if e.human_label == "correct" and e.verifier_status in ("WARN", "FLAG", "FAIL")
    )
    pass_overturned = sum(
        1 for e in entries
        if e.human_label == "wrong" and e.verifier_status == "PASS"
    )
    agreements = sum(1 for e in entries if not e.disagrees)
    suggestions: list[str] = []
    if flag_overturned:
        suggestions.append(
            f"{flag_overturned} cell(s) flagged but analyst-correct -> bands may be "
            f"too tight; review xvendor/materiality thresholds."
        )
    if pass_overturned:
        suggestions.append(
            f"{pass_overturned} cell(s) passed but analyst-wrong -> bands may be too "
            f"loose; this is the more serious miss (false PASS)."
        )
    return FeedbackSummary(
        total=len(entries),
        agreements=agreements,
        flag_overturned_correct=flag_overturned,
        pass_overturned_wrong=pass_overturned,
        suggestions=suggestions,
    )

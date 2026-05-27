"""M7.2: candidate generator — bounded edits, token cap, body protected."""

import pytest

from finskill_eval.optimize.candidate import (
    count_token_edits,
    make_candidate,
    validate_edit,
)
from finskill_eval.optimize.skilldoc import SkillDoc

SAMPLE = """---
name: comps
description: Trading comparables analysis with peer multiples
argument-hint: TICKER
---

## 1. Lookup
Body prose that must never change.
"""


def test_count_token_edits():
    assert count_token_edits("a b c", "a b c") == 0
    assert count_token_edits("a b c", "a b d") == 1          # one replace
    assert count_token_edits("a b", "a b c d") == 2          # two inserts


def test_validate_edit_accepts_small_compact_edit():
    ok, _ = validate_edit(
        "Trading comparables analysis with peer multiples",
        "Trading comparables analysis with peer multiples and implied valuation",
        max_edits=6, token_cap=920,
    )
    assert ok


def test_validate_edit_rejects_too_many_edits():
    ok, reason = validate_edit("a b c", "x y z w q r s", max_edits=4, token_cap=920)
    assert not ok and "edits" in reason.lower()


def test_validate_edit_rejects_over_token_cap():
    long = " ".join(["word"] * 50)
    ok, reason = validate_edit("a b c", long, max_edits=100, token_cap=10)
    assert not ok and "cap" in reason.lower()


def test_make_candidate_protects_body_and_applies_desc():
    doc = SkillDoc.parse(SAMPLE)

    def fake_llm(prompt: str) -> str:
        # LLM returns a new description (even if it tries to smuggle body text,
        # only the description is taken)
        return "Peer comps with implied valuation. Use for relative-value questions."

    cand = make_candidate(doc, fake_llm, max_edits=12, token_cap=920)
    assert cand is not None
    assert cand.body_hash() == doc.body_hash()           # body untouched
    assert "relative-value" in cand.description
    assert "Body prose that must never change." in cand.to_text()


def test_make_candidate_returns_none_on_guard_violation():
    doc = SkillDoc.parse(SAMPLE)
    # LLM blows the token cap -> rejected -> None
    cand = make_candidate(doc, lambda p: " ".join(["x"] * 200), max_edits=6, token_cap=10)
    assert cand is None

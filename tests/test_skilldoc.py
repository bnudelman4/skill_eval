"""M7.1: SkillDoc — parse/edit/emit SKILL.md with a protected (immutable) body."""

import pytest

from finskill_eval.optimize.skilldoc import SkillDoc

SAMPLE = """---
name: comps
description: Trading comparables analysis with peer multiples and implied valuation
argument-hint: TICKER
---

Build a trading comparables analysis for the company: $ARGUMENTS

## 1. Company Lookup
Look up the company by ticker using fmp_profile.
"""


def test_parse_extracts_description_and_body():
    doc = SkillDoc.parse(SAMPLE)
    assert doc.name == "comps"
    assert doc.description == "Trading comparables analysis with peer multiples and implied valuation"
    assert "## 1. Company Lookup" in doc.body


def test_roundtrip_is_byte_identical():
    assert SkillDoc.parse(SAMPLE).to_text() == SAMPLE


def test_with_description_changes_only_description():
    doc = SkillDoc.parse(SAMPLE)
    new = doc.with_description("Peer comps + implied valuation. Use for relative-value questions.")
    assert new.description == "Peer comps + implied valuation. Use for relative-value questions."
    # body must be byte-identical — the protected-section invariant
    assert new.body == doc.body
    assert new.body_hash() == doc.body_hash()
    # and the new description appears in the emitted text
    assert "relative-value questions" in new.to_text()
    assert "## 1. Company Lookup" in new.to_text()


def test_with_description_preserves_other_frontmatter_keys():
    new = SkillDoc.parse(SAMPLE).with_description("X")
    txt = new.to_text()
    assert "name: comps" in txt
    assert "argument-hint: TICKER" in txt


def test_body_hash_stable_across_description_edits():
    doc = SkillDoc.parse(SAMPLE)
    h0 = doc.body_hash()
    for desc in ["a", "b longer description here", "c"]:
        assert doc.with_description(desc).body_hash() == h0


def test_parse_rejects_missing_frontmatter():
    with pytest.raises(ValueError):
        SkillDoc.parse("no frontmatter here\njust body")

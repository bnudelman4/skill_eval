"""LLM label resolver tests — injectable LLM, no network."""

import json
from pathlib import Path

from finskill_eval.checks.llm_label_resolver import LLMLabelResolver
from finskill_eval.groundtruth.base import Value
from finskill_eval.groundtruth.fmp import FMPClient

CATALOG = {
    "income-statement": ["revenue", "netIncome", "grossProfit"],
    "ratios": ["grossProfitMargin", "netProfitMargin", "currentRatio"],
}


def test_resolver_returns_llm_proposal(tmp_path):
    cache = tmp_path / "label_cache.json"
    calls = []
    def fake_llm(label, catalog):
        calls.append(label)
        return ("ratios", "currentRatio")
    r = LLMLabelResolver(CATALOG, fake_llm, cache)
    assert r.resolve("liquidity_current_ratio") == ("ratios", "currentRatio")
    assert calls == ["liquidity_current_ratio"]
    # cached on disk
    cached = json.loads(cache.read_text())
    assert cached["liquidity_current_ratio"] == ["ratios", "currentRatio"]


def test_resolver_caches_on_second_call(tmp_path):
    cache = tmp_path / "c.json"
    calls = []
    def fake_llm(label, catalog):
        calls.append(label)
        return ("income-statement", "revenue")
    r = LLMLabelResolver(CATALOG, fake_llm, cache)
    r.resolve("top_line")
    r.resolve("top_line")
    assert len(calls) == 1   # second hit -> cache, no LLM call


def test_resolver_validates_proposal_against_catalog(tmp_path):
    """A hallucinated endpoint or field returns None and caches the negative."""
    cache = tmp_path / "c.json"
    def bad_llm(label, catalog):
        return ("non-existent-endpoint", "madeUpField")
    r = LLMLabelResolver(CATALOG, bad_llm, cache)
    assert r.resolve("weird_label") is None
    # cached as None so we don't re-ask the LLM
    cached = json.loads(cache.read_text())
    assert cached["weird_label"] is None


def test_resolver_caches_negative_resolution(tmp_path):
    cache = tmp_path / "c.json"
    calls = []
    def declining_llm(label, catalog):
        calls.append(label)
        return None
    r = LLMLabelResolver(CATALOG, declining_llm, cache)
    assert r.resolve("uncoverable_metric") is None
    assert r.resolve("uncoverable_metric") is None
    assert len(calls) == 1


def test_fmp_client_uses_resolver_on_label_map_miss(tmp_path):
    """FMPClient.get falls back to the resolver when LABEL_MAP doesn't have the label."""
    cache = tmp_path / "c.json"
    def fake_llm(label, catalog):
        return ("ratios", "currentRatio")

    fake_response = [{"fiscalYear": 2024, "currentRatio": 1.5}]
    def fake_fetch(endpoint, params):
        return fake_response

    resolver = LLMLabelResolver(
        {"ratios": ["currentRatio"]},
        fake_llm,
        cache,
    )
    client = FMPClient(api_key="x", fetch=fake_fetch, resolver=resolver)
    v = client.get("AAPL", "FY2024", "some_unmapped_liquidity_metric")
    assert v is not None
    assert v.value == 1.5

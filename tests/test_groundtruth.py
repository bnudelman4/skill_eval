"""M4: ground-truth sources + frozen snapshots. All network is injected/mocked."""

import json

import pytest

from finskill_eval.groundtruth.base import Value
from finskill_eval.groundtruth.cache import SnapshotStore
from finskill_eval.groundtruth.fmp import FMPClient, check_denomination
from finskill_eval.groundtruth.sec_xbrl import SECXBRLClient


# --------------------------------------------------------------------------- #
# FMP candidate client (injected fetcher -> no network)
# --------------------------------------------------------------------------- #
FMP_INCOME = [
    {"symbol": "AAPL", "fiscalYear": 2025, "revenue": 400000000000, "netIncome": 99000000000,
     "grossProfit": 185000000000, "operatingIncome": 127000000000},
    {"symbol": "AAPL", "fiscalYear": 2024, "revenue": 391035000000, "netIncome": 93736000000,
     "grossProfit": 180683000000, "operatingIncome": 123216000000},
]


def _fmp_fetch(endpoint, params):
    return {"income-statement": FMP_INCOME}[endpoint]


def test_fmp_returns_value_for_known_cell():
    c = FMPClient(api_key="x", fetch=_fmp_fetch)
    v = c.get("AAPL", "FY2024", "revenue")
    assert v is not None
    assert v.value == pytest.approx(391035000000.0)
    assert v.source_id == "fmp"
    assert v.period == "FY2024"


def test_fmp_picks_correct_period():
    c = FMPClient(api_key="x", fetch=_fmp_fetch)
    assert c.get("AAPL", "FY2025", "net_income").value == pytest.approx(99000000000.0)


def test_fmp_unknown_label_returns_none():
    c = FMPClient(api_key="x", fetch=_fmp_fetch)
    assert c.get("AAPL", "FY2024", "made_up_metric") is None


def test_fmp_missing_period_returns_none():
    c = FMPClient(api_key="x", fetch=_fmp_fetch)
    assert c.get("AAPL", "FY2099", "revenue") is None


def test_check_denomination_flags_scale_error():
    # netIncome > revenue by 1000x => suspected thousands/millions mix-up
    good = {"revenue": 391035000000, "netIncome": 93736000000}
    bad = {"revenue": 391035000, "netIncome": 93736000000}
    assert check_denomination(good) == []
    assert check_denomination(bad)  # non-empty warning list


# --------------------------------------------------------------------------- #
# SEC XBRL anchor / bootstrap-gold client (injected fetcher -> no network)
# --------------------------------------------------------------------------- #
SEC_FACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {"end": "2024-09-28", "val": 391035000000, "fy": 2024, "fp": "FY", "form": "10-K"},
                        {"end": "2023-09-30", "val": 383285000000, "fy": 2023, "fp": "FY", "form": "10-K"},
                        {"end": "2024-06-29", "val": 85000000000, "fy": 2024, "fp": "Q3", "form": "10-Q"},
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {"USD": [{"end": "2024-09-28", "val": 93736000000, "fy": 2024, "fp": "FY", "form": "10-K"}]}
            },
        }
    }
}


def _sec_fetch(cik):
    return SEC_FACTS


def test_sec_returns_annual_value():
    c = SECXBRLClient(user_agent="ua", cik_lookup={"AAPL": "0000320193"}, fetch=_sec_fetch)
    v = c.get("AAPL", "FY2024", "revenue")
    assert v.value == pytest.approx(391035000000.0)
    assert v.source_id == "sec_xbrl"
    assert v.vintage == "2024-09-28"


def test_sec_ignores_non_annual_form():
    c = SECXBRLClient(user_agent="ua", cik_lookup={"AAPL": "0000320193"}, fetch=_sec_fetch)
    # FY2024 annual must come from the 10-K row, not the Q3 10-Q
    assert c.get("AAPL", "FY2024", "revenue").value == pytest.approx(391035000000.0)


def test_sec_concept_fallback_list():
    c = SECXBRLClient(user_agent="ua", cik_lookup={"AAPL": "0000320193"}, fetch=_sec_fetch)
    assert c.get("AAPL", "FY2024", "net_income").value == pytest.approx(93736000000.0)


def test_sec_market_metric_is_none():
    # SEC XBRL cannot supply market cap / EV
    c = SECXBRLClient(user_agent="ua", cik_lookup={"AAPL": "0000320193"}, fetch=_sec_fetch)
    assert c.get("AAPL", "FY2024", "market_capitalization") is None


# --------------------------------------------------------------------------- #
# Frozen snapshots
# --------------------------------------------------------------------------- #
def test_snapshot_round_trip(tmp_path):
    store = SnapshotStore(root=tmp_path, pull_date="2026-05-26")
    v = Value(value=391035000000.0, unit="USD", vintage="2024-09-28",
              source_id="sec_xbrl", period="FY2024", canonical_label="revenue")
    store.write("sec_xbrl", "AAPL", "FY2024", "revenue", v)
    back = store.read("sec_xbrl", "AAPL", "FY2024", "revenue")
    assert back == v


def test_snapshot_get_or_fetch_freezes(tmp_path):
    store = SnapshotStore(root=tmp_path, pull_date="2026-05-26")
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return Value(value=1.0, unit="USD", vintage="v", source_id="fmp",
                     period="FY2024", canonical_label="revenue")

    a = store.get_or_fetch("fmp", "AAPL", "FY2024", "revenue", fetch)
    b = store.get_or_fetch("fmp", "AAPL", "FY2024", "revenue", fetch)
    assert a == b
    assert calls["n"] == 1  # second call served from frozen snapshot


def test_snapshot_miss_returns_none(tmp_path):
    store = SnapshotStore(root=tmp_path, pull_date="2026-05-26")
    assert store.read("fmp", "AAPL", "FY2024", "revenue") is None


# --------------------------------------------------------------------------- #
# Integration: M2 verifier pointed at a real (mocked) GroundTruthSource
# --------------------------------------------------------------------------- #
def test_verifier_accepts_real_source_returning_value_objects():
    from finskill_eval.ledger import Cell, Ledger
    from finskill_eval.normalize import Period
    from finskill_eval.verify import verify

    sec = SECXBRLClient(user_agent="ua", cik_lookup={"AAPL": "0000320193"}, fetch=_sec_fetch)
    cell = Cell(
        cell_id="revenue__FY2024", label="Revenue", canonical_label="revenue",
        period=Period("annual", 2024, None), raw_value="391,035",
        value=391035000000.0, unit="$mm", kind="direct",
    )
    led = Ledger(skill="tearsheet", ticker="AAPL", cells=[cell])
    report = verify(led, sec)
    v = report.verdicts[0]
    assert v.status == "PASS"
    assert v.band == "exact"

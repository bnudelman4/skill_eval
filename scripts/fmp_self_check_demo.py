"""Run FMP-self-check on a cached skill artifact.

Loads the artifact, parses to a Ledger, then for each cell asks FMP independently
("what does FMP itself say about this metric?") and compares to what the skill
wrote. Catches LLM transcription/selection/arithmetic errors deterministically.

Two modes:
  live   — uses FMP_API_KEY from .env (default)
  mock   — uses a baked-in AAPL FY2024 truth set (offline, for demo)

Run:
    PYTHONPATH=src python scripts/fmp_self_check_demo.py
    PYTHONPATH=src python scripts/fmp_self_check_demo.py --mock
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from finskill_eval.checks.fmp_self_check import render_markdown, run_fmp_self_check
from finskill_eval.checks.llm_label_resolver import (
    LLMLabelResolver,
    claude_resolver_fn,
)
from finskill_eval.groundtruth.base import Value
from finskill_eval.groundtruth.fmp import LABEL_MAP, FMPClient
from finskill_eval.parse_xlsx import parse


# Baked-in truth set (AAPL FY2024) for offline demo. Pulled from the actual
# AAPL FY2024 10-K so the demo can run without network or API key.
AAPL_FY2024_TRUTH = {
    "revenue":              391_035_000_000.0,
    "gross_profit":         180_683_000_000.0,
    "operating_income":     123_216_000_000.0,
    "ebitda":               134_930_000_000.0,
    "net_income":            93_736_000_000.0,
    "cash_and_equivalents":  29_943_000_000.0,
    "total_debt":           119_059_000_000.0,
    "operating_cash_flow":  118_254_000_000.0,
    "capital_expenditures":   9_447_000_000.0,
    "free_cash_flow":       108_807_000_000.0,
    "share_repurchases":     94_949_000_000.0,
    "dividends_paid":        15_234_000_000.0,
    "shares_outstanding":    15_408_095_000.0,
    "diluted_eps":                       6.08,
}


class MockFMP:
    def __init__(self, by_label):
        self._by = by_label

    def get(self, ticker, period, canonical_label):
        v = self._by.get(canonical_label)
        if v is None:
            return None
        return Value(value=v, unit="USD", vintage=str(period),
                     source_id="fmp_mock", period=period,
                     canonical_label=canonical_label)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", default="results/_pilot/workdirs/"
                    "tearsheet__AAPL__FY2024/output/tearsheet_AAPL_FY2024.xlsx")
    ap.add_argument("--mock", action="store_true",
                    help="use baked-in AAPL FY2024 truth, no network")
    ap.add_argument("--ticker", default="AAPL")
    ap.add_argument("--skill", default="tearsheet")
    ap.add_argument("--resolver", action="store_true",
                    help="enable LLM fallback for unmapped canonical labels "
                         "(uses claude -p; results cached to data/label_cache.json)")
    args = ap.parse_args()

    artifact = Path(args.artifact)
    if not artifact.exists():
        print(f"ERROR: artifact not found: {artifact}")
        return 1
    print(f"Loading {artifact}")
    led = parse(artifact, skill=args.skill, ticker=args.ticker)
    print(f"  parsed {len(led.cells)} cells")

    if args.mock:
        fmp = MockFMP(AAPL_FY2024_TRUTH)
        print("Mode: mock (baked AAPL FY2024 truth)")
    else:
        load_dotenv(".env", override=True)
        key = os.environ.get("FMP_API_KEY")
        if not key:
            print("ERROR: FMP_API_KEY not set; use --mock for offline demo")
            return 2
        resolver = None
        if args.resolver:
            # Use FMP's FULL field universe (probed live, persisted to
            # data/fmp_field_catalog.json) so the resolver can propose any
            # FMP field, not just the ones already mapped.
            cat_path = Path("data/fmp_field_catalog.json")
            if not cat_path.exists():
                print("ERROR: data/fmp_field_catalog.json missing; "
                      "see scripts/fmp_self_check_demo.py for how to generate")
                return 3
            import json as _json
            cat = _json.loads(cat_path.read_text())
            resolver = LLMLabelResolver(
                cat, claude_resolver_fn, Path("data/label_cache.json"),
            )
            print(f"Resolver: ENABLED ({sum(len(v) for v in cat.values())} fields, "
                  f"{len(cat)} endpoints)")
        fmp = FMPClient(api_key=key, resolver=resolver)
        print("Mode: live FMP")

    report = run_fmp_self_check(led, fmp)
    print()
    print(render_markdown(report))

    out = Path("results/_fmp_self_check") / f"{args.skill}_{args.ticker}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(report), encoding="utf-8")
    print(f"\nwrote {out}")
    print(f"\nheadline: pass-rate {report.pass_rate:.1%}  "
          f"PASS={report.counts.get('PASS',0)}  "
          f"FAIL={report.counts.get('FAIL',0)}  "
          f"SKIP={report.counts.get('SKIP',0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

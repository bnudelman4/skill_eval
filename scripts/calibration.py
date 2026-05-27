"""Step 0 calibration: does the verifier actually catch wrong numbers?

Runs unoptimized FMP skills live, verifies each artifact vs SEC gold, and
reports the catch-rate among cells SEC actually covers (coverage gaps are NOT
catches). Settles the 'is hallucination real here' question empirically.

Run: PYTHONPATH=src python scripts/calibration.py
"""

import time
from pathlib import Path

from dotenv import load_dotenv

from finskill_eval.config import load_settings
from finskill_eval.groundtruth.sec_xbrl import SECXBRLClient
from finskill_eval.parse_xlsx import parse
from finskill_eval.runner.invoke_skill import run_skill
from finskill_eval.verify import verify

load_dotenv(Path(".env"), override=True)

S = load_settings()
TICKER, PERIOD = "AAPL", "FY2024"
CIK = {"AAPL": "0000320193"}
UA = "finskill-eval Benjamin Nudelman bnudelman2@gmail.com"
SKILLS = ["tearsheet", "capital-allocation"]
ROOT = Path("results/_calibration/workdirs")
OUT = Path("results/calibration_catchrate.md")

gt = SECXBRLClient(user_agent=UA, cik_lookup=CIK)
lines = ["# Step 0 — Verifier Catch-Rate Calibration", "",
         f"Ticker {TICKER} {PERIOD}; gold = SEC XBRL. "
         f"A 'catch' = a cell SEC covers where the skill disagrees beyond the "
         f"PASS bands (WARN/FLAG/FAIL with a real gold value). Coverage gaps "
         f"(SEC has no value) are excluded.", ""]
grand = {"covered": 0, "pass": 0, "caught": 0, "cost": 0.0}

MAX_TRIES = 2  # transient exit_ok=False -> retry (runs are nondeterministic)

for skill in SKILLS:
    print(f"\n=== {skill} {TICKER} {PERIOD} (fmp) ===", flush=True)
    run = None
    for attempt in range(1, MAX_TRIES + 1):
        run = run_skill(
            skill, TICKER, PERIOD, "fmp",
            workdir=ROOT / f"{skill}__{TICKER}__{PERIOD}__try{attempt}",
            model=S.pins.model_snapshot, timeout=900,
            allowed_tools=S.invocation.allowed_tools, bare=S.invocation.bare,
            skill_src_dir=Path("skills/fmp") / skill,
        )
        grand["cost"] += run.cost_usd
        print(f"  try{attempt}: cost=${run.cost_usd:.4f} latency={run.latency_s:.0f}s "
              f"exit_ok={run.exit_ok} artifact={bool(run.artifact_path)}", flush=True)
        if run.artifact_path:
            break
    lines += [f"## {skill}",
              f"- cost ${run.cost_usd:.4f}, latency {run.latency_s:.0f}s, "
              f"exit_ok={run.exit_ok}, artifact={bool(run.artifact_path)}"]
    if not run.artifact_path:
        lines.append("- NO ARTIFACT after retries (timeout/crash) — skipped\n")
        continue

    try:
        led = parse(Path(run.artifact_path), skill=skill, ticker=TICKER)
        rep = verify(led, gt)
    except Exception as exc:  # layout the parser can't yet ingest
        print(f"  PARSE/VERIFY FAILED: {type(exc).__name__}: {exc}", flush=True)
        lines.append(f"- PARSE/VERIFY FAILED: {type(exc).__name__}: {exc} "
                     f"(parser does not yet support this artifact layout)\n")
        continue
    covered = [v for v in rep.verdicts if v.truth is not None]
    passed = [v for v in covered if v.status == "PASS"]
    caught = [v for v in covered if v.status in ("WARN", "FLAG", "FAIL")]
    grand["covered"] += len(covered); grand["pass"] += len(passed)
    grand["caught"] += len(caught)
    print(f"  covered={len(covered)} pass={len(passed)} caught={len(caught)}", flush=True)
    lines.append(f"- cells: {len(led.cells)} total, {len(covered)} SEC-covered, "
                 f"{len(passed)} PASS, **{len(caught)} caught**")
    for v in caught:
        lines.append(f"  - CATCH `{v.canonical_label}`: pred={v.pred} "
                     f"truth={v.truth} rel_err={v.rel_err:.4f} [{v.band}/{v.status}]")
    lines.append("")

rate = grand["caught"] / grand["covered"] if grand["covered"] else 0.0
lines += ["## Summary",
          f"- SEC-covered cells: {grand['covered']}",
          f"- PASS: {grand['pass']}  |  caught (WARN/FLAG/FAIL): {grand['caught']}",
          f"- **catch-rate: {rate:.1%}**",
          f"- total Anthropic cost: ${grand['cost']:.4f}",
          "",
          "Interpretation: high catch-rate -> hallucination/data errors are real "
          "here, verifier earns its keep. Near-zero -> FMP fundamentals match SEC "
          "for clean large-caps; expand to messy tickers to stress it."]
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"\nWROTE {OUT}  catch-rate={rate:.1%} cost=${grand['cost']:.4f}", flush=True)

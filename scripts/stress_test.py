"""Stress test: run skills on MESSY tickers, extract via LLM, verify vs SEC.

NKE = off-calendar fiscal year (ends May) -> stresses period selection.
JPM = bank -> different GAAP concepts -> stresses concept mapping (coverage).

Skills run UNTOUCHED via Max auth; artifacts extracted by Haiku (Option C);
graded deterministically vs SEC (auto-CIK). No metered $.
"""

import time
from pathlib import Path
from dotenv import load_dotenv

from finskill_eval.config import load_settings
from finskill_eval.extract.llm_extract import extract_ledger
from finskill_eval.groundtruth.sec_xbrl import SECXBRLClient
from finskill_eval.runner.invoke_skill import run_skill
from finskill_eval.verify import verify

load_dotenv(Path(".env"), override=True)
S = load_settings()
UA = "finskill-eval Benjamin Nudelman bnudelman2@gmail.com"
gt = SECXBRLClient(user_agent=UA)   # auto-resolves CIK per ticker
ROOT = Path("results/_stress/workdirs")
CASES = [("tearsheet", "NKE", "FY2024"), ("tearsheet", "JPM", "FY2024")]
MAX_TRIES = 3


def fmt(x):
    try: return f"{float(x):>16.2f}"
    except: return f"{str(x):>16s}"


tc = tp = tk = 0
for skill, ticker, period in CASES:
    print(f"\n=== {skill} {ticker} {period} (fmp, Max) ===", flush=True)
    run = None
    for attempt in range(1, MAX_TRIES + 1):
        run = run_skill(
            skill, ticker, period, "fmp",
            workdir=ROOT / f"{skill}__{ticker}__{period}__try{attempt}",
            model=S.pins.model_snapshot, timeout=900,
            allowed_tools=S.invocation.allowed_tools, bare=S.invocation.bare,
            skill_src_dir=Path("skills/fmp") / skill, use_subscription=True,
        )
        print(f"  try{attempt}: latency={run.latency_s:.0f}s exit_ok={run.exit_ok} "
              f"artifact={bool(run.artifact_path)}", flush=True)
        if run.artifact_path:
            break
    if not run.artifact_path:
        print("  NO ARTIFACT — skipped", flush=True)
        continue

    led = extract_ledger(Path(run.artifact_path), skill=skill, ticker=ticker)
    rep = verify(led, gt)
    cov = [v for v in rep.verdicts if v.truth is not None]
    pa = [v for v in cov if v.status == "PASS"]
    ck = [v for v in cov if v.status in ("WARN", "FLAG", "FAIL")]
    tc += len(cov); tp += len(pa); tk += len(ck)
    print(f"  {len(led.cells)} cells, {len(cov)} SEC-covered, {len(pa)} PASS, {len(ck)} caught", flush=True)
    for v in cov:
        note = f"  [{v.note}]" if v.note else ""
        rel = v.rel_err if v.rel_err is not None else -1
        print(f"    {v.canonical_label:22s} pred={fmt(v.pred)} truth={fmt(v.truth)} "
              f"rel={rel:.4f} [{v.band}/{v.status}]{note}", flush=True)

print(f"\n=== STRESS: covered={tc} PASS={tp} caught={tk} "
      f"catch-rate={tk/tc if tc else 0:.1%} ===", flush=True)

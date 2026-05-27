"""3-run live cost pilot. Measures real Anthropic cost/latency/turns per skill
run on the converted FMP skills. FMP (flat plan) and SEC (free) add no $.

Run: PYTHONPATH=src python scripts/cost_pilot.py
"""

import time
from pathlib import Path

from dotenv import load_dotenv

from finskill_eval.config import load_settings
from finskill_eval.runner.invoke_skill import run_skill

load_dotenv(Path(".env"), override=True)  # metered ANTHROPIC_API_KEY + FMP_API_KEY

S = load_settings()
TICKER, PERIOD = "AAPL", "FY2024"
SKILL_DIRS = ["tearsheet", "comps", "capital-allocation"]
FMP_SKILLS = Path("skills/fmp")
ROOT = Path("results/_pilot/workdirs")

total = 0.0
rows = []
for skill in SKILL_DIRS:
    print(f"\n=== running {skill} {TICKER} {PERIOD} (fmp) ===", flush=True)
    t0 = time.monotonic()
    run = run_skill(
        skill, TICKER, PERIOD, "fmp",
        workdir=ROOT / f"{skill}__{TICKER}__{PERIOD}",
        model=S.pins.model_snapshot,
        timeout=S.invocation.timeout_s,
        allowed_tools=S.invocation.allowed_tools,
        bare=S.invocation.bare,
        skill_src_dir=FMP_SKILLS / skill,
    )
    total += run.cost_usd
    rows.append(run)
    print(f"  cost=${run.cost_usd:.4f} latency={run.latency_s:.0f}s "
          f"turns={run.num_turns} exit_ok={run.exit_ok} "
          f"activation={run.activation_observed} artifact={bool(run.artifact_path)}",
          flush=True)

print("\n========== PILOT SUMMARY ==========")
for r in rows:
    print(f"  {r.skill:20s} ${r.cost_usd:7.4f}  {r.latency_s:5.0f}s  {r.num_turns:2d}t  "
          f"exit_ok={r.exit_ok}")
print(f"  {'TOTAL':20s} ${total:7.4f}")
n96 = total / len(rows) * 96 if rows else 0
print(f"\n  mean ${total/len(rows):.4f}/run -> 96-run FMP grid ~${n96:.2f} "
      f"(192 both-arms ~${n96*2:.2f})")

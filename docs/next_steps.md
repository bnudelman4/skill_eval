# What I'd Build Next

Ordered by leverage. Each item names the rough cost (live $ vs. offline only)
and the artifact it would produce.

---

## Tier 1 — closes the headline experiment

### 1. Daloopa MCP credentials → full paired A/B

- **Why:** the project was named for the paired Daloopa-skill vs FMP-skill
  comparison. Variant B (FMP) runs end-to-end; variant A is wiring only.
- **Cost:** credentials + one full-grid live run (≈ 192 invocations at ~$0.60
  mean ≈ **$60–120 metered**).
- **Output:** `conversion/compare.py` paired-delta scorecard with confidence
  intervals; per-cell `A vs B` table; the headline "is FMP variant
  production-acceptable" verdict at the ≥85% pass bar.

### 2. Authoritative activation-event detection

- **Why:** current activation rate is at 22% because the stream-json signal
  only fires when the agent explicitly Reads the staged `SKILL.md`. Claude
  Code can inject a skill as system context with no Read event. Closing this
  unlocks accurate activation/selection metrics, which the M7 optimizer
  optimizes against.
- **Cost:** one live inspection of `--output-format stream-json` to identify
  the authoritative skill-load event type, then a 20-line parser update.
  **Sub-$1 metered.**
- **Output:** activation rate near ground truth; reward signal becomes
  reliable.

### 3. Quarterly SEC 10-Q gold

- **Why:** `capital-allocation` emits 8 quarters of data; SEC anchor today is
  annual-only, so most of those cells SKIP. Adding 10-Q coverage materially
  increases gold-graded cell count and gives the _bank_ tickers gradeable
  quarterly fundamentals.
- **Cost:** offline implementation + small live verification call (sub-$1).
- **Open work:** XBRL stores YTD vs Q values inconsistently across filers
  (some companies report Q3 standalone, others as YTD9M); the client needs
  to disambiguate end-date + duration heuristically.

---

## Tier 2 — strengthens the evidence base

### 4. Expand the ticker universe to the spec's recommended 30

- **Why:** today's pilot is 3 tickers (clean / bank / off-cal). The spec's
  suggested 30 includes a recent restater, a de-SPAC, a foreign filer (ADR),
  a conglomerate (BRK.B). These stress different parts of the pipeline.
- **Cost:** ~360 invocations grand total (30 × 4 × 3 × 1 source @ FMP only)
  ≈ **$200–300 metered**, or free under Max with patience.
- **Output:** statistically meaningful per-skill effect sizes with
  confidence intervals (M5 already supports per-skill breakdown; just needs
  N).

### 5. End-to-end M7 optimization run with measured before/after

- **Why:** the loop, candidate generator, validation gate, and feedback
  ingestion are TDD'd offline. A real description-rewrite-and-re-evaluate
  cycle on `tearsheet` (the most reliable skill) would give a measured
  activation lift.
- **Cost:** baseline grid + 5 candidate iterations × 3 runs/query × M
  positive queries ≈ **~$30–60 metered** depending on M.
- **Output:** `results/_m7/iteration_report.md` with baseline vs best
  candidate vs accepted description diff. Demonstrates the optimizer
  isn't just plumbing.

---

## Tier 3 — hardening for production

### 6. Activation completeness verification + selection accuracy on neg-queries

- **Why:** today's query set is implicit ("if the prompt names the skill, it
  should trigger"). A proper M7 needs a curated set with explicit positive
  AND negative queries (description shouldn't trigger on the wrong prompts
  either). Then selection accuracy means something.
- **Cost:** offline authoring; one live grid to baseline.

### 7. Feedback-capture UI hook

- **Why:** `optimize/feedback.py` ingests FLAG-override judgments but
  there's no surface for an analyst to enter them. A minimal CLI or a
  spreadsheet round-trip would close the human-in-loop loop.
- **Cost:** offline only.

### 8. CI scorecard pinning

- **Why:** the scorecard JSON is the natural artifact for a "skill ship
  gate" in CI. A GitHub Action that runs the dry-run scorecard on PRs
  against the skill repo would catch regressions before merge.
- **Cost:** offline configuration; depends on where the skill repo lives.

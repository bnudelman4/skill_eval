# What I'd Build Next

Ordered by leverage. Each item names the rough cost (live $ vs. offline only)
and the artifact it would produce.

A second worker at the company reframed the eval question after the first
draft. Their take is that process drift, when the agent goes off the path
the skill specified, is a more interesting failure mode than arithmetic
drift. The first new item below is built around that framing. The rest are
the original Tier 1 through Tier 3 priorities.

Recently completed work that is no longer in the next-steps queue:

- FMP-self-check layer with the LLM extractor seeing SKILL.md and the
  full FMP field catalog inline. Live results 100% pass-rate on AAPL,
  JPM, and NKE with zero skill arithmetic errors. Coverage went from
  about 40% to over 90% on the cells the data source actually carries.
- LABEL_MAP expanded from 11 entries to 132 by probing FMP's stable API
  endpoints (about 466 fields). Used as the fallback when the extractor
  has not been asked for inline mappings.
- LLM-backed label resolver with disk-cached responses. Used as a
  secondary fallback when LABEL_MAP misses.
- Quarterly period support on FMPClient with the right limit parameter
  so historical FY2024 quarters do not get dropped by FMP's default
  five-row cap.
- Scale and sign aware compare on the FMP-self-check leg, which clears
  the cosmetic display-convention failures (margins as fractions vs
  percents, cash items as outflow-negative vs absolute-positive).
- NKE matrix-layout parser bug fix (the "FY5720" garbage period keys),
  which unblocked NKE's segment artifact.

---

## Tier 0 — the second worker's framing: behavioral conformance

### 0. Process-drift evaluation layer

- **Why:** the numerical layer this project ships is necessary but not
  sufficient. An arithmetically correct deliverable can still be
  analytically wrong if the agent made bad procedural choices. Examples:
  picks 30 peers when the skill says 5 to 10; spends turns on D&A after
  the skill flagged it as not relevant; searches obscure news in the
  middle of a JPM run; ships a partial deliverable; hallucinates a
  metric definition the skill never mentioned. None of those are caught
  by FMP-self-check or by the SEC anchor.
- **What it looks like in practice:** four LLM-as-judge layers with
  SKILL.md as the source of truth.
  1. Tool-call trace conformance. Parse the stream-json events into a
     tool sequence and compare against the SKILL.md's prescribed flow.
     Report percent of expected steps done and percent of unexpected
     steps.
  2. Decision-quality scoring. For analytical choices like peer set,
     KPI selection, or segment emphasis, an analyst-LLM scores them 0
     to 5 with rationale.
  3. Off-path detection. A judge LLM reads the run log and flags
     deviations from SKILL.md ("at turn 12 the agent began researching
     crypto news despite no instruction to do so").
  4. Workflow-completion check. Parse the deliverable structure and
     confirm every section the skill prescribed is present.
- **Cost:** offline authoring for the judge prompts, plus one live
  judge LLM call per sample at the end of each run. Cheap under
  Max-sub auth.
- **Output:** a `results/_behavioral/scorecard.md` with the four
  layers' verdicts per sample, plus an aggregate. Sits on top of the
  existing numerical scorecard rather than replacing it.

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

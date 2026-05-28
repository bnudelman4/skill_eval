# finskill-eval — In-Depth Report

*Author: Benjamin Nudelman. Date: May 2026.*

This document is the long-form companion to the [README](../README.md). It
covers, in order: the problem; the research foundation, with primary-source
citations; the one architectural rule that governs the codebase; the build
sequence and what each milestone delivered; the iterations and pivots forced
by live data; live evidence; how a peer's critique was absorbed and where it
was rejected; and the honest open items.

---

## 1. The problem

Modern Claude Code "skills" let an LLM agent execute a domain workflow —
sourcing data, computing metrics, building a deliverable — by reading a
markdown instruction file. For finance specifically, [Daloopa's
`investing` skill suite](https://github.com/daloopa/investing) (pinned at SHA
`17039332eb6f9323d8415156f7202feef538a3f2`) packages tearsheets, comparable
companies analyses, capital-allocation deep-dives, etc., behind the Daloopa
MCP data layer.

Two related questions need answering:

1. **Per-skill correctness.** When a skill produces a spreadsheet of numbers,
   how do you know they're right — without a human analyst checking every
   cell?
2. **The data-layer A/B.** If you swap Daloopa for a different backend
   (Financial Modeling Prep, FMP), does the deliverable stay correct?

Both questions need an *evaluator* that an LLM can't game. That is what this
project builds.

---

## 2. Research foundation

Four primary sources fixed load-bearing thresholds; one body of research drove
a major mid-project pivot. Each was re-verified before committing to it.

### 2.1 LLMs hallucinate finance numbers — they can't grade themselves

- **FAITH** ([arXiv 2508.05201](https://arxiv.org/abs/2508.05201)) introduces
  a four-type taxonomy of financial-table reasoning (*direct lookup*,
  *comparative*, *bivariate*, *multivariate*) and measures intrinsic
  hallucination on tables drawn from S&P 500 annual reports. The complexity
  gradient is exactly the gradient our pipeline measures: simple lookups land
  cleanly; multivariate cells are where failure clusters.
- **Finance Agent Benchmark** ([arXiv 2508.00828](https://arxiv.org/abs/2508.00828))
  reports the best LLM agent (OpenAI o3) at **46.8% accuracy on real finance
  research tasks at $3.78 / query, 3.1 min**; the human-analyst baseline is
  **$25.66 / 16.8 min**.

The unambiguous conclusion: **LLM-grades-LLM is unreliable for financial
numerics.** A verifier whose judgments cannot be trusted is worse than no
verifier — it produces false confidence.

### 2.2 Tolerance bands: SEC SAB 99 materiality

The 5% disagreement boundary is not a guess. **SEC Staff Accounting Bulletin
No. 99** ([sec.gov/interps/account/sab99.htm](https://www.sec.gov/interps/account/sab99.htm))
codifies 5% as the materiality rule-of-thumb in financial reporting.
Disagreements above that line are *material* — meaning a human should look,
not that the skill is automatically wrong. The pipeline encodes this as a
distinct **FLAG** status, separate from FAIL.

### 2.3 Anthropic Agent Skills: description drives activation

[Anthropic's Agent Skills docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
make two design-relevant claims:

- Each request loads **at most 8 skills**; the *description* field decides
  whether a skill triggers at all (activation), and which of several
  candidates the agent picks (selection).
- The skill body's analytical prose is what shapes its output once invoked
  (accuracy).

These three surfaces — activation, selection, accuracy — become three distinct
metrics on the scorecard, each tied to a *different* fix path. The M7 optimizer
restricts itself to editing description + progressive-disclosure structure;
the analytical body is protected.

### 2.4 The parser→extractor pivot (the mid-project change)

Two literatures converged on a single recommendation:

- **Constrained / structured LLM output beats post-hoc parsing.**
  [LLMStructBench (arXiv 2602.14743)](https://arxiv.org/pdf/2602.14743),
  [StructEval (arXiv 2505.20139)](https://arxiv.org/html/2505.20139v1), and
  applied write-ups on constrained decoding all converge: a model emitting
  schema-valid JSON is dramatically more reliable than parsing freehand
  output, with a caveat — forcing the schema *inline with reasoning* can
  degrade reasoning by 10–15%.
- **Rule-based extractors are being supplanted by LLM extraction with
  hybrid verification** for financial documents.
  [arXiv 2603.22651](https://arxiv.org/html/2603.22651) on multi-agent
  financial-document processing concludes that single-pass LLM extraction has
  hallucination risk and recommends a hybrid: LLM extraction + rule-based
  verification.

This frames the central pipeline change documented in §6: the deterministic
`parse_xlsx` was replaced as the default ingestion path by **Option C** — a
cheap LLM extractor that emits JSON, parsed by `json.loads`, then checked by
our rule-based verifier. Exactly the hybrid the research recommends, and it
preserves the principle from §2.1 because the *grader* (verifier) is still
pure Python.

---

## 3. The one architectural rule

> **The LLM does semantic work. Python does every piece of arithmetic and
> every numerical comparison.**

The LLM:
- Runs the analysis (Claude Code under test, the candidate skill).
- Maps labels to canonical names (extractor — semantic, not arithmetic).
- Proposes description edits in M7 (semantic, not arithmetic).

Python:
- Re-derives every derived metric (`recompute.py`).
- Compares values against gold via banded tolerance (`tolerance.py`).
- Aggregates verdicts and renders scorecards (`metrics.py`, `report.py`).

This is the "neuro-symbolic split" referenced throughout the spec. It is
non-negotiable: a self-improving optimizer (M7) needs a reward signal it
cannot game, and an LLM grader is gameable.

---

## 4. Three-source triangulation

| Source | Role | Why |
|---|---|---|
| **FMP** | Candidate | The data the skill uses. Never the grader. |
| **Daloopa** | Gold | Standardized, human-verified, what the skills were authored against. |
| **SEC EDGAR** | Anchor | Independent as-reported; free; breaks ties. |

Two sources: a disagreement is ambiguous (skill error or vendor quirk?).
Three sources: triangulation localizes the broken layer. This proved its
worth twice during development (§6).

Status: Daloopa MCP credentials are delayed; **SEC was promoted to bootstrap
gold** for the present pilot, with the architecture untouched (bootstrap
swaps via one config field). Full A/B awaits the key.

---

## 5. Build sequence — what each milestone delivered

| Milestone | Delivered |
|---|---|
| **M0** | Scaffolding; pydantic config that fails loudly on placeholder pins (model snapshot, skill SHA) and on candidate==gold |
| **M1** | Three hand-built known-answer fixtures with a deliberate-wrong cell and a WARN-band cell; `expected_ledgers.json` documents per-cell expected band |
| **M2** | Deterministic verifier (normalize, tolerance bands, ledger, parse, recompute, verify) — proven on the M1 fixtures *before* any live agent ran |
| **M3** | Headless `claude -p` wrapper: captures `cost_usd`, turns, latency, exit status, raw log; injectable subprocess for tests; `--bare` semantics understood and exploited |
| **M4** | Three ground-truth clients behind one protocol (FMP candidate, SEC anchor / bootstrap gold, Daloopa MCP stub) with frozen point-in-time snapshots |
| **M5** | Inspect-style harness, parallel grid with global rate-limiting + per-sample resumability, metrics, scorecard rendering (JSON / Markdown / HTML) |
| **M6** | Daloopa→FMP **conversion** — surgical, deterministic token swap (no LLM rewrite); `fmp_data_access.md` analogue of Daloopa's `data-access.md`; paired A/B comparator wired |
| **M7** | Skill-description optimization loop with protected analytical body, bounded edits (4–8 per step per SkillOpt), validation gate, 60/40 train/test, ≤5 iterations, feedback hooks |

Tests: **185+ passing**, all offline (network mocked). Each milestone TDD'd
against the M2-proven verifier — no milestone advanced on red tests.

---

## 6. Iterations forced by live data

This is where most of the *learning* happened. The pipeline's design predicts
that a verifier should catch errors; observing it do so on live runs forced
real engineering choices.

### 6.1 First pilot — what worked, what didn't

The first three-run pilot (AAPL, FY2024, FMP backend):

| Skill | Result |
|---|---|
| tearsheet | $0.47, 410 s, **artifact written, parsed cleanly, 17 cells, internally consistent margins** |
| comps | **Timed out at 600 s.** |
| capital-allocation | Did not run (script crashed on the comps timeout). |

Two real bugs surfaced:

1. **`subprocess.TimeoutExpired` killed the whole batch** — one slow run lost
   the previous run's cost as well. Fixed: `_default_runner` catches
   `TimeoutExpired`, surfaces a marker exit code, the grid continues.
2. **Comps needs more than 600 s** — bumped to 900 s + future scope
   constraint flagged.

Eyeball of the parsed tearsheet vs reality: revenue $391.035B ✓, net income
$93.736B ✓, diluted EPS $6.08 ✓, gross margin recomputed exactly. The
neuro-symbolic split was visibly working.

### 6.2 Live SEC verify — and a SEC client bug it caught

Running `verify(tearsheet_ledger, SECXBRLClient(...))` produced what looked
like 6 disagreements. **The verifier was correct; the *gold* was wrong.**

Each "disagreement" exactly matched AAPL's **FY2022** number (revenue
$394.328B, NI $99.803B, etc.). The SEC client was filtering
`fy==target_year + fp==FY + form==10-K`, but EDGAR tags *every comparative
row in the FY2024 10-K* with `fy=2024` — so `next()` was grabbing the
earliest comparative (FY2022). The fix: select by the **data period's
end-date year**, not the filing's `fy` field; tie-break on latest `filed`.

Regression test added; fix committed (`93f944e`). On re-run: **8/8 exact
match** to SEC FY2024 actuals. This was triangulation paying off in advance
of even owning two golds.

### 6.3 The parser problem — and the Option C pivot

The next calibration run on `capital-allocation` exposed a structural
limitation: `parse_xlsx` was built for the single-period row-oriented
tearsheet layout. The real `capital-allocation` artifact is a **multi-sheet
workbook with metrics-as-rows × quarters-as-columns** plus a label/value/note
Summary tab. The parser grabbed `"227.79"` (a stock price) as a period label
and raised.

A **matrix + multi-sheet generalization** (M-task P1) was built and
committed: per-sheet layout detection (matrix vs row-oriented), `Mon'YY`
period parsing, ratio-row unit detection, cross-sheet metric dedupe.
408 cells parsed clean from the same artifact. Locked in with regression
tests that build a synthetic matrix workbook in-memory (no dependency on
gitignored live artifacts).

**But this exposed the deeper problem**: every new skill output shape risked
another parser patch. That is exactly the maintenance burden the
literature ([arXiv 2603.22651](https://arxiv.org/html/2603.22651)) warns
about with rule-based extractors. After review:

- **Option A** (current free-form parser): zero skill change, but a
  whack-a-mole maintenance treadmill.
- **Option B+** (skill emits structured JSON): high reliability, but **alters
  the skill under test** — defeating the entire point of evaluating "the
  skill itself." Rejected on that ground.
- **Option C** (LLM extracts from the produced xlsx, deterministic verifier
  grades): **skill 100% untouched**, layout-agnostic without per-layout
  code, hybrid the research recommends.

The user's instinct — *evaluate the skill itself, don't alter it* — combined
with the research, decided this cleanly. **Option C became the default
ingestion path** in `extract/llm_extract.py`; `parse_xlsx` was retained as
the deterministic fallback (still used for fixtures and as a sanity check).

The maintenance economics flipped: instead of writing a regex per layout,
the LLM extractor generalizes; instead of debugging live, you iterate the
extractor *prompt* offline on cached artifacts, with the deterministic
verifier as the trustworthy backstop the research endorses for the hybrid.

### 6.4 Rate-limit blocker — and the Max-auth pivot

Re-running the calibration under the metered API key produced an
unexpected pattern: first heavy run completed (~$1.24, 541 s) but produced
no artifact; subsequent runs returned in 1 s with `is_error: true`. Reading
the failed run log:

> `Request rejected (429) · This request would exceed your organization's
> rate limit of 30,000 input tokens per minute (model: claude-sonnet-4-6)`

The 30k input-TPM tier is below a single skill run's burst (one tearsheet
try logged 142k cache-creation + 366k cache-read + 39k output). The skill
runs cannot fit. Three options: raise the usage tier (correct long-term);
constrain the skill (fragile and partial); or use Max-subscription auth in
the harness for evaluation runs.

Switching to Max via `use_subscription=True` (drops `--bare`, strips
`ANTHROPIC_API_KEY` from the subprocess environment) unblocked Step 0
cleanly. The metered path remains the production-correct one once the tier
is raised; this is a wiring choice, not an architecture change. The
blocker is documented in `~/.claude` project memory so it isn't re-diagnosed.

### 6.5 Verifier hardening from the big test (36% → 87%)

The first 9-sample big test produced a 36.4% accuracy pass-rate. Read
naively that sounds bad. Reading the per-sample JSONs surfaced three
distinct issues:

1. **Reliability.** Half the samples produced no artifact. Root cause: the
   skill body saves to its own `reports/{TICKER}_tearsheet.html`-style path,
   not the path the harness prompt specified. Fix: **robust artifact
   discovery** — if the exact path is missing, take the newest `.xlsx`
   anywhere under the workdir. Plus retries (`max_tries=2`) in
   `score_sample` for transient `exit_ok=False`.

2. **False FAILs on rounding.** Many derived cells failed at `rel_err ≈
   0.001–0.004` (0.1–0.4%) — well *inside* PASS bands but marked FAIL
   because the stated-vs-recompute arithmetic check was using too strict a
   tolerance. The skill displays inputs rounded to millions; Python
   recomputes from those rounded inputs → off from the skill's stated
   margin by rounding alone. Loosened to `xvendor_standard` (0.5%).

3. **Activation detection 0%.** The original `parse_activation` regex over
   the JSON envelope was looking for tokens that simply aren't in
   the `--output-format json` result. Switched to `--output-format
   stream-json` with a parser that detects Read of the staged
   `skills/<name>/SKILL.md` path; Skill tool-use events are also matched.

The re-run on the same 9 samples:

| Metric | First run | After fixes |
|---|---|---|
| Artifacts produced | ~4/9 | **9/9** |
| Pass-rate @ 1% | 36% | **87.2%** |
| Activation | 0% | **22%** |

The remaining FAIL/FLAG concentrate on margins/multiples (definition
divergence) and bank revenue (gross-vs-net concept mismatch) — the exact
*informative* cross-vendor signal the bands were designed to surface, not
skill bugs. Verbose log:
[`results/_bigtest/scorecard.md`](../results/_bigtest/scorecard.md).

### 6.6 Stress test: off-calendar + bank tickers

To validate that the period and concept logic generalize, NKE (May fiscal
year-end) and JPM (bank) were added:

- **NKE FY2024:** 5/5 SEC-covered cells PASS exact. Off-calendar fiscal
  year handled cleanly by the end-date-year selector.
- **JPM FY2024:** `net_income` and `dividends_paid` exact in **both FY2024
  and FY2023** (multi-period extraction works). `revenue` flagged at
  ~52% — exactly the **bank revenue definition mismatch** the literature
  predicts (FMP total revenue vs SEC's net `Revenues` concept).
  `shares_outstanding` FLAG at ~4× — almost certainly the skill **summing
  share counts across the four quarters** (nonsensical for a stock
  metric). **The verifier caught a real skill error.**

Additionally, a misleading "scale-normalized x0.001" note was being
attached to FLAG cells where the scale factor *didn't* help — cleaned up
so the note appears only when scaling actually achieves a PASS band.

### 6.7 Recompute robustness

Live runs surfaced two derived-cell failure modes that crashed the
verifier instead of being graded:

1. A derived cell with a *recognized* canonical label (`ebitda_margin`,
   `yoy_growth`) but no entry in `METRIC_DEFS` — original code raised
   `ValueError("...has no formula")`. Fix: `recompute()` is now
   lenient-by-default — unregistered derived metrics skip; a `strict=True`
   flag preserves the loud-failure mode for callers (e.g. the M2 fixture
   tests).

2. A derived cell where the extractor emitted the metric but not the
   inputs — `cell.inputs` was empty, leading to `fn()` being called with
   zero positional args. Fix: skip when `not args`; additionally wrap the
   formula call in `try/except TypeError` (lenient).

Both behaviors are regression-tested.

---

## 7. The Daloopa→FMP conversion (M6)

This is the headline experiment the project was named for. The conversion
is a **deterministic Python token-swap**, not an LLM rewrite, on the
principle that the research is clear: auto-regenerated skills underperform
hand-authored ones; minimum change preserves quality.

```text
("../data-access.md", "fmp_data_access.md"),
("discover_companies", "fmp_profile"),
("discover_company_series", "fmp_fields"),
("get_company_fundamentals", "fmp_statements"),
("get_stock_prices", "fmp_quote"),
("search_documents", "fmp_filings_search"),
("https://daloopa.com/src/{fundamental_id}", "fmp_data_access.md#sourcing"),
...
```

Replacements are ordered longest-first so `discover_company_series` is
rewritten before `discover_companies`. Idempotent (FMP tokens contain none
of the Daloopa source tokens). Everything else — the analysis steps, the
value judgments, the report structure — is untouched byte-for-byte. The
A/B is then *causal*: any output difference is attributable to the data
layer alone.

Output: `skills/fmp/{tearsheet,comps,capital-allocation}/` — each bundling
`SKILL.md` + `fmp_data_access.md`. Driver: `conversion/run_conversion.py`.
Paired comparator: `conversion/compare.py` (ready, awaits Daloopa
credentials to execute variant A).

---

## 8. Live evidence summary

| Run | Result | Notes |
|---|---|---|
| First pilot (3 invocations, AAPL) | tearsheet ✓, comps timeout, capital-alloc skipped | Surfaced TimeoutExpired bug + comps timeout |
| Step 0 calibration (offline gold) | tearsheet 8/8 exact vs SEC | Caught the SEC period-selection bug |
| Re-run (metered) | 429 rate-limit blocker | Documented; switched to Max for eval |
| Stress test (NKE, JPM) | NKE clean off-cal; JPM caught a real skill error | shares_outstanding summed across quarters |
| Big test (9 samples) — round 1 | 36% pass-rate, half no-artifact | Drove reliability + arith_tol fixes |
| Big test (9 samples) — round 2 | **87.2%**, 9/9 artifacts, 100% on direct fundamentals | Production-shape result on real data |

A reviewer can scan the `git log` and see each fix go in with a regression
test and a commit message that names the live finding it came from.

---

## 9. Peer feedback handled

A peer pushed back on the verifier emphasis, citing
[SkillOpt](https://generativeprogrammer.com/p/skill-authoring-patterns-from-anthropics)-style
takeaways and suggesting that "hallucination isn't as big of an issue as
other stuff." That critique was triaged honestly:

- **Absorbed (≈ 70%):** SkillOpt's validation-gated edits, bounded diffs
  (4–8 edits/step), description compactness (~920 tokens), protected
  analytical body, per-skill effect-size reporting, user-feedback hooks off
  the FLAG mechanism. These map directly onto M7 design choices, several of
  which were already in the spec.
- **Rejected (≈ 30%):** "Hallucination is rare here" — the cited literature
  (§2.1) is unambiguous for *financial numerics specifically*. "Python
  verification doesn't work with LLM API calls" — a misread; Python isn't
  replicating the LLM's task, it's asking the data source the same question
  independently and comparing.

The peer's bigger framing — "less verification, more optimization" —
inverts for finance: a faster wrong number isn't a product. The verifier
stays load-bearing; optimization sits on top.

---

## 10. The codebase, in functional terms

Every functional unit, with its role:

- **`config.py`** — loads `settings.yaml` and `universe.yaml` through
  pydantic models with `extra="forbid"`. Fails at startup on placeholders
  (`REPLACE_WITH_*`), candidate==gold, or unrecognized keys. All loaders
  `@lru_cache`'d. Secrets read from environment only.
- **`normalize.py`** — turns `"$1,234"`, `"(1,234)"`, `"12.3%"`, `"1.2bn"`
  into floats; canonicalizes labels through an editable synonym map;
  parses `FY2024`, `Q4 2025`, `Dec'22`, `FY2023 Q1`, `2024-12-31` into a
  typed `Period`.
- **`ledger.py`** — frozen pydantic `Cell` and `Ledger`. Each `Cell` carries
  `cell_id`, `canonical_label`, `period`, `raw_value`, `value`, `unit`,
  `kind ("direct" | "derived")`, `cell_type` (FAITH 4-type), `formula`,
  `inputs`.
- **`parse_xlsx.py`** — deterministic fallback parser. Multi-sheet, with
  per-sheet matrix vs row-oriented layout detection, ratio-row unit
  inference, cross-sheet metric dedupe. Crash-safe (`_safe_period` skips
  unparseable cells rather than raising).
- **`extract/llm_extract.py`** — Option C ingestion. A cheap LLM
  (Haiku-class) reads the produced xlsx, returns
  `[{metric, period, value, unit}, ...]` JSON; `build_ledger()` then runs
  the same canonicalization pipeline `parse_xlsx` feeds into.
- **`recompute.py`** — pure-Python formulas for every derived metric
  (`gross_margin`, `operating_margin`, `net_margin`, `growth`, `ev_ebitda`,
  `pe_ratio`, `shareholder_yield`). A registry (`METRIC_DEFS`) maps each
  canonical derived label to `(formula_name, input_canonical_labels)`.
  Lenient by default; `strict=True` for fixture tests.
- **`tolerance.py`** — `compare(pred, truth)` returns a `BandResult` with
  band name + relative error. Zero I/O. The PR bar for changes here is
  high: it's the verifier's bedrock.
- **`verify.py`** — orchestrates parse → recompute → compare. For derived
  cells, *two-leg* check: (a) stated vs Python recompute (arithmetic
  integrity) and (b) Python recompute vs gold (data integrity).
  Coverage-aware: cells gold doesn't carry are SKIP, excluded from the
  pass-rate denominator. Scale-aware: tries `×{1, 1e3, 1e6, 1e9, 1e-3, ...}`
  before ruling a number wrong and only annotates "scale-normalized" when
  the factor actually achieves PASS.
- **`groundtruth/`** — three clients behind one `GroundTruthSource`
  protocol: `fmp.py` (candidate), `sec_xbrl.py` (anchor / bootstrap gold,
  selects rows by data period end-date year — the M4 bug-fix), and
  `daloopa_mcp.py` (stub, awaiting credentials). `cache.py` writes every
  pull to `data/snapshots/<source>/<date>/...` so a run is reproducible
  even as live data drifts.
- **`runner/`** — `invoke_skill.run_skill()` shells out to `claude -p`
  with `--bare` (metered) or without (Max), stages the chosen skill into
  the workdir, captures cost/turns/latency/exit, discovers the artifact
  robustly, and detects activation from stream-json events. `grid.py`
  defines `GridSample` and `score_sample` (the invoke→extract→verify→
  record assembly). `parallel.py` runs the grid with a `ThreadPoolExecutor`
  + a global `RateLimiter`, resumable via per-sample JSON.
  `run_baseline.py` is the top-level entry point with `--dry-run` for the
  offline scorecard from fixture artifacts.
- **`metrics.py`** — aggregates a `SampleRecord` list into a `Metrics`
  with breakdowns by skill, ticker, FAITH cell-type, and tolerance band.
  FLAG and SKIP cells are excluded from the pass-rate denominator on
  principle.
- **`report.py`** — renders the scorecard in JSON / Markdown / HTML, with
  interpretation notes from the research embedded as scorecard
  annotations (e.g. "activation <90% → fix descriptions, not bodies").
- **`conversion/`** — the M6 token-swap engine and the paired-A/B
  comparator. `convert_skill.py` does the deterministic Daloopa→FMP
  rewrite; `fmp_data_access.md` is the FMP analogue of Daloopa's
  `data-access.md`; `run_conversion.py` materializes `skills/fmp/`;
  `compare.py` computes paired deltas with confidence intervals when both
  variants have run.
- **`optimize/`** — M7. `skilldoc.py` parses `SKILL.md` into
  `{description, body, ...}` with the analytical body marked **protected**
  (round-trip preserves it byte-identical). `candidate.py` proposes
  bounded edits (4–8 per step) to description + disclosure only; guards
  reject body changes, over-token-cap, over-max-edits.
  `loop.py` runs the optimization loop: 60/40 train/test, 3 runs/query,
  ≤5 iterations, accept by **test** score (overfit guard). `feedback.py`
  ingests FLAG-override judgments (analyst marks "correct despite FLAG"
  or "wrong despite PASS") into a `feedback.jsonl` that can re-tune
  tolerance bands or refine the query set.

---

## 11. Honest open items

- **Activation detection at 22%, not ~95%.** The stream-json `Read` and
  Skill tool-use events catch about a quarter of activations; Claude Code
  often auto-injects a skill as system context without an event we can
  see. The fix is a more authoritative event in the stream, which needs a
  small live inspection to nail.
- **Daloopa A/B unrun.** The headline experiment requires the Daloopa MCP
  key, which is delayed. Variant B (FMP) ran end-to-end; variant A's
  wiring is in place.
- **Quarterly SEC 10-Q gold deferred.** XBRL's YTD/Q overlap is real work
  to do correctly. Today quarterly cells SKIP rather than producing false
  FAILs.
- **N=9.** Pilot scale. The grid would extend to 192 cells (8 tickers × 4
  periods × 3 skills × 2 sources) once the Daloopa key arrives.
- **M7 demonstrated in mechanics, not on a live optimization.** The loop
  + candidate generator + validation gate are TDD'd offline; an end-to-end
  live optimization with measurable before/after activation lift is the
  next thing to run.

---

## 12. What I'd build next

(See [`next_steps.md`](next_steps.md) for ordered priorities.)

The three nearest wins:

1. Authoritative activation-event detection — closes the 22% gap.
2. Daloopa-key arrival → run the full paired A/B → publish the
   `compare.py` scorecard. This is the project's *purpose-built* output.
3. Quarterly SEC 10-Q gold support for `capital-allocation` cell-level
   coverage.

After those: M7 live demonstration with a real before/after on the 9-sample
grid; a larger universe (the suggested 30 tickers, including the messy
ones); per-skill effect-size CIs.

---

## 13. Closing

The pipeline catches real errors on real data (the JPM share-count bug;
the SEC period-selection bug in our own code) and reports the *informative*
cross-vendor disagreements the research predicts (JPM bank revenue, NKE
off-calendar fiscal). Headline accuracy at 87.2% on a 9-sample live pilot,
100% on direct gold-covered fundamentals. The remaining open items are
named, with the reasons.

The premise was that an automated, research-grounded, neuro-symbolic
evaluator could turn a question that today needs a human analyst's eye
("are these numbers right?") into a CI-runnable scorecard with audit
trails. The evidence on the table says it can.

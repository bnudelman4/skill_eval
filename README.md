# finskill-eval

**An automated evaluation pipeline for Claude Code finance skills.** It runs a
skill headlessly, grades every number it produced against an independent
financial data source, and reports activation, accuracy, latency, and cost on a
research-grounded scorecard.

The headline experiment ("M6 A/B") converts each Daloopa-authored skill to use
the [Financial Modeling Prep (FMP)](https://site.financialmodelingprep.com/) API
as its data backend with a surgical, deterministic token swap (no LLM
regeneration), then measures whether the converted skill reproduces the
deliverable cell-for-cell.

---

## The one architectural rule

**The LLM does semantic work. Python does every piece of arithmetic and every
numerical comparison.** The LLM (the candidate skill, Claude Code under test)
runs the analysis and produces a spreadsheet. A deterministic Python verifier
re-fetches the same fields directly from the data source and grades each cell
against banded tolerances. The LLM never grades a number.

Why: the research is unambiguous that LLMs hallucinate financial numerics. An
LLM grading an LLM inherits the same failure mode. See
[FAITH (arXiv 2508.05201)](https://arxiv.org/abs/2508.05201) and
[Finance Agent Benchmark (arXiv 2508.00828)](https://arxiv.org/abs/2508.00828)

- best-model accuracy on real finance research tasks <50%.

---

## Headline result (live, 9-sample pilot on the converted FMP skills)

| Metric                        | Value         | Notes                                                                                                                        |
| ----------------------------- | ------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **Accuracy pass-rate @ 1%**   | **87.2%**     | `tearsheet`, `comps`, `capital-allocation` × AAPL, JPM, NKE (clean + bank + off-calendar FYE)                                |
| Direct fundamentals pass-rate | **100%**      | Every gold-covered direct lookup matched to the dollar                                                                       |
| Real catches                  | 2             | JPM `shares_outstanding` summed across 4 quarters (~4× wrong); a SEC client period-selection bug it surfaced in our own code |
| Reliability                   | 9/9 artifacts | After robust-discovery + retries                                                                                             |
| Activation detection          | 22%           | Partial — stream-json signal fires only when the agent explicitly Reads the staged SKILL.md                                  |
| Cost / run                    | ~$0.60 mean   | Notional under Max; metered ≈ $0.30–1.50 depending on skill                                                                  |

The dominant remaining FLAGs are exactly the _informative_ cross-vendor
disagreements the design predicts: bank revenue definition (gross vs net) and
multiples requiring market data SEC doesn't carry.

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# fill in FMP_API_KEY, ANTHROPIC_API_KEY, DALOOPA_MCP_URL/token

python -m finskill_eval.config                          # validate config
pytest                                                  # 185+ tests, all offline (network mocked)

python -m finskill_eval.runner.run_baseline --dry-run   # offline scorecard from fixture artifacts
python -m finskill_eval.runner.run_baseline             # live grid (needs auth + the skills under skills/fmp/)
```

---

## Pipeline

```
GridSample(skill × ticker × period × data_source)
  │
  ├─► invoke_skill.run_skill()             # headless `claude -p`
  │     stages skills/fmp/<skill>/ into workdir/.claude/skills/
  │     captures cost_usd / num_turns / latency / activation
  │
  ├─► robust artifact discovery            # newest .xlsx anywhere under workdir
  │
  ├─► extract/llm_extract.py (Option C)    # cheap LLM reads the produced xlsx,
  │     returns {metric, period, value, unit} JSON - generalizes to any layout
  │
  ├─► build_ledger()                       # canonicalize labels, periods, units;
  │     wire derived cells to their input cells via METRIC_DEFS
  │
  ├─► recompute.py                         # pure Python re-derives every margin
  │     / ratio / growth from the ledger's own inputs (lenient, unregistered
  │     derived metrics skip, never crash)
  │
  ├─► verify.py                            # for each cell: lookup gold (SEC /
  │     Daloopa), compare via banded tolerance; for derived cells, two-leg check
  │     (stated-vs-recompute AND recompute-vs-gold)
  │
  ├─► metrics.py                           # aggregate: activation rate, selection
  │     accuracy, per-cell pass-rate per band, FLAG/WARN, cost, latency;
  │     breakdowns by skill / ticker / FAITH cell-type / band
  │
  └─► report.py                            # JSON + Markdown + HTML scorecard,
        with interpretation notes from the research baked in
```

---

## Tolerance bands (the heart of the design)

Banded comparison, not pass/fail. Relative error `|pred − truth| / |truth|`:

| Band               | Threshold | Status   | Source                                                      |
| ------------------ | --------- | -------- | ----------------------------------------------------------- |
| `exact`            | ==        | PASS     | tickers, dates, CIK                                         |
| `tight`            | ≤0.1%     | PASS     | same-vendor sanity                                          |
| `xvendor_standard` | ≤0.5%     | PASS     | std vs std                                                  |
| `xvendor_liberal`  | ≤1.0%     | PASS     | as-reported vs lightly standardized                         |
| `materiality`      | ≤5.0%     | **WARN** | [SEC SAB 99](https://www.sec.gov/interps/account/sab99.htm) |
| `disagreement`     | >5.0%     | **FLAG** | likely restatement / definition mismatch — manual review    |

Primary accuracy target: **pass-rate at `xvendor_liberal` (≤1%)**. The premise:
cross-vendor disagreements are _expected and informative_, not automatically
bugs. The pipeline reports where on this spectrum each cell lands instead of a
misleading binary.

---

## Triangulation — three data sources, three roles

| Source        | Role      | Why                                                                            |
| ------------- | --------- | ------------------------------------------------------------------------------ |
| **FMP**       | Candidate | The data the skill under test uses. Never grades itself.                       |
| **Daloopa**   | Gold      | The reference the skills were authored against. Standardized + human-verified. |
| **SEC EDGAR** | Anchor    | Independent as-reported; free; breaks ties when FMP and Daloopa disagree.      |

Two sources can't tell skill error from vendor quirk; triangulation localizes
which layer broke. _Status:_ Daloopa key delayed → bootstrap gold = SEC; the
full A/B awaits credentials. The `conversion/compare.py` driver is ready.

---

## Repository layout

```
finskill-eval/
  config/
    settings.yaml            # tolerance bands, targets, pinned model + skill SHA
    universe.yaml            # tickers × periods
  src/finskill_eval/
    config.py                # pydantic-validated; fails loud on placeholders
    ledger.py / normalize.py # typed cell container; label/number/period normalization
    parse_xlsx.py            # deterministic fallback parser (multi-sheet + matrix)
    extract/llm_extract.py   # layout-agnostic LLM ingestion
    recompute.py             # pure-Python derived-metric formulas + registry
    tolerance.py             # banded comparator (no I/O)
    verify.py                # parse → recompute → compare → CellVerdict
    groundtruth/             # FMP (candidate), SEC XBRL (anchor / bootstrap gold),
                             # Daloopa MCP (gold, deferred), cache (frozen snapshots)
    runner/                  # invoke_skill, grid, parallel (resumable), run_baseline
    metrics.py / report.py   # aggregation + scorecard rendering
    conversion/              # Daloopa → FMP skill token swap + fmp_data_access.md
    optimize/                # SkillDoc (protected body), candidate generator,
                             # validation gate, loop, feedback
  skills/
    daloopa/   pinned upstream, read-only
    fmp/       converted variants
  fixtures/                  # known-answer xlsx + expected_ledgers.json
  tests/                     # 185+ tests, all green; network always mocked
  results/                   # scorecards + per-sample JSON (gitignored)
```

---

## Research foundation (re-verified against primary sources)

- **FAITH** — financial tabular hallucination taxonomy (Direct / Comparative /
  Bivariate / Multivariate) → drives the `by_cell_type` scorecard breakdown.
  [arXiv 2508.05201](https://arxiv.org/abs/2508.05201)
- **Finance Agent Benchmark** — o3 = $3.78/query, 3.1 min; human analyst =
  $25.66, 16.8 min; best-model accuracy 46.8% on real finance research tasks.
  Anchors the `budgets:` section.
  [arXiv 2508.00828](https://arxiv.org/abs/2508.00828)
- **Anthropic Agent Skills** — ≤8 skills per request, description-drives-
  selection. Defines activation and selection metrics + the M7 optimization
  targets (description + progressive-disclosure structure only).
  [platform.claude.com docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- **SEC SAB 99** — 5% materiality threshold for accounting judgments. Defines
  the `materiality` WARN boundary.
  [sec.gov/interps/account/sab99.htm](https://www.sec.gov/interps/account/sab99.htm)
- **Constrained / structured LLM output** and **LLM extraction with hybrid
  verification** ([LLMStructBench arXiv 2602.14743](https://arxiv.org/pdf/2602.14743),
  [Multi-Agent Financial Doc Processing arXiv 2603.22651](https://arxiv.org/html/2603.22651))
  → motivated the pivot from `parse_xlsx` to Option C (LLM extraction → trivial
  `json.loads` → deterministic verifier as the rule-based check).

---

## Honest Results

- **Activation detection partial (22%).** Stream-json fires when the agent
  Reads the staged SKILL.md; Claude Code can auto-inject a skill without a Read
  event. Needs a more authoritative skill-load event.
- **Daloopa A/B not executed.** Wiring intact; awaits MCP credentials.
- **Quarterly SEC 10-Q gold deferred.** XBRL YTD/Q overlap is non-trivial. Today
  quarterly cells SKIP (not wrong) on the SEC anchor.
- **Sample size 9.** Pilot scale. The architecture supports the full 192-cell
  grid (8 tickers × 4 periods × 3 skills × 2 sources) once Daloopa lands.

A thorough write-up is in
[`docs/in_depth_report.md`](docs/in_depth_report.md). Design-decisions mapping
in [`docs/design_decisions.md`](docs/design_decisions.md). What I'd build next
in [`docs/next_steps.md`](docs/next_steps.md).

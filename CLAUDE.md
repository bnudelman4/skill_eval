# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in FMP_API_KEY, ANTHROPIC_API_KEY, DALOOPA_MCP_URL/token

# Validate config objects
python -m finskill_eval.config

# Run tests
pytest
pytest tests/test_verify_endtoend.py         # single test file
pytest -k test_compare_scaled                # single test by name

# Run baseline scorecard
python -m finskill_eval.runner.run_baseline --dry-run    # offline, no agent/network
python -m finskill_eval.runner.run_baseline              # live (requires M6 skills + opt-in)
```

## Core principle

**LLM does semantic work only. Python owns every arithmetic operation and every numerical comparison.** The LLM maps labels to canonical names, selects the right skill, and extracts cells from spreadsheets. It never grades a number. `recompute.py` re-derives every derived metric from the skill's own stated inputs; `tolerance.py` compares values to ground truth — both are pure Python with no LLM involvement.

## Architecture

### Data flow

```
GridSample(skill × ticker × period × data_source)
  → invoke_skill.run_skill()     # headless `claude -p ... --bare --output-format json`
  → artifact .xlsx in workdir/output/
  → extract/llm_extract.py       # Option C: LLM renders xlsx to text, extracts cells as JSON
    OR parse_xlsx.parse()        # deterministic fallback (row-oriented or matrix layouts)
  → build_ledger()               # shared normalizer + wiring (both paths)
  → Ledger (typed Cell list)
  → recompute.py                 # derives margins/ratios from the Ledger's own inputs
  → verify.py                    # compare each cell against ground truth; emit CellVerdicts
  → metrics.py / report.py       # aggregate into Metrics + scorecard
```

### Module map

| Module | Role |
|--------|------|
| `config.py` | Pydantic-validated config; secrets from env only, never yaml |
| `ledger.py` / `normalize.py` | Typed cell container; number/label/period normalization |
| `parse_xlsx.py` | Deterministic xlsx → Ledger (matrix + row-oriented layouts) |
| `extract/llm_extract.py` | LLM-based xlsx → Ledger (Option C, layout-agnostic) |
| `recompute.py` | Pure Python formulas for every derived metric; `METRIC_DEFS` registry wires inputs |
| `tolerance.py` | Banded comparator: `exact → tight → xvendor_standard → xvendor_liberal → materiality → disagreement` |
| `verify.py` | Orchestrates parse → recompute → compare; arithmetic vs. sourcing checks for derived cells |
| `groundtruth/` | `sec_xbrl.py` (bootstrap gold), `fmp.py` (candidate), `daloopa_mcp.py` (future gold), `cache.py` (frozen snapshots) |
| `runner/invoke_skill.py` | Subprocess wrapper for `claude -p`; parses JSON envelope for cost/turns |
| `runner/grid.py` | `GridSample` + `score_sample` (ties invocation to verify pipeline) |
| `runner/parallel.py` | `ThreadPoolExecutor` + `RateLimiter`; resumable via per-sample JSON |
| `runner/run_baseline.py` | Top-level entry point; `--dry-run` uses fixture artifacts + fixture gold |
| `metrics.py` | Aggregates `SampleRecord` list into `Metrics`; SKIP/FLAG excluded from pass-rate denominator |
| `optimize/` | M7 description-optimization loop (disabled by default in settings) |

### Key design decisions

**Neuro-symbolic split:** `build_ledger()` is the boundary. Everything before it is LLM-permitted; everything after (recompute, compare, aggregate) is deterministic Python only.

**Derived cell verification (verify.py):** Two-stage check — (a) arithmetic: stated value vs. Python recompute of its own inputs (must be within `tight` band or FAIL); (b) sourcing: Python recompute vs. gold (cross-vendor band). Reported band = wider of the two. This separates "wrong math" from "wrong source data."

**Scale normalization:** `verify.py` tries ×{1, 1e3, 1e6, 1e9, 1e-3, ...} before ruling a number wrong — skills may output $mm while gold is absolute; matching a PASS band at any factor is a display-unit difference, not a value error.

**Ground truth hierarchy:** gold = Daloopa (pending) → bootstrap_gold = SEC XBRL (active). FMP is the *candidate* source (what the skill under test uses), never gold. `SKIP` verdicts (no gold coverage) are excluded from the pass-rate denominator.

**Headless auth:** `run_skill(use_subscription=True)` drops `--bare` and strips `ANTHROPIC_API_KEY` from the subprocess env so the CLI falls back to the Max subscription account (no 30k-TPM metered cap). Metered key runs use `load_dotenv(override=True)` in `run_baseline.py`.

**Config immutability:** All `config.py` loaders are `@lru_cache`. Pydantic `extra="forbid"` across all models. Any unrecognized key or placeholder (`REPLACE_WITH_*`) raises at startup.

### Tolerance bands (settings.yaml)

`exact (0%) → tight (0.1%) → xvendor_standard (0.5%) → xvendor_liberal (1%) → materiality (5%, WARN) → disagreement (FLAG)`

Primary accuracy target: **90% pass rate at `xvendor_liberal`**.

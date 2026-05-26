# finskill-eval

Automated evaluation pipeline for financial AI agent skills.

**The one rule:** the LLM does semantic work (map a row label to a data field,
fill a template, write prose); deterministic Python does every piece of
arithmetic and every numerical comparison. The LLM never grades a number.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in secrets (gitignored)
```

Secrets (`FMP_API_KEY`, `DALOOPA_MCP_URL`/token, `ANTHROPIC_API_KEY`) load from
the environment only — never from yaml.

## Config

- `config/settings.yaml` — tolerance bands, targets, budgets, pins. Human-ratified.
- `config/universe.yaml` — the ticker × period grid.
- `config/skills.lock.yaml` — pinned skill-repo SHA (reviewed by hand).

```bash
python -m finskill_eval.config   # prints the validated config objects
pytest                           # run the suite
```

## Build status

- [x] M0 — scaffolding & config
- [x] M1 — known-answer fixtures
- [x] M2 — deterministic verifier (built + proven before any live run)
- [x] M3 — headless skill invocation
- [x] M4 — ground-truth sources & frozen snapshots
- [x] M5 — harness, metrics, scorecard
- [ ] M6 — Daloopa→FMP conversion & A/B
- [ ] M7 — description-optimization loop (optional)

Ground truth is bootstrapped on SEC XBRL (Daloopa MCP access pending); the M6
A/B uses Daloopa as primary gold once available.

## Run the baseline scorecard

```bash
# offline: fixture artifacts + fixture gold, no agent/network
python -m finskill_eval.runner.run_baseline --dry-run
# -> results/scorecard.{json,md,html}
```

Live mode (real `claude -p` per sample, FMP/SEC pulls) is wired but requires the
converted FMP skills (M6) and bills the metered key; it is opt-in, not default.

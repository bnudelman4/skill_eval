# Design Decisions & Evidence

One-page mapping from each spec milestone → the code that implements it → the
tests that prove it → the live evidence that exercises it. Use this to verify
spec compliance at a glance.

| Milestone | Decision | Code | Tests | Live evidence |
|---|---|---|---|---|
| **M0** | Pydantic config; fail loud on placeholders, on `candidate==gold`, or unrecognized keys; secrets from env only. | `src/finskill_eval/config.py`, `config/settings.yaml`, `config/universe.yaml` | `tests/test_config.py` | every run loads through this |
| **M1** | Hand-built known-answer fixtures with one deliberate-wrong cell and one WARN-band cell. | `fixtures/*.xlsx`, `fixtures/expected_ledgers.json` | `tests/test_parse_xlsx.py`, `tests/test_verify_endtoend.py` | offline `--dry-run` scorecard |
| **M2 — neuro-symbolic verifier** | Pure-Python tolerance bands (SEC SAB 99 grounded), label/number/period normalization, derived-metric recompute, two-leg derived-cell check (stated vs recompute AND recompute vs gold). | `tolerance.py`, `normalize.py`, `ledger.py`, `recompute.py`, `parse_xlsx.py`, `verify.py` | `test_tolerance.py`, `test_normalize.py`, `test_ledger.py`, `test_recompute.py`, `test_parse_xlsx.py`, `test_parse_matrix.py`, `test_verify_endtoend.py` | tearsheet AAPL FY2024 verified 8/8 exact vs SEC |
| **M3 — headless invocation** | `claude -p` subprocess wrapped; `--bare` semantics understood; injectable runner for tests; activation detection via stream-json; robust artifact discovery; retries. | `runner/invoke_skill.py` | `test_invoke_skill.py` (incl. timeout regression) | live pilot + big test (9/9 artifacts) |
| **M4 — ground truth + snapshots** | One `GroundTruthSource` protocol; FMP (candidate), SEC XBRL (anchor, bootstrap gold), Daloopa MCP (stub). Frozen point-in-time snapshots. | `groundtruth/{base,fmp,sec_xbrl,daloopa_mcp,cache}.py` | `test_groundtruth.py` (incl. *period-end-vs-filing-fy regression* from the live bug) | SEC live verify on tearsheet; stress test on NKE / JPM |
| **M5 — harness + parallel + scorecard** | Inspect-style Task/Solver/Scorer pattern, parallel grid with global rate limiter + per-sample resumability, metrics with FAITH cell-type breakdown, scorecard JSON/Markdown/HTML. | `runner/{grid,parallel,harness,run_baseline}.py`, `metrics.py`, `report.py` | `test_m5.py` | `results/_bigtest/scorecard.{json,md,html}` |
| **M6 — Daloopa→FMP conversion** | Deterministic token swap (no LLM regeneration); ordered longest-first replacement; `fmp_data_access.md` analogue. Paired-A/B comparator wired. | `conversion/{convert_skill,fmp_data_access.md,run_conversion,compare}.py` | included in M6 test set | `skills/fmp/*` materialized; variant B ran end-to-end |
| **M7 — description-optimization loop** | SkillDoc parser with protected body (round-trips byte-identical); bounded edit guard (4–8 per step, ≤920 token cap); validation gate; 60/40 train/test; ≤5 iterations; select by **test** score (overfit guard); feedback ingestion. | `optimize/{skilldoc,candidate,loop,report,feedback,run_optimization}.py` | included in M7 test set | mechanics demonstrated; live optimization deferred |
| **P1 — matrix + multi-sheet parser** | Per-sheet layout detection; `Mon'YY` / `FY2023 Q1` period parsing; ratio-row unit inference; cross-sheet dedupe; crash-safe `_safe_period`. | `parse_xlsx.py` | `test_parse_matrix.py` | parsed the real `capital-allocation` artifact (408 cells, no crash) |
| **Option C — LLM extraction (post-pivot default)** | Cheap LLM emits `{metric, period, value, unit}` JSON; `json.loads` trivially parses; deterministic verifier grades. Skill **untouched**. | `extract/llm_extract.py`, `runner/grid.py` (wired as default `parse_fn`) | `test_extract.py` | every big-test sample ingested via Option C |
| **Security (Part A4)** | Source skills pinned at SHA `17039332…a3f2`; hand-reviewed for tool scope / network endpoints / credential reads; review result archived to project memory. | `skills/daloopa/` (read-only), `config/settings.yaml#pins.skill_repo_sha` | n/a (procedural) | clean at pinned SHA; documented in memory |

---

## Cross-cutting evidence

- **185+ tests, all green**, all offline (network mocked). `pytest -q` runs
  in ~2 s.
- **Headline live result:** 9-sample big test on the converted FMP variants
  scored **87.2% pass-rate @ 1%**, **100% on direct gold-covered
  fundamentals**, **9/9 artifacts**.
- **Real catches on live data:** JPM `shares_outstanding` (~4× off — summed
  across quarters); SEC client period-selection bug in `groundtruth/sec_xbrl.py`
  (fix in commit `93f944e`).
- **Reproducibility pins** (`config/settings.yaml`):
  `model_snapshot: claude-sonnet-4-6`, `skill_repo_sha:
  17039332eb6f9323d8415156f7202feef538a3f2`, snapshots written under
  `data/snapshots/<source>/<date>/`.
- **Research citations** for every load-bearing threshold — see
  [`in_depth_report.md §2`](in_depth_report.md#2-research-foundation).

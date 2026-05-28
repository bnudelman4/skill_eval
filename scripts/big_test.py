"""Big test: full grid path on a 9-sample slice via Max + Option C extraction.
3 skills x [AAPL clean, NKE off-cal, JPM bank] x FY2024 -> scorecard."""
from pathlib import Path
from finskill_eval.runner.run_baseline import run_baseline

metrics, paths = run_baseline(
    dry_run=False,
    tickers=["AAPL", "NKE", "JPM"],
    periods=["FY2024"],
    data_sources=["fmp"],
    results_dir=Path("results/_bigtest"),
    concurrency=2,   # cap parallel Max-auth skill runs
)
print("\n=== SCORECARD PATHS ===")
for k, v in paths.items():
    print(f"  {k}: {v}")
print("\n=== HEADLINE ===")
for f in ("activation_rate","selection_accuracy","accuracy_pass_rate",
          "mean_cost_usd","total_cost_usd","n_samples"):
    print(f"  {f}: {getattr(metrics, f, 'n/a')}")

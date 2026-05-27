"""Deterministic recompute of derived metrics (M2.5).

Each formula is a named pure function. A derived Cell names its formula and its
ordered input cell_ids; recompute() resolves those inputs from the ledger and
applies the formula. Python owns this arithmetic — the LLM's stated value for a
derived cell is never trusted, only checked against the recompute.
"""

from __future__ import annotations

from typing import Callable, Optional

from finskill_eval.ledger import Ledger


def gross_margin(gross_profit: float, revenue: float) -> float:
    """Gross margin % = gross profit / revenue * 100."""
    return gross_profit / revenue * 100.0


def operating_margin(operating_income: float, revenue: float) -> float:
    """Operating margin % = operating income / revenue * 100."""
    return operating_income / revenue * 100.0


def net_margin(net_income: float, revenue: float) -> float:
    """Net margin % = net income / revenue * 100."""
    return net_income / revenue * 100.0


def growth(current: float, prior: float) -> float:
    """Period-over-period growth % = (current - prior) / prior * 100."""
    return (current - prior) / prior * 100.0


def ebitda_margin(ebitda: float, revenue: float) -> float:
    """EBITDA margin % = EBITDA / revenue * 100."""
    return ebitda / revenue * 100.0


def ev_ebitda(enterprise_value: float, ebitda: float) -> float:
    """EV/EBITDA multiple = enterprise value / EBITDA."""
    return enterprise_value / ebitda


def pe_ratio(price: float, eps: float) -> float:
    """P/E = price / earnings per share (= 1 / earnings yield)."""
    return price / eps


def shareholder_yield(
    share_repurchases: float, dividends_paid: float, market_capitalization: float
) -> float:
    """Shareholder yield % = (buybacks + dividends) / market cap * 100."""
    return (share_repurchases + dividends_paid) / market_capitalization * 100.0


FORMULAS: dict[str, Callable[..., float]] = {
    "gross_margin": gross_margin,
    "operating_margin": operating_margin,
    "net_margin": net_margin,
    "growth": growth,
    "ebitda_margin": ebitda_margin,
    "ev_ebitda": ev_ebitda,
    "pe_ratio": pe_ratio,
    "shareholder_yield": shareholder_yield,
}

# Maps a derived metric's canonical label -> (formula name, ordered input
# canonical labels). parse_xlsx uses this to wire a derived cell to the sibling
# cells that feed it. Editable as new derived metrics are added.
METRIC_DEFS: dict[str, tuple[str, tuple[str, ...]]] = {
    "gross_margin": ("gross_margin", ("gross_profit", "revenue")),
    "operating_margin": ("operating_margin", ("operating_income", "revenue")),
    "net_margin": ("net_margin", ("net_income", "revenue")),
    "ebitda_margin": ("ebitda_margin", ("ebitda", "revenue")),
    "ev_ebitda": ("ev_ebitda", ("enterprise_value", "ebitda")),
    "pe_ratio": ("pe_ratio", ("price", "eps")),
    "shareholder_yield": (
        "shareholder_yield",
        ("share_repurchases", "dividends_paid", "market_capitalization"),
    ),
}


def recompute(
    ledger: Ledger, inputs: Optional[dict[str, float]] = None, *, strict: bool = False
) -> dict[str, float]:
    """Recompute every derived cell. Returns {cell_id: recomputed_value}.

    Input values resolve from the named input cells in the ledger; the optional
    `inputs` dict overrides/supplies values by cell_id (e.g. external market
    data not present as a cell).

    Lenient by default: a derived cell that cannot be recomputed (no registered
    formula, unknown formula, or a missing/non-numeric input) is SKIPPED, not
    fatal — real skills emit derived metrics we haven't registered, and verify()
    falls back to comparing those against gold directly. Pass strict=True to
    raise instead (used where every derived cell is expected to be computable).
    """
    overrides = inputs or {}
    out: dict[str, float] = {}
    for cell in ledger.cells:
        if cell.kind != "derived":
            continue
        fn = FORMULAS.get(cell.formula) if cell.formula else None
        if fn is None:
            if strict:
                raise ValueError(
                    f"derived cell {cell.cell_id} has no usable formula "
                    f"({cell.formula!r})"
                )
            continue  # unregistered/unknown derived metric -> skip recompute
        args: list[float] = []
        missing = False
        for input_id in cell.inputs:
            if input_id in overrides:
                args.append(overrides[input_id])
                continue
            src = ledger.by_id(input_id)
            if src is None or not isinstance(src.value, (int, float)):
                if strict:
                    raise ValueError(
                        f"derived cell {cell.cell_id} input {input_id!r} "
                        f"missing or non-numeric"
                    )
                missing = True
                break
            args.append(float(src.value))
        if missing:
            continue  # can't recompute without all inputs -> skip
        out[cell.cell_id] = fn(*args)
    return out

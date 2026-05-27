"""Number / label / period normalization (M2.1).

The semantic-to-canonical bridge. Numbers are parsed to floats (inline suffix
scaling applied, parentheses = negative); labels are canonicalized via an
editable synonym map; periods are parsed to a typed Period. Unit-based scaling
($mm, thousands) is applied later in parse_xlsx, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

_BLANKS = {"", "na", "n/a", "-", "—", "none", "nil"}
_SUFFIX = {"bn": 1e9, "b": 1e9, "m": 1e6, "mm": 1e6, "k": 1e3}

# Editable synonym map. Keys are pre-canonicalized (lowercase, _-joined) labels.
# Distinct definitions are kept distinct on purpose (e.g. net income variants).
_SYNONYMS = {
    "total_revenue": "revenue",
    "net_revenue": "revenue",
    "net_sales": "revenue",
    "sales": "revenue",
}


def normalize_number(raw: object) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if s.lower() in _BLANKS:
        return None

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]

    s = s.replace("$", "").replace(",", "").replace("%", "").strip()

    mult = 1.0
    m = re.fullmatch(r"(-?\d*\.?\d+)\s*([a-zA-Z]+)", s)
    if m:
        suffix = m.group(2).lower()
        if suffix not in _SUFFIX:
            return None
        mult = _SUFFIX[suffix]
        s = m.group(1)

    try:
        val = float(s)
    except ValueError:
        return None
    val *= mult
    return -val if negative else val


def normalize_label(raw: object) -> str:
    s = str(raw).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    key = re.sub(r"\s+", "_", s)
    return _SYNONYMS.get(key, key)


@dataclass(frozen=True)
class Period:
    kind: Literal["annual", "quarterly"]
    fiscal_year: int
    fiscal_quarter: Optional[int] = None


def _four_digit_year(token: str) -> int:
    n = int(token)
    return 2000 + n if n < 100 else n


# calendar month abbrev -> calendar quarter (consistent key for matrix columns)
_MONTH_Q = {
    "jan": 1, "feb": 1, "mar": 1,
    "apr": 2, "may": 2, "jun": 2,
    "jul": 3, "aug": 3, "sep": 3,
    "oct": 4, "nov": 4, "dec": 4,
}


def normalize_period(raw: object) -> Optional[Period]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    mq = re.fullmatch(r"[Qq]([1-4])\s*[- ]?\s*(\d{2,4})", s)
    if mq:
        return Period("quarterly", _four_digit_year(mq.group(2)), int(mq.group(1)))

    # "FY2023 Q1" / "FY23 Q1"
    mfyq = re.fullmatch(r"(?:FY|fy)\s*(\d{2,4})\s*[Qq]([1-4])", s)
    if mfyq:
        return Period("quarterly", _four_digit_year(mfyq.group(1)), int(mfyq.group(2)))

    # "Dec'22" / "Sep 24" / "Mar'2023" — calendar month + year -> calendar quarter
    mmon = re.fullmatch(r"([A-Za-z]{3,9})\s*['’]?\s*(\d{2,4})", s)
    if mmon and mmon.group(1).lower()[:3] in _MONTH_Q:
        q = _MONTH_Q[mmon.group(1).lower()[:3]]
        return Period("quarterly", _four_digit_year(mmon.group(2)), q)

    mfy = re.fullmatch(r"(?:FY|fy)?\s*(\d{2,4})", s)
    if mfy:
        return Period("annual", _four_digit_year(mfy.group(1)), None)

    mdate = re.fullmatch(r"(\d{4})-\d{2}-\d{2}", s)
    if mdate:
        return Period("annual", int(mdate.group(1)), None)

    raise ValueError(f"unparseable period: {raw!r}")


def period_key(period: Optional[Period]) -> Optional[str]:
    """Canonical string key for a Period: 'FY2024' / 'Q4 2025' / None."""
    if period is None:
        return None
    if period.kind == "annual":
        return f"FY{period.fiscal_year}"
    return f"Q{period.fiscal_quarter} {period.fiscal_year}"

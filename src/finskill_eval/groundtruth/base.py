"""GroundTruthSource protocol + the Value record (M4)."""

from __future__ import annotations

from typing import Optional, Protocol, Union

from pydantic import BaseModel, ConfigDict


class Value(BaseModel):
    """A single ground-truth datum with provenance."""

    model_config = ConfigDict(frozen=True)

    value: Union[float, str]
    unit: str
    vintage: str            # as-of date / fiscal period the value was reported for
    source_id: str          # "fmp" | "sec_xbrl" | "daloopa"
    period: Optional[str]   # canonical period key, e.g. "FY2024"
    canonical_label: str


class GroundTruthSource(Protocol):
    def get(
        self, ticker: str, period: Optional[str], canonical_label: str
    ) -> Optional[Value]: ...

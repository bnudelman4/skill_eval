"""Typed cell ledger datatypes (M2.3)."""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict

from finskill_eval.normalize import Period

Kind = Literal["direct", "derived"]
CellType = Literal["direct_lookup", "comparative", "bivariate", "multivariate"]


class Cell(BaseModel):
    model_config = ConfigDict(frozen=True)

    cell_id: str
    label: str
    canonical_label: str
    period: Optional[Period]
    raw_value: Optional[str]
    value: Union[float, str, None]
    unit: str
    kind: Kind
    cell_type: Optional[CellType] = None
    source_ref: Optional[str] = None
    # derived-cell provenance: formula name + input cell_ids it recomputes from
    formula: Optional[str] = None
    inputs: tuple[str, ...] = ()


class Ledger(BaseModel):
    skill: str
    ticker: str
    cells: list[Cell]

    def by_id(self, cell_id: str) -> Optional[Cell]:
        return next((c for c in self.cells if c.cell_id == cell_id), None)

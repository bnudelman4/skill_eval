"""Daloopa MCP client — primary gold for the M6 conversion A/B (M4).

DEFERRED: Daloopa MCP access is pending (Part A1). M0-M5 bootstrap on SEC XBRL
gold. This stub documents the intended 4-step flow and fails loudly if used
before access is wired, rather than silently returning wrong data.
"""

from __future__ import annotations

from typing import Optional

from finskill_eval.groundtruth.base import Value


class DaloopaClient:
    """Placeholder until MCP credentials/endpoint are provisioned.

    Documented flow once available:
      1. discover_companies     -> resolve ticker to Daloopa company id
      2. discover_company_series -> find the series for a canonical label
      3. get_company_fundamentals -> fetch standardized + as-reported values
      4. search_documents        -> qualitative backup
    """

    def __init__(self, *, mcp_url: Optional[str] = None, token: Optional[str] = None):
        self._url = mcp_url
        self._token = token

    def get(
        self, ticker: str, period: Optional[str], canonical_label: str
    ) -> Optional[Value]:
        raise NotImplementedError(
            "Daloopa MCP access is not yet provisioned (Part A1). Use SEC XBRL "
            "as bootstrap gold until DALOOPA_MCP_URL/token are available."
        )

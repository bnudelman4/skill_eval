"""Convert a Daloopa skill into an FMP skill by swapping ONLY the data layer.

Per the research: do NOT regenerate skills from scratch (auto-generated skills
underperform hand-authored ones). This is a targeted, deterministic token swap
that keeps the SKILL.md prose, workflow, and frontmatter byte-for-byte except on
the lines that name a Daloopa data tool, point at Daloopa's data-access.md, or
emit a Daloopa citation. The output bundles `fmp_data_access.md` alongside.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Ordered, longest-first so substrings don't get partially rewritten
# (e.g. discover_company_series before discover_companies).
DALOOPA_TO_FMP: list[tuple[str, str]] = [
    ("../data-access.md", "fmp_data_access.md"),
    ("discover_company_series", "fmp_fields"),
    ("discover_companies", "fmp_profile"),
    ("get_company_fundamentals", "fmp_statements"),
    ("get_stock_prices", "fmp_quote"),
    ("search_documents", "fmp_filings_search"),
    ("https://daloopa.com/src/{fundamental_id}", "fmp_data_access.md#sourcing"),
    ("https://marketplace.daloopa.com/document/{document_id}", "fmp_data_access.md#sourcing"),
    ("Data sourced from Daloopa", "Data sourced from Financial Modeling Prep (FMP)"),
]

_REFERENCE = Path(__file__).with_name("fmp_data_access.md")


def convert_skill_text(src_md: str) -> str:
    """Apply the data-layer swaps. Idempotent: replacement targets contain no
    source token, so re-running is a no-op."""
    out = src_md
    for src, dst in DALOOPA_TO_FMP:
        out = out.replace(src, dst)
    return out


def convert_skill_file(src_skill_md: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    converted = convert_skill_text(Path(src_skill_md).read_text(encoding="utf-8"))
    out_md = dest_dir / "SKILL.md"
    out_md.write_text(converted, encoding="utf-8")
    shutil.copyfile(_REFERENCE, dest_dir / "fmp_data_access.md")
    return out_md


def convert_all(
    src_root: Path, dest_root: Path, *, skills: list[str]
) -> list[Path]:
    src_root, dest_root = Path(src_root), Path(dest_root)
    written = []
    for skill in skills:
        src = src_root / skill / "SKILL.md"
        written.append(convert_skill_file(src, dest_root / skill))
    return written

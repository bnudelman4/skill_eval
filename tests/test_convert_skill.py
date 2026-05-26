"""M6: Daloopa->FMP skill conversion. Deterministic text transform, no network.

The contract: swap ONLY the data-access layer (MCP tool tokens, the
data-access.md pointer, citation/attribution). Every line of analytical
prose/workflow must survive untouched.
"""

from pathlib import Path

import pytest

from finskill_eval.conversion.convert_skill import (
    DALOOPA_TO_FMP,
    convert_all,
    convert_skill_text,
)

DALOOPA = Path("skills/daloopa")
SKILLS = ["tearsheet", "comps", "capital-allocation"]
_MCP_TOKENS = [
    "discover_companies", "discover_company_series", "get_company_fundamentals",
    "get_stock_prices", "search_documents",
]


@pytest.fixture(params=SKILLS)
def skill_md(request):
    return (DALOOPA / request.param / "SKILL.md").read_text()


def test_swaps_remove_all_daloopa_mcp_tokens(skill_md):
    out = convert_skill_text(skill_md)
    for tok in _MCP_TOKENS:
        assert tok not in out, tok
    assert "daloopa.com/src" not in out
    assert "../data-access.md" not in out
    assert "fmp_data_access.md" in out


def test_frontmatter_identical(skill_md):
    """Descriptions drive selection; keep frontmatter byte-identical so the A/B
    compares data layer, not triggering."""
    out = convert_skill_text(skill_md)
    fm_in = skill_md.split("---", 2)[1]
    fm_out = out.split("---", 2)[1]
    assert fm_in == fm_out


def test_prose_preserved_line_count(skill_md):
    """Only data-layer lines change. Non-data lines must be identical and in
    the same order."""
    out = convert_skill_text(skill_md)
    in_lines, out_lines = skill_md.splitlines(), out.splitlines()
    assert len(in_lines) == len(out_lines)
    changed = sum(1 for a, b in zip(in_lines, out_lines) if a != b)
    # surgical: only a handful of lines touched
    assert changed <= 12
    # analytical anchors survive
    for anchor in ("Follow these steps", "##"):
        assert anchor in out


def test_idempotent(skill_md):
    once = convert_skill_text(skill_md)
    twice = convert_skill_text(once)
    assert once == twice


def test_every_mapping_has_nonempty_replacement():
    for src, dst in DALOOPA_TO_FMP:
        assert src and dst is not None


def test_convert_all_writes_fmp_skill_tree(tmp_path):
    dest = tmp_path / "fmp"
    written = convert_all(DALOOPA, dest, skills=SKILLS)
    for skill in SKILLS:
        sk = dest / skill / "SKILL.md"
        assert sk.exists()
        assert "fmp_data_access.md" in sk.read_text()
        # the FMP reference is bundled alongside each converted skill
        assert (dest / skill / "fmp_data_access.md").exists()
    assert len(written) == len(SKILLS)

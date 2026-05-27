"""Propose a bounded edit to a skill's description.

The only LLM role in the optimization loop besides running the skill itself, and
it is a *semantic* one (write a better trigger description) — never arithmetic.
Guards enforce the SkillOpt findings:
  - bounded diff: <= max_edits token-level changes per step (4-8 sweet spot)
  - compactness: description <= token_cap (and the 1024-char Anthropic limit)
  - protected body: only the description is applied; the body is structurally
    untouchable via SkillDoc.with_description.
"""

from __future__ import annotations

import difflib
from typing import Callable, Optional

from finskill_eval.optimize.skilldoc import SkillDoc

LLM = Callable[[str], str]

CHAR_HARD_LIMIT = 1024  # Anthropic description field hard cap


def _tokens(s: str) -> list[str]:
    return s.split()


def count_token_edits(old: str, new: str) -> int:
    """Number of token-level changes (replace/insert/delete) between two
    descriptions, via difflib opcodes."""
    sm = difflib.SequenceMatcher(a=_tokens(old), b=_tokens(new))
    edits = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            edits += max(i2 - i1, j2 - j1)
        elif tag == "delete":
            edits += i2 - i1
        elif tag == "insert":
            edits += j2 - j1
    return edits


def validate_edit(
    old_desc: str, new_desc: str, *, max_edits: int, token_cap: int
) -> tuple[bool, str]:
    new_desc = new_desc.strip()
    if not new_desc:
        return False, "empty description"
    if len(new_desc) > CHAR_HARD_LIMIT:
        return False, f"over {CHAR_HARD_LIMIT}-char hard limit"
    if len(_tokens(new_desc)) > token_cap:
        return False, f"over token cap ({token_cap})"
    n_edits = count_token_edits(old_desc, new_desc)
    if n_edits > max_edits:
        return False, f"too many edits ({n_edits} > {max_edits})"
    if n_edits == 0:
        return False, "no change"
    return True, "ok"


_PROMPT = """You are tuning ONLY the `description` field of an Agent Skill so it
triggers reliably for the right queries and not for the wrong ones. The skill's
analytical body is frozen and not shown — do not try to change it.

Current description:
{desc}

Rewrite the description to be a crisp, compact trigger: say what the skill does
AND when to use it. Make at most {max_edits} token-level changes. Keep it under
{token_cap} tokens. Return ONLY the new description text, no quotes, no prose."""


def make_candidate(
    doc: SkillDoc,
    llm: LLM,
    *,
    max_edits: int,
    token_cap: int,
) -> Optional[SkillDoc]:
    """Ask the LLM for a new description, validate the guards, and return a
    candidate SkillDoc (body protected) — or None if the edit is rejected."""
    proposed = llm(
        _PROMPT.format(desc=doc.description, max_edits=max_edits, token_cap=token_cap)
    ).strip()
    ok, _reason = validate_edit(
        doc.description, proposed, max_edits=max_edits, token_cap=token_cap
    )
    if not ok:
        return None
    return doc.with_description(proposed)

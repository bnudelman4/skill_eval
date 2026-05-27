"""Parse/edit/emit a SKILL.md while keeping the body a protected (immutable)
section.

The optimizer may only rewrite the frontmatter `description` (and, later,
progressive-disclosure structure). The body — the hand-authored analytical
prose — must never change. We guarantee that structurally: edits replace only
the `description:` line inside the frontmatter block; everything else (other
frontmatter keys, the entire body) is carried through byte-for-byte.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_DESC_LINE = re.compile(r"^(description:[ \t]*)(.*)$", re.MULTILINE)
_NAME_LINE = re.compile(r"^name:[ \t]*(.*)$", re.MULTILINE)


@dataclass(frozen=True)
class SkillDoc:
    frontmatter: str  # text between the --- fences (no fences)
    body: str         # everything after the closing fence, byte-for-byte

    @classmethod
    def parse(cls, text: str) -> "SkillDoc":
        m = _FRONTMATTER.match(text)
        if not m:
            raise ValueError("SKILL.md missing leading --- frontmatter block")
        return cls(frontmatter=m.group(1), body=text[m.end():])

    @property
    def name(self) -> str:
        m = _NAME_LINE.search(self.frontmatter)
        return m.group(1).strip() if m else ""

    @property
    def description(self) -> str:
        m = _DESC_LINE.search(self.frontmatter)
        return m.group(2).strip() if m else ""

    def with_description(self, new_description: str) -> "SkillDoc":
        """Return a copy with only the description line rewritten. Body and all
        other frontmatter keys are untouched."""
        new_description = new_description.strip()
        if _DESC_LINE.search(self.frontmatter):
            fm = _DESC_LINE.sub(
                lambda mm: f"{mm.group(1)}{new_description}", self.frontmatter, count=1
            )
        else:  # no description key yet: append one
            fm = self.frontmatter.rstrip("\n") + f"\ndescription: {new_description}"
        return SkillDoc(frontmatter=fm, body=self.body)

    def to_text(self) -> str:
        return f"---\n{self.frontmatter}\n---\n{self.body}"

    def body_hash(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()

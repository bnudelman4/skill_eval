"""LLM fallback: resolve any unmapped canonical_label to an (endpoint, field).

When the deterministic LABEL_MAP doesn't have an entry for a canonical_label
emitted by a skill, ask a cheap LLM "which FMP endpoint + field corresponds to
this canonical name?" using FMP's documented field catalog as in-context
grounding. Results are cached to disk so we only pay the LLM cost once per
label.

This closes the bounded LABEL_MAP gap into automatic coverage: any new metric a
skill emits gets a mapping proposal on first encounter, persisted forever after.
The LLM does *semantic* work (label -> field name) — never arithmetic.

The LLM is injectable (Callable[[str, dict[str, list[str]]], Optional[tuple[str,str]]])
so tests run offline with a deterministic stub.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

# LLM signature: (canonical_label, catalog) -> Optional[(endpoint, field)]
# `catalog` is {endpoint_name: [field_name, ...]} so the model can pick.
LLMResolveFn = Callable[[str, dict[str, list[str]]], Optional[tuple[str, str]]]


class LLMLabelResolver:
    """Cached LLM-backed resolver. Falls back to None when the LLM declines
    to map (signaling 'no good match exists')."""

    def __init__(
        self,
        catalog: dict[str, list[str]],
        llm: LLMResolveFn,
        cache_path: Path,
    ):
        self._catalog = catalog
        self._llm = llm
        self._cache_path = Path(cache_path)
        self._cache: dict[str, Optional[list[str]]] = self._load()

    def _load(self) -> dict:
        if self._cache_path.exists():
            try:
                return json.loads(self._cache_path.read_text())
            except json.JSONDecodeError:
                return {}
        return {}

    def _save(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(self._cache, indent=2, sort_keys=True))

    def resolve(self, canonical_label: str) -> Optional[tuple[str, str]]:
        if canonical_label in self._cache:
            cached = self._cache[canonical_label]
            return tuple(cached) if cached else None
        proposed = self._llm(canonical_label, self._catalog)
        # validate proposal: endpoint must exist; field must exist in that endpoint
        if proposed is not None:
            endpoint, field = proposed
            if endpoint not in self._catalog or field not in self._catalog[endpoint]:
                proposed = None
        self._cache[canonical_label] = list(proposed) if proposed else None
        self._save()
        return proposed


def claude_resolver_fn(canonical_label: str, catalog: dict[str, list[str]]) -> Optional[tuple[str, str]]:
    """Production LLM call via `claude -p` headless. Used as the default LLM
    function when no override is provided. Returns None on parse failure or
    when the model declines to map.

    Kept light on imports so tests don't pull subprocess machinery.
    """
    import json as _json
    import subprocess

    flat = "\n".join(
        f"{ep}: {', '.join(sorted(fields))}"
        for ep, fields in sorted(catalog.items())
    )
    prompt = (
        f"You map a canonical financial-metric label to an FMP API field.\n\n"
        f"Canonical label: {canonical_label}\n\n"
        f"Available endpoints and fields:\n{flat}\n\n"
        f"If a single best match exists, respond with ONLY a JSON object: "
        f'{{"endpoint": "<name>", "field": "<name>"}}. '
        f"If no good match exists, respond with the literal token NONE."
    )
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json", "--max-turns", "1"],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            return None
        env = _json.loads(proc.stdout)
        result = (env.get("result") or "").strip()
        if result.upper().startswith("NONE"):
            return None
        # try to parse a JSON object from the result
        i, j = result.find("{"), result.rfind("}")
        if i == -1 or j == -1:
            return None
        obj = _json.loads(result[i:j+1])
        ep, fld = obj.get("endpoint"), obj.get("field")
        return (ep, fld) if (ep and fld) else None
    except Exception:
        return None

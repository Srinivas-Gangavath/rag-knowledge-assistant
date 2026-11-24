"""Deterministic lexical helpers for PostgreSQL FTS.

plainto_tsquery is used at query time (never to_tsquery on user text).
Identifier extraction is regex-only — not query rewriting.
"""

from __future__ import annotations

import re

# At least two letters, then one or more hyphen/underscore groups.
# Matches POL-HR-2041, SKU-PRO-99, OPS-ROT-3300, PIN-DOCS-4411, SUP-DESK-440.
IDENTIFIER_PATTERN = re.compile(r"\b[A-Za-z]{2,}(?:[-_][A-Za-z0-9]+)+\b")
MAX_IDENTIFIERS = 16


def extract_identifiers(question: str) -> list[str]:
    """Return unique identifier-like tokens in first-seen order."""
    found: list[str] = []
    seen: set[str] = set()
    for match in IDENTIFIER_PATTERN.findall(question or ""):
        key = match.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append(match)
        if len(found) >= MAX_IDENTIFIERS:
            break
    return found


def escape_like_pattern(value: str) -> str:
    """Escape ILIKE wildcards and backslash for a parameterized ESCAPE '\\' clause."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

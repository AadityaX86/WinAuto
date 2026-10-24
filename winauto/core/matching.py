"""Loose name matching: "vs code" -> "Visual Studio Code", "spotfy" -> "Spotify"."""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from rapidfuzz import fuzz

# Keep + # . so "notepad++" and "c#" survive.
_PUNCT = re.compile(r"[^\w\s+#.]")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower().strip()
    text = text.replace("&", " and ")
    text = re.sub(r"\.(exe|lnk)$", "", text)
    text = _PUNCT.sub(" ", text)
    # Drop sentence dots but keep ones inside names like "paint.net".
    text = re.sub(r"\.(?=\s|$)|(?:^|(?<=\s))\.", " ", text)
    return " ".join(text.split())


def score(query: str, candidate: str) -> float:
    """0-100 similarity between what the user typed and a name."""
    q = normalize(query)
    c = normalize(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 100.0
    qc, cc = q.replace(" ", ""), c.replace(" ", "")
    if qc == cc:
        return 99.0
    q_tokens, c_tokens = q.split(), c.split()
    ratio = len(q_tokens) / max(len(c_tokens), 1)
    if set(q_tokens) <= set(c_tokens):
        return 90.0 + 8.0 * ratio
    initials = "".join(t[0] for t in c_tokens if t)
    if len(qc) >= 2 and qc == initials:
        return 88.0
    if all(any(ct.startswith(qt) for ct in c_tokens) for qt in q_tokens):
        return 80.0 + 8.0 * ratio
    return fuzz.WRatio(q, c) * 0.85


def rank(query: str, choices: Iterable[str], limit: int = 5, cutoff: float = 75.0) -> list[tuple[str, float]]:
    scored = [(c, score(query, c)) for c in choices]
    scored = [x for x in scored if x[1] >= cutoff]
    scored.sort(key=lambda x: (-x[1], len(x[0])))
    return scored[:limit]


def best(query: str, choices: Iterable[str], cutoff: float = 75.0) -> str | None:
    found = rank(query, choices, limit=1, cutoff=cutoff)
    return found[0][0] if found else None

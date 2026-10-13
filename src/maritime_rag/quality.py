"""Text quality metric: share of word tokens found in an Indonesian wordlist.

Used to compare an OCR text layer against a re-OCR or a born-digital copy. Born-digital
regulations give the ceiling (legal abbreviations and names are never 100% in a wordlist).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_EDGE_PUNCT = "\"'“”‘’.,;:()[]{}!?*/"
_ROMAN = re.compile(r"^[ivxlc]+$")


@lru_cache(maxsize=4)
def load_wordlist(path: Path) -> frozenset[str]:
    with path.open(encoding="utf-8", errors="ignore") as f:
        return frozenset(w.strip().lower() for w in f if w.strip())


@dataclass(frozen=True)
class QualityScore:
    tokens: int
    known: int

    @property
    def hit_rate(self) -> float:
        return self.known / self.tokens if self.tokens else 0.0


def word_tokens(lines: Iterable[str], min_len: int) -> list[str]:
    """Lowercased word tokens; hyphenated compounds ("Undang-Undang") are split into parts.

    Tokens containing no letters (numbers, "(1)") and roman numerals are skipped. Tokens with
    OCR debris inside ("pe}.iyelenggaraan", "2O2L") are kept, so they count as unknown.
    """
    out: list[str] = []
    for line in lines:
        for raw in line.split():
            for part in raw.strip(_EDGE_PUNCT).split("-"):
                tok = part.strip(_EDGE_PUNCT).lower()
                if len(tok) < min_len or not any(c.isalpha() for c in tok) or _ROMAN.match(tok):
                    continue
                out.append(tok)
    return out


def score(lines: Iterable[str], wordlist: frozenset[str], min_len: int) -> QualityScore:
    tokens = word_tokens(lines, min_len)
    return QualityScore(len(tokens), sum(1 for t in tokens if t in wordlist))

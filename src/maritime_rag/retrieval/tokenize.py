"""BM25 tokenization for Indonesian and English: lowercase, split on non-alphanumerics, drop stopwords."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

_TOKEN = re.compile(r"[a-z0-9]+")


def load_stopwords(path: Path) -> frozenset[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return frozenset(w.lower() for lang in data.values() for w in lang)


class Tokenizer:
    def __init__(self, stopwords: frozenset[str], min_token_len: int) -> None:
        self.stopwords = stopwords
        self.min_len = min_token_len

    def __call__(self, text: str) -> list[str]:
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
        return [
            t
            for t in _TOKEN.findall(text)
            if t not in self.stopwords and (len(t) >= self.min_len or t.isdigit())
        ]

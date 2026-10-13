"""Chunk corpus, search filters, hit records, and the text each retriever indexes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

Chunk = dict[str, Any]  # one row of chunks.jsonl


@dataclass(frozen=True)
class Corpus:
    chunks: list[Chunk]
    sha256: str  # of the chunks file, to detect stale persisted indexes

    @property
    def ids(self) -> list[str]:
        return [c["chunk_id"] for c in self.chunks]

    def by_id(self) -> dict[str, Chunk]:
        return {c["chunk_id"]: c for c in self.chunks}


def load_corpus(path: Path) -> Corpus:
    raw = path.read_bytes()
    chunks = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    return Corpus(chunks, hashlib.sha256(raw).hexdigest())


def indexed_text(chunk: Chunk, include_heading: bool) -> str:
    """Text a retriever indexes: optional "doc > BAB > Pasal" context + the original chunk text.

    The context exists only in the index; hits return the stored text unchanged.
    """
    return f"{chunk['heading']}\n{chunk['text']}" if include_heading else chunk["text"]


@dataclass(frozen=True)
class Filters:
    doc_ids: Sequence[str] | None = None
    doc_types: Sequence[str] | None = None  # UU | PP | PM | Report
    parts: Sequence[str] | None = None  # preamble | body | penjelasan | lampiran | report
    exclude_superseded: bool = False  # drop chunks whose Pasal has newer wording or was repealed

    def accepts(self, chunk: Chunk) -> bool:
        return (
            (self.doc_ids is None or chunk["doc_id"] in self.doc_ids)
            and (self.doc_types is None or chunk["doc_type"] in self.doc_types)
            and (self.parts is None or chunk["part"] in self.parts)
            and not (self.exclude_superseded and chunk.get("superseded_by"))
        )


def mask(chunks: Sequence[Chunk], filters: Filters | None) -> Callable[[int], bool]:
    if filters is None:
        return lambda i: True
    allowed = [filters.accepts(c) for c in chunks]
    return lambda i: allowed[i]


@dataclass
class Hit:
    chunk_id: str
    score: float
    rank: int  # 1-based
    retriever: str
    chunk: Chunk  # full metadata incl. text, superseded_by, partially_amended_by, amends_*
    stage_scores: dict[str, float] = field(default_factory=dict)  # e.g. first-stage score before rerank


class Retriever(Protocol):
    name: str

    def search(self, query: str, k: int, filters: Filters | None = None) -> list[Hit]: ...


def top_hits(
    scores: Sequence[float], corpus: Corpus, k: int, filters: Filters | None, retriever: str
) -> list[Hit]:
    """Rank all chunks by score (ties broken by corpus order, so results are deterministic)."""
    ok = mask(corpus.chunks, filters)
    order = sorted((i for i in range(len(scores)) if ok(i)), key=lambda i: (-scores[i], i))[:k]
    return [
        Hit(corpus.chunks[i]["chunk_id"], float(scores[i]), r, retriever, corpus.chunks[i])
        for r, i in enumerate(order, start=1)
    ]

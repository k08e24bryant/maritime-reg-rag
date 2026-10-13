"""BM25 (Okapi) over chunk text, optionally with the "doc > BAB > Pasal" heading prepended."""

from __future__ import annotations

from typing import Any

from rank_bm25 import BM25Okapi

from maritime_rag.retrieval.corpus import Corpus, Filters, Hit, indexed_text, top_hits
from maritime_rag.retrieval.tokenize import Tokenizer


class BM25Retriever:
    name = "bm25"

    def __init__(self, corpus: Corpus, tokenizer: Tokenizer, cfg: dict[str, Any]) -> None:
        self.corpus = corpus
        self.tokenize = tokenizer
        docs = [tokenizer(indexed_text(c, cfg["include_heading"])) for c in corpus.chunks]
        self.bm25 = BM25Okapi(docs, k1=cfg["k1"], b=cfg["b"])

    def scores(self, query: str) -> list[float]:
        tokens = self.tokenize(query)
        return list(self.bm25.get_scores(tokens)) if tokens else [0.0] * len(self.corpus.chunks)

    def search(self, query: str, k: int, filters: Filters | None = None) -> list[Hit]:
        scores = self.scores(query)
        # a chunk sharing no query term is not a match, even if it would fill the top k
        return [h for h in top_hits(scores, self.corpus, k, filters, self.name) if h.score > 0]

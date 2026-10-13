"""Hybrid retrieval: reciprocal rank fusion (RRF) of BM25 and dense rankings."""

from __future__ import annotations

from typing import Any

from maritime_rag.retrieval.corpus import Corpus, Filters, Hit, Retriever


class HybridRetriever:
    name = "hybrid"

    def __init__(self, corpus: Corpus, retrievers: list[Retriever], cfg: dict[str, Any]) -> None:
        self.corpus = corpus
        self.retrievers = retrievers
        self.k_rrf: int = cfg["k_rrf"]
        self.candidates: int = cfg["candidates"]
        self.position = {cid: i for i, cid in enumerate(corpus.ids)}

    def search(self, query: str, k: int, filters: Filters | None = None) -> list[Hit]:
        fused: dict[str, float] = {}
        ranks: dict[str, dict[str, float]] = {}
        chunks: dict[str, dict] = {}
        depth = max(self.candidates, k)
        for retriever in self.retrievers:  # filters apply before fusion
            for hit in retriever.search(query, depth, filters):
                fused[hit.chunk_id] = fused.get(hit.chunk_id, 0.0) + 1.0 / (self.k_rrf + hit.rank)
                ranks.setdefault(hit.chunk_id, {})[f"{retriever.name}_rank"] = hit.rank
                chunks[hit.chunk_id] = hit.chunk
        order = sorted(fused, key=lambda cid: (-fused[cid], self.position[cid]))[:k]
        return [
            Hit(cid, fused[cid], r, self.name, chunks[cid], stage_scores=ranks[cid])
            for r, cid in enumerate(order, start=1)
        ]

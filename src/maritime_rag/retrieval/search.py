"""Search pipeline: one retriever (bm25 | dense | hybrid) + optional reranker, behind search()."""

from __future__ import annotations

from typing import Any

from maritime_rag.config import resolve
from maritime_rag.retrieval.bm25 import BM25Retriever
from maritime_rag.retrieval.corpus import Chunk, Corpus, Filters, Hit, Retriever, load_corpus
from maritime_rag.retrieval.dense import DenseRetriever, SentenceTransformerEncoder, load_or_build_index
from maritime_rag.retrieval.hybrid import HybridRetriever
from maritime_rag.retrieval.rerank import CrossEncoderReranker
from maritime_rag.retrieval.tokenize import Tokenizer, load_stopwords

RETRIEVERS = ("bm25", "dense", "hybrid")


class Searcher:
    """Builds only what the chosen retriever needs; models load lazily and are reused."""

    def __init__(self, cfg: dict[str, Any], corpus: Corpus | None = None, reranker: str | None = None) -> None:
        self.cfg = cfg
        self.reranker_choice = reranker  # "default" | "small" | model id; None = config
        self.corpus = corpus or load_corpus(resolve(cfg["paths"]["chunks_file"]))
        self._retrievers: dict[str, Retriever] = {}
        self._reranker: CrossEncoderReranker | None = None
        self.build_stats = None

    def retriever(self, name: str) -> Retriever:
        if name not in RETRIEVERS:
            raise ValueError(f"unknown retriever {name!r}; choose from {RETRIEVERS}")
        if name not in self._retrievers:
            if name == "bm25":
                p = self.cfg["paths"]
                tok = Tokenizer(load_stopwords(resolve(p["stopwords"])), self.cfg["bm25"]["min_token_len"])
                self._retrievers[name] = BM25Retriever(self.corpus, tok, self.cfg["bm25"])
            elif name == "dense":
                d = self.cfg["dense"]
                encoder = SentenceTransformerEncoder(d["model"], d, resolve(self.cfg["paths"]["hf_cache"]))
                index, self.build_stats = load_or_build_index(
                    self.corpus, encoder, d, resolve(self.cfg["paths"]["index_dir"])
                )
                self._retrievers[name] = DenseRetriever(self.corpus, encoder, index, d)
            else:
                parts = [self.retriever("bm25"), self.retriever("dense")]
                self._retrievers[name] = HybridRetriever(self.corpus, parts, self.cfg["hybrid"])
        return self._retrievers[name]

    @property
    def loaded_reranker(self) -> CrossEncoderReranker | None:
        """The reranker if a --rerank query already loaded it (it is never loaded eagerly)."""
        return self._reranker

    def reranker(self) -> CrossEncoderReranker:
        if self._reranker is None:
            self._reranker = CrossEncoderReranker(
                self.cfg["rerank"],
                resolve(self.cfg["paths"]["hf_cache"]),
                self.cfg["dense"]["include_heading"],
                self.reranker_choice,
            )
        return self._reranker

    def search(
        self,
        query: str,
        k: int | None = None,
        filters: Filters | None = None,
        retriever: str | None = None,
        rerank: bool | None = None,
    ) -> list[Hit]:
        k = k or self.cfg["search"]["k"]
        name = retriever or self.cfg["search"]["retriever"]
        rerank = self.cfg["rerank"]["enabled"] if rerank is None else rerank
        if not rerank:
            return self.retriever(name).search(query, k, filters)
        first = self.retriever(name).search(query, max(self.cfg["rerank"]["top_n"], k), filters)
        return self.reranker().rerank(query, first, k)


def version_status(chunk: Chunk, corpus: Corpus) -> str:
    """Human-readable version info for a hit (Phase 3 decides how to present versions)."""
    notes = []
    if chunk.get("superseded_by"):
        newest = chunk["superseded_by"][-1]
        base = chunk.get("amends_doc") or chunk["doc_id"]
        repeal = any(
            c["doc_id"] == newest and c.get("amends_doc") == base and c.get("amends_pasal") == chunk["pasal"]
            and c.get("amendment_kind") == "delete"
            for c in corpus.chunks
        )
        notes.append(f"{'REPEALED' if repeal else 'SUPERSEDED'} by {newest}")
    if chunk.get("partially_amended_by"):
        notes.append(f"partially amended by {', '.join(chunk['partially_amended_by'])}")
    if chunk.get("amends_doc"):
        notes.append(f"amends {chunk['amends_doc']} Pasal {chunk['amends_pasal']} ({chunk['amendment_kind'] or 'penjelasan'})")
    if chunk.get("may_be_amended_by_out_of_corpus"):
        notes.append(f"may be amended by {', '.join(chunk['may_be_amended_by_out_of_corpus'])} (not in corpus)")
    return "; ".join(notes) or "current"

"""Retrieval tests on the real corpus and the real e5 model.

Skipped unless chunks.jsonl and a built dense index exist (run maritime-ingest and
maritime-index first), so a plain `pytest` never downloads models or embeds the corpus.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from maritime_rag.config import load_config, resolve
from maritime_rag.retrieval.corpus import Filters, load_corpus
from maritime_rag.retrieval.dense import passages

CFG = load_config("configs/retrieval.yaml")
CHUNKS = resolve(CFG["paths"]["chunks_file"])
INDEX = resolve(CFG["paths"]["index_dir"]) / "dense.faiss"

pytestmark = pytest.mark.skipif(
    not (CHUNKS.exists() and INDEX.exists()), reason="needs chunks.jsonl and a built index (maritime-index)"
)


@pytest.fixture(scope="module")
def searcher():
    from maritime_rag.retrieval.search import Searcher

    return Searcher(CFG)


@pytest.fixture(scope="module")
def sample():
    """20 seeded chunks with distinctive text (amended pairs share wording, so they are excluded)."""
    corpus = load_corpus(CHUNKS)
    texts = [c["text"] for c in corpus.chunks]
    pool = [
        c for c in corpus.chunks
        if c["n_tokens"] >= 40 and not c["superseded_by"] and not c["amends_doc"] and texts.count(c["text"]) == 1
    ]
    return random.Random(CFG["seed"]).sample(pool, 20)


@pytest.mark.parametrize("retriever", ["bm25", "dense"])
def test_verbatim_chunk_text_is_rank_1(searcher, sample, retriever: str) -> None:
    misses = [c["chunk_id"] for c in sample if searcher.search(c["text"], 1, retriever=retriever)[0].chunk_id != c["chunk_id"]]
    assert misses == []


def test_dense_index_matches_a_fresh_embedding(searcher, sample) -> None:
    """Persisted vectors equal a fresh encode of the same passages (build is deterministic)."""
    dense = searcher.retriever("dense")
    corpus = searcher.corpus
    pos = {cid: i for i, cid in enumerate(corpus.ids)}
    texts = passages(corpus, CFG["dense"])
    rows = [pos[c["chunk_id"]] for c in sample]
    fresh = dense.encoder.encode([texts[i] for i in rows], CFG["dense"]["batch_size"])
    stored = np.stack([dense.index.reconstruct(i) for i in rows])
    assert np.allclose(fresh, stored, atol=2e-3)


def test_filters_on_real_corpus(searcher) -> None:
    q = "izin usaha perusahaan angkutan laut"
    for name in ("bm25", "dense", "hybrid"):
        hits = searcher.search(q, 10, Filters(doc_ids=["pm_93_2013"], exclude_superseded=True), retriever=name)
        assert hits and all(h.chunk["doc_id"] == "pm_93_2013" and not h.chunk["superseded_by"] for h in hits)

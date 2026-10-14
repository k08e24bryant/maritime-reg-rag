"""Same-Pasal budget: lower-ranked hits are dropped only when that makes the priority chunks fit."""

from __future__ import annotations

from maritime_rag.answer.versions import VersionIndex, build_context, expand_siblings
from maritime_rag.retrieval.corpus import Corpus, Hit


def _chunk(cid: str, pasal: str, ayat: str | None, n_tokens: int) -> dict:
    return {"chunk_id": cid, "doc_id": "uu_17_2008", "doc_type": "UU", "number": "17", "year": 2008, "title": "T",
            "part": "body", "pasal": pasal, "ayat": ayat, "heading": f"UU 17/2008 > Pasal {pasal}",
            "source_file": "uu_17_2008.pdf", "page_start": 1, "page_end": 1, "text": f"Pasal {pasal} ...",
            "section": None, "subsection": None, "status": "amended", "doc_amends": [], "amends_doc": None,
            "amends_pasal": None, "amendment_kind": None, "superseded_by": [], "partially_amended_by": [],
            "may_be_amended_by_out_of_corpus": [], "n_tokens": n_tokens}


# UU 17/2008 Pasal 1 (definitions) spans 7 chunks of ~400 tokens, like uu_17_2008-0002..0008
DEFINITIONS = [_chunk(f"uu_17_2008-000{i}", "1", f"{i}", 400) for i in range(2, 9)]
OTHERS = [
    _chunk("uu_17_2008-0216", "207", None, 300),  # rank 2
    _chunk("uu_17_2008-0217", "209", None, 250),  # rank 3
    _chunk("uu_17_2008-0233", "224", None, 116),  # rank 4: the gold of F05
    _chunk("uu_17_2008-0075", "66", None, 200),   # rank 5
]


def _context(ids: list[str]):
    corpus = Corpus(DEFINITIONS + OTHERS, "sha")
    by_id = corpus.by_id()
    index = VersionIndex(corpus)
    hits = [Hit(c, 1.0, r, "hybrid+rerank", by_id[c]) for r, c in enumerate(ids, start=1)]
    return build_context(hits, index, 8), index


def test_f05_no_hit_is_dropped_when_dropping_cannot_make_room() -> None:
    # rank 1 = Pasal 1 chunk (400); its 6 siblings need 2400 more; the context already holds 1266.
    # Dropping ranks 3-5 frees at most 566: 1266 - 566 + 2400 = 3100 > 2800, so nothing may be dropped
    # (the old rule dropped ranks 5, 4 and 3, including the gold at rank 4, and still cut the siblings).
    ctx, index = _context(["uu_17_2008-0002", "uu_17_2008-0216", "uu_17_2008-0217", "uu_17_2008-0233", "uu_17_2008-0075"])
    result = expand_siblings(ctx, index, max_tokens=2800, priority_hits=2)
    assert result.dropped == []
    ids = [c.chunk_id for c in ctx]
    assert "uu_17_2008-0233" in ids  # the gold stays
    assert {"uu_17_2008-0216", "uu_17_2008-0217", "uu_17_2008-0075"} <= set(ids)
    # siblings are still admitted greedily in ayat order while they fit: 1266 + 3 x 400 = 2466 <= 2800
    assert result.cut == ["uu_17_2008-0006", "uu_17_2008-0007", "uu_17_2008-0008"]


def test_drops_happen_when_they_make_the_priority_chunks_fit() -> None:
    # with a 3500 budget, dropping rank 5 (200) is enough: 1266 - 200 + 2400 = 3466 <= 3500
    ctx, index = _context(["uu_17_2008-0002", "uu_17_2008-0216", "uu_17_2008-0217", "uu_17_2008-0233", "uu_17_2008-0075"])
    result = expand_siblings(ctx, index, max_tokens=3500, priority_hits=2)
    assert result.dropped == ["uu_17_2008-0075"] and result.cut == []
    assert "uu_17_2008-0233" in [c.chunk_id for c in ctx]

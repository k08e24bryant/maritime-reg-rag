"""Per-Pasal revocation lists (PP 31/2021 Pasal 233 style) -> REPEALED labels; labels only."""

from __future__ import annotations

import copy

import pytest

from maritime_rag.answer.versions import (
    CURRENT,
    REPEALED,
    DocNames,
    VersionIndex,
    build_context,
    describe,
    status_short,
)
from maritime_rag.config import load_config, resolve
from maritime_rag.retrieval.corpus import Corpus, Hit, load_corpus
from maritime_rag.revocations import parse_revocations

_DOCS = {"pp_20_2010": ("PP", "20", 2010), "pp_31_2021": ("PP", "31", 2021), "uu_17_2008": ("UU", "17", 2008)}


def _chunk(cid: str, pasal: str, text: str, part: str = "body", ayat: str | None = None) -> dict:
    doc = cid.rsplit("-", 1)[0]
    t, n, y = _DOCS[doc]
    return {"chunk_id": cid, "doc_id": doc, "doc_type": t, "number": n, "year": y, "title": "T", "part": part,
            "pasal": pasal, "ayat": ayat, "heading": f"{doc} > Pasal {pasal}", "source_file": f"{doc}.pdf",
            "page_start": 1, "page_end": 1, "text": text, "section": None, "subsection": None,
            "status": "partially_revoked" if doc == "pp_20_2010" else "in_force",
            "doc_amends": ["pp_20_2010"] if doc == "pp_31_2021" else [], "amends_doc": None, "amends_pasal": None,
            "amendment_kind": None, "superseded_by": [], "partially_amended_by": [],
            "may_be_amended_by_out_of_corpus": [], "n_tokens": 50}


PROVISION = [  # one revocation Pasal split over two chunks, like PP 31/2021 Pasal 233
    _chunk("pp_31_2021-0001", "233", "Pasal 233 (1) Pada saat Peraturan Pemerintah ini mulai berlaku: a. Pasal 7, "
           "Pasal 40 ayat (1), Pasal 43 ayat (1) dan ayat (2), dan Pasal 86 Peraturan Pemerintah Nomor 20 Tahun 2010 "
           "tentang Angkutan di Perairan (Lembaran Negara Tahun 2010 Nomor 26) sebagaimana telah diubah dengan "
           "Peraturan Pemerintah Nomor 22 Tahun 2011 tentang Perubahan;", ayat="1"),
    _chunk("pp_31_2021-0002", "233", "b. Pasal 5 dan Pasal 9 Peraturan Pemerintah Nomor 51 Tahun 2002 tentang "
           "Perkapalan; dicabut dan dinyatakan tidak berlaku. (2) Terhadap pasal yang dicabut sebagaimana dimaksud "
           "pada ayat (1) yang menjadi acuan pada: a. Peraturan Pemerintah Nomor 20 Tahun 2010 ...", ayat="1"),
    _chunk("pp_31_2021-0003", "1", "Pasal 1 Undang-Undang Nomor 17 Tahun 2008 Pasal 3 berlaku."),  # no revoke phrase
]
TARGETS = [
    _chunk("pp_20_2010-0001", "86", "Pasal 86 Kegiatan jasa terkait ..."),
    _chunk("pp_20_2010-0002", "86", "Pasal 86 Yang dimaksud dengan ...", part="penjelasan"),
    _chunk("pp_20_2010-0003", "40", "Pasal 40 (1) ... (2) ..."),
    _chunk("pp_20_2010-0004", "182", "Pasal 182 (1) Perusahaan angkutan di perairan wajib ..."),
    _chunk("uu_17_2008-0001", "3", "Pasal 3 Pelayaran diselenggarakan ..."),
]


@pytest.fixture
def corpus() -> Corpus:
    return Corpus(copy.deepcopy(PROVISION + TARGETS), "sha")


def test_parse_revocation_list(corpus: Corpus) -> None:
    rev = parse_revocations(corpus)
    assert sorted(rev) == [("pp_20_2010", "40"), ("pp_20_2010", "43"), ("pp_20_2010", "7"), ("pp_20_2010", "86")]
    assert rev[("pp_20_2010", "86")].whole and rev[("pp_20_2010", "86")].by_doc == "pp_31_2021"
    assert rev[("pp_20_2010", "86")].provision == "Pasal 233"
    assert rev[("pp_20_2010", "40")].ayat == [1] and rev[("pp_20_2010", "43")].ayat == [1, 2]
    # PP 51/2002 is not in the corpus; "Pasal 3 Undang-Undang 17/2008" is not in a revocation provision
    assert ("uu_17_2008", "3") not in rev


def test_labels_whole_ayat_and_unlisted(corpus: Corpus) -> None:
    index, names = VersionIndex(corpus), DocNames(corpus)
    by_id = corpus.by_id()
    ids = ["pp_20_2010-0001", "pp_20_2010-0002", "pp_20_2010-0003", "pp_20_2010-0004"]
    ctx = build_context([Hit(c, 1.0, r, "hybrid", by_id[c]) for r, c in enumerate(ids, 1)], index, 8)
    whole, penj, ayat, unlisted = ctx
    assert (whole.status, whole.status_by) == (REPEALED, "pp_31_2021") and whole.partly_revoked_by == []
    assert describe(whole, ctx, names, index).startswith("REPEALED by PP 31/2021 (Pasal 233 of PP 31/2021 lists")
    assert penj.status == REPEALED  # the Penjelasan of a revoked Pasal goes with it
    assert ayat.status == CURRENT and ayat.partly_revoked_by == []
    assert "ayat (1) of this Pasal revoked by PP 31/2021 Pasal 233" in describe(ayat, ctx, names, index)
    assert status_short(ayat, names) == "CURRENT (ayat (1) revoked by PP 31/2021)"
    assert unlisted.status == CURRENT and unlisted.partly_revoked_by == ["pp_31_2021"]
    assert "not in its revocation list" in describe(unlisted, ctx, names, index)


CHUNKS = resolve(load_config("configs/retrieval.yaml")["paths"]["chunks_file"])


@pytest.mark.skipif(not CHUNKS.exists(), reason="needs chunks.jsonl (maritime-ingest)")
def test_real_corpus_pp31_pasal_233() -> None:
    corpus = load_corpus(CHUNKS)
    rev = parse_revocations(corpus)
    assert {r.by_doc for r in rev.values()} == {"pp_31_2021"}
    assert sum(r.doc_id == "pp_61_2009" for r in rev.values()) == 43
    assert sum(r.doc_id == "pp_20_2010" for r in rev.values()) == 80
    assert rev[("pp_61_2009", "111")].whole and rev[("pp_61_2009", "122")].whole
    assert rev[("pp_20_2010", "40")].ayat == [1] and rev[("pp_20_2010", "43")].ayat == [1, 2]
    for kept in (("pp_20_2010", "182"), ("pp_20_2010", "185"), ("pp_61_2009", "6"), ("pp_61_2009", "28")):
        assert kept not in rev

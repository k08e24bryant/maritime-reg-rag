from __future__ import annotations

import pytest

from maritime_rag.amendments import link_amendments
from maritime_rag.chunk import Chunk
from maritime_rag.manifest import DocMeta
from maritime_rag.regulation import amendment_kind

DOCS = {
    "base": DocMeta("base", "base.pdf", "Base", "PM", "93", 2013, "amended", (), ""),
    "amd1": DocMeta("amd1", "amd1.pdf", "Amd 1", "PM", "74", 2016, "in_force", ("base",), ""),
    "amd2": DocMeta("amd2", "amd2.pdf", "Amd 2", "PM", "23", 2022, "in_force", ("base",), ""),
}


def _chunk(doc: str, pasal: str, part: str = "body", kind: str | None = None) -> Chunk:
    amending = doc != "base"
    return Chunk(
        chunk_id=f"{doc}-{pasal}-{part}", doc_id=doc, doc_type="PM", title="t", number="1", year=2000,
        status="s", part=part, text="x", heading="h", source_file=f"{doc}.pdf", page_start=1, page_end=1,
        pasal=pasal, amends_doc="base" if amending else None, amends_pasal=pasal if amending else None,
        amendment_kind=kind if amending else None,
    )


@pytest.mark.parametrize(
    ("instruction", "has_text", "expected"),
    [
        ("1. Ketentuan Pasal 5 diubah sehingga berbunyi sebagai berikut:", True, "replace"),
        ("2. Di antara Pasal 7 dan Pasal 8 disisipkan 1 (satu) pasal, yakni Pasal 7A", True, "insert"),
        ("3. Pasal 9 dihapus.", False, "delete"),
        ("4. Ketentuan ayat (2) Pasal 23 dihapus.", False, "partial"),
        ("32. Penjelasan Pasal 195 huruf b diubah menjadi sebagaimana tercantum", False, "penjelasan"),
        ("37. Ketentuan ayat (1) Pasal 223 diubah dan ayat (2) dihapus, sehingga berbunyi:", True, "replace"),
    ],
)
def test_amendment_kind(instruction: str, has_text: bool, expected: str) -> None:
    assert amendment_kind(instruction, has_text) == expected


def test_chain_of_amendments_marks_older_versions() -> None:
    base_71, base_71_pj = _chunk("base", "71"), _chunk("base", "71", "penjelasan")
    amd1_71, amd2_71 = _chunk("amd1", "71", kind="replace"), _chunk("amd2", "71", kind="replace")
    base_9, amd2_9 = _chunk("base", "9"), _chunk("amd2", "9", kind="delete")
    base_23, amd1_23 = _chunk("base", "23"), _chunk("amd1", "23", kind="partial")
    untouched = _chunk("base", "1")
    chunks = [base_71, base_71_pj, amd1_71, amd2_71, base_9, amd2_9, base_23, amd1_23, untouched]

    report = link_amendments(chunks, DOCS, {})

    assert base_71.superseded_by == ["amd1", "amd2"]  # newest last
    assert base_71_pj.superseded_by == ["amd1", "amd2"]
    assert amd1_71.superseded_by == ["amd2"]  # an amendment can itself be superseded
    assert amd2_71.superseded_by == []  # newest version
    assert base_9.superseded_by == ["amd2"]  # repealed
    assert base_23.superseded_by == [] and base_23.partially_amended_by == ["amd1"]
    assert untouched.superseded_by == [] and untouched.partially_amended_by == []
    assert report.targets_not_found == []


def test_insert_of_new_pasal_marks_nothing_and_missing_targets_are_reported() -> None:
    base_7 = _chunk("base", "7")
    inserted = _chunk("amd1", "7A", kind="insert")
    orphan = _chunk("amd1", "40", kind="replace")  # base has no Pasal 40 chunk: parse issue upstream
    report = link_amendments([base_7, inserted, orphan], DOCS, {})
    assert base_7.superseded_by == [] and base_7.partially_amended_by == []
    assert report.targets_not_found == ["amd1 amends base Pasal 40"]


def test_out_of_corpus_flags() -> None:
    body, pj = _chunk("base", "1"), _chunk("base", "2", "penjelasan")
    preamble = _chunk("base", "1", "preamble")
    preamble.pasal = None
    link_amendments([body, pj, preamble], DOCS, {"base": ["UU 11/2020", "UU 6/2023"]})
    assert body.may_be_amended_by_out_of_corpus == ["UU 11/2020", "UU 6/2023"]
    assert pj.may_be_amended_by_out_of_corpus == ["UU 11/2020", "UU 6/2023"]
    assert preamble.may_be_amended_by_out_of_corpus == []

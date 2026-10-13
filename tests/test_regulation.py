from __future__ import annotations

import pytest

from conftest import load_lines
from maritime_rag.cleaning import PageCleaner
from maritime_rag.manifest import DocMeta
from maritime_rag.regulation import RegulationChunker, SourceText, has_amending_structure, segment_parts

CFG = {
    "max_tokens": 400,
    "window_overlap_tokens": 10,
    "drop_trivial_penjelasan": True,
    "trivial_penjelasan_line_pattern": r"^(Cukup\s*je\S{0,8}|Dihapus\S{0,3})$",
}


def _meta(doc_type: str = "UU", amends: tuple[str, ...] = ()) -> DocMeta:
    return DocMeta("x", "x.pdf", "Contoh", doc_type, "99", 2030, "in_force", amends, "")


def _source(name: str, sha: str = "abc123") -> SourceText:
    return SourceText(name, sha, load_lines(name), "born_digital")


@pytest.fixture
def uu_chunks(count_tokens):
    return RegulationChunker(CFG, count_tokens).chunk(_meta(), _source("uu_small.txt"))


def test_segment_parts() -> None:
    lines = load_lines("uu_small.txt")
    parts = segment_parts(lines, allow_roman=False)
    assert lines[parts["body"][0]].text == "BAB I"
    assert lines[parts["body"][1]].text == "Disahkan di Jakarta"
    assert lines[parts["penjelasan"][0]].text == "PENJELASAN"
    assert lines[parts["penjelasan"][1]].text.startswith("TAMBAHAN LEMBARAN")


def test_one_chunk_per_pasal_with_structure(uu_chunks) -> None:
    chunks, report = uu_chunks
    body = [c for c in chunks if c.part == "body"]
    assert [c.pasal for c in body] == ["1", "2", "3", "4", "5"]
    by_pasal = {c.pasal: c for c in body}
    assert (by_pasal["1"].bab, by_pasal["1"].bab_title, by_pasal["1"].bagian) == ("I", "KETENTUAN UMUM", None)
    assert (by_pasal["3"].bab, by_pasal["3"].bagian) == ("II", "Kesatu Angkutan Laut")
    assert by_pasal["4"].text.startswith("Pasal 4\n")  # OCR "Pasa14" normalised
    assert "Pasal 12 dan peraturan" in by_pasal["2"].text  # cross-reference stays inside Pasal 2
    assert (by_pasal["2"].page_start, by_pasal["2"].page_end) == (2, 2)
    assert by_pasal["5"].page_start == 3
    assert report.missing_pasal == {"body": [], "penjelasan": []}


def test_preamble_and_penjelasan(uu_chunks) -> None:
    chunks, report = uu_chunks
    preamble = [c for c in chunks if c.part == "preamble"]
    assert len(preamble) == 1 and "Menimbang" in preamble[0].text and "BAB I" not in preamble[0].text
    pj = [c for c in chunks if c.part == "penjelasan"]
    assert pj[0].section == "Penjelasan Umum"
    # "Cukup jelas." entries (Pasal 1, 3) are dropped; Pasal 2 has real content
    assert [c.pasal for c in pj if c.pasal] == ["2"]
    assert report.dropped_trivial == 2
    assert all("Disahkan" not in c.text for c in chunks)  # signature block dropped


def test_long_pasal_split_by_ayat(count_tokens) -> None:
    cfg = dict(CFG, max_tokens=25)
    chunks, _ = RegulationChunker(cfg, count_tokens).chunk(_meta(), _source("uu_small.txt"))
    pasal2 = [c for c in chunks if c.part == "body" and c.pasal == "2"]
    assert len(pasal2) > 1
    assert [c.ayat for c in pasal2][0].startswith("1")
    assert "ayat (" in pasal2[0].heading


def test_amendment_instructions_attach_to_pasal(count_tokens) -> None:
    meta = _meta("PM", amends=("pm_99_2030",))
    chunks, report = RegulationChunker(CFG, count_tokens).chunk(meta, _source("amendment_small.txt"))
    body = {c.pasal: c for c in chunks if c.part == "body"}
    assert list(body) == ["I", "5", "7A", "9", "12", "II"]
    assert body["5"].text.startswith("1. Ketentuan Pasal 5 diubah")
    assert body["7A"].text.startswith("2 Di antara Pasal 7 dan Pasal 8")
    assert body["9"].text == "3. Pasal 9 dihapus."  # deletion becomes its own chunk
    assert "Pasal 9 dihapus" not in body["7A"].text
    assert report.amending and report.instruction_mismatches == []
    # amendment metadata only inside Pasal I
    assert {p: (c.amends_doc, c.amends_pasal, c.amendment_kind) for p, c in body.items()} == {
        "I": (None, None, None),
        "5": ("pm_99_2030", "5", "replace"),
        "7A": ("pm_99_2030", "7A", "insert"),
        "9": ("pm_99_2030", "9", "delete"),
        "12": ("pm_99_2030", "12", "replace"),
        "II": (None, None, None),
    }


def test_manifest_amends_alone_does_not_make_an_amending_layout(count_tokens) -> None:
    # PP 31/2021 revokes PP 20/2010 in the manifest but is a standalone regulation
    assert not has_amending_structure(load_lines("uu_small.txt"))
    assert has_amending_structure(load_lines("amendment_small.txt"))
    meta = _meta("PP", amends=("pp_old",))
    chunks, report = RegulationChunker(CFG, count_tokens).chunk(meta, _source("uu_small.txt"))
    assert not report.amending and report.missing_pasal["body"] == []
    assert all(c.amends_doc is None for c in chunks)


def test_separate_penjelasan_file(count_tokens) -> None:
    lines = load_lines("uu_small.txt")
    main = SourceText("x.pdf", "aaa", lines[: next(i for i, ln in enumerate(lines) if ln.text == "PENJELASAN")], "born_digital")
    pj_lines = [ln for ln in lines if ln.page == 4]
    pj = SourceText("x_penjelasan.pdf", "bbb", pj_lines, "born_digital")
    chunks, _ = RegulationChunker(CFG, count_tokens).chunk(_meta(), main, pj)
    penjelasan = [c for c in chunks if c.part == "penjelasan"]
    assert [c.pasal for c in penjelasan if c.pasal] == ["2"]
    assert {c.source_file for c in penjelasan} == {"x_penjelasan.pdf"}
    assert {c.source_file for c in chunks if c.part == "body"} == {"x.pdf"}


def test_header_override_pins_and_reports(count_tokens) -> None:
    from maritime_rag.overrides import HeaderOverride

    def override(sha: str, line: str, pasal: str | None) -> HeaderOverride:
        return HeaderOverride("x", sha, "body", 3, line, pasal, "test")

    # "Pasal 5" on page 3 is really Pasal 6; "Pasa14" is not a header at all
    overrides = [override("abc", "Pasal 5", "6"), override("abc", "Pasa14", None), override("abc", "nope", "9")]
    chunks, report = RegulationChunker(CFG, count_tokens).chunk(_meta(), _source("uu_small.txt"), None, overrides)
    assert [c.pasal for c in chunks if c.part == "body"] == ["1", "2", "3", "6"]
    assert [r.status for r in report.overrides] == ["applied", "applied", "unmatched"]
    stale = [override("fff", "Pasal 5", "6")]
    _, report = RegulationChunker(CFG, count_tokens).chunk(_meta(), _source("uu_small.txt"), None, stale)
    assert [r.status for r in report.overrides] == ["stale (file changed)"]


def test_cleaner_drops_running_headers_page_numbers_and_catchwords() -> None:
    cleaner = PageCleaner(
        {
            "edge_lines": 3,
            "running_min_ratio": 0.5,
            "running_min_pages": 2,
            "catchword_max_chars": 60,
            "running_line_patterns": [r"^SK\s*No"],
            "protected_line_patterns": [r"^(Pasal|BAB)\b"],
        }
    )
    pages = [
        ["PRESIDEN", "- 2 -", "Pasal 7", "Teks pasal tujuh.", "14. Terminal", "SK No 123 A"],
        ["PRESIDEN", "-to7-", "14. Terminal adalah fasilitas.", "Pasal 21 . . .", "SK No 124 A"],
        ["PRESIDEN", "- 4 -", "Pasal 21", "Teks."],
    ]
    assert cleaner.clean(pages) == [
        ["Pasal 7", "Teks pasal tujuh."],
        ["14. Terminal adalah fasilitas."],
        ["Pasal 21", "Teks."],
    ]

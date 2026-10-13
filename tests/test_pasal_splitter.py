from __future__ import annotations

import pytest

from conftest import load_lines, word_count
from maritime_rag.cleaning import Line, join_lines
from maritime_rag.pasal_splitter import (
    PasalNum,
    find_ayat_starts,
    parse_pasal_header,
    select_pasal_headers,
    split_pasal,
)


# --- header parsing --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Pasal 1", PasalNum(1)),
        ("Pasal 15A", PasalNum(15, "A")),
        ("Pasal 15 A", PasalNum(15, "A")),
        ("Pasa171", PasalNum(71)),  # "l" of Pasal read as "1"
        ("Pasal 1O0", PasalNum(100)),
        ("Pasal I 1O", PasalNum(110)),
        ("Pasal 1 13", PasalNum(113)),
        ("Fasal 104", PasalNum(104)),
        ("Pas al 226", PasalNum(226)),
        ("Pasal2lT", PasalNum(217)),
        ("Pasal 25L", PasalNum(251)),
    ],
)
def test_parse_header_tolerates_ocr(line: str, expected: PasalNum) -> None:
    assert parse_pasal_header(line) == expected


@pytest.mark.parametrize(
    "line",
    ["Pasal", "Pasal 5 ayat (1)", "Pasal 35 ditetapkan oleh:", "sebagaimana dimaksud dalam Pasal 5", "Pasal 21 . . ."],
)
def test_parse_header_rejects_non_headers(line: str) -> None:
    assert parse_pasal_header(line) is None


def test_roman_headers_only_in_amendments() -> None:
    assert parse_pasal_header("Pasal II", allow_roman=True) == PasalNum(2, is_roman=True)
    assert parse_pasal_header("PasalI", allow_roman=True) == PasalNum(1, is_roman=True)
    assert parse_pasal_header("Pasal I") == PasalNum(1)  # OCR "I" for "1" in ordinary regulations


# --- header selection ------------------------------------------------------------------------


def _labels(lines: list[str], allow_roman: bool = False) -> list[str]:
    sel = select_pasal_headers(lines, allow_roman)
    return [n.label for n in sel.accepted.values()]


def test_cross_reference_after_connector_is_rejected() -> None:
    lines = ["Pasal 1", "diatur sebagaimana dimaksud dalam", "Pasal 7", "ayat (2).", "Pasal 2"]
    sel = select_pasal_headers(lines)
    assert [n.label for n in sel.accepted.values()] == ["1", "2"]
    assert sel.rejected == [(2, "follows an unfinished sentence (cross-reference)")]


def test_out_of_sequence_candidate_is_rejected() -> None:
    lines = ["Pasal 10", "teks.", "Pasal 11", "teks.", "Pasal 3", "teks.", "Pasal 12"]
    sel = select_pasal_headers(lines)
    assert [n.label for n in sel.accepted.values()] == ["10", "11", "12"]
    assert [i for i, _ in sel.rejected] == [4]


def test_duplicate_header_is_repaired_into_gap() -> None:
    # OCR printed "Pasal 15" twice; the second must be 16 because 17 follows
    lines = ["Pasal 14", "a.", "Pasal 15", "b.", "Pasal 15", "c.", "Pasal 17"]
    sel = select_pasal_headers(lines)
    assert [n.label for n in sel.accepted.values()] == ["14", "15", "16", "17"]
    assert sel.repaired == [(4, "Pasal 15 read as Pasal 16")]


def test_inserted_pasal_suffix_misread_as_digit_is_repaired() -> None:
    lines = ["Pasal 26A", "a.", "Pasal 268", "b.", "Pasal 26C"]
    assert _labels(lines) == ["26A", "26B", "26C"]


def test_roman_headers_split_amendment_sequence() -> None:
    lines = ["Pasal I", "x.", "Pasal 71", "x.", "Pasal 72", "x.", "Pasal 5", "x.", "Pasal 80", "x.", "Pasal II"]
    # the stray 5 breaks the increasing sequence within Pasal I and is dropped
    assert _labels(lines, allow_roman=True) == ["I", "71", "72", "80", "II"]


# --- ayat detection --------------------------------------------------------------------------


def test_find_ayat_starts_sequential_with_ocr_variants() -> None:
    lines = [
        "Pasal 3",
        "(1) Angkutan laut dilakukan oleh perusahaan nasional.",
        "l2l Kegiatan angkutan menggunakan kapal",
        "berbendera Indonesia.",
        "(21 Bukan ayat baru karena (2) sudah lewat.",
        "(3) Ketentuan lebih lanjut diatur oleh Menteri.",
    ]
    assert find_ayat_starts(lines) == [(1, 1), (2, 2), (5, 3)]


def test_wrapped_ayat_reference_is_not_a_new_ayat() -> None:
    lines = ["(1) Izin diberikan oleh Menteri.", "Izin sebagaimana dimaksud pada", "(2) huruf a berlaku 5 tahun."]
    assert find_ayat_starts(lines) == [(0, 1)]


def test_penjelasan_ayat_labels() -> None:
    assert find_ayat_starts(["Pasal 2", "Ayat (1)", "Teks.", "Ayat (2)", "Cukup jelas."]) == [(1, 1), (3, 2)]


# --- splitting long Pasal --------------------------------------------------------------------


def _pasal(n_ayat: int, words_per_ayat: int) -> list[Line]:
    lines = [Line("Pasal 9", 1)]
    for k in range(1, n_ayat + 1):
        lines.append(Line(f"({k}) " + " ".join(["kata"] * words_per_ayat), 1 + k // 3))
    return lines


def test_short_pasal_stays_whole(count_tokens) -> None:
    pieces = split_pasal(_pasal(3, 5), count_tokens, max_tokens=100)
    assert len(pieces) == 1 and pieces[0].ayat is None


def test_long_pasal_split_by_ayat_under_cap(count_tokens) -> None:
    lines = _pasal(6, 20)
    pieces = split_pasal(lines, count_tokens, max_tokens=50)
    assert [p.ayat for p in pieces] == ["1-2", "3-4", "5-6"]
    assert all(count_tokens(p.text) <= 50 for p in pieces)
    assert pieces[0].lines[0].text == "Pasal 9"  # header stays with ayat (1)
    assert [ln for p in pieces for ln in p.lines] == lines  # nothing lost or reordered


def test_oversized_ayat_falls_back_to_list_items(count_tokens) -> None:
    lines = [
        Line("Pasal 4", 1),
        Line("(1) Kewajiban perusahaan meliputi:", 1),
        *[Line(f"{c}. " + " ".join(["kata"] * 15) + ";", 1) for c in "abcdef"],
        Line("(2) Ketentuan lebih lanjut diatur dengan Peraturan Menteri.", 2),
    ]
    pieces = split_pasal(lines, count_tokens, max_tokens=40)
    assert all(count_tokens(p.text) <= 40 for p in pieces)
    assert {p.ayat for p in pieces} == {"1", "2"}
    assert [ln for p in pieces for ln in p.lines] == lines


def test_pasal_without_ayat_splits_by_definitions(count_tokens) -> None:
    lines = [Line("Pasal 1", 1), Line("Dalam Peraturan ini yang dimaksud dengan:", 1)]
    lines += [Line(f"{k}. Istilah{k} adalah " + " ".join(["kata"] * 10) + ".", 1) for k in range(1, 9)]
    pieces = split_pasal(lines, count_tokens, max_tokens=40)
    assert len(pieces) > 1 and all(p.ayat is None for p in pieces)
    assert all(count_tokens(p.text) <= 40 for p in pieces)
    assert [ln for p in pieces for ln in p.lines] == lines


def test_join_lines_keeps_list_items_and_merges_wraps() -> None:
    text = join_lines(["(1) Setiap kapal wajib", "memiliki izin.", "a. Undang-", "Undang ini;", "Pasal 5"])
    assert text == "(1) Setiap kapal wajib memiliki izin.\na. Undang-Undang ini;\nPasal 5"


def test_fixture_headers() -> None:
    lines = [ln.text for ln in load_lines("uu_small.txt")]
    body = lines[: lines.index("Disahkan di Jakarta")]
    sel = select_pasal_headers(body)
    assert [n.label for n in sel.accepted.values()] == ["1", "2", "3", "4", "5"]
    assert [body[i] for i, _ in sel.rejected] == ["Pasal 12"]
    assert word_count("a b") == 2

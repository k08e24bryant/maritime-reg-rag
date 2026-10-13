from __future__ import annotations

from maritime_rag.quality import score, word_tokens

WORDS = frozenset({"setiap", "kapal", "wajib", "memiliki", "undang", "pelayaran", "rakyat"})


def test_word_tokens_split_hyphens_and_skip_numbers() -> None:
    tokens = word_tokens(["(1) Setiap kapal wajib; Undang-Undang 2008", "BAB IV pelayaran-rakyat."], min_len=3)
    assert tokens == ["setiap", "kapal", "wajib", "undang", "undang", "bab", "pelayaran", "rakyat"]


def test_ocr_debris_counts_as_unknown() -> None:
    clean = score(["Setiap kapal wajib memiliki"], WORDS, min_len=3)
    noisy = score(["Setiap kapa1 wajib rnemiliki pe}.iyelenggaraan"], WORDS, min_len=3)
    assert clean.hit_rate == 1.0
    assert (noisy.known, noisy.tokens) == (2, 5)


def test_empty_text_scores_zero() -> None:
    assert score([], WORDS, min_len=3).hit_rate == 0.0

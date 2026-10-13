from __future__ import annotations

import re
from pathlib import Path

import pytest

from maritime_rag.cleaning import Line

FIXTURES = Path(__file__).parent / "fixtures"


def load_lines(name: str) -> list[Line]:
    """Read a fixture with <<<PAGE n>>> markers into Lines."""
    lines: list[Line] = []
    page = 1
    for raw in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        if m := re.match(r"<<<PAGE (\d+)>>>", raw):
            page = int(m[1])
        elif raw.strip():
            lines.append(Line(raw.strip(), page))
    return lines


def word_count(text: str) -> int:
    """Deterministic stand-in for the model tokenizer."""
    return len(text.split())


@pytest.fixture
def count_tokens():
    return word_count

"""Chunk record written to chunks.jsonl."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_type: str
    title: str
    number: str | None
    year: int | None
    status: str
    part: str  # preamble | body | penjelasan | lampiran | report
    text: str
    heading: str  # human-readable breadcrumb for citations and embedding context
    page_start: int
    page_end: int
    bab: str | None = None
    bab_title: str | None = None
    bagian: str | None = None
    pasal: str | None = None
    ayat: str | None = None
    section: str | None = None  # report chapter
    subsection: str | None = None  # report sub-heading
    amends: list[str] = field(default_factory=list)
    n_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

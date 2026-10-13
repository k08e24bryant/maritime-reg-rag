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
    text: str  # original document text; context is prepended only at embedding time
    heading: str  # "doc title > BAB > Bagian > Pasal" breadcrumb for citations and embedding context
    source_file: str  # PDF the page numbers refer to (physical, 1-based)
    page_start: int
    page_end: int
    text_layer: str = "born_digital"  # born_digital | ocr_embedded | tesseract_reocr
    bab: str | None = None
    bab_title: str | None = None
    bagian: str | None = None
    pasal: str | None = None
    ayat: str | None = None
    section: str | None = None  # report chapter
    subsection: str | None = None  # report sub-heading
    doc_amends: list[str] = field(default_factory=list)  # manifest-level: documents this one amends/revokes
    # set on chunks inside "Pasal I" of an amending regulation
    amends_doc: str | None = None
    amends_pasal: str | None = None
    amendment_kind: str | None = None  # replace | insert | delete | partial | penjelasan
    # set by the amendment linker on chunks whose Pasal was later amended within the corpus
    superseded_by: list[str] = field(default_factory=list)  # doc_ids, oldest first; last = newest
    partially_amended_by: list[str] = field(default_factory=list)
    may_be_amended_by_out_of_corpus: list[str] = field(default_factory=list)
    n_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

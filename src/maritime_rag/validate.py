"""Check that every manifest PDF exists and has extractable text."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maritime_rag.manifest import DocMeta
from maritime_rag.pdf_text import page_info


@dataclass
class FileValidation:
    doc_id: str
    file: str
    exists: bool
    sha256: str = ""
    n_pages: int = 0
    n_chars: int = 0
    low_text_pages: list[int] = field(default_factory=list)
    ocr_pages: int = 0  # pages whose text comes from an OCR layer over a full-page scan

    @property
    def ok(self) -> bool:
        return self.exists and self.n_chars > 0

    @property
    def text_layer(self) -> str:
        return "ocr_embedded" if self.ocr_pages else "born_digital"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def validate_file(doc_id: str, path: Path, cfg: dict[str, Any]) -> FileValidation:
    if not path.exists():
        return FileValidation(doc_id, path.name, exists=False)
    infos = page_info(path)
    return FileValidation(
        doc_id=doc_id,
        file=path.name,
        exists=True,
        sha256=sha256_file(path),
        n_pages=len(infos),
        n_chars=sum(p.n_chars for p in infos),
        low_text_pages=[p.page for p in infos if p.n_chars < cfg["min_chars_per_page"]],
        ocr_pages=sum(1 for p in infos if p.image_coverage >= cfg["ocr_image_coverage"] and p.n_chars),
    )


def validate(docs: list[DocMeta], raw_dir: Path, cfg: dict[str, Any]) -> tuple[list[FileValidation], list[str]]:
    """Validate every file the manifest references (main PDF and optional Penjelasan PDF)."""
    results = []
    listed = set()
    for meta in docs:
        for file in filter(None, [meta.file, meta.penjelasan_file]):
            listed.add(file)
            results.append(validate_file(meta.doc_id, raw_dir / file, cfg))
    unlisted = sorted(p.name for p in raw_dir.glob("*.pdf") if p.name not in listed)
    return results, unlisted

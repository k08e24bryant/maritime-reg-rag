"""Check that every manifest PDF exists and has extractable text."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maritime_rag.manifest import DocMeta
from maritime_rag.pdf_text import page_info


@dataclass
class DocValidation:
    doc_id: str
    exists: bool
    sha256: str = ""
    n_pages: int = 0
    n_chars: int = 0
    low_text_pages: list[int] = field(default_factory=list)
    ocr_pages: int = 0  # pages whose text comes from an OCR layer over a full-page scan

    @property
    def ok(self) -> bool:
        return self.exists and self.n_chars > 0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def validate(docs: list[DocMeta], raw_dir: Path, cfg: dict[str, Any]) -> tuple[list[DocValidation], list[str]]:
    results = []
    for meta in docs:
        path = raw_dir / meta.file
        if not path.exists():
            results.append(DocValidation(meta.doc_id, exists=False))
            continue
        infos = page_info(path)
        results.append(
            DocValidation(
                doc_id=meta.doc_id,
                exists=True,
                sha256=_sha256(path),
                n_pages=len(infos),
                n_chars=sum(p.n_chars for p in infos),
                low_text_pages=[p.page for p in infos if p.n_chars < cfg["min_chars_per_page"]],
                ocr_pages=sum(1 for p in infos if p.image_coverage >= cfg["ocr_image_coverage"] and p.n_chars),
            )
        )
    listed = {d.file for d in docs}
    unlisted = sorted(p.name for p in raw_dir.glob("*.pdf") if p.name not in listed)
    return results, unlisted

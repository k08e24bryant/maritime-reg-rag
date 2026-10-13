"""Read data/manifest.csv into typed records."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DocMeta:
    doc_id: str
    file: str
    title: str
    doc_type: str  # UU | PP | PM | Report
    number: str | None
    year: int | None
    status: str
    amends: tuple[str, ...]
    source_url: str

    @property
    def is_regulation(self) -> bool:
        return self.doc_type in {"UU", "PP", "PM"}

    @property
    def is_amendment(self) -> bool:
        return bool(self.amends)

    @property
    def citation_name(self) -> str:
        if self.is_regulation:
            return f"{self.doc_type} {self.number}/{self.year}"
        return self.title


def load_manifest(path: Path) -> list[DocMeta]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    docs = []
    for r in rows:
        file = r["file"].strip()
        docs.append(
            DocMeta(
                doc_id=Path(file).stem,
                file=file,
                title=r["title"].strip(),
                doc_type=r["type"].strip(),
                number=r["number"].strip() or None,
                year=int(r["year"]) if r["year"].strip() else None,
                status=r["status"].strip(),
                amends=tuple(a for a in r["amends"].split(";") if a.strip()),
                source_url=r["source_url"].strip(),
            )
        )
    return docs

"""Manual parsing overrides from configs/overrides.yaml.

Overrides fix specific OCR misreads that heuristics should not chase. Each entry is pinned
to the SHA-256 of the file it was written against; when the file changes (e.g. a scan is
replaced by a born-digital copy) the entry is skipped and reported as stale.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from maritime_rag.cleaning import Line
from maritime_rag.pasal_splitter import PasalNum, parse_pasal_header


@dataclass(frozen=True)
class HeaderOverride:
    doc_id: str
    file_sha256: str  # prefix of the SHA-256 of the file the entry was written against
    part: str  # body | penjelasan
    page: int
    line: str  # the extracted line exactly as the pipeline sees it
    pasal: str | None  # forced Pasal label, or None for "not a header"
    reason: str

    @property
    def num(self) -> PasalNum | None:
        return None if self.pasal is None else parse_pasal_header(f"Pasal {self.pasal}")

    def describe(self) -> str:
        target = f"Pasal {self.pasal}" if self.pasal else "not a header"
        return f"{self.doc_id} {self.part} p{self.page}: {self.line!r} -> {target} ({self.reason})"


def load_overrides(path: Path) -> list[HeaderOverride]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        HeaderOverride(
            doc_id=e["doc_id"],
            file_sha256=str(e["file_sha256"]),
            part=e["part"],
            page=int(e["page"]),
            line=e["line"],
            pasal=None if e.get("pasal") is None else str(e["pasal"]),
            reason=e.get("reason", ""),
        )
        for e in data.get("pasal_headers", [])
    ]


@dataclass
class OverrideResult:
    override: HeaderOverride
    status: str  # applied | stale (file changed) | unmatched


def resolve_overrides(
    overrides: list[HeaderOverride], part: str, lines: list[Line], file_sha256: str
) -> tuple[dict[int, PasalNum | None], list[OverrideResult]]:
    """Map overrides for one part onto line indices."""
    forced: dict[int, PasalNum | None] = {}
    results = []
    for o in (o for o in overrides if o.part == part):
        if not file_sha256.startswith(o.file_sha256):
            results.append(OverrideResult(o, "stale (file changed)"))
            continue
        idx = next((i for i, ln in enumerate(lines) if ln.page == o.page and ln.text == o.line), None)
        if idx is None:
            results.append(OverrideResult(o, "unmatched"))
            continue
        forced[idx] = o.num
        results.append(OverrideResult(o, "applied"))
    return forced, results

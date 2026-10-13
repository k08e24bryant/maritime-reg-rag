"""Remove running headers/footers, page numbers, and catchwords; join wrapped lines."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Line:
    text: str
    page: int  # 1-based physical page


PAGE_NUMBER = re.compile(
    r"^[-–—.\s]*(\d{1,3}|[ivxlc]{1,6})[-–—.\s]*$"  # "- 3 -", "4-", "iv"
    r"|^\s*[-–—]\s?\w{1,4}\s?[-–—]\s*$",  # OCR-garbled but dashed: "-to7-", "-t37-"
    re.IGNORECASE,
)
CATCHWORD_DOTS = re.compile(r"(\.\s*){2,}$|…$")
_NON_ALNUM = re.compile(r"[^0-9A-Za-z]+")


def edge_key(line: str) -> str:
    """Normalize a line so running headers match across pages ("2013, No.1523 4" -> "#no#")."""
    return re.sub(r"[\W\d_]+", "#", line.lower())


_CONFUSABLES = str.maketrans({"o": "0", "l": "1", "i": "1", "s": "5"})


def _alnum(s: str) -> str:
    """Comparable form of a line, folding OCR confusables ("16O" == "160")."""
    return _NON_ALNUM.sub("", s).lower().translate(_CONFUSABLES)


class PageCleaner:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.edge_lines: int = cfg["edge_lines"]
        self.min_ratio: float = cfg["running_min_ratio"]
        self.min_pages: int = cfg["running_min_pages"]
        self.catchword_max: int = cfg["catchword_max_chars"]
        self.running_patterns = [re.compile(p, re.IGNORECASE) for p in cfg["running_line_patterns"]]
        self.protected = [re.compile(p) for p in cfg["protected_line_patterns"]]

    def _is_protected(self, line: str) -> bool:
        return any(p.search(line) for p in self.protected)

    def _running_keys(self, pages: list[list[str]]) -> set[str]:
        counts: Counter[str] = Counter()
        for lines in pages:
            edges = lines[: self.edge_lines] + lines[-self.edge_lines :]
            counts.update({edge_key(ln) for ln in edges if not self._is_protected(ln)})
        threshold = max(self.min_pages, self.min_ratio * len(pages))
        return {k for k, n in counts.items() if n >= threshold and k.strip("#")}

    def _is_running(self, line: str, keys: set[str]) -> bool:
        if self._is_protected(line):
            return False
        return (
            edge_key(line) in keys
            or bool(PAGE_NUMBER.match(line))
            or any(p.search(line) for p in self.running_patterns)
        )

    def clean(self, pages: list[list[str]]) -> list[list[str]]:
        pages = [[ln.strip() for ln in lines if re.search(r"[0-9A-Za-z]", ln)] for lines in pages]
        keys = self._running_keys(pages)
        out: list[list[str]] = []
        for lines in pages:
            lines = list(lines)
            for _ in range(self.edge_lines):
                if lines and self._is_running(lines[0], keys):
                    lines.pop(0)
            for _ in range(self.edge_lines):
                if lines and self._is_running(lines[-1], keys):
                    lines.pop()
            out.append(lines)
        return self._drop_catchwords(out)

    def _is_dotted_catchword(self, line: str) -> bool:
        return len(line) <= self.catchword_max and len(line.split()) <= 6 and bool(CATCHWORD_DOTS.search(line))

    def _drop_catchwords(self, pages: list[list[str]]) -> list[list[str]]:
        """Drop continuation markers ("Pasal 21 . . .", "14. Terminal").

        Dotted markers are dropped anywhere (some PDFs keep stale ones mid-page); undotted ones
        only at a page bottom when the next page starts with the same words.
        """
        pages = [[ln for ln in lines if not self._is_dotted_catchword(ln)] for lines in pages]
        for i, lines in enumerate(pages):
            if not lines:
                continue
            last = lines[-1]
            if len(last) > self.catchword_max:
                continue
            nxt = next((p for p in pages[i + 1 :] if p), None)
            first = next((ln for ln in nxt or [] if not PAGE_NUMBER.match(ln)), "")
            stem = _alnum(last)
            if len(stem) >= 3 and _alnum(first).startswith(stem):
                lines.pop()
        return pages


def flatten(pages: list[list[str]]) -> list[Line]:
    return [Line(text, pno) for pno, lines in enumerate(pages, start=1) for text in lines]


LIST_ITEM = re.compile(
    r"^(\(\s*\w{1,3}\s*\)|[a-z]\.|\d{1,3}\s?\.|[a-z]\)|\d{1,3}\))\s"
    r"|^[(\[{lI|]\s?\d{1,2}\s?[)\]}lI1|]\s"  # OCR'd ayat markers: "(21", "l2l"
)
# A line ending like this continues on the next line ("... sebagaimana dimaksud dalam" / "Pasal 12").
CONNECTOR_END = re.compile(
    r"(\b(dalam|dan|atau|pada|dengan|dimaksud|oleh|ke|di|sesuai|berdasarkan|terhadap|ayat|huruf|angka)|,)$",
    re.IGNORECASE,
)
HEADER_LIKE = re.compile(
    r"^([PF]\s?a\s?s\s?a\s?[l1I!|]\s*\S{1,5}|(BAB|Bagian|Paragraf|Huruf|Angka)\s+\S+|Ayat\s*\S{1,5})$"
)


def join_lines(lines: list[str]) -> str:
    """Merge visually wrapped lines; keep list items and headers on their own line."""
    out: list[str] = []
    for ln in lines:
        ln = re.sub(r"\s+", " ", ln).strip()
        if not ln:
            continue
        continues = bool(out) and CONNECTOR_END.search(out[-1]) is not None
        starts_new = not out or (
            not continues and (LIST_ITEM.match(ln) or HEADER_LIKE.match(ln) or HEADER_LIKE.match(out[-1]))
        )
        if starts_new:
            out.append(ln)
        elif out[-1].endswith("-") and not out[-1].endswith(" -"):
            out[-1] += ln  # "Undang-" + "Undang"
        else:
            out[-1] += " " + ln
    return "\n".join(out)

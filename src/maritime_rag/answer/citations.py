"""Citation post-check: parse [doc, Pasal X ayat Y, p. N] citations and map them to context chunks.

A citation is valid when one provided context chunk matches its document, Pasal (Penjelasan if
stated), ayat (when the chunk records an ayat range) and page (overlap with page_start-page_end).
Report chunks (UNCTAD) match on document and page. Brackets may hold several citations
separated by ";". Brackets that name no document, Pasal or page (e.g. "[sic]") are not citations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from maritime_rag.answer.versions import ContextChunk, DocNames

_BRACKET = re.compile(r"\[([^\[\]]+)\]")
_REG_DOC = re.compile(
    r"\b(UU|PP|PM|Permenhub|Peraturan Menteri Perhubungan)\s*(?:No(?:mor)?\.?\s*)?(\d+)\s*(?:/|Tahun|of)\s*(\d{4})",
    re.IGNORECASE,
)
_REPORT_DOC = re.compile(r"\bUNCTAD\b|Review of Maritime Transport", re.IGNORECASE)
_PASAL = re.compile(r"\bPasal\s+(\d+\s*[A-Za-z]?|[IVX]+)\b", re.IGNORECASE)
_AYAT = re.compile(r"\bayat\s+(.+?)(?=,|;|\bpp?\.|\bhlm\b|\bhal\b|\bpages?\b|$)", re.IGNORECASE)
# "p." needs its dot, so "PP 31/2021" is not read as page 31
_PAGE = re.compile(r"\b(?:pp?\.|hlm\.?|hal\.?|halaman|pages?)\s*(\d+)(?:\s*[-–]\s*(\d+))?", re.IGNORECASE)
_RANGE_WORD = re.compile(r"-|–|sampai|s\.d\.?|\bto\b|hingga", re.IGNORECASE)
_TYPE_ALIASES = {"permenhub": "PM", "peraturan menteri perhubungan": "PM"}


@dataclass
class Citation:
    raw: str  # one citation, e.g. "PM 74/2016, Pasal 71 ayat (2), p. 11"
    bracket: tuple[int, int]  # span of the enclosing [...] in the answer text
    doc_id: str | None
    pasal: str | None
    ayat: list[int]
    penjelasan: bool
    pages: tuple[int, int] | None
    source: int | None = None  # 1-based index into the context when valid
    problem: str | None = None

    @property
    def valid(self) -> bool:
        return self.source is not None


class DocMatcher:
    """Resolves the document named in a citation to a doc_id."""

    def __init__(self, names: DocNames) -> None:
        self.by_key: dict[tuple[str, int, int], str] = {}
        self.reports: list[str] = []
        for doc_id, name in names.names.items():
            if m := _REG_DOC.search(name):
                self.by_key[(_doc_type(m[1]), int(m[2]), int(m[3]))] = doc_id
            else:
                self.reports.append(doc_id)

    def __call__(self, text: str) -> tuple[str | None, bool]:
        """(doc_id, a document was named at all)."""
        if m := _REG_DOC.search(text):
            return self.by_key.get((_doc_type(m[1]), int(m[2]), int(m[3]))), True
        if _REPORT_DOC.search(text):
            return (self.reports[0] if len(self.reports) == 1 else None), True
        return None, False


def _doc_type(t: str) -> str:
    return _TYPE_ALIASES.get(t.lower(), t.upper())


def _ayat_numbers(text: str) -> list[int]:
    m = _AYAT.search(text)
    if not m:
        return []
    nums = [int(n) for n in re.findall(r"\d+", m[1])]
    if len(nums) == 2 and _RANGE_WORD.search(m[1]) and nums[0] < nums[1]:
        return list(range(nums[0], nums[1] + 1))
    return nums


def parse_citations(text: str, match_doc: DocMatcher) -> list[Citation]:
    out: list[Citation] = []
    for b in _BRACKET.finditer(text):
        for part in b[1].split(";"):
            raw = part.strip()
            doc_id, named = match_doc(raw)
            pasal_m, page_m = _PASAL.search(raw), _PAGE.search(raw)
            if not (named or pasal_m or page_m):
                continue
            pages = None
            if page_m:
                start = int(page_m[1])
                pages = (start, int(page_m[2]) if page_m[2] else start)
            out.append(Citation(
                raw=raw,
                bracket=b.span(),
                doc_id=doc_id,
                pasal=re.sub(r"\s+", "", pasal_m[1]).upper() if pasal_m else None,
                ayat=_ayat_numbers(raw),
                penjelasan=bool(re.search(r"\bpenjelasan\b", raw, re.IGNORECASE)),
                pages=pages,
            ))
    return out


def _ayat_range(chunk: dict) -> set[int] | None:
    """Ayat numbers a chunk covers ("1-8" -> 1..8); None when the chunk is a whole Pasal."""
    ayat = chunk.get("ayat")
    if not ayat:
        return None
    nums = [int(n) for n in re.findall(r"\d+", ayat)]
    return set(range(nums[0], nums[-1] + 1)) if nums else None


def validate(citations: list[Citation], context: list[ContextChunk], require_page: bool) -> None:
    """Sets .source (1-based context index) or .problem on each citation."""
    for cit in citations:
        cit.source, cit.problem = _match(cit, context, require_page)


def _match(cit: Citation, context: list[ContextChunk], require_page: bool) -> tuple[int | None, str | None]:
    if cit.doc_id is None:
        return None, "document not recognised"
    cands = [(i, cc.chunk) for i, cc in enumerate(context, start=1) if cc.chunk["doc_id"] == cit.doc_id]
    if not cands:
        return None, "document not among the provided sources"
    if cands[0][1]["part"] != "report":
        cands = [(i, c) for i, c in cands if (c.get("pasal") or "").upper() == (cit.pasal or "")]
        if not cands:
            return None, f"Pasal {cit.pasal or '?'} not among the provided sources of this document"
        same_part = [(i, c) for i, c in cands if (c["part"] == "penjelasan") == cit.penjelasan]
        if cit.penjelasan or same_part:  # "Penjelasan" must match; a plain Pasal may fall back
            cands = same_part
        if not cands:
            return None, "Penjelasan not among the provided sources"
        if cit.ayat:
            cands = [(i, c) for i, c in cands if (r := _ayat_range(c)) is None or set(cit.ayat) <= r]
            if not cands:
                return None, f"ayat {cit.ayat} not in the provided chunk(s)"
    if cit.pages is None:
        return (None, "no page") if require_page else (cands[0][0], None)
    lo, hi = cit.pages
    paged = [(i, c) for i, c in cands if lo <= c["page_end"] and hi >= c["page_start"]]
    if not paged:
        return None, f"page {lo if lo == hi else f'{lo}-{hi}'} does not match the source pages"
    return paged[0][0], None


def rewrite(text: str, citations: list[Citation], mode: str, marker: str) -> str:
    """Rebuild each bracket that holds an invalid citation: flag = replace it with the
    unverified marker, drop = remove it. Brackets with only valid citations are unchanged."""
    by_bracket: dict[tuple[int, int], list[Citation]] = {}
    for c in citations:
        by_bracket.setdefault(c.bracket, []).append(c)
    out, last = [], 0
    for (start, end), cits in sorted(by_bracket.items()):
        if all(c.valid for c in cits):
            continue
        valid = [c.raw for c in cits if c.valid]
        keep = f"[{'; '.join(valid)}]" if valid else ""
        flags = "".join(marker.format(cite=c.raw) for c in cits if not c.valid) if mode == "flag" else ""
        out += [text[last:start], keep + flags]
        last = end
    out.append(text[last:])
    result = "".join(out)
    return re.sub(r"[ \t]+([.,;:])", r"\1", re.sub(r"[ \t]{2,}", " ", result)) if mode == "drop" else result

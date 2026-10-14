"""Citation post-check: parse citations in an answer and map them to the provided context chunks.

The expected form is "[doc, Pasal X ayat Y, p. N]"; brackets may hold several citations
separated by ";", and brackets that name no document, Pasal or page (e.g. "[sic]") are ignored.
Models also write citations without brackets, e.g. "(PM 93/2013, Pasal 69 ayat 2)" or
"PM 93/2013 Pasal 69 ayat (2)" (document first, then Pasal); those are parsed too.

A citation is valid when it maps to one provided chunk: document, Pasal (Penjelasan if stated),
ayat (when the chunk records an ayat range) and page (overlap with page_start-page_end). Report
chunks (UNCTAD) match on document and page. A citation without a page is accepted only when it
maps unambiguously to one chunk; its page is then filled from that chunk. Valid citations that
were not in the standard form are rewritten as "[doc, Pasal X ayat (Y), p. N]" and record what
was normalized. Citations that do not map to a provided source stay invalid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from maritime_rag.answer.versions import ContextChunk, DocNames, citation_locator, page_label

_BRACKET = re.compile(r"\[([^\[\]]+)\]")
_DOC = r"\b(?:UU|PP|PM|Permenhub|Peraturan Menteri Perhubungan)\s*(?:No(?:mor)?\.?\s*)?\d+\s*(?:/|Tahun|of)\s*\d{4}"
_REG_DOC = re.compile(
    r"\b(UU|PP|PM|Permenhub|Peraturan Menteri Perhubungan)\s*(?:No(?:mor)?\.?\s*)?(\d+)\s*(?:/|Tahun|of)\s*(\d{4})",
    re.IGNORECASE,
)
_REPORT_DOC = re.compile(r"\bUNCTAD\b|Review of Maritime Transport", re.IGNORECASE)
_PASAL = re.compile(r"\bPasal\s+(\d+\s?[A-Za-z]?|[IVX]+)\b", re.IGNORECASE)
_AYAT = re.compile(r"\bayat\s+(.+?)(?=,|;|\bpp?\.|\bhlm\b|\bhal\b|\bpages?\b|$)", re.IGNORECASE)
_PASAL_PAREN_AYAT = re.compile(r"\bPasal\s+\w+\s*\((\d+)[a-z]?\)", re.IGNORECASE)  # "Pasal 8(2)"
# "p." needs its dot, so "PP 31/2021" is not read as page 31
_PAGE = re.compile(r"\b(?:pp?\.|hlm\.?|hal\.?|halaman|pages?)\s*(\d+)(?:\s*[-‐-–]\s*(\d+))?", re.IGNORECASE)
# hyphen, non-breaking hyphen (gpt-oss writes "ayat 1‑2"), figure dash, en dash
_RANGE_WORD = re.compile(r"[-‐-–]|sampai|s\.d\.?|\bto\b|hingga", re.IGNORECASE)
_TYPE_ALIASES = {"permenhub": "PM", "peraturan menteri perhubungan": "PM"}
# some models (gpt-oss) write citations in lenticular or full-width brackets: 【...】, ［...］
_BRACKET_FORMS = str.maketrans({"【": "[", "】": "]", "［": "[", "］": "]"})

# An unbracketed citation: document first, then (Penjelasan) Pasal, optional ayat and page,
# optionally wrapped in parentheses. "Pasal 71 PM 93/2013" (Pasal first) is prose, not a citation.
_AYAT_NUM = r"\(?\s*\d+\s*[a-z]?\s*\)?"
_INNER = (
    _DOC + r"(?:\s*,\s*|\s+)(?:Penjelasan\s+)?Pasal\s+(?:\d+\s?[A-Z]?|[IVX]+)\b"
    r"(?:\s*\(\d+[a-z]?\))?"
    r"(?:\s*,?\s*ayat\s*" + _AYAT_NUM + r"(?:\s*(?:[-‐-–,]|dan|sampai|s\.d\.?|hingga)\s*" + _AYAT_NUM + r")*)?"
    r"(?:\s*,?\s*(?:pp?\.|hlm\.?|hal\.?|halaman)\s*\d+(?:\s*[-‐-–]\s*\d+)?)?"
)
_UNBRACKETED = re.compile(r"\(\s*(" + _INNER + r")\s*\)|(" + _INNER + r")", re.IGNORECASE)


def normalize_brackets(text: str) -> str:
    """Rewrite 【...】 and ［...］ citations as [...] so they are parsed and checked like the rest."""
    return text.translate(_BRACKET_FORMS)


@dataclass
class Citation:
    raw: str  # one citation as written, e.g. "PM 74/2016, Pasal 71 ayat (2), p. 11"
    span: tuple[int, int]  # in the answer text: the enclosing [...], or the unbracketed citation
    doc_id: str | None
    pasal: str | None
    ayat: list[int]
    penjelasan: bool
    pages: tuple[int, int] | None
    source: int | None = None  # 1-based index into the context when valid
    problem: str | None = None  # why it is invalid
    flag: str | None = None  # valid, but suspicious (e.g. the cited ayat is not in the chunk text)
    bracketed: bool = True
    normalized: list[str] = field(default_factory=list)  # e.g. ["no brackets", "page filled from source"]
    canonical: str | None = None  # standard form, set when the citation was normalized

    @property
    def valid(self) -> bool:
        return self.source is not None


class DocMatcher:
    """Resolves the document named in a citation to a doc_id."""

    def __init__(self, names: DocNames) -> None:
        self.names = names
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
        paren = _PASAL_PAREN_AYAT.search(text)
        return [int(paren[1])] if paren else []
    nums = [int(n) for n in re.findall(r"\d+", m[1])]
    if len(nums) == 2 and _RANGE_WORD.search(m[1]) and nums[0] < nums[1]:
        return list(range(nums[0], nums[1] + 1))
    return nums


def _parse_one(raw: str, span: tuple[int, int], bracketed: bool, match_doc: DocMatcher) -> Citation | None:
    doc_id, named = match_doc(raw)
    pasal_m, page_m = _PASAL.search(raw), _PAGE.search(raw)
    if not (named or pasal_m or page_m):
        return None
    pages = None
    if page_m:
        start = int(page_m[1])
        pages = (start, int(page_m[2]) if page_m[2] else start)
    return Citation(
        raw=raw,
        span=span,
        doc_id=doc_id,
        pasal=re.sub(r"\s+", "", pasal_m[1]).upper() if pasal_m else None,
        ayat=_ayat_numbers(raw),
        penjelasan=bool(re.search(r"\bpenjelasan\b", raw, re.IGNORECASE)),
        pages=pages,
        bracketed=bracketed,
    )


def parse_citations(text: str, match_doc: DocMatcher) -> list[Citation]:
    """Bracketed citations first; then unbracketed ones in the text outside any [...]."""
    out: list[Citation] = []
    masked = list(text)
    for b in _BRACKET.finditer(text):
        for part in b[1].split(";"):
            if cit := _parse_one(part.strip(), b.span(), True, match_doc):
                out.append(cit)
        masked[b.start():b.end()] = " " * (b.end() - b.start())
    for m in _UNBRACKETED.finditer("".join(masked)):
        raw = (m[1] or m[2]).strip()
        if cit := _parse_one(raw, m.span(), False, match_doc):
            out.append(cit)
    return sorted(out, key=lambda c: c.span)


def _ayat_range(chunk: dict) -> set[int] | None:
    """Ayat numbers a chunk covers ("1-8" -> 1..8); None when the chunk is a whole Pasal."""
    ayat = chunk.get("ayat")
    if not ayat:
        return None
    nums = [int(n) for n in re.findall(r"\d+", ayat)]
    return set(range(nums[0], nums[-1] + 1)) if nums else None


def ayat_in_text(ayat: int, text: str) -> bool:
    """"(4)" or "(4a)" appears in the chunk text."""
    return re.search(rf"\(\s*{ayat}\s*[a-z]?\s*\)", text) is not None


def _ayat_label(ayat: list[int]) -> str:
    if not ayat:
        return ""
    if len(ayat) > 1 and ayat == list(range(ayat[0], ayat[-1] + 1)):
        return f" ayat ({ayat[0]})-({ayat[-1]})"
    return " ayat " + ", ".join(f"({n})" for n in ayat)


def canonical_form(cit: Citation, chunk: dict, names: DocNames) -> str:
    """'[PM 93/2013, Pasal 69 ayat (2), p. 44]': the cited page if given, else the chunk's pages."""
    if cit.pages is not None:
        lo, hi = cit.pages
        page = f"p. {lo}" if lo == hi else f"p. {lo}-{hi}"
    else:
        page = page_label(chunk)
    where = citation_locator(chunk) + ("" if chunk["part"] == "report" else _ayat_label(cit.ayat))
    return f"[{names(chunk['doc_id'])}, {where}, {page}]"


def validate(
    citations: list[Citation], context: list[ContextChunk], fill_missing_page: bool = True,
    names: DocNames | None = None,
) -> None:
    """Sets .source (1-based context index) or .problem on each citation; .flag when a cited ayat
    number does not appear in the matched chunk's text; .normalized/.canonical (needs `names`)
    when a valid citation had no brackets or no page."""
    for cit in citations:
        cit.source, cit.problem = _match(cit, context, fill_missing_page)
        if cit.source is None:
            continue
        chunk = context[cit.source - 1].chunk
        if cit.ayat:
            missing = [n for n in cit.ayat if not ayat_in_text(n, chunk["text"])]
            if missing:
                cit.flag = f"ayat {', '.join(f'({n})' for n in missing)} not found in the cited text"
        if not cit.bracketed:
            cit.normalized.append("no brackets")
        if cit.pages is None:
            cit.normalized.append(f"page filled from source ({page_label(chunk)})")
        if cit.normalized and names is not None:
            cit.canonical = canonical_form(cit, chunk, names)


def _match(cit: Citation, context: list[ContextChunk], fill_missing_page: bool) -> tuple[int | None, str | None]:
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
    # prefer the chunk whose text contains the cited ayat (siblings share Pasal and pages)
    if cit.ayat:
        cands = [(i, c) for i, c in cands if all(ayat_in_text(n, c["text"]) for n in cit.ayat)] or cands
    if cit.pages is None:
        if not fill_missing_page:
            return None, "no page"
        if len(cands) > 1:
            return None, f"no page, and it matches {len(cands)} provided chunks (ambiguous)"
        return cands[0][0], None
    lo, hi = cit.pages
    paged = [(i, c) for i, c in cands if lo <= c["page_end"] and hi >= c["page_start"]]
    if not paged:
        return None, f"page {lo if lo == hi else f'{lo}-{hi}'} does not match the source pages"
    return paged[0][0], None


def rewrite(text: str, citations: list[Citation], mode: str, marker: str) -> str:
    """Rebuild every citation span that holds an invalid or normalized citation.

    Valid normalized citations become their canonical "[doc, Pasal X ayat (Y), p. N]" form.
    Invalid ones: flag = add the unverified marker, drop = remove a bracketed one (unbracketed
    prose is kept). Spans with only valid, standard citations are unchanged."""
    by_span: dict[tuple[int, int], list[Citation]] = {}
    for c in citations:
        by_span.setdefault(c.span, []).append(c)
    out, last = [], 0
    for (start, end), cits in sorted(by_span.items()):
        if all(c.valid and not c.canonical for c in cits):
            continue
        flags = "".join(marker.format(cite=c.raw) for c in cits if not c.valid) if mode == "flag" else ""
        if cits[0].bracketed:
            valid = [(c.canonical or f"[{c.raw}]")[1:-1] for c in cits if c.valid]
            new = (f"[{'; '.join(valid)}]" if valid else "") + flags
        else:
            c = cits[0]
            new = c.canonical if c.valid and c.canonical else text[start:end] + flags
        out += [text[last:start], new]
        last = end
    out.append(text[last:])
    result = "".join(out)
    return re.sub(r"[ \t]+([.,;:])", r"\1", re.sub(r"[ \t]{2,}", " ", result)) if mode == "drop" else result

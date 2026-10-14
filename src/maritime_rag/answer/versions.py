"""Version expansion: turn retrieved hits into labelled context chunks.

The corpus has no consolidated text, so an amended Pasal exists as the base chunk plus the
amending chunks (amends_doc, amends_pasal, amendment_kind). For each retrieved chunk this adds
the chunks needed to read it correctly, even when retrieval did not return them:
  superseded_by[-1]      the newest wording (or the repeal) of the Pasal, placed before the hit
  partially_amended_by   the amending chunks that changed some ayat/huruf or the Penjelasan
  amending chunk         for an insert/partial amendment: the base Pasal it amends (still in force);
                         for a "Penjelasan Pasal X diubah" instruction: the new Penjelasan text
Each context chunk gets a status: CURRENT, SUPERSEDED (by <doc>) or REPEALED (by <doc>).
Documents marked partially_revoked in the manifest (PP 20/2010, PP 61/2009 by PP 31/2021) have
no per-Pasal links, so their chunks stay CURRENT with a note that the Pasal may be revoked.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from maritime_rag.retrieval.corpus import Chunk, Corpus, Hit

CURRENT, SUPERSEDED, REPEALED = "CURRENT", "SUPERSEDED", "REPEALED"


class DocNames:
    """Citation names: "PM 74/2016", "UU 17/2008", or a configured short name (UNCTAD RMT 2025)."""

    def __init__(self, corpus: Corpus, short_names: dict[str, str] | None = None) -> None:
        self.names: dict[str, str] = {}
        self.titles: dict[str, str] = {}
        for c in corpus.chunks:
            if c["doc_id"] not in self.names:
                default = f"{c['doc_type']} {c['number']}/{c['year']}" if c.get("number") else c["title"]
                self.names[c["doc_id"]] = (short_names or {}).get(c["doc_id"], default)
                self.titles[c["doc_id"]] = c["title"]

    def __call__(self, doc_id: str) -> str:
        return self.names.get(doc_id, doc_id)


def page_label(chunk: Chunk) -> str:
    s, e = chunk["page_start"], chunk["page_end"]
    return f"p. {s}" if s == e else f"p. {s}-{e}"


def citation_locator(chunk: Chunk) -> str:
    """The middle part of a citation: "Pasal 71", "Penjelasan Pasal 5", a report section, ..."""
    if chunk["part"] == "report":
        return chunk.get("section") or "Overview"
    prefix = "Penjelasan " if chunk["part"] == "penjelasan" else ""
    if chunk.get("pasal"):
        return f"{prefix}Pasal {chunk['pasal']}"
    if chunk["part"] == "penjelasan":
        return "Penjelasan Umum"
    if chunk["part"] in {"preamble", "lampiran"}:
        return {"preamble": "Pembukaan", "lampiran": "Lampiran"}[chunk["part"]]
    return chunk["heading"].rsplit(" > ", 1)[-1]


def cite_as(chunk: Chunk, names: DocNames) -> str:
    return f"[{names(chunk['doc_id'])}, {citation_locator(chunk)}, {page_label(chunk)}]"


class VersionIndex:
    """Lookups from a Pasal to the chunks that amend it, and back."""

    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        # (amending doc, base doc, pasal) -> amending chunks (body instructions and new Penjelasan)
        self.amending: dict[tuple[str, str, str], list[Chunk]] = defaultdict(list)
        # (base doc, pasal) -> the base document's own chunks
        self.base: dict[tuple[str, str], list[Chunk]] = defaultdict(list)
        for c in corpus.chunks:
            if c.get("amends_doc") and c.get("amends_pasal"):
                self.amending[(c["doc_id"], c["amends_doc"], c["amends_pasal"])].append(c)
            elif c.get("pasal") and c["part"] in {"body", "penjelasan"}:
                self.base[(c["doc_id"], c["pasal"])].append(c)
        # partially revoked doc -> the docs that revoke parts of it (manifest `amends`, no Pasal links)
        self.revoked_by: dict[str, list[str]] = defaultdict(list)
        partly_revoked = {c["doc_id"] for c in corpus.chunks if c.get("status") == "partially_revoked"}
        for c in corpus.chunks:
            for target in c.get("doc_amends") or []:
                if target in partly_revoked and c["doc_id"] not in self.revoked_by[target]:
                    self.revoked_by[target].append(c["doc_id"])

    def changes_by(self, chunk: Chunk, doc: str) -> list[Chunk]:
        """Chunks of `doc` that amend this chunk's Pasal, matching its part where possible.

        A Penjelasan chunk gets the amending doc's new Penjelasan for that Pasal; without one it
        gets the body amendment (new wording or repeal). A body chunk gets body amendments, not
        "Penjelasan Pasal X diubah" instructions."""
        base = chunk.get("amends_doc") or chunk["doc_id"]
        cands = self.amending.get((doc, base, chunk["pasal"]), [])
        body = [c for c in cands if c["part"] == "body" and c.get("amendment_kind") != "penjelasan"]
        if chunk["part"] == "penjelasan":
            return [c for c in cands if c["part"] == "penjelasan"] or body
        return body

    def is_repealed(self, chunk: Chunk) -> bool:
        newest = chunk["superseded_by"][-1] if chunk.get("superseded_by") else None
        return newest is not None and any(c.get("amendment_kind") == "delete" for c in self.changes_by(chunk, newest))

    def newer(self, chunk: Chunk) -> list[Chunk]:
        """Chunks to show before this one: its newest wording, repeal, or partial changes."""
        out: list[Chunk] = []
        if chunk.get("superseded_by"):
            out += self.changes_by(chunk, chunk["superseded_by"][-1])
        for doc in chunk.get("partially_amended_by") or []:
            out += self.changes_by(chunk, doc)
        if chunk.get("amendment_kind") == "penjelasan":  # "Penjelasan Pasal X diubah ..." -> the new text
            key = (chunk["doc_id"], chunk["amends_doc"], chunk["amends_pasal"])
            out += [c for c in self.amending.get(key, []) if c["part"] == "penjelasan"]
        return out

    def amended_base(self, chunk: Chunk) -> list[Chunk]:
        """For an amending chunk: base chunks it changed only partly (they stay in force)."""
        if not chunk.get("amends_doc"):
            return []
        part = "penjelasan" if chunk["part"] == "penjelasan" else "body"
        return [
            c for c in self.base.get((chunk["amends_doc"], chunk["amends_pasal"]), [])
            if c["part"] == part and chunk["doc_id"] in (c.get("partially_amended_by") or [])
        ]


@dataclass
class ContextChunk:
    chunk: Chunk
    status: str  # CURRENT | SUPERSEDED | REPEALED
    status_by: str | None = None  # doc_id of the newest amending doc for SUPERSEDED / REPEALED
    retrieved_rank: int | None = None  # None = added by version expansion
    score: float | None = None
    related: list[str] = field(default_factory=list)  # chunk_ids of the other versions in the context

    @property
    def chunk_id(self) -> str:
        return self.chunk["chunk_id"]

    partly_revoked_by: list[str] = field(default_factory=list)  # doc-level revocation, Pasal unknown

    @property
    def out_of_corpus(self) -> list[str]:
        return list(self.chunk.get("may_be_amended_by_out_of_corpus") or [])


def status_of(chunk: Chunk, index: VersionIndex) -> tuple[str, str | None]:
    if chunk.get("superseded_by"):
        return (REPEALED if index.is_repealed(chunk) else SUPERSEDED), chunk["superseded_by"][-1]
    return CURRENT, None


def build_context(hits: list[Hit], index: VersionIndex, max_added: int) -> list[ContextChunk]:
    """Retrieved hits in rank order, each preceded by its newer versions and followed by the
    partly amended base Pasal it belongs to. Chunks appear once; expansion adds at most max_added."""
    out: list[ContextChunk] = []
    pos: dict[str, ContextChunk] = {}
    added = 0

    def place(chunk: Chunk, hit: Hit | None) -> None:
        nonlocal added
        cid = chunk["chunk_id"]
        if cid in pos:
            if hit is not None and pos[cid].retrieved_rank is None:  # expanded earlier, retrieved too
                pos[cid].retrieved_rank, pos[cid].score = hit.rank, hit.score
            return
        if hit is None:
            if added >= max_added:
                return
            added += 1
        status, by = status_of(chunk, index)
        cc = ContextChunk(chunk, status, by, hit.rank if hit else None, hit.score if hit else None,
                          partly_revoked_by=list(index.revoked_by.get(chunk["doc_id"], [])))
        pos[cid] = cc
        for newer in index.newer(chunk):
            place(newer, None)
            _link(cc, pos.get(newer["chunk_id"]))
        out.append(cc)
        for base in index.amended_base(chunk):
            place(base, None)
            _link(cc, pos.get(base["chunk_id"]))

    for hit in hits:
        place(hit.chunk, hit)
    return out


def _link(a: ContextChunk, b: ContextChunk | None) -> None:
    if b is None or a is b:
        return
    if b.chunk_id not in a.related:
        a.related.append(b.chunk_id)
    if a.chunk_id not in b.related:
        b.related.append(a.chunk_id)


def describe(cc: ContextChunk, context: list[ContextChunk], names: DocNames, index: VersionIndex) -> str:
    """Status line for the prompt and the source list, e.g.
    "SUPERSEDED by PM 74/2016 (current wording: SOURCE 1)"."""
    number = {c.chunk_id: i for i, c in enumerate(context, start=1)}
    c = cc.chunk
    refs = [r for r in cc.related if r in number]

    def sources(ids: list[str]) -> str:
        return ", ".join(f"SOURCE {number[i]}" for i in ids)

    if cc.status in {SUPERSEDED, REPEALED}:
        by = names(cc.status_by or "")
        newer = [r for r in refs if _is_newer(context[number[r] - 1].chunk, c)]
        tail = f" ({'see' if cc.status == REPEALED else 'current wording:'} {sources(newer)})" if newer else ""
        return f"{cc.status} by {by}{tail}; do not present this text as current law"
    notes = []
    if c.get("amends_doc"):
        base = f"{names(c['amends_doc'])} Pasal {c['amends_pasal']}"
        kind = c.get("amendment_kind")
        if kind == "delete":
            notes.append(f"repeals {base}")
        elif kind == "insert" and (c["amends_doc"], c["amends_pasal"]) not in index.base:
            notes.append(f"Pasal {c['amends_pasal']} inserted into {names(c['amends_doc'])} by {names(c['doc_id'])}")
        elif kind == "penjelasan":
            notes.append(f"instruction amending the Penjelasan of {base}")
        elif c["part"] == "penjelasan":
            notes.append(f"new Penjelasan of {base}, set by {names(c['doc_id'])}")
        else:
            notes.append(f"wording of {base} as amended by {names(c['doc_id'])}")
        older = [r for r in refs if not _is_newer(context[number[r] - 1].chunk, c)]
        if older:
            notes.append(f"amends {sources(older)}")
    if c.get("partially_amended_by"):
        newer = [r for r in refs if _is_newer(context[number[r] - 1].chunk, c)]
        by = ", ".join(names(d) for d in c["partially_amended_by"])
        where = f" ({sources(newer)} prevails where they differ)" if newer else ""
        notes.append(f"partly amended by {by}{where}")
    if cc.partly_revoked_by:
        by = ", ".join(names(d) for d in cc.partly_revoked_by)
        notes.append(f"{names(c['doc_id'])} was partly revoked by {by} (not linked per Pasal): this Pasal may no longer apply")
    if cc.out_of_corpus:
        notes.append(f"may also have been amended by {', '.join(cc.out_of_corpus)} (not in the documents)")
    return CURRENT + (f": {'; '.join(notes)}" if notes else "")


def _is_newer(a: Chunk, b: Chunk) -> bool:
    """a amends b's Pasal (a newer version of it)."""
    return bool(a.get("amends_doc")) and (
        not b.get("amends_doc") or (a["year"], _num(a)) > (b["year"], _num(b))
    )


def _num(c: Chunk) -> int:
    n = c.get("number") or ""
    return int(n) if str(n).isdigit() else 0


def status_short(cc: ContextChunk, names: DocNames) -> str:
    """One-word status for source lists: CURRENT, SUPERSEDED by PM 74/2016, REPEALED by ..."""
    if cc.status == CURRENT:
        if cc.chunk.get("partially_amended_by"):
            return f"{CURRENT} (partly amended)"
        if cc.partly_revoked_by:
            return f"{CURRENT}? (document partly revoked by {', '.join(names(d) for d in cc.partly_revoked_by)})"
        return CURRENT
    return f"{cc.status} by {names(cc.status_by or '')}"

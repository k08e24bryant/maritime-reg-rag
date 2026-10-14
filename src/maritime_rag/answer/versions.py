"""Version expansion: turn retrieved hits into labelled context chunks.

The corpus has no consolidated text, so an amended Pasal exists as the base chunk plus the
amending chunks (amends_doc, amends_pasal, amendment_kind). For each retrieved chunk this adds
the chunks needed to read it correctly, even when retrieval did not return them:
  superseded_by[-1]      the newest wording (or the repeal) of the Pasal, placed before the hit
  partially_amended_by   the amending chunks that changed some ayat/huruf or the Penjelasan
  amending chunk         for an insert/partial amendment: the base Pasal it amends (still in force);
                         for a "Penjelasan Pasal X diubah" instruction: the new Penjelasan text
Each context chunk gets a status: CURRENT, SUPERSEDED (by <doc>) or REPEALED (by <doc>).
Sibling expansion: a long Pasal is split into several chunks (by ayat). When any of them is in
the context, the others (same doc, Pasal, part) are added in ayat order, within a per-question
token budget; siblings that do not fit are reported as cut. A Penjelasan chunk also brings in
the body of its Pasal (docs/eval_plan.md, post-hoc change 1).
Per-Pasal revocations listed in a closing provision (PP 31/2021 Pasal 233 revokes listed Pasal of
PP 20/2010 and PP 61/2009; see maritime_rag.revocations) make those Pasal REPEALED, or add an
"ayat (n) revoked" note when only some ayat are listed. Other Pasal of a document marked
partially_revoked in the manifest keep a note that the Pasal may no longer apply.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field

from maritime_rag.retrieval.corpus import Chunk, Corpus, Hit
from maritime_rag.revocations import Revocation, parse_revocations

log = logging.getLogger(__name__)

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
        self.position = {c["chunk_id"]: i for i, c in enumerate(corpus.chunks)}
        # (doc, pasal, part, amends_doc) -> all chunks of that Pasal (a long Pasal is split by ayat)
        self.siblings: dict[tuple, list[Chunk]] = defaultdict(list)
        for c in corpus.chunks:
            if (key := sibling_key(c)) is not None:
                self.siblings[key].append(c)
        # (amending doc, base doc, pasal) -> amending chunks (body instructions and new Penjelasan)
        self.amending: dict[tuple[str, str, str], list[Chunk]] = defaultdict(list)
        # (base doc, pasal) -> the base document's own chunks
        self.base: dict[tuple[str, str], list[Chunk]] = defaultdict(list)
        for c in corpus.chunks:
            if c.get("amends_doc") and c.get("amends_pasal"):
                self.amending[(c["doc_id"], c["amends_doc"], c["amends_pasal"])].append(c)
            elif c.get("pasal") and c["part"] in {"body", "penjelasan"}:
                self.base[(c["doc_id"], c["pasal"])].append(c)
        # (doc, Pasal) -> revocation listed in a closing provision (labels only)
        self.revocations: dict[tuple[str, str], Revocation] = parse_revocations(corpus)
        # partially revoked doc -> the docs that revoke parts of it (manifest `amends`)
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

    def revocation(self, chunk: Chunk) -> Revocation | None:
        if not chunk.get("pasal") or chunk["part"] not in {"body", "penjelasan"} or chunk.get("amends_doc"):
            return None
        return self.revocations.get((chunk["doc_id"], chunk["pasal"]))

    def doc_level_revokers(self, chunk: Chunk) -> list[str]:
        """Revoking docs for the generic "may no longer apply" note: only for Pasal not listed."""
        if self.revocation(chunk) is not None:
            return []
        return list(self.revoked_by.get(chunk["doc_id"], []))

    def ayat_order(self, chunk: Chunk) -> tuple[int, int]:
        m = re.match(r"\d+", chunk.get("ayat") or "")
        return (int(m[0]) if m else 0, self.position.get(chunk["chunk_id"], 0))

    def amended_base(self, chunk: Chunk) -> list[Chunk]:
        """For an amending chunk: base chunks it changed only partly (they stay in force)."""
        if not chunk.get("amends_doc"):
            return []
        part = "penjelasan" if chunk["part"] == "penjelasan" else "body"
        return [
            c for c in self.base.get((chunk["amends_doc"], chunk["amends_pasal"]), [])
            if c["part"] == part and chunk["doc_id"] in (c.get("partially_amended_by") or [])
        ]


def sibling_key(chunk: Chunk) -> tuple | None:
    if not chunk.get("pasal"):
        return None
    return (chunk["doc_id"], chunk["pasal"], chunk["part"], chunk.get("amends_doc"))


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

    partly_revoked_by: list[str] = field(default_factory=list)  # doc-level revocation, Pasal not listed
    revocation: Revocation | None = None  # this Pasal (or some of its ayat) is listed as revoked
    added_by: str | None = None  # None = retrieved; "version" | "sibling" | "body" = added by expansion

    @property
    def out_of_corpus(self) -> list[str]:
        return list(self.chunk.get("may_be_amended_by_out_of_corpus") or [])


def status_of(chunk: Chunk, index: VersionIndex) -> tuple[str, str | None]:
    if chunk.get("superseded_by"):
        return (REPEALED if index.is_repealed(chunk) else SUPERSEDED), chunk["superseded_by"][-1]
    rev = index.revocation(chunk)
    if rev is not None and rev.whole:
        return REPEALED, rev.by_doc
    return CURRENT, None


def new_context_chunk(chunk: Chunk, index: VersionIndex, **kw) -> ContextChunk:
    status, by = status_of(chunk, index)
    return ContextChunk(chunk, status, by, partly_revoked_by=index.doc_level_revokers(chunk),
                        revocation=index.revocation(chunk), **kw)


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
                pos[cid].retrieved_rank, pos[cid].score, pos[cid].added_by = hit.rank, hit.score, None
            return
        if hit is None:
            if added >= max_added:
                return
            added += 1
        cc = new_context_chunk(chunk, index, retrieved_rank=hit.rank if hit else None,
                               score=hit.score if hit else None, added_by=None if hit else "version")
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


def chunk_tokens(chunk: Chunk) -> int:
    return int(chunk.get("n_tokens") or 0)


@dataclass
class SiblingExpansion:
    cut: list[str] = field(default_factory=list)  # siblings left out by the token budget
    dropped: list[str] = field(default_factory=list)  # low-ranked retrieved hits removed to fit the top Pasal


def body_key(chunk: Chunk) -> tuple | None:
    """For a Penjelasan chunk: the key of its Pasal's body chunks (same doc, Pasal, amends_doc)."""
    if chunk["part"] != "penjelasan" or not chunk.get("pasal"):
        return None
    return (chunk["doc_id"], chunk["pasal"], "body", chunk.get("amends_doc"))


def expand_siblings(
    context: list[ContextChunk], index: VersionIndex, max_tokens: int, priority_hits: int = 2
) -> SiblingExpansion:
    """Group the chunks of each Pasal together in ayat order and add the missing ones while the
    context stays within max_tokens (chunk n_tokens). Mutates `context`.

    A Penjelasan chunk also brings in the body chunk(s) of its Pasal, placed before it (a
    Penjelasan alone rarely holds the rule itself). Same budget and priority as siblings.
    Same-Pasal chunks of the top `priority_hits` retrieved hits come first; to fit them, the
    lowest-ranked retrieved hits below that (without linked versions) may be dropped, which is
    logged. Same-Pasal chunks of other hits are added only while the budget allows."""
    result = SiblingExpansion()
    present = {cc.chunk_id: cc for cc in context}
    used = sum(chunk_tokens(cc.chunk) for cc in context)
    retrieved = sorted((cc for cc in context if cc.retrieved_rank is not None), key=lambda c: c.retrieved_rank or 0)
    top = retrieved[:priority_hits]
    added_by: dict[str, str] = {}

    def groups(chunk: Chunk) -> list[tuple[tuple, bool]]:
        """(key, is_body_of_penjelasan) for the chunk's own Pasal part and, for a Penjelasan, its body."""
        out = []
        if (bk := body_key(chunk)) is not None and index.siblings.get(bk):
            out.append((bk, True))
        if (sk := sibling_key(chunk)) is not None:
            out.append((sk, False))
        return out

    def missing(key: tuple, body: bool) -> list[Chunk]:
        group = index.siblings.get(key, [])
        if len(group) < 2 and not body:  # a single chunk has no siblings; a body is wanted even alone
            return []
        out = [s for s in sorted(group, key=index.ayat_order) if s["chunk_id"] not in present]
        for s in out:
            added_by.setdefault(s["chunk_id"], "body" if body else "sibling")
        return out

    top_keys = [k for cc in top for k, _ in groups(cc.chunk)]
    admitted: set[str] = set()
    decided: set[str] = set()
    need = list({s["chunk_id"]: s for cc in top for k, body in groups(cc.chunk) for s in missing(k, body)}.values())
    need_tokens = sum(chunk_tokens(s) for s in need)
    if used + need_tokens > max_tokens:
        top_ids = {cc.chunk_id for cc in top}
        for cc in reversed(retrieved):
            if used + need_tokens <= max_tokens:
                break
            if cc.chunk_id in top_ids or sibling_key(cc.chunk) in top_keys or cc.related:
                continue
            context.remove(cc)
            del present[cc.chunk_id]
            used -= chunk_tokens(cc.chunk)
            result.dropped.append(cc.chunk_id)
            log.warning("dropped retrieved hit #%d %s (%d tokens) to fit the rest of the top-%d Pasal",
                        cc.retrieved_rank, cc.chunk_id, chunk_tokens(cc.chunk), priority_hits)

    def admit(sibs: list[Chunk]) -> None:
        nonlocal used
        for s in sibs:
            sid = s["chunk_id"]
            if sid in decided:
                continue
            decided.add(sid)
            if used + chunk_tokens(s) <= max_tokens:
                used += chunk_tokens(s)
                admitted.add(sid)
            else:
                result.cut.append(sid)

    admit(need)
    for cc in list(context):
        for k, body in groups(cc.chunk):
            admit(missing(k, body))

    out: list[ContextChunk] = []
    emitted: set[str] = set()
    for cc in context:
        if cc.chunk_id in emitted:
            continue
        for key, _ in groups(cc.chunk) or [(None, False)]:
            group = index.siblings.get(key, []) if key else []
            members = [s for s in sorted(group, key=index.ayat_order)
                       if s["chunk_id"] in present or s["chunk_id"] in admitted]
            for sib in members or [cc.chunk]:
                sid = sib["chunk_id"]
                if sid in emitted or (sid not in present and sid not in admitted and sid != cc.chunk_id):
                    continue
                if sid not in present:
                    new = new_context_chunk(sib, index, added_by=added_by.get(sid, "sibling"))
                    for other in index.newer(sib) + index.amended_base(sib):
                        _link(new, present.get(other["chunk_id"]))
                    present[sid] = new
                out.append(present[sid])
                emitted.add(sid)
        if cc.chunk_id not in emitted:
            out.append(cc)
            emitted.add(cc.chunk_id)
    context[:] = out
    if result.cut:
        log.warning("token budget (%d) cut %d same-Pasal chunk(s) of retrieved Pasal: %s",
                    max_tokens, len(result.cut), ", ".join(result.cut))
    return result


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

    if cc.status == REPEALED and cc.revocation is not None:
        return (f"REPEALED by {names(cc.status_by or '')} ({cc.revocation.provision} of {names(cc.status_by or '')} "
                "lists this Pasal as revoked); do not present this text as current law")
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
    if cc.revocation is not None and cc.revocation.ayat:
        rev = cc.revocation
        ayat = ", ".join(f"({n})" for n in rev.ayat)
        notes.append(f"ayat {ayat} of this Pasal revoked by {names(rev.by_doc)} {rev.provision}; the other ayat remain")
    if cc.partly_revoked_by:
        by = ", ".join(names(d) for d in cc.partly_revoked_by)
        notes.append(f"{names(c['doc_id'])} was partly revoked by {by}; this Pasal is not in its revocation list, "
                     "but may still be affected")
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
        if cc.revocation is not None and cc.revocation.ayat:
            return f"{CURRENT} (ayat {', '.join(f'({n})' for n in cc.revocation.ayat)} revoked by {names(cc.revocation.by_doc)})"
        if cc.partly_revoked_by:
            return f"{CURRENT}? (document partly revoked by {', '.join(names(d) for d in cc.partly_revoked_by)})"
        return CURRENT
    return f"{cc.status} by {names(cc.status_by or '')}"

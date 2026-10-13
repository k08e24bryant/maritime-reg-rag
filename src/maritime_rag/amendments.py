"""Link amended Pasal to the chunks that amend them (no consolidated text is built).

An amending chunk (amends_doc, amends_pasal, amendment_kind) affects every older chunk about
the same Pasal of the same base document: the base document's own chunk and earlier
amendments of it. The linker records, on the older chunks,
  superseded_by          replace / delete: newer wording (or repeal) exists in the corpus
  partially_amended_by   partial: an ayat/huruf was changed or deleted, or an insert landed
                         in an existing Pasal; penjelasan: the Penjelasan was changed
At answer time the newest version is shown and older ones are labelled "superseded by <doc>".
Amendments by documents outside the corpus are flagged from config.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from maritime_rag.chunk import Chunk
from maritime_rag.manifest import DocMeta


@dataclass
class AmendmentReport:
    amending_chunks: dict[str, dict[str, int]] = field(default_factory=dict)  # doc -> kind -> count
    linked: dict[str, int] = field(default_factory=dict)  # amending doc -> older chunks marked
    targets_not_found: list[str] = field(default_factory=list)
    out_of_corpus_flagged: dict[str, int] = field(default_factory=dict)


def _order(meta: DocMeta) -> tuple[int, int]:
    return (meta.year or 0, int(meta.number) if meta.number and meta.number.isdigit() else 0)


def _base_key(c: Chunk) -> tuple[str, str] | None:
    if c.pasal is None or c.part not in {"body", "penjelasan"}:
        return None
    if c.amends_doc:
        return (c.amends_doc, c.pasal)
    if c.amends_pasal is None and c.pasal[0].isdigit():
        return (c.doc_id, c.pasal)
    return None


def link_amendments(
    chunks: list[Chunk], docs: dict[str, DocMeta], out_of_corpus: dict[str, list[str]]
) -> AmendmentReport:
    report = AmendmentReport()
    # amending body chunks, grouped by the Pasal they amend
    amenders: dict[tuple[str, str], list[Chunk]] = defaultdict(list)
    for c in chunks:
        if c.amendment_kind and c.amends_doc and c.part == "body":
            amenders[(c.amends_doc, c.pasal)].append(c)
            kinds = report.amending_chunks.setdefault(c.doc_id, {})
            kinds[c.amendment_kind] = kinds.get(c.amendment_kind, 0) + 1

    existing = {k for c in chunks if c.amends_doc is None and (k := _base_key(c))}
    for key, amending in amenders.items():
        if key not in existing and all(a.amendment_kind != "insert" for a in amending):
            report.targets_not_found.append(f"{amending[0].doc_id} amends {key[0]} Pasal {key[1]}")

    for c in chunks:
        key = _base_key(c)
        if key is None or key not in amenders:
            continue
        own = _order(docs[c.doc_id])
        newer = sorted(
            {a.doc_id for a in amenders[key] if _order(docs[a.doc_id]) > own}, key=lambda d: _order(docs[d])
        )
        for doc_id in newer:
            kinds = {a.amendment_kind for a in amenders[key] if a.doc_id == doc_id}
            if kinds & {"replace", "delete"}:
                c.superseded_by.append(doc_id)
            elif kinds & {"partial", "insert"} or ("penjelasan" in kinds and c.part == "penjelasan"):
                c.partially_amended_by.append(doc_id)
            else:
                continue
            report.linked[doc_id] = report.linked.get(doc_id, 0) + 1

    for c in chunks:
        if c.doc_id in out_of_corpus and c.part in {"body", "penjelasan"}:
            c.may_be_amended_by_out_of_corpus = list(out_of_corpus[c.doc_id])
            report.out_of_corpus_flagged[c.doc_id] = report.out_of_corpus_flagged.get(c.doc_id, 0) + 1
    return report

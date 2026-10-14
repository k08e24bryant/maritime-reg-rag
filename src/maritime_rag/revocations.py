"""Per-Pasal revocations: "Pasal X, Pasal Y, ... <regulation> ... dicabut dan dinyatakan tidak berlaku".

Closing provisions can revoke individual Pasal of an older regulation, e.g. PP 31/2021 Pasal 233
ayat (1) lists the Pasal of PP 20/2010 and PP 61/2009 that are revoked. This module reads those
lists from the corpus at load time (labels only: chunks.jsonl, chunk ids and text are untouched).
A provision is a Pasal whose text (all its chunks joined) says "dicabut dan dinyatakan tidak
berlaku"; inside it, every run of "Pasal N[ ayat (n)]" references directly followed by a
regulation citation that resolves to a corpus document becomes a revocation of those Pasal.
References to regulations outside the corpus are ignored.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from maritime_rag.retrieval.corpus import Chunk, Corpus

_REVOKE = re.compile(r"dicabut\s+dan\s+dinyatakan\s+tidak\s+berlaku", re.IGNORECASE)
_CITATION = re.compile(
    r"\b(Undang-Undang|Peraturan Pemerintah|Peraturan Menteri Perhubungan)\s+(?:Republik Indonesia\s+)?"
    r"Nomor\s+(?:PM\s+|KM\.?\s+)?(\d+)\s+Tahun\s+(\d{4})",
    re.IGNORECASE,
)
_TYPES = {"undang-undang": "UU", "peraturan pemerintah": "PP", "peraturan menteri perhubungan": "PM"}
# one "Pasal 40 ayat (1)" / "Pasal 43 ayat (1) dan ayat (2)" reference
_PASAL_REF = re.compile(
    r"Pasal\s+(\d+[A-Z]?)((?:\s*(?:,|dan)?\s*ayat\s*\(\s*\d+[a-z]?\s*\))*)", re.IGNORECASE
)
# a list of references that ends right where the regulation citation starts
_LIST_TAIL = re.compile(r"((?:Pasal\s+\d+[A-Z]?(?:\s*(?:,|dan)?\s*ayat\s*\(\s*\d+[a-z]?\s*\))*\s*(?:,|dan|,\s*dan)?\s*)+)$",
                        re.IGNORECASE)


@dataclass
class Revocation:
    doc_id: str  # the revoked regulation (in the corpus)
    pasal: str
    by_doc: str  # the revoking regulation
    provision: str  # e.g. "Pasal 233"
    ayat: list[int] = field(default_factory=list)  # empty = the whole Pasal is revoked

    @property
    def whole(self) -> bool:
        return not self.ayat


def _doc_keys(corpus: Corpus) -> dict[tuple[str, int, int], str]:
    keys = {}
    for c in corpus.chunks:
        if c.get("number") and str(c["number"]).isdigit():
            keys[(c["doc_type"], int(c["number"]), int(c["year"]))] = c["doc_id"]
    return keys


def parse_revocations(corpus: Corpus) -> dict[tuple[str, str], Revocation]:
    """(revoked doc_id, Pasal) -> Revocation. Ayat-level entries merge into one Revocation."""
    docs = _doc_keys(corpus)
    pasal_text: dict[tuple[str, str], list[Chunk]] = defaultdict(list)
    for c in corpus.chunks:
        if c["part"] == "body" and c.get("pasal"):
            pasal_text[(c["doc_id"], c["pasal"])].append(c)
    out: dict[tuple[str, str], Revocation] = {}
    for (doc_id, pasal), chunks in pasal_text.items():
        text = " ".join(" ".join(c["text"].split()) for c in chunks)
        if not _REVOKE.search(text):
            continue
        for m in _CITATION.finditer(text):
            target = docs.get((_TYPES[m[1].lower()], int(m[2]), int(m[3])))
            if target is None or target == doc_id:
                continue
            tail = _LIST_TAIL.search(text[:m.start()].rstrip())
            if not tail:
                continue
            for ref in _PASAL_REF.finditer(tail[1]):
                ayat = [int(a) for a in re.findall(r"\(\s*(\d+)", ref[2] or "")]
                key = (target, ref[1].upper())
                prev = out.get(key)
                if prev is None:
                    out[key] = Revocation(target, ref[1].upper(), doc_id, f"Pasal {pasal}", ayat)
                elif prev.ayat and ayat:
                    prev.ayat = sorted(set(prev.ayat) | set(ayat))
                elif prev.ayat and not ayat:
                    prev.ayat = []  # listed once whole: the whole Pasal is revoked
    return out

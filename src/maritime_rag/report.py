"""Chunk the UNCTAD Review of Maritime Transport by section heading with a token cap and overlap.

Headings are recognised by font size: chapter titles (>= h1_min_size, e.g. "1. International
maritime trade") and bold sub-headings (>= h2_min_size). Content before the first chapter
heading (cover, copyright, contents) is skipped.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from maritime_rag.chunk import Chunk
from maritime_rag.cleaning import PAGE_NUMBER, Line, edge_key
from maritime_rag.manifest import DocMeta
from maritime_rag.pasal_splitter import TokenCounter, window_lines
from maritime_rag.pdf_text import Block


@dataclass
class Section:
    title: str
    subsection: str | None
    lines: list[Line] = field(default_factory=list)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _paragraph(text: str) -> str:
    """Join a block's wrapped lines, keeping hyphenated compounds ("Net-" + "zero")."""
    out = ""
    for ln in text.splitlines():
        ln = ln.strip()
        if not out:
            out = ln
        elif out.endswith("-"):
            out += ln
        else:
            out += " " + ln
    return out


class ReportChunker:
    def __init__(self, cfg: dict[str, Any], count_tokens: TokenCounter) -> None:
        self.cfg = cfg
        self.count_tokens = count_tokens

    def _running_keys(self, pages: list[list[Block]]) -> set[str]:
        counts: Counter[str] = Counter()
        for blocks in pages:
            counts.update({edge_key(b.text) for b in blocks[:2] + blocks[-2:]})
        nonempty = sum(1 for b in pages if b)
        return {k for k, n in counts.items() if n >= max(3, 0.3 * nonempty) and k.strip("#")}

    def _is_noise(self, block: Block) -> bool:
        text = _flat(block.text)
        letters = sum(c.isalpha() for c in text)
        return (
            letters < self.cfg["min_alpha_ratio"] * max(len(text.replace(" ", "")), 1)
            or len(text.split()) < self.cfg["min_words"]
        )

    def sections(self, pages: list[list[Block]]) -> list[Section]:
        running = self._running_keys(pages)
        h1, h2 = self.cfg["h1_min_size"], self.cfg["h2_min_size"]
        sections: list[Section] = []
        number_prefix = ""  # the large "1." printed above a chapter title
        for blocks in pages:
            for b in blocks:
                text = _flat(b.text)
                if edge_key(b.text) in running or PAGE_NUMBER.match(text):
                    continue
                if b.size >= h1:
                    if re.fullmatch(r"\d+\.", text):
                        number_prefix = text + " "
                        continue
                    if sections and sections[-1].subsection is None and not sections[-1].lines:
                        sections[-1].title += " " + text  # chapter title wrapped into two blocks
                    else:
                        sections.append(Section(number_prefix + text, None))
                    number_prefix = ""
                    continue
                if not sections:
                    continue  # front matter
                if b.size >= h2 and b.bold:
                    cur = sections[-1]
                    if cur.lines or cur.subsection is not None:
                        sections.append(Section(cur.title, text))
                    else:
                        cur.subsection = text
                    continue
                if self._is_noise(b):
                    continue
                sections[-1].lines.append(Line(_paragraph(b.text), b.page))
        return [s for s in sections if s.lines]

    def chunk(self, meta: DocMeta, pages: list[list[Block]]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for sec in self.sections(pages):
            header_tokens = self.count_tokens(sec.subsection or "")
            windows = window_lines(
                sec.lines, self.count_tokens, self.cfg["max_tokens"] - header_tokens, self.cfg["overlap_tokens"]
            )
            for w in windows:
                body = "\n".join(ln.text for ln in w)
                text = f"{sec.subsection}\n{body}" if sec.subsection else body
                crumbs = [meta.title, sec.title] + ([sec.subsection] if sec.subsection else [])
                chunks.append(
                    Chunk(
                        chunk_id=f"{meta.doc_id}-{len(chunks):04d}",
                        doc_id=meta.doc_id,
                        doc_type=meta.doc_type,
                        title=meta.title,
                        number=meta.number,
                        year=meta.year,
                        status=meta.status,
                        part="report",
                        text=text,
                        heading=" > ".join(crumbs),
                        source_file=meta.file,
                        page_start=w[0].page,
                        page_end=w[-1].page,
                        section=sec.title,
                        subsection=sec.subsection,
                        n_tokens=self.count_tokens(text),
                    )
                )
        return chunks

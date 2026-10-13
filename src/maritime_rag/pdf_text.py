"""PDF text extraction with PyMuPDF.

Regulations are mostly scans with an OCR text layer whose native reading order is often
broken (one word per line, columns out of order), so lines are rebuilt from word boxes.
The UNCTAD report is born-digital with a sidebar layout, so it is read as font-aware blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass(frozen=True)
class Block:
    text: str
    page: int  # 1-based physical page
    size: float  # max font size in the block
    bold: bool
    x0: float
    y0: float


@dataclass(frozen=True)
class PageInfo:
    page: int
    n_chars: int
    image_coverage: float  # largest image area / page area


def _rebuild_lines(page: pymupdf.Page) -> list[str]:
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, wno)
    if not words:
        return []
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines: list[list[tuple]] = []
    cur: list[tuple] = []
    cur_y = cur_h = 0.0
    for w in words:
        yc, h = (w[1] + w[3]) / 2, w[3] - w[1]
        if cur and abs(yc - cur_y) <= 0.5 * min(h, cur_h):
            cur.append(w)
            continue
        if cur:
            lines.append(cur)
        cur, cur_y, cur_h = [w], yc, h
    lines.append(cur)
    return [" ".join(w[4] for w in sorted(line, key=lambda w: w[0])) for line in lines]


def extract_lines(path: Path) -> list[list[str]]:
    """Return text lines per page, rebuilt from word positions."""
    with pymupdf.open(path) as doc:
        return [_rebuild_lines(page) for page in doc]


def extract_blocks(path: Path, skip_pages: set[int] | None = None) -> list[list[Block]]:
    """Return text blocks per page with font size and boldness."""
    skip_pages = skip_pages or set()
    pages: list[list[Block]] = []
    with pymupdf.open(path) as doc:
        for pno, page in enumerate(doc, start=1):
            blocks: list[Block] = []
            if pno not in skip_pages:
                for b in page.get_text("dict", sort=True)["blocks"]:
                    if b["type"] != 0:
                        continue
                    line_texts = []
                    spans = []
                    for line in b["lines"]:
                        s_text = "".join(s["text"] for s in line["spans"]).strip()
                        if s_text:
                            line_texts.append(s_text)
                        spans.extend(s for s in line["spans"] if s["text"].strip())
                    if not spans:
                        continue
                    blocks.append(
                        Block(
                            text="\n".join(line_texts),
                            page=pno,
                            size=max(s["size"] for s in spans),
                            bold=all("Bd" in s["font"] or "Bold" in s["font"] for s in spans),
                            x0=b["bbox"][0],
                            y0=b["bbox"][1],
                        )
                    )
            pages.append(blocks)
    return pages


def page_info(path: Path) -> list[PageInfo]:
    infos = []
    with pymupdf.open(path) as doc:
        for pno, page in enumerate(doc, start=1):
            area = abs(page.rect) or 1.0
            cover = 0.0
            for img in page.get_images(full=True):
                for rect in page.get_image_rects(img[0]):
                    cover = max(cover, abs(rect & page.rect) / area)
            infos.append(PageInfo(pno, len(page.get_text().strip()), cover))
    return infos

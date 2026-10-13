"""Re-OCR scanned PDFs with Tesseract and cache the result as a searchable PDF.

Each page is rendered at the configured dpi (grayscale), OCR'd by the tesseract CLI into a
one-page image+text PDF, and the pages are merged. Page count and order match the source,
so physical page numbers used in citations stay valid. The cache is keyed by the source
SHA-256 and OCR settings (sidecar JSON) and rebuilt only when either changes.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pymupdf

from maritime_rag.config import resolve
from maritime_rag.validate import sha256_file


def _tesseract_version(cmd: str) -> str:
    out = subprocess.run([cmd, "--version"], capture_output=True, text=True, check=True)
    return (out.stdout or out.stderr).splitlines()[0].strip()


def _settings(src: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_sha256": sha256_file(src),
        "lang": cfg["lang"],
        "dpi": cfg["dpi"],
        "psm": cfg["psm"],
        "tesseract": _tesseract_version(cfg["tesseract_cmd"]),
        "model": (resolve(cfg["tessdata_dir"]) / f"{cfg['lang']}.traineddata").stat().st_size,
    }


def _ocr_page(png: Path, out_base: Path, cfg: dict[str, Any]) -> Path:
    cmd = [
        cfg["tesseract_cmd"], str(png), str(out_base),
        "-l", cfg["lang"], "--dpi", str(cfg["dpi"]), "--psm", str(cfg["psm"]),
        "--tessdata-dir", str(resolve(cfg["tessdata_dir"])), "pdf",
    ]
    env = dict(os.environ, OMP_THREAD_LIMIT="1")  # parallelism comes from the page pool
    subprocess.run(cmd, check=True, capture_output=True, env=env)
    return out_base.with_suffix(".pdf")


def reocr_pdf(src: Path, doc_id: str, cfg: dict[str, Any]) -> Path:
    """Return a cached Tesseract re-OCR of src, building it if missing or stale."""
    cache_dir = resolve(cfg["cache_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    dst = cache_dir / f"{doc_id}.pdf"
    meta_path = dst.with_suffix(".json")
    settings = _settings(src, cfg)
    if dst.exists() and meta_path.exists() and json.loads(meta_path.read_text()) == settings:
        return dst

    with tempfile.TemporaryDirectory() as tmp, pymupdf.open(src) as doc:
        tmp_dir = Path(tmp)
        pngs = []
        for pno, page in enumerate(doc, start=1):
            png = tmp_dir / f"p{pno:04d}.png"
            page.get_pixmap(dpi=cfg["dpi"], colorspace=pymupdf.csGRAY).save(png)
            pngs.append(png)
        with ThreadPoolExecutor(max_workers=cfg["workers"]) as pool:
            parts = list(pool.map(lambda p: _ocr_page(p, p.with_suffix(""), cfg), pngs))
        merged = pymupdf.open()
        for part in parts:
            with pymupdf.open(part) as one:
                merged.insert_pdf(one)
        merged.save(dst, garbage=3, deflate=True)
        merged.close()
    meta_path.write_text(json.dumps(settings, indent=2))
    return dst

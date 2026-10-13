"""Report OCR quality (Indonesian wordlist hit rate) before and after re-OCR or replacement.

  before     the text layer of the PDF in data/raw (embedded OCR for scans)
  re-OCR     the Tesseract output, for docs listed in ocr.reocr_docs
  candidate  replacement files given with --candidate (e.g. a born-digital copy found online)
Born-digital regulations in the manifest give the baseline a clean text reaches.

Usage: uv run maritime-ocr-quality [--candidate DOC_ID=PATH[,PATH]] ...
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from maritime_rag.cleaning import PageCleaner, flatten
from maritime_rag.config import load_config, resolve
from maritime_rag.manifest import load_manifest
from maritime_rag.ocr import reocr_pdf
from maritime_rag.pdf_text import extract_lines
from maritime_rag.quality import QualityScore, load_wordlist, score
from maritime_rag.validate import sha256_file, validate_file


def _score_files(paths: list[Path], cleaner: PageCleaner, wordlist: frozenset[str], min_len: int) -> QualityScore:
    lines = [ln.text for p in paths for ln in flatten(cleaner.clean(extract_lines(p)))]
    return score(lines, wordlist, min_len)


def _fmt(s: QualityScore) -> str:
    return f"{s.hit_rate:.1%} ({s.known:,}/{s.tokens:,})"


def run(config_path: str, candidates: dict[str, list[Path]]) -> str:
    cfg = load_config(config_path)
    docs = load_manifest(resolve(cfg["paths"]["manifest"]))
    raw_dir = resolve(cfg["paths"]["raw_dir"])
    cleaner = PageCleaner(cfg["cleaning"])
    q = cfg["quality"]
    wordlist = load_wordlist(resolve(q["wordlist"]))
    min_len = q["min_token_len"]

    baseline, rows = [], []
    for meta in docs:
        if not meta.is_regulation:
            continue
        files = [raw_dir / f for f in [meta.file, meta.penjelasan_file] if f]
        checks = [validate_file(meta.doc_id, f, cfg["validation"]) for f in files]
        before = _score_files(files, cleaner, wordlist, min_len)
        if not any(c.ocr_pages for c in checks):
            baseline.append((meta.doc_id, before))
            continue
        row = [meta.doc_id, f"{sum(c.ocr_pages for c in checks)}/{sum(c.n_pages for c in checks)}", _fmt(before)]
        if meta.doc_id in cfg["ocr"]["reocr_docs"]:
            redone = reocr_pdf(raw_dir / meta.file, meta.doc_id, cfg["ocr"])
            row.append(_fmt(_score_files([redone], cleaner, wordlist, min_len)))
        else:
            row.append("-")
        if meta.doc_id in candidates:
            paths = candidates[meta.doc_id]
            names = ", ".join(f"{p.name} `{sha256_file(p)[:12]}`" for p in paths)
            row.append(f"{_fmt(_score_files(paths, cleaner, wordlist, min_len))}: {names}")
        else:
            row.append("-")
        rows.append(row)

    rates = [s.hit_rate for _, s in baseline]
    out = [
        "# OCR quality",
        "",
        f"Metric: share of word tokens (>= {min_len} letters, lowercased, hyphenated words split) found in "
        f"`{Path(q['wordlist']).name}` ({len(wordlist):,} entries). Legal abbreviations and names are never "
        "all in a wordlist, so born-digital regulations set the ceiling.",
        "",
        f"Born-digital baseline: median {statistics.median(rates):.1%}, "
        f"range {min(rates):.1%} to {max(rates):.1%} over {len(rates)} regulations.",
        "",
        "| doc | OCR-layer pages | before (embedded OCR) | after: Tesseract re-OCR | after: replacement candidate |",
        "|---|---|---|---|---|",
        *[f"| {' | '.join(r)} |" for r in rows],
        "",
        "Baseline per document:",
        "",
        *[f"- {doc}: {_fmt(s)}" for doc, s in baseline],
    ]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="configs/ingest.yaml")
    parser.add_argument("--candidate", action="append", default=[], help="DOC_ID=PATH[,PATH]")
    args = parser.parse_args()
    candidates = {}
    for c in args.candidate:
        doc_id, paths = c.split("=", 1)
        candidates[doc_id] = [Path(p) for p in paths.split(",")]
    report = run(args.config, candidates)
    out = resolve(load_config(args.config)["paths"]["reports_dir"]) / "ocr_quality.md"
    out.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()

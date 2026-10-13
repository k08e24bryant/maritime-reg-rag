"""Phase 1 pipeline: validate manifest PDFs, parse, chunk, link amendments, write chunks.jsonl and reports.

Usage: uv run maritime-ingest [--config configs/ingest.yaml]
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from maritime_rag.amendments import AmendmentReport, link_amendments
from maritime_rag.chunk import Chunk
from maritime_rag.cleaning import PageCleaner, flatten
from maritime_rag.config import load_config, resolve
from maritime_rag.manifest import DocMeta, load_manifest
from maritime_rag.ocr import reocr_pdf
from maritime_rag.overrides import load_overrides
from maritime_rag.pdf_text import extract_blocks, extract_lines
from maritime_rag.regulation import ParseReport, RegulationChunker, SourceText
from maritime_rag.report import ReportChunker
from maritime_rag.tokens import load_token_counter
from maritime_rag.validate import FileValidation, validate


def _percentiles(values: list[int]) -> dict[str, float]:
    if not values:
        return {}
    qs = statistics.quantiles(values, n=20, method="inclusive") if len(values) > 1 else [values[0]] * 19
    return {"min": min(values), "p25": qs[4], "median": statistics.median(values), "p75": qs[14],
            "p95": qs[18], "max": max(values), "mean": round(statistics.fmean(values), 1)}


def _histogram(values: list[int], edges: list[int]) -> list[tuple[str, int]]:
    rows = []
    for lo, hi in zip([0] + edges, edges + [None]):
        n = sum(1 for v in values if v >= lo and (hi is None or v < hi))
        rows.append((f"{lo}-{hi - 1}" if hi else f"{lo}+", n))
    return rows


def render_validation(results: list[FileValidation], unlisted: list[str], reocr: set[str]) -> str:
    out = ["# Manifest validation", "",
           "| doc | file | exists | pages | chars | OCR-layer pages | low-text pages | sha256 |",
           "|---|---|---|---|---|---|---|---|"]
    for r in results:
        low = ", ".join(map(str, r.low_text_pages)) or "-"
        ocr = f"{r.ocr_pages}/{r.n_pages}" + (" (re-OCR'd with Tesseract)" if r.doc_id in reocr else "")
        out.append(f"| {r.doc_id} | {r.file} | {'yes' if r.exists else '**MISSING**'} | {r.n_pages} | "
                   f"{r.n_chars:,} | {ocr} | {low} | `{r.sha256[:12]}` |")
    if unlisted:
        out += ["", f"PDFs in data/raw not in the manifest: {', '.join(unlisted)}"]
    return "\n".join(out) + "\n"


def render_stats(
    chunks: list[Chunk], reports: list[ParseReport], amend: AmendmentReport, max_tokens: int
) -> str:
    by_doc: dict[str, list[Chunk]] = defaultdict(list)
    for c in chunks:
        by_doc[c.doc_id].append(c)
    out = ["# Ingestion stats", "", f"Total chunks: **{len(chunks)}**", "",
           "## Chunks per document", "",
           "| doc | text layer | chunks | preamble | body | penjelasan | lampiran | report | Pasal (body) | median tok | max tok |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    rep = {r.doc_id: r for r in reports}
    for doc_id, cs in by_doc.items():
        parts = defaultdict(int)
        for c in cs:
            parts[c.part] += 1
        toks = [c.n_tokens for c in cs]
        layers = "+".join(sorted({c.text_layer for c in cs}))
        n_pasal = rep[doc_id].n_pasal.get("body", "-") if doc_id in rep else "-"
        out.append(f"| {doc_id} | {layers} | {len(cs)} | " + " | ".join(str(parts.get(p, 0)) for p in
                   ["preamble", "body", "penjelasan", "lampiran", "report"]) +
                   f" | {n_pasal} | {statistics.median(toks):.0f} | {max(toks)} |")

    toks = [c.n_tokens for c in chunks]
    out += ["", f"## Token length distribution (tokenizer = embedding model, cap = {max_tokens})", "",
            "| stat | " + " | ".join(_percentiles(toks)) + " |",
            "|---|" + "---|" * len(_percentiles(toks)),
            "| tokens | " + " | ".join(str(v) for v in _percentiles(toks).values()) + " |", "",
            "| tokens | chunks |", "|---|---|"]
    out += [f"| {b} | {n} |" for b, n in _histogram(toks, [25, 50, 100, 200, 300, 400, 512])]
    over = [c for c in chunks if c.n_tokens > max_tokens]
    out += ["", f"Chunks over the cap: {len(over)}"]
    out += [f"- {c.chunk_id} ({c.heading}): {c.n_tokens} tokens" for c in over[:20]]

    out += ["", "## Amendment links", "",
            "Amending chunks (inside Pasal I of an amending regulation) by kind, and how many older chunks",
            "each amending document marks as superseded or partially amended.", "",
            "| amending doc | kinds | older chunks marked |", "|---|---|---|"]
    for doc_id, kinds in amend.amending_chunks.items():
        k = ", ".join(f"{n} {kind}" for kind, n in sorted(kinds.items()))
        out.append(f"| {doc_id} | {k} | {amend.linked.get(doc_id, 0)} |")
    superseded = sum(1 for c in chunks if c.superseded_by)
    partial = sum(1 for c in chunks if c.partially_amended_by)
    out += ["", f"Chunks with superseded_by: {superseded}; with partially_amended_by: {partial}."]
    for doc_id, n in amend.out_of_corpus_flagged.items():
        flags = next(c.may_be_amended_by_out_of_corpus for c in by_doc[doc_id] if c.may_be_amended_by_out_of_corpus)
        out.append(f"{doc_id}: {n} chunks flagged may_be_amended_by_out_of_corpus = {flags}.")
    if amend.targets_not_found:
        out += ["", f"Amended Pasal not found in the base document ({len(amend.targets_not_found)}):"]
        out += [f"- {t}" for t in amend.targets_not_found]

    applied = [o for r in reports for o in r.overrides]
    out += ["", "## Manual overrides (configs/overrides.yaml)", ""]
    out += [f"- {o.status}: {o.override.describe()}" for o in applied] or ["- none"]

    out += ["", "## Pasal parsing issues", ""]
    for r in reports:
        lines = []
        if r.amending:
            lines.append("- amending regulation layout (Pasal I / Pasal II)")
        for part, missing in r.missing_pasal.items():
            if missing:
                lines.append(f"- missing Pasal numbers in {part}: {missing}")
        for m in r.instruction_mismatches:
            lines.append(f"- amendment instruction mismatch: {m}")
        if r.repaired_headers:
            lines.append(f"- repaired OCR-misread headers ({len(r.repaired_headers)}):")
            lines += [f"  - {x}" for x in r.repaired_headers]
        if r.rejected_headers:
            lines.append(f"- rejected header candidates ({len(r.rejected_headers)}):")
            lines += [f"  - {x}" for x in r.rejected_headers]
        lines += [f"- note: {n}" for n in r.notes]
        if r.dropped_trivial:
            lines.append(f"- dropped {r.dropped_trivial} trivial Penjelasan entries ('Cukup jelas.')")
        out += [f"### {r.doc_id}", "", *(lines or ["- no issues"]), ""]
    return "\n".join(out) + "\n"


def load_source(
    meta: DocMeta, file: str, validation: FileValidation, raw_dir: Path, cleaner: PageCleaner, ocr_cfg: dict[str, Any]
) -> SourceText:
    """Cleaned lines of one regulation PDF, re-OCR'd first when configured."""
    path = raw_dir / file
    layer = validation.text_layer
    if meta.doc_id in ocr_cfg["reocr_docs"] and file == meta.file:
        path, layer = reocr_pdf(path, meta.doc_id, ocr_cfg), "tesseract_reocr"
    lines = flatten(cleaner.clean(extract_lines(path)))
    return SourceText(file=file, sha256=validation.sha256, lines=lines, text_layer=layer)


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    paths = cfg["paths"]
    docs = load_manifest(resolve(paths["manifest"]))
    raw_dir = resolve(paths["raw_dir"])
    reports_dir = resolve(paths["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)
    ocr_cfg = cfg["ocr"]

    results, unlisted = validate(docs, raw_dir, cfg["validation"])
    validation_md = render_validation(results, unlisted, set(ocr_cfg["reocr_docs"]))
    (reports_dir / "validation.md").write_text(validation_md, encoding="utf-8")
    print(validation_md)
    checks = {(r.doc_id, r.file): r for r in results}

    count_tokens = load_token_counter(cfg["tokenizer"]["name"])
    cleaner = PageCleaner(cfg["cleaning"])
    reg_chunker = RegulationChunker(cfg["regulation"], count_tokens)
    rep_chunker = ReportChunker(cfg["report"], count_tokens)
    doc_overrides = cfg.get("doc_overrides") or {}
    header_overrides = load_overrides(resolve(paths["overrides"]))

    chunks: list[Chunk] = []
    reports: list[ParseReport] = []
    for meta in docs:
        files = [f for f in [meta.file, meta.penjelasan_file] if f]
        if not all(checks[(meta.doc_id, f)].ok for f in files):
            print(f"skip {meta.doc_id}: missing file or no text")
            continue
        if meta.is_regulation:
            main = load_source(meta, meta.file, checks[(meta.doc_id, meta.file)], raw_dir, cleaner, ocr_cfg)
            pj = None
            if meta.penjelasan_file:
                pj_check = checks[(meta.doc_id, meta.penjelasan_file)]
                pj = load_source(meta, meta.penjelasan_file, pj_check, raw_dir, cleaner, ocr_cfg)
            doc_chunks, report = reg_chunker.chunk(meta, main, pj, header_overrides)
            reports.append(report)
        else:
            skip = set(doc_overrides.get(meta.doc_id, {}).get("skip_pages", []))
            doc_chunks = rep_chunker.chunk(meta, extract_blocks(raw_dir / meta.file, skip_pages=skip))
        print(f"{meta.doc_id:18} {len(doc_chunks):5d} chunks")
        chunks += doc_chunks

    amend = link_amendments(chunks, {d.doc_id: d for d in docs}, cfg["amendments"]["out_of_corpus"])

    out_path = resolve(paths["chunks_file"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

    stats_md = render_stats(chunks, reports, amend, cfg["regulation"]["max_tokens"])
    (reports_dir / "ingest_stats.md").write_text(stats_md, encoding="utf-8")
    print(stats_md)
    print(f"wrote {len(chunks)} chunks -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ingest.yaml")
    run(parser.parse_args().config)


if __name__ == "__main__":
    main()

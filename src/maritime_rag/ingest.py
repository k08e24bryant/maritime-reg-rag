"""Phase 1 pipeline: validate manifest PDFs, parse, chunk, write chunks.jsonl, report stats.

Usage: uv run maritime-ingest [--config configs/ingest.yaml]
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from maritime_rag.chunk import Chunk
from maritime_rag.cleaning import PageCleaner, flatten
from maritime_rag.config import load_config, resolve
from maritime_rag.manifest import DocMeta, load_manifest
from maritime_rag.pdf_text import extract_blocks, extract_lines
from maritime_rag.regulation import ParseReport, RegulationChunker
from maritime_rag.report import ReportChunker
from maritime_rag.tokens import load_token_counter
from maritime_rag.validate import DocValidation, validate


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


def render_validation(results: list[DocValidation], unlisted: list[str]) -> str:
    out = ["# Manifest validation", "", "| doc | exists | pages | chars | OCR-layer pages | low-text pages | sha256 |",
           "|---|---|---|---|---|---|---|"]
    for r in results:
        low = ", ".join(map(str, r.low_text_pages)) or "-"
        out.append(f"| {r.doc_id} | {'yes' if r.exists else '**MISSING**'} | {r.n_pages} | {r.n_chars:,} | "
                   f"{r.ocr_pages}/{r.n_pages} | {low} | `{r.sha256[:12]}` |")
    if unlisted:
        out += ["", f"PDFs in data/raw not in the manifest: {', '.join(unlisted)}"]
    return "\n".join(out) + "\n"


def render_stats(chunks: list[Chunk], reports: list[ParseReport], max_tokens: int) -> str:
    by_doc: dict[str, list[Chunk]] = defaultdict(list)
    for c in chunks:
        by_doc[c.doc_id].append(c)
    out = ["# Ingestion stats", "", f"Total chunks: **{len(chunks)}**", "",
           "## Chunks per document", "",
           "| doc | chunks | preamble | body | penjelasan | lampiran | report | Pasal (body) | median tok | max tok |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    rep = {r.doc_id: r for r in reports}
    for doc_id, cs in by_doc.items():
        parts = defaultdict(int)
        for c in cs:
            parts[c.part] += 1
        toks = [c.n_tokens for c in cs]
        n_pasal = rep[doc_id].n_pasal.get("body", "-") if doc_id in rep else "-"
        out.append(f"| {doc_id} | {len(cs)} | " + " | ".join(str(parts.get(p, 0)) for p in
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

    out += ["", "## Pasal parsing issues", ""]
    for r in reports:
        lines = []
        if r.missing_pasal:
            lines.append(f"- missing Pasal numbers in body: {r.missing_pasal}")
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


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    paths = cfg["paths"]
    docs = load_manifest(resolve(paths["manifest"]))
    raw_dir = resolve(paths["raw_dir"])
    reports_dir = resolve(paths["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)

    results, unlisted = validate(docs, raw_dir, cfg["validation"])
    validation_md = render_validation(results, unlisted)
    (reports_dir / "validation.md").write_text(validation_md, encoding="utf-8")
    print(validation_md)
    valid = {r.doc_id for r in results if r.ok}

    count_tokens = load_token_counter(cfg["tokenizer"]["name"])
    cleaner = PageCleaner(cfg["cleaning"])
    reg_chunker = RegulationChunker(cfg["regulation"], count_tokens)
    rep_chunker = ReportChunker(cfg["report"], count_tokens)
    overrides = cfg.get("doc_overrides") or {}

    chunks: list[Chunk] = []
    reports: list[ParseReport] = []
    for meta in docs:
        if meta.doc_id not in valid:
            print(f"skip {meta.doc_id}: missing or no text")
            continue
        path = raw_dir / meta.file
        doc_cfg = overrides.get(meta.doc_id, {})
        if meta.is_regulation:
            lines = flatten(cleaner.clean(extract_lines(path)))
            doc_chunks, report = reg_chunker.chunk(meta, lines)
            reports.append(report)
        else:
            pages = extract_blocks(path, skip_pages=set(doc_cfg.get("skip_pages", [])))
            doc_chunks = rep_chunker.chunk(meta, pages)
        print(f"{meta.doc_id:18} {len(doc_chunks):5d} chunks")
        chunks += doc_chunks

    out_path = resolve(paths["chunks_file"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

    stats_md = render_stats(chunks, reports, cfg["regulation"]["max_tokens"])
    (reports_dir / "ingest_stats.md").write_text(stats_md, encoding="utf-8")
    print(stats_md)
    print(f"wrote {len(chunks)} chunks -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ingest.yaml")
    run(parser.parse_args().config)


if __name__ == "__main__":
    main()

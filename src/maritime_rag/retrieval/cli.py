"""CLI: uv run maritime-search "pertanyaan" --retriever hybrid --k 5 [--rerank]"""

from __future__ import annotations

import argparse
import textwrap

from maritime_rag.config import load_config
from maritime_rag.retrieval.corpus import Filters, Hit
from maritime_rag.retrieval.search import RETRIEVERS, Searcher, version_status


def locator(chunk: dict) -> str:
    """'PM 74/2016 Pasal 71 ayat (1)-(6)' or 'Review ... > section'."""
    if chunk["doc_type"] == "Report":
        return f"{chunk['title']} > {chunk['section']}" + (f" > {chunk['subsection']}" if chunk.get("subsection") else "")
    name = f"{chunk['doc_type']} {chunk['number']}/{chunk['year']}"
    part = {"penjelasan": " Penjelasan", "preamble": " (pembukaan)", "lampiran": " Lampiran"}.get(chunk["part"], "")
    where = f" Pasal {chunk['pasal']}" if chunk.get("pasal") else ""
    if chunk.get("ayat"):
        where += f" ayat ({chunk['ayat'].replace('-', ')-(')})"
    return f"{name}{part}{where}"


def pages(chunk: dict) -> str:
    p = chunk["page_start"] if chunk["page_start"] == chunk["page_end"] else f"{chunk['page_start']}-{chunk['page_end']}"
    return f"{chunk['source_file']} p. {p}"


def format_hit(hit: Hit, searcher: Searcher, snippet_chars: int) -> str:
    c = hit.chunk
    snippet = " ".join(c["text"].split())[:snippet_chars]
    extra = ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in hit.stage_scores.items())
    lines = [
        f"{hit.rank}. [{hit.score:.4f}] {locator(c)}  ({pages(c)})",
        f"   id={hit.chunk_id}  status: {version_status(c, searcher.corpus)}" + (f"  [{extra}]" if extra else ""),
        textwrap.indent(textwrap.fill(snippet + ("..." if len(c["text"]) > snippet_chars else ""), 100), "   > "),
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the regulation corpus.")
    parser.add_argument("query")
    parser.add_argument("--config", default="configs/retrieval.yaml")
    parser.add_argument("--retriever", choices=RETRIEVERS)
    parser.add_argument("--k", type=int)
    parser.add_argument("--rerank", action="store_true", help="rerank the top-N with the cross-encoder")
    parser.add_argument("--reranker", help="default | small (key in rerank.models) or a model id")
    parser.add_argument("--doc", action="append", help="restrict to doc_id (repeatable)")
    parser.add_argument("--type", action="append", help="restrict to doc type: UU, PP, PM, Report")
    parser.add_argument("--exclude-superseded", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    searcher = Searcher(cfg, reranker=args.reranker)
    filters = None
    if args.doc or args.type or args.exclude_superseded:
        filters = Filters(doc_ids=args.doc, doc_types=args.type, exclude_superseded=args.exclude_superseded)
    hits = searcher.search(args.query, args.k, filters, args.retriever, args.rerank or None)
    name = (args.retriever or cfg["search"]["retriever"]) + ("+rerank" if args.rerank else "")
    print(f"query: {args.query}\nretriever: {name}")
    reranker = searcher.loaded_reranker
    if args.rerank and reranker and reranker.last_timing:
        t = reranker.last_timing
        print(f"reranker: {reranker.model_id} on {reranker.device}, {t.n_pairs} pairs in "
              f"{t.seconds * 1000:.0f} ms (a single call includes CUDA warm-up)")
    print()
    if not hits:
        print("No matching chunks.")
    for hit in hits:
        print(format_hit(hit, searcher, cfg["search"]["snippet_chars"]) + "\n")


if __name__ == "__main__":
    main()

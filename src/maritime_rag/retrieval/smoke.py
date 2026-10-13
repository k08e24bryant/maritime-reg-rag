"""Smoke check: top-k per retriever for hand-written queries -> reports/retrieval_smoke.md.

Not an evaluation: no gold labels and no metrics (the gold set comes in Phase 4).
Usage: uv run maritime-smoke [--rerank [--reranker small]]
"""

from __future__ import annotations

import argparse
import statistics

import yaml

from maritime_rag.config import load_config, resolve
from maritime_rag.retrieval.cli import locator, pages
from maritime_rag.retrieval.search import Searcher, version_status


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def run(config_path: str, rerank: bool, reranker: str | None) -> str:
    import torch

    cfg = load_config(config_path)
    queries = yaml.safe_load(resolve(cfg["paths"]["smoke_queries"]).read_text(encoding="utf-8"))["queries"]
    searcher = Searcher(cfg, reranker=reranker)
    latencies: list[float] = []
    k = cfg["search"]["k"]
    configs = [("bm25", False), ("dense", False), ("hybrid", False)] + ([("hybrid", True)] if rerank else [])
    out = [
        "# Retrieval smoke check",
        "",
        f"Top-{k} per retriever for {len(queries)} hand-written queries. Not an evaluation: no gold labels, "
        "no metrics. `expect` is a human hint written with the query. Scores are not comparable across "
        "retrievers (BM25 = Okapi score, dense = cosine, hybrid = RRF, rerank = cross-encoder logit).",
        "",
        f"BM25 heading prefix: {cfg['bm25']['include_heading']}; dense model: {cfg['dense']['model']}; "
        f"RRF k={cfg['hybrid']['k_rrf']}, candidates={cfg['hybrid']['candidates']}.",
    ]
    for q in queries:
        out += ["", f"## {q['id']}: {q['text']}", "", f"Expect: {q['expect']}"]
        for name, rr in configs:
            hits = searcher.search(q["text"], k, retriever=name, rerank=rr)
            if rr and searcher.loaded_reranker and searcher.loaded_reranker.last_timing:
                latencies.append(searcher.loaded_reranker.last_timing.seconds)
            label = name + ("+rerank" if rr else "")
            out += ["", f"**{label}**", ""]
            if not hits:
                out.append("_no matching chunks_")
                continue
            out += ["| # | score | where | pages | status | snippet |", "|---|---|---|---|---|---|"]
            for h in hits:
                snippet = " ".join(h.chunk["text"].split())[:110]
                out.append(
                    f"| {h.rank} | {h.score:.3f} | {_cell(locator(h.chunk))} | {_cell(pages(h.chunk))} | "
                    f"{_cell(version_status(h.chunk, searcher.corpus))} | {_cell(snippet)} |"
                )
    if latencies:
        rr = searcher.loaded_reranker
        warm = latencies[1:] or latencies  # the first call includes CUDA warm-up
        vram = torch.cuda.max_memory_allocated() / 2**20 if torch.cuda.is_available() else 0.0
        precision = "fp16" if rr.device == "cuda" and cfg["rerank"]["fp16"] else "fp32"
        out[5:5] = [
            "",
            f"Reranker: {rr.model_id} on {rr.device} ({precision}), top-{cfg['rerank']['top_n']} hybrid hits per "
            f"query, batch {cfg['rerank']['batch_size']}. Latency: median {statistics.median(warm) * 1000:.0f} ms, "
            f"max {max(warm) * 1000:.0f} ms over {len(warm)} queries after warm-up (first call "
            f"{latencies[0] * 1000:.0f} ms). Peak VRAM, encoder + reranker: {vram:.0f} MB.",
        ]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="configs/retrieval.yaml")
    parser.add_argument("--rerank", action="store_true", help="add a hybrid+rerank column")
    parser.add_argument("--reranker", help="default | small (key in rerank.models) or a model id")
    args = parser.parse_args()
    report = run(args.config, args.rerank, args.reranker)
    out = resolve(load_config(args.config)["paths"]["reports_dir"]) / "retrieval_smoke.md"
    out.write_text(report, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

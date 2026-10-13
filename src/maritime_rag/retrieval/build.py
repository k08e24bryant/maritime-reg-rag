"""Build the dense index (and time BM25); writes reports/retrieval_index.md.

Loads only the e5 encoder, once (fp16 on CUDA). Never loads the reranker. Embeddings are
committed to the cache batch by batch, so an interrupted run resumes where it stopped.
--no-cache ignores the cache (no reads, no writes, nothing deleted) to time cold embedding.

Usage: uv run maritime-index [--batch-size N] [--force] [--no-cache]
"""

from __future__ import annotations

import argparse
import platform
import sys
import time
from pathlib import Path

import psutil

from maritime_rag.config import load_config, resolve
from maritime_rag.retrieval.bm25 import BM25Retriever
from maritime_rag.retrieval.corpus import load_corpus
from maritime_rag.retrieval.dense import (
    BuildStats,
    SentenceTransformerEncoder,
    load_or_build_index,
    resolve_device,
)
from maritime_rag.retrieval.tokenize import Tokenizer, load_stopwords


def peak_ram_mb() -> float:
    info = psutil.Process().memory_info()
    return getattr(info, "peak_wset", info.rss) / 2**20  # peak working set on Windows, else current RSS


def _size_mb(paths: list[Path]) -> float:
    return sum(p.stat().st_size for p in paths if p.exists()) / 2**20


def _progress(embedded: int, reused: int, total: int) -> None:
    print(f"\r  {total} chunks: embedded {embedded}, reused {reused} from cache",
          end="" if embedded + reused < total else "\n", file=sys.stderr, flush=True)


def run(config_path: str, batch_size: int | None, force: bool, use_cache: bool = True) -> str:
    import torch

    cfg = load_config(config_path)
    p, d = cfg["paths"], cfg["dense"]
    if batch_size:
        d = d | {"batch_size": batch_size}
    index_dir = resolve(p["index_dir"])
    corpus = load_corpus(resolve(p["chunks_file"]))
    device = resolve_device(d["device"])

    t = time.perf_counter()
    BM25Retriever(corpus, Tokenizer(load_stopwords(resolve(p["stopwords"])), cfg["bm25"]["min_token_len"]), cfg["bm25"])
    bm25_s = time.perf_counter() - t

    print(f"loading {d['model']} on {device} ({'fp16' if device == 'cuda' and d['fp16'] else 'fp32'})", file=sys.stderr)
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    t = time.perf_counter()
    encoder = SentenceTransformerEncoder(d["model"], d, resolve(p["hf_cache"]))
    load_s = time.perf_counter() - t
    bs = encoder.batch_size

    print(f"building index, batch size {bs}" + ("" if use_cache else ", embedding cache ignored"), file=sys.stderr)
    _, stats = load_or_build_index(corpus, encoder, d, index_dir, force=force, progress=_progress, use_cache=use_cache)
    vram_peak = torch.cuda.max_memory_allocated() / 2**20 if device == "cuda" else 0.0
    encoder.release()
    ram_peak = peak_ram_mb()

    files = [index_dir / n for n in ("dense.faiss", "dense_ids.json", "dense_meta.json", "embeddings.sqlite")]
    out = [
        "# Retrieval index build",
        "",
        f"Corpus: {len(corpus.chunks)} chunks. Machine: {platform.processor() or platform.machine()}, "
        f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none'}, torch {torch.__version__}. "
        f"Encoder: {d['model']} on {device}, {'fp16' if device == 'cuda' and d['fp16'] else 'fp32'}, batch size {bs}. "
        "The reranker is not loaded here (query time only).",
        "",
        "| step | value |",
        "|---|---|",
        f"| BM25 build (tokenize + index) | {bm25_s:.2f} s |",
        f"| e5 model load | {load_s:.1f} s |",
    ]
    if stats is None:
        out.append("| dense index | persisted index matches corpus and settings; loaded, nothing embedded (use --force to rebuild) |")
    else:
        out += _build_rows(stats, d["max_seq_length"], use_cache)
    out += [
        f"| index size on disk | {_size_mb(files):.1f} MB (FAISS {_size_mb(files[:1]):.1f} MB, "
        f"embedding cache {_size_mb(files[3:]):.1f} MB) |",
        f"| peak VRAM (torch.cuda.max_memory_allocated) | {vram_peak:.0f} MB |",
        f"| peak RAM (psutil, process peak working set) | {ram_peak:.0f} MB |",
    ]
    return "\n".join(out) + "\n"


def _build_rows(s: BuildStats, max_len: int, use_cache: bool) -> list[str]:
    cache_note = f"{s.n_cached} reused from cache" if use_cache else "cache ignored (--no-cache, cold run)"
    return [
        f"| dense build | {s.total_seconds:.1f} s total, {s.embed_seconds:.1f} s embedding; "
        f"{s.n_embedded} chunks embedded this run, {cache_note} |",
        f"| embedding throughput | {s.n_embedded / s.embed_seconds:.0f} chunks/s |" if s.n_embedded else
        "| embedding throughput | - (all from cache) |",
        f"| embedded input length (tokens, incl. prefix + heading) | max {s.max_input_tokens}; "
        f"{s.n_truncated} over {max_len} (truncated) |",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="configs/retrieval.yaml")
    parser.add_argument("--batch-size", type=int, help="override config (auto = 16 on GPU, 8 on CPU)")
    parser.add_argument("--force", action="store_true", help="rebuild even if the persisted index matches")
    parser.add_argument("--no-cache", action="store_true",
                        help="embed every chunk, ignoring the embedding cache (not read, written or deleted); implies --force")
    args = parser.parse_args()
    report = run(args.config, args.batch_size, args.force, use_cache=not args.no_cache)
    out = resolve(load_config(args.config)["paths"]["reports_dir"]) / "retrieval_index.md"
    out.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()

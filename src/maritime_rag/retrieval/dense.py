"""Dense retrieval: multilingual-e5 embeddings in a persisted FAISS inner-product index.

Embeddings are L2-normalized, so inner product = cosine similarity. Each embedded text is
cached in SQLite under sha256(model, prefix + text); re-indexing after re-ingestion only
embeds chunks whose embedded text changed. use_cache=False (maritime-index --no-cache) neither
reads nor writes the cache, so a cold embedding run can be timed without deleting it.
"""

from __future__ import annotations

import gc
import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import faiss
import numpy as np

from maritime_rag.retrieval.corpus import Corpus, Filters, Hit, indexed_text, top_hits


class Encoder(Protocol):
    model_id: str
    dim: int
    batch_size: int  # resolved default, never "auto"

    def encode(self, texts: list[str], batch_size: int | str | None = None) -> np.ndarray:
        """(n, dim) float32, L2-normalized. batch_size: None = self.batch_size; "auto" is accepted."""
        ...


Progress = Callable[[int, int, int], None]  # (embedded this run, reused from cache, total)


def resolve_device(setting: str) -> str:
    if setting != "auto":
        return setting
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def resolve_batch_size(setting: int | str, device: str) -> int:
    """Config/CLI batch size; "auto" = 16 on GPU, 8 on CPU."""
    if setting == "auto":
        return 16 if device == "cuda" else 8
    return int(setting)


def load_sentence_transformer(model_id: str, cfg: dict[str, Any], device: str, cache_folder: Path) -> Any:
    import torch
    from sentence_transformers import SentenceTransformer

    kwargs = {"dtype": torch.float16} if device == "cuda" and cfg["fp16"] else {}
    model = SentenceTransformer(model_id, device=device, cache_folder=str(cache_folder), model_kwargs=kwargs)
    model.max_seq_length = cfg["max_seq_length"]
    return model


class SentenceTransformerEncoder:
    """sentence-transformers model loaded once, in fp16 on CUDA when available, else fp32 on CPU.

    The one place a config batch size ("auto" or int) becomes an int, so callers can pass
    cfg["batch_size"] straight through.
    """

    def __init__(self, model_id: str, cfg: dict[str, Any], cache_folder: Path) -> None:
        self.device = resolve_device(cfg["device"])
        self.model = load_sentence_transformer(model_id, cfg, self.device, cache_folder)
        self.model_id = model_id
        self.dim = self.model.get_embedding_dimension()
        self.batch_size = resolve_batch_size(cfg["batch_size"], self.device)

    def encode(self, texts: list[str], batch_size: int | str | None = None) -> np.ndarray:
        bs = self.batch_size if batch_size is None else resolve_batch_size(batch_size, self.device)
        vecs = self.model.encode(
            texts, batch_size=bs, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
        return np.asarray(vecs, dtype=np.float32)

    def token_lengths(self, texts: list[str]) -> list[int]:
        tok = self.model.tokenizer
        return [len(ids) for ids in tok(texts, add_special_tokens=True)["input_ids"]]

    def release(self) -> None:
        """Drop the model and return cached CUDA memory to the driver."""
        import torch

        del self.model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


class EmbeddingCache:
    """SQLite store: sha256(model + embedded text) -> float32 vector."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS emb (key TEXT PRIMARY KEY, vec BLOB NOT NULL)")

    @staticmethod
    def key(model_id: str, text: str) -> str:
        return hashlib.sha256(f"{model_id}\0{text}".encode()).hexdigest()

    def get_many(self, keys: list[str]) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        for start in range(0, len(keys), 500):
            batch = keys[start : start + 500]
            rows = self.db.execute(
                f"SELECT key, vec FROM emb WHERE key IN ({','.join('?' * len(batch))})", batch
            ).fetchall()
            out.update({k: np.frombuffer(v, dtype=np.float32) for k, v in rows})
        return out

    def put_many(self, items: dict[str, np.ndarray]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO emb (key, vec) VALUES (?, ?)",
            [(k, v.astype(np.float32).tobytes()) for k, v in items.items()],
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()


@dataclass
class BuildStats:
    n_chunks: int
    n_embedded: int  # computed this run
    n_cached: int  # reused from the cache
    embed_seconds: float
    total_seconds: float
    max_input_tokens: int = 0
    n_truncated: int = 0  # passages longer than max_seq_length


def passages(corpus: Corpus, cfg: dict[str, Any]) -> list[str]:
    return [cfg["passage_prefix"] + indexed_text(c, cfg["include_heading"]) for c in corpus.chunks]


def build_index(
    corpus: Corpus,
    encoder: Encoder,
    cfg: dict[str, Any],
    cache: EmbeddingCache | None,
    batch_size: int,
    progress: Progress | None = None,
) -> tuple[faiss.Index, BuildStats]:
    """Embed uncached passages batch by batch; each batch is committed to the cache as it
    finishes, so an interrupted build resumes where it stopped. cache=None embeds everything
    and leaves the cache untouched."""
    t0 = time.perf_counter()
    texts = passages(corpus, cfg)
    keys = [EmbeddingCache.key(encoder.model_id, t) for t in texts]
    cached = cache.get_many(keys) if cache is not None else {}
    todo = [i for i, k in enumerate(keys) if k not in cached]
    t_embed = time.perf_counter()
    reused, embedded = len(texts) - len(todo), 0
    if progress:
        progress(embedded, reused, len(texts))
    for start in range(0, len(todo), batch_size):
        batch = todo[start : start + batch_size]
        vecs = encoder.encode([texts[i] for i in batch], batch_size)
        fresh = {keys[i]: vecs[j] for j, i in enumerate(batch)}
        if cache is not None:
            cache.put_many(fresh)
        cached.update(fresh)
        embedded += len(batch)
        if progress:
            progress(embedded, reused, len(texts))
    embed_seconds = time.perf_counter() - t_embed
    matrix = np.stack([cached[k] for k in keys]).astype(np.float32)
    index = faiss.IndexFlatIP(matrix.shape[1])
    index.add(matrix)
    stats = BuildStats(len(texts), len(todo), len(texts) - len(todo), embed_seconds, time.perf_counter() - t0)
    if hasattr(encoder, "token_lengths"):
        lengths = encoder.token_lengths(texts)
        stats.max_input_tokens = max(lengths)
        stats.n_truncated = sum(1 for n in lengths if n > cfg["max_seq_length"])
    return index, stats


def _meta(corpus: Corpus, encoder: Encoder, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": encoder.model_id,
        "dim": encoder.dim,
        "chunks_sha256": corpus.sha256,
        "include_heading": cfg["include_heading"],
        "passage_prefix": cfg["passage_prefix"],
    }


def load_or_build_index(
    corpus: Corpus,
    encoder: Encoder,
    cfg: dict[str, Any],
    index_dir: Path,
    force: bool = False,
    batch_size: int | None = None,
    progress: Progress | None = None,
    use_cache: bool = True,
) -> tuple[faiss.Index, BuildStats | None]:
    """Load the persisted index if it matches corpus + settings, else (re)build it with the cache.

    batch_size None = the encoder's resolved default. use_cache=False implies force."""
    index_path, meta_path, ids_path = index_dir / "dense.faiss", index_dir / "dense_meta.json", index_dir / "dense_ids.json"
    meta = _meta(corpus, encoder, cfg)
    if use_cache and not force and index_path.exists() and meta_path.exists() and ids_path.exists():
        if json.loads(meta_path.read_text()) == meta and json.loads(ids_path.read_text()) == corpus.ids:
            return faiss.read_index(str(index_path)), None
    cache = EmbeddingCache(index_dir / "embeddings.sqlite") if use_cache else None
    try:
        index, stats = build_index(corpus, encoder, cfg, cache, batch_size or encoder.batch_size, progress)
    finally:
        if cache is not None:
            cache.close()
    index_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(index_path))
    ids_path.write_text(json.dumps(corpus.ids))
    meta_path.write_text(json.dumps(meta, indent=2))
    return index, stats


class DenseRetriever:
    name = "dense"

    def __init__(self, corpus: Corpus, encoder: Encoder, index: faiss.Index, cfg: dict[str, Any]) -> None:
        if index.ntotal != len(corpus.chunks):
            raise ValueError("FAISS index does not match the corpus; rebuild it")
        self.corpus = corpus
        self.encoder = encoder
        self.index = index
        self.query_prefix: str = cfg["query_prefix"]

    def scores(self, query: str) -> np.ndarray:
        q = self.encoder.encode([self.query_prefix + query], batch_size=1)
        sims, idx = self.index.search(q, self.index.ntotal)  # exact; the corpus is small
        out = np.empty(self.index.ntotal, dtype=np.float32)
        out[idx[0]] = sims[0]
        return out

    def search(self, query: str, k: int, filters: Filters | None = None) -> list[Hit]:
        return top_hits(self.scores(query), self.corpus, k, filters, self.name)

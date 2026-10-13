"""Retrieval unit tests with a deterministic fake encoder (no model download needed)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pytest

from maritime_rag.retrieval.bm25 import BM25Retriever
from maritime_rag.retrieval.corpus import Corpus, Filters, Hit
from maritime_rag.retrieval.dense import DenseRetriever, load_or_build_index
from maritime_rag.retrieval.hybrid import HybridRetriever
from maritime_rag.retrieval.search import version_status
from maritime_rag.retrieval.tokenize import Tokenizer

DENSE_CFG = {"query_prefix": "query: ", "passage_prefix": "passage: ", "include_heading": True,
             "batch_size": 4, "max_seq_length": 512}
BM25_CFG = {"k1": 1.5, "b": 0.75, "include_heading": True, "min_token_len": 2}
STOP = frozenset({"yang", "dan", "di", "the", "of"})


class FakeEncoder:
    """Hashed bag-of-words vectors: deterministic, and similar texts get similar vectors."""

    model_id = "fake-encoder"
    dim = 256
    batch_size = 4

    def __init__(self) -> None:
        self.encoded = 0  # texts encoded, to check cache reuse

    def encode(self, texts: list[str], batch_size: int | str | None = None) -> np.ndarray:
        self.encoded += len(texts)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for tok in re.findall(r"[a-z0-9]+", text.lower().removeprefix("query: ").removeprefix("passage: ")):
                out[row, int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim] += 1.0
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


def _chunk(cid: str, doc: str, doc_type: str, part: str, text: str, **kw) -> dict:
    base = {"chunk_id": cid, "doc_id": doc, "doc_type": doc_type, "part": part, "text": text,
            "heading": f"{doc} > Pasal {cid[-1]}", "pasal": cid[-1], "superseded_by": [],
            "partially_amended_by": [], "amends_doc": None, "amends_pasal": None, "amendment_kind": None,
            "may_be_amended_by_out_of_corpus": []}
    return base | kw


@pytest.fixture
def corpus() -> Corpus:
    chunks = [
        _chunk("base-1", "base", "PM", "body", "Izin usaha angkutan laut diberikan oleh Menteri kepada perusahaan",
               superseded_by=["amd"]),
        _chunk("base-2", "base", "PM", "body", "Kapal wajib memiliki surat persetujuan berlayar dari syahbandar"),
        _chunk("base-3", "base", "PM", "penjelasan", "Yang dimaksud dengan kapal tunda adalah kapal penarik"),
        _chunk("amd-1", "amd", "PM", "body", "Izin usaha angkutan laut diterbitkan melalui sistem perizinan elektronik",
               amends_doc="base", amends_pasal="1", amendment_kind="replace"),
        _chunk("rep-1", "rep", "Report", "report", "Seaborne trade volumes grew in 2024 as ships rerouted around the Cape"),
    ]
    return Corpus(chunks, "sha-test")


def test_tokenizer_keeps_numbers_drops_stopwords_and_accents() -> None:
    tok = Tokenizer(STOP, min_token_len=2)
    assert tok("Pasal 71 ayat (2) yang di Undang-Undang café") == ["pasal", "71", "ayat", "2", "undang", "undang", "cafe"]


def test_bm25_verbatim_and_filters(corpus: Corpus) -> None:
    bm25 = BM25Retriever(corpus, Tokenizer(STOP, 2), BM25_CFG)
    assert bm25.search("surat persetujuan berlayar dari syahbandar", 3)[0].chunk_id == "base-2"
    assert bm25.search("tiket pesawat bali", 3) == []  # no shared term -> no hits
    hits = bm25.search("izin usaha angkutan laut", 5)
    assert {h.chunk_id for h in hits[:2]} == {"base-1", "amd-1"}
    assert all("superseded_by" in h.chunk and "amends_doc" in h.chunk for h in hits)  # full metadata
    excl = bm25.search("izin usaha angkutan laut", 5, Filters(exclude_superseded=True))
    assert "base-1" not in {h.chunk_id for h in excl} and "amd-1" in {h.chunk_id for h in excl}
    assert [h.chunk_id for h in bm25.search("kapal", 5, Filters(parts=["penjelasan"]))] == ["base-3"]
    assert {h.chunk["doc_id"] for h in bm25.search("izin kapal", 5, Filters(doc_ids=["amd"]))} == {"amd"}
    assert bm25.search("izin kapal", 5, Filters(doc_types=["Report"])) == []


def test_bm25_build_is_deterministic(corpus: Corpus) -> None:
    a = BM25Retriever(corpus, Tokenizer(STOP, 2), BM25_CFG).scores("izin kapal laut")
    b = BM25Retriever(corpus, Tokenizer(STOP, 2), BM25_CFG).scores("izin kapal laut")
    assert a == b


def test_dense_index_deterministic_verbatim_and_filters(corpus: Corpus, tmp_path: Path) -> None:
    enc = FakeEncoder()
    idx1, _ = load_or_build_index(corpus, enc, DENSE_CFG, tmp_path / "a")
    idx2, _ = load_or_build_index(corpus, FakeEncoder(), DENSE_CFG, tmp_path / "b")
    assert np.array_equal(idx1.reconstruct_n(0, idx1.ntotal), idx2.reconstruct_n(0, idx2.ntotal))
    dense = DenseRetriever(corpus, enc, idx1, DENSE_CFG)
    for c in corpus.chunks:
        assert dense.search(c["text"], 1)[0].chunk_id == c["chunk_id"]
    hits = dense.search("izin usaha angkutan laut", 5, Filters(exclude_superseded=True, doc_types=["PM"]))
    assert "base-1" not in {h.chunk_id for h in hits} and all(h.chunk["doc_type"] == "PM" for h in hits)


def test_embedding_cache_reused_and_index_persisted(corpus: Corpus, tmp_path: Path) -> None:
    enc = FakeEncoder()
    _, stats = load_or_build_index(corpus, enc, DENSE_CFG, tmp_path)
    assert (stats.n_embedded, stats.n_cached, enc.encoded) == (5, 0, 5)
    _, stats = load_or_build_index(corpus, enc, DENSE_CFG, tmp_path)
    assert stats is None and enc.encoded == 5  # persisted index matches: loaded, nothing embedded
    _, stats = load_or_build_index(corpus, enc, DENSE_CFG, tmp_path, force=True)
    assert (stats.n_embedded, stats.n_cached, enc.encoded) == (0, 5, 5)  # rebuilt from the cache
    changed = Corpus([c | {"text": c["text"] + " (diubah)"} if c["chunk_id"] == "base-2" else c
                      for c in corpus.chunks], "sha-changed")
    _, stats = load_or_build_index(changed, enc, DENSE_CFG, tmp_path)
    assert (stats.n_embedded, stats.n_cached, enc.encoded) == (1, 4, 6)  # only the changed chunk


def test_no_cache_embeds_everything_and_leaves_cache_untouched(corpus: Corpus, tmp_path: Path) -> None:
    load_or_build_index(corpus, FakeEncoder(), DENSE_CFG, tmp_path)
    db = tmp_path / "embeddings.sqlite"
    before = db.read_bytes()
    enc = FakeEncoder()
    progress: list[tuple[int, int, int]] = []
    _, stats = load_or_build_index(corpus, enc, DENSE_CFG, tmp_path, use_cache=False,
                                   progress=lambda *a: progress.append(a))
    assert (stats.n_embedded, stats.n_cached, enc.encoded) == (5, 0, 5)  # rebuilt although the index matched
    assert progress[0] == (0, 0, 5) and progress[-1] == (5, 0, 5)
    assert db.read_bytes() == before


class _Stub:
    def __init__(self, name: str, order: list[str], corpus: Corpus) -> None:
        self.name, self.order, self.corpus = name, order, corpus

    def search(self, query: str, k: int, filters: Filters | None = None) -> list[Hit]:
        by_id = self.corpus.by_id()
        ids = [i for i in self.order if filters is None or filters.accepts(by_id[i])][:k]
        return [Hit(i, 1.0, r, self.name, by_id[i]) for r, i in enumerate(ids, start=1)]


def test_rrf_fusion_and_filters(corpus: Corpus) -> None:
    a = _Stub("bm25", ["base-2", "base-1", "amd-1"], corpus)
    b = _Stub("dense", ["base-1", "amd-1", "base-2"], corpus)
    hybrid = HybridRetriever(corpus, [a, b], {"k_rrf": 60, "candidates": 10})
    hits = hybrid.search("q", 3)
    # base-1: 1/62 + 1/61 > base-2: 1/61 + 1/63 > amd-1: 1/63 + 1/62
    assert [h.chunk_id for h in hits] == ["base-1", "base-2", "amd-1"]
    assert hits[0].stage_scores == {"bm25_rank": 2, "dense_rank": 1}
    assert [h.chunk_id for h in hybrid.search("q", 3, Filters(exclude_superseded=True))] == ["base-2", "amd-1"]


def test_version_status(corpus: Corpus) -> None:
    by_id = corpus.by_id()
    assert version_status(by_id["base-1"], corpus) == "SUPERSEDED by amd"
    assert version_status(by_id["amd-1"], corpus) == "amends base Pasal 1 (replace)"
    assert version_status(by_id["base-2"], corpus) == "current"


class _FailingEncoder(FakeEncoder):
    """Raises after `ok_batches` batches, like a run killed for low memory."""

    def __init__(self, ok_batches: int) -> None:
        super().__init__()
        self.ok_batches = ok_batches

    def encode(self, texts: list[str], batch_size: int | str | None = None) -> np.ndarray:
        if self.ok_batches == 0:
            raise MemoryError("simulated")
        self.ok_batches -= 1
        return super().encode(texts, batch_size)


def test_interrupted_build_resumes_from_cached_batches(corpus: Corpus, tmp_path: Path) -> None:
    with pytest.raises(MemoryError):
        load_or_build_index(corpus, _FailingEncoder(ok_batches=1), DENSE_CFG, tmp_path, batch_size=2)
    progress: list[tuple[int, int, int]] = []
    enc = FakeEncoder()
    _, stats = load_or_build_index(corpus, enc, DENSE_CFG, tmp_path, batch_size=2,
                                   progress=lambda *a: progress.append(a))
    assert (stats.n_cached, stats.n_embedded, enc.encoded) == (2, 3, 3)  # first batch survived the crash
    assert progress == [(0, 2, 5), (2, 2, 5), (3, 2, 5)]  # (embedded, reused, total)


def test_batch_size_and_reranker_choice() -> None:
    from maritime_rag.retrieval.dense import resolve_batch_size
    from maritime_rag.retrieval.rerank import reranker_model_id

    assert (resolve_batch_size("auto", "cuda"), resolve_batch_size("auto", "cpu"), resolve_batch_size(4, "cuda")) == (16, 8, 4)
    cfg = {"model": "default", "models": {"default": "BAAI/bge-reranker-v2-m3",
                                          "small": "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"}}
    assert reranker_model_id(cfg) == "BAAI/bge-reranker-v2-m3"
    assert reranker_model_id(cfg, "small") == "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    assert reranker_model_id(cfg, "org/other-model") == "org/other-model"


class _FakeSentenceTransformer:
    def __init__(self) -> None:
        self.batch_sizes: list[object] = []

    def get_embedding_dimension(self) -> int:
        return 3

    def encode(self, texts: list[str], batch_size: int, **_: object) -> np.ndarray:
        self.batch_sizes.append(batch_size)
        return np.ones((len(texts), 3), dtype=np.float32)


@pytest.mark.parametrize(("device", "auto_bs"), [("cpu", 8), ("cuda", 16)])
def test_encoder_resolves_auto_batch_size(monkeypatch: pytest.MonkeyPatch, device: str, auto_bs: int) -> None:
    """The encoder accepts the raw config value ("auto"), so callers never pass a str to the model."""
    from maritime_rag.retrieval import dense

    model = _FakeSentenceTransformer()
    monkeypatch.setattr(dense, "load_sentence_transformer", lambda *a, **kw: model)
    enc = dense.SentenceTransformerEncoder("m", {"device": device, "batch_size": "auto"}, Path("."))
    assert (enc.batch_size, enc.dim) == (auto_bs, 3)
    for bs in ("auto", None, 2, "4"):
        enc.encode(["a"], bs)
    assert model.batch_sizes == [auto_bs, auto_bs, 2, 4]
    assert all(isinstance(b, int) for b in model.batch_sizes)


def test_index_cli_never_imports_the_reranker() -> None:
    src = (Path(__file__).parents[1] / "src/maritime_rag/retrieval/build.py").read_text(encoding="utf-8")
    assert "import" not in "".join(line for line in src.splitlines() if "rerank" in line.lower())

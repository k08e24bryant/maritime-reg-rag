"""Demo service shared by the JSON API and the Gradio UI.

One instance per server: the retrieval models (e5, bge reranker) load once, an Answerer per LLM
profile is created on first use (its startup probe runs then), and calls are serialised with a
lock because retrieval shares one GPU. Only the configured cloud profiles are offered.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from maritime_rag.answer.cli import source_rows
from maritime_rag.answer.pipeline import Answer, Answerer, Retrieval
from maritime_rag.answer.prompt import LanguageDetector
from maritime_rag.answer.providers import Provider, make_provider
from maritime_rag.answer.versions import page_label
from maritime_rag.config import load_config, load_env_file, resolve
from maritime_rag.retrieval.cli import locator
from maritime_rag.retrieval.corpus import Corpus


class InvalidQuestion(ValueError):
    """Empty or too long question."""


@dataclass
class DemoConfig:
    llms: list[str]
    default_llm: str
    rerank_default: bool
    max_question_chars: int
    examples: list[str]


class DemoService:
    def __init__(self, dcfg: DemoConfig, acfg: dict[str, Any], corpus: Corpus,
                 retrieve: Callable[[str, bool], Retrieval], provider_factory: Callable[[str], Provider],
                 detect: LanguageDetector, retrieval_info: dict[str, Any] | None = None) -> None:
        self.cfg = dcfg
        self.acfg = acfg
        self.corpus = corpus
        self.by_id = corpus.by_id()
        self.retrieve = retrieve  # (question, rerank) -> Retrieval
        self.provider_factory = provider_factory
        self.detect = detect
        self.retrieval_info = retrieval_info or {}
        self.answerers: dict[str, Answerer] = {}
        self.lock = threading.Lock()

    @classmethod
    def from_config(cls, path: str = "configs/demo.yaml") -> DemoService:
        from maritime_rag.answer.pipeline import SearcherRetrieve
        from maritime_rag.retrieval.search import Searcher

        raw = load_config(path)
        acfg = load_config(raw["answer_config"])
        acfg["gate"]["enabled"] = False  # as evaluated in Phase 4
        load_env_file(acfg["env_file"])
        rcfg = load_config(acfg["retrieval_config"])
        searcher = Searcher(rcfg)
        r = acfg["retrieval"]
        retrievers = {flag: SearcherRetrieve(searcher, r["retriever"], r["k"], flag) for flag in (True, False)}
        calls_file = resolve(acfg["logging"]["calls_file"])

        def provider(name: str) -> Provider:
            p = make_provider(acfg["llm"], name, calls_file=calls_file)  # never allow_local
            p.check()
            return p

        dcfg = DemoConfig(raw["llms"], raw["default_llm"], raw["rerank_default"], raw["max_question_chars"], raw["examples"])
        service = cls(dcfg, acfg, searcher.corpus, lambda q, rerank: retrievers[rerank](q), provider,
                      LanguageDetector(resolve(rcfg["paths"]["stopwords"])),
                      {"retriever": r["retriever"], "k": r["k"], "loader": retrievers})
        return service

    def load(self) -> float:
        """Load the retrieval models (e5 + reranker) before the first request."""
        loader = self.retrieval_info.get("loader")
        return loader[True].load() if loader else 0.0

    def answerer(self, llm: str) -> Answerer:
        if llm not in self.cfg.llms:
            raise InvalidQuestion(f"unknown LLM {llm!r}; choose from {self.cfg.llms}")
        if llm not in self.answerers:
            def no_retrieval(question: str) -> Retrieval:
                raise RuntimeError("the demo passes its own retrieval")

            self.answerers[llm] = Answerer(self.acfg, self.corpus, no_retrieval, self.provider_factory(llm), self.detect)
        return self.answerers[llm]

    def validate(self, question: str) -> str:
        q = " ".join((question or "").split())
        if not q:
            raise InvalidQuestion("the question is empty")
        if len(q) > self.cfg.max_question_chars:
            raise InvalidQuestion(f"the question is longer than {self.cfg.max_question_chars} characters")
        return q

    def ask(self, question: str, llm: str | None = None, rerank: bool | None = None) -> dict[str, Any]:
        q = self.validate(question)
        llm = llm or self.cfg.default_llm
        rerank = self.cfg.rerank_default if rerank is None else rerank
        with self.lock:
            answerer = self.answerer(llm)
            t0 = time.perf_counter()
            retrieval = self.retrieve(q, rerank)
            ans = answerer.answer(q, retrieval)
            total = time.perf_counter() - t0
        return self.to_dict(ans, answerer, llm, rerank, total)

    def to_dict(self, ans: Answer, answerer: Answerer, llm: str, rerank: bool, total_s: float) -> dict[str, Any]:
        g = ans.generation
        rows = source_rows(ans, answerer.names)
        return {
            "question": ans.question, "language": ans.language, "answer": ans.text,
            "refused": ans.refused, "refusal_reason": ans.refusal_reason, "disclaimer": ans.disclaimer,
            "warnings": ans.warnings,
            "sources": [{"n": r.n, "chunk_id": cc.chunk_id, "cite": r.cite, "where": r.where, "file_pages": r.file_pages,
                         "status": r.status, "cited": r.cited, "origin": r.origin} for r, cc in zip(rows, ans.context)],
            "citations": {"valid": sum(c.valid for c in ans.citations), "invalid": sum(not c.valid for c in ans.citations),
                          "normalized": sum(bool(c.normalized) for c in ans.citations if c.valid)},
            "llm": {"profile": llm, "model": g.model if g else self.acfg["llm"]["profiles"][llm]["model"], "called": g is not None},
            "retrieval": {"retriever": self.retrieval_info.get("retriever", "hybrid"), "rerank": rerank,
                          "k": self.retrieval_info.get("k"), "siblings_cut": ans.siblings_cut, "hits_dropped": ans.hits_dropped},
            "latency_s": {**{k: round(v, 3) for k, v in ans.times.items()}, "total_s": round(total_s, 3)},
            "tokens": None if g is None else {"prompt": g.prompt_tokens, "output": g.output_tokens},
            "cost_usd": None if g is None else g.cost_usd,
        }

    def source(self, chunk_id: str) -> dict[str, Any]:
        c = self.by_id.get(chunk_id)
        if c is None:
            raise KeyError(chunk_id)
        return {"chunk_id": chunk_id, "where": locator(c), "file": c["source_file"], "pages": page_label(c),
                "heading": c["heading"], "text": c["text"]}

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "chunks": len(self.corpus.chunks), "llms": self.cfg.llms, "default_llm": self.cfg.default_llm,
                "rerank_default": self.cfg.rerank_default, "loaded_llms": sorted(self.answerers)}


def eval_headline(path: str) -> list[str]:
    """The five headline lines of the Phase 4 report (empty if the report is missing)."""
    p = resolve(path)
    if not p.exists():
        return []
    return [h["text"] for h in json.loads(p.read_text(encoding="utf-8")).get("headline", [])]

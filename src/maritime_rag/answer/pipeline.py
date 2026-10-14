"""Answer pipeline: retrieve -> (score gate) -> version expansion -> prompt -> LLM -> citation post-check.

Refusals return the fixed "not found" message in the question's language, with a reason:
  no_hits            retrieval returned nothing
  gate               best reranker score below gate.min_rerank_score (gate off by default)
  model_not_found    the model said the sources do not contain the answer
  no_valid_citation  the model answered, but no citation matched a provided source
  truncated          the output limit cut the answer off; a partial answer is never returned
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol

from maritime_rag.answer.citations import (
    Citation,
    DocMatcher,
    normalize_brackets,
    parse_citations,
    rewrite,
    validate,
)
from maritime_rag.answer.prompt import LanguageDetector, build_messages
from maritime_rag.answer.providers import Generation, Message, Provider
from maritime_rag.answer.versions import (
    CURRENT,
    ContextChunk,
    DocNames,
    SiblingExpansion,
    VersionIndex,
    build_context,
    cite_as,
    expand_siblings,
    status_short,
)
from maritime_rag.retrieval.corpus import Corpus, Hit


@dataclass
class Retrieval:
    hits: list[Hit]
    reranked: bool
    times: dict[str, float]  # retrieve_s, rerank_s


class Retrieve(Protocol):
    def __call__(self, question: str) -> Retrieval: ...


class SearcherRetrieve:
    """First-stage retrieval and reranking timed separately; models load in load(), not per query."""

    def __init__(self, searcher: Any, retriever: str, k: int, rerank: bool) -> None:
        self.searcher = searcher
        self.retriever = retriever
        self.k = k
        self.rerank = rerank

    def load(self) -> float:
        t0 = time.perf_counter()
        self.searcher.retriever(self.retriever)
        if self.rerank:
            self.searcher.reranker()
        return time.perf_counter() - t0

    def __call__(self, question: str) -> Retrieval:
        depth = max(self.searcher.cfg["rerank"]["top_n"], self.k) if self.rerank else self.k
        t0 = time.perf_counter()
        hits = self.searcher.retriever(self.retriever).search(question, depth)
        times = {"retrieve_s": time.perf_counter() - t0}
        if self.rerank:
            t0 = time.perf_counter()
            hits = self.searcher.reranker().rerank(question, hits, self.k)
            times["rerank_s"] = time.perf_counter() - t0
        return Retrieval(hits, self.rerank, times)


@dataclass
class Answer:
    question: str
    language: str  # id | en
    text: str  # the post-checked answer, or the "not found" message
    refused: bool
    refusal_reason: str | None
    context: list[ContextChunk]
    reranked: bool
    top_score: float | None
    times: dict[str, float]
    raw_text: str | None = None  # model output before the post-check
    citations: list[Citation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    disclaimer: str | None = None
    generation: Generation | None = None
    messages: list[Message] = field(default_factory=list)
    siblings_cut: list[str] = field(default_factory=list)  # same-Pasal chunks left out by the token budget
    hits_dropped: list[str] = field(default_factory=list)  # low-ranked hits removed to fit the top Pasal

    @property
    def truncated(self) -> bool:
        return self.refusal_reason == "truncated"

    @property
    def result(self) -> str:
        """answered | TRUNCATED | refused: <reason> (a truncated answer never counts as an answer)."""
        if self.truncated:
            return "TRUNCATED"
        return f"refused: {self.refusal_reason}" if self.refused else "answered"

    @property
    def cited(self) -> set[int]:
        """1-based context indexes cited by at least one valid citation."""
        return {c.source for c in self.citations if c.source is not None}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


class Answerer:
    def __init__(
        self, cfg: dict[str, Any], corpus: Corpus, retrieve: Retrieve, provider: Provider, detect: LanguageDetector
    ) -> None:
        """cfg = configs/answer.yaml."""
        gate = cfg["gate"]
        if gate["enabled"] and gate["min_rerank_score"] is None:
            raise ValueError("gate.enabled is true but gate.min_rerank_score is not set (configs/answer.yaml)")
        self.cfg = cfg
        self.retrieve = retrieve
        self.provider = provider
        self.detect = detect
        self.index = VersionIndex(corpus)
        self.names = DocNames(corpus, cfg.get("short_names"))
        self.match_doc = DocMatcher(self.names)
        self.msgs = cfg["messages"]

    def context_for(self, hits: list[Hit]) -> tuple[list[ContextChunk], SiblingExpansion]:
        """The answer context for retrieved hits: version expansion, then same-Pasal expansion."""
        v = self.cfg["versions"]
        context = build_context(hits, self.index, v["max_added_chunks"])
        sib = expand_siblings(context, self.index, v["max_context_tokens"], v["sibling_priority_hits"])
        return context, sib

    def answer(self, question: str, retrieval: Retrieval | None = None) -> Answer:
        """retrieval: a precomputed (e.g. cached) retrieval instead of calling self.retrieve."""
        lang = self.detect(question)
        r = retrieval if retrieval is not None else self.retrieve(question)
        times = dict(r.times)
        top = r.hits[0].score if r.hits and r.reranked else None
        context, sib = self.context_for(r.hits)
        ans = Answer(question, lang, "", False, None, context, r.reranked, top, times,
                     siblings_cut=sib.cut, hits_dropped=sib.dropped)
        if not r.hits:
            return self._refuse(ans, "no_hits")
        gate = self.cfg["gate"]
        if gate["enabled"]:
            if not r.reranked:
                raise ValueError("the retrieval-score gate needs the reranker; drop --no-rerank or disable gate")
            if top is not None and top < gate["min_rerank_score"]:
                return self._refuse(ans, "gate")

        ans.messages = build_messages(question, lang, context, self.names, self.index, self.cfg)
        ans.generation = self.provider.generate(ans.messages)
        times["generate_s"] = ans.generation.latency_s
        if ans.generation.wait_s:
            times["llm_wait_s"] = ans.generation.wait_s  # rate-limit pacing and 429 backoff
        ans.raw_text = ans.generation.text.strip()
        if ans.generation.truncated:
            return self._refuse(ans, "truncated")
        return self._postcheck(ans)

    def _postcheck(self, ans: Answer) -> Answer:
        pc = self.cfg["postcheck"]
        text = normalize_brackets(ans.raw_text or "")
        ans.citations = parse_citations(text, self.match_doc)
        validate(ans.citations, ans.context, pc["fill_missing_page"], self.names)
        if not ans.cited:
            said_not_found = any(_normalize(m) in _normalize(ans.raw_text or "") for m in self.msgs["not_found"].values())
            return self._refuse(ans, "model_not_found" if said_not_found else "no_valid_citation")

        lang = ans.language
        ans.text = rewrite(text, ans.citations, pc["invalid_citations"], self.msgs["unverified_marker"])
        invalid = [c.raw for c in ans.citations if not c.valid]
        if invalid:
            ans.warnings.append(self.msgs["invalid_citations"][lang].format(
                n=len(invalid), cites="; ".join(f"[{c}]" for c in invalid)))
        flagged = [c.raw for c in ans.citations if c.valid and c.flag]
        if flagged:
            ans.warnings.append(self.msgs["ayat_not_in_text"][lang].format(
                n=len(flagged), cites="; ".join(f"[{c}]" for c in flagged)))
        cited = [ans.context[i - 1] for i in sorted(ans.cited)]
        for cc in cited:
            if cc.status != CURRENT:
                ans.warnings.append(self.msgs["cites_outdated"][lang].format(
                    cite=cite_as(cc.chunk, self.names), status=status_short(cc, self.names)))
        flagged: dict[str, list[str]] = {}
        for cc in cited:
            if cc.out_of_corpus:
                flagged.setdefault(cc.chunk["doc_id"], cc.out_of_corpus)
        for doc_id, amenders in flagged.items():
            ans.warnings.append(self.msgs["out_of_corpus"][lang].format(doc=self.names(doc_id), amenders=", ".join(amenders)))
        revoked: dict[str, list[str]] = {}
        for cc in cited:
            if cc.partly_revoked_by:
                revoked.setdefault(cc.chunk["doc_id"], cc.partly_revoked_by)
        for doc_id, by in revoked.items():
            ans.warnings.append(self.msgs["partly_revoked"][lang].format(
                doc=self.names(doc_id), by=", ".join(self.names(d) for d in by)))
        ans.disclaimer = self.msgs["disclaimer"][lang]
        return ans

    def _refuse(self, ans: Answer, reason: str) -> Answer:
        ans.refused, ans.refusal_reason = True, reason
        ans.text = self.msgs["truncated" if reason == "truncated" else "not_found"][ans.language]
        return ans

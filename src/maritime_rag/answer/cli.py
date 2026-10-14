"""CLI: uv run maritime-ask "pertanyaan" [--no-rerank] [--provider ollama|openai|anthropic|groq|google] [--model NAME]

Prints the answer, a numbered source list (document, Pasal/ayat, page, version status),
warnings, the citation check, and latency per stage. Exit code 2 when the LLM cannot be called.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from typing import Any

from maritime_rag.answer.pipeline import Answer, Answerer, SearcherRetrieve
from maritime_rag.answer.prompt import LanguageDetector
from maritime_rag.answer.providers import PROVIDERS, ProviderError, make_provider
from maritime_rag.answer.versions import DocNames, cite_as, status_short
from maritime_rag.config import load_config, load_env_file, resolve
from maritime_rag.retrieval.cli import locator, pages


@dataclass
class App:
    cfg: dict[str, Any]
    answerer: Answerer
    retrieve: SearcherRetrieve
    names: DocNames


def build_app(config_path: str, provider: str | None, model: str | None, rerank: bool | None) -> App:
    """Wire config -> provider (checked) -> searcher -> answerer. Retrieval models load in App.retrieve.load()."""
    from maritime_rag.retrieval.search import Searcher

    cfg = load_config(config_path)
    load_env_file(cfg["env_file"])
    rcfg = load_config(cfg["retrieval_config"])
    llm = make_provider(cfg["provider"], provider, model, resolve(cfg["logging"]["calls_file"]))
    llm.check()  # before loading the retrieval models
    searcher = Searcher(rcfg)
    r = cfg["retrieval"]
    retrieve = SearcherRetrieve(searcher, r["retriever"], r["k"], r["rerank"] if rerank is None else rerank)
    detect = LanguageDetector(resolve(rcfg["paths"]["stopwords"]))
    answerer = Answerer(cfg, searcher.corpus, retrieve, llm, detect)
    return App(cfg, answerer, retrieve, answerer.names)


@dataclass
class SourceRow:
    n: int
    cite: str
    where: str  # "PM 74/2016 Pasal 71 ayat (1)-(6)"
    file_pages: str  # "pm_74_2016.pdf p. 11-12"
    status: str
    cited: bool
    origin: str  # "retrieved #2 (0.812)" | "added: version expansion"


def source_rows(ans: Answer, names: DocNames) -> list[SourceRow]:
    rows = []
    for i, cc in enumerate(ans.context, start=1):
        if cc.retrieved_rank is None:
            origin = "added: version expansion"
        else:
            origin = f"retrieved #{cc.retrieved_rank}" + (f" ({cc.score:.3f})" if ans.reranked and cc.score is not None else "")
        rows.append(SourceRow(i, cite_as(cc.chunk, names), locator(cc.chunk), pages(cc.chunk),
                              status_short(cc, names), i in ans.cited, origin))
    return rows


def latency_line(ans: Answer, load_s: float | None = None) -> str:
    t = ans.times
    parts = [f"load {load_s:.1f} s (models, once)"] if load_s is not None else []
    parts.append(f"retrieve {t['retrieve_s']:.2f} s")
    if "rerank_s" in t:
        parts.append(f"rerank {t['rerank_s']:.2f} s")
    if "generate_s" in t:
        parts.append(f"generate {t['generate_s']:.1f} s")
    return " | ".join(parts)


def token_line(ans: Answer) -> str | None:
    g = ans.generation
    if g is None:
        return None
    line = f"{g.provider} {g.model}: {g.prompt_tokens} prompt + {g.output_tokens} output tokens"
    return line + (f" (model load {g.load_s:.1f} s)" if g.load_s else "")


def citation_check(ans: Answer) -> str:
    valid = sum(c.valid for c in ans.citations)
    lines = [f"{valid} valid, {len(ans.citations) - valid} invalid"]
    lines += [f"  invalid: [{c.raw}]: {c.problem}" for c in ans.citations if not c.valid]
    return "\n".join(lines)


def format_terminal(ans: Answer, app: App, load_s: float | None) -> str:
    r = app.retrieve
    added = sum(1 for c in ans.context if c.retrieved_rank is None)
    out = [
        f"Question: {ans.question}",
        f"Retrieval: {r.retriever}{'+rerank' if ans.reranked else ''}, k={r.k}"
        + (f" (+{added} added by version expansion)" if added else ""),
        "",
        "Answer:",
        ans.text,
    ]
    if ans.refused:
        out.append(f"(refusal reason: {ans.refusal_reason})")
    if ans.disclaimer:
        out += ["", ans.disclaimer]
    if ans.warnings:
        out += ["", "Warnings:"] + [f"  - {w}" for w in ans.warnings]
    out += ["", "Sources:" if not ans.refused else "Retrieved (not used for an answer):"]
    for s in source_rows(ans, app.names):
        mark = "cited" if s.cited else "not cited"
        out.append(f"  {s.n}. {s.where}  ({s.file_pages})")
        out.append(f"     {s.status} | {mark} | {s.origin}")
    if ans.raw_text is not None:
        out += ["", "Citation check: " + citation_check(ans)]
    out += ["", "Latency: " + latency_line(ans, load_s)]
    if tl := token_line(ans):
        out.append("Tokens: " + tl)
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Answer a question from the regulation corpus, with citations.")
    parser.add_argument("question")
    parser.add_argument("--config", default="configs/answer.yaml")
    parser.add_argument("--provider", choices=PROVIDERS, help="default: provider.default in the config")
    parser.add_argument("--model", help="override the provider's model, e.g. qwen2.5:3b-instruct")
    parser.add_argument("--no-rerank", action="store_true", help="skip the cross-encoder reranker")
    parser.add_argument("--show-prompt", action="store_true", help="print the messages sent to the model")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    try:
        app = build_app(args.config, args.provider, args.model, False if args.no_rerank else None)
        load_s = app.retrieve.load()
        ans = app.answerer.answer(args.question)
    except ProviderError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    if args.show_prompt:
        for m in ans.messages:
            print(f"----- {m['role']} -----\n{m['content']}\n")
    print(format_terminal(ans, app, load_s))


if __name__ == "__main__":
    main()

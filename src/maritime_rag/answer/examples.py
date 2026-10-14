"""Answer the example questions (smoke query ids in examples.queries) -> reports/answer_examples.md.

Not an evaluation (no gold answers; that is Phase 4): a readable record of answers, sources,
version labels, warnings, the citation check and latency per stage.
Usage: uv run maritime-answer-examples [--no-rerank] [--provider ollama|openai|anthropic|groq|google] [--model NAME]
"""

from __future__ import annotations

import argparse
import logging
import platform
import sys
from datetime import date

import yaml

from maritime_rag.answer.cli import App, build_app, latency_line, source_rows, token_line
from maritime_rag.answer.pipeline import Answer
from maritime_rag.answer.providers import PROVIDERS, ProviderError
from maritime_rag.config import load_config, resolve


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _quote(text: str) -> list[str]:
    return [f"> {line}" if line.strip() else ">" for line in text.splitlines()]


def _section(qid: str, expect: str, ans: Answer, app: App) -> list[str]:
    out = ["", f"## {qid}: {ans.question}", "", f"Expect (hint written with the query): {expect}", ""]
    status = f"refused ({ans.refusal_reason})" if ans.refused else "answered"
    out += [f"**Answer** ({status}, language: {ans.language})", ""] + _quote(ans.text)
    if ans.disclaimer:
        out += ["", f"_{ans.disclaimer}_"]
    if ans.warnings:
        out += ["", "**Warnings**", ""] + [f"- {w}" for w in ans.warnings]
    if ans.raw_text is not None and ans.raw_text != ans.text:
        out += ["", "<details><summary>Model output before the post-check</summary>", ""]
        out += _quote(ans.raw_text) + ["", "</details>"]
    out += ["", "**Sources**" if not ans.refused else "**Retrieved (not used for an answer)**", "",
            "| # | where | file, pages | status | cited | origin |", "|---|---|---|---|---|---|"]
    for s in source_rows(ans, app.names):
        out.append(f"| {s.n} | {_cell(s.where)} | {_cell(s.file_pages)} | {_cell(s.status)} | "
                   f"{'yes' if s.cited else 'no'} | {_cell(s.origin)} |")
    if ans.raw_text is not None:
        valid = sum(c.valid for c in ans.citations)
        out += ["", f"**Citation check**: {valid} valid, {len(ans.citations) - valid} invalid"]
        out += [f"- invalid `[{c.raw}]`: {c.problem}" for c in ans.citations if not c.valid]
    out += ["", f"**Latency**: {latency_line(ans)}"]
    if tl := token_line(ans):
        out.append(f"**Tokens**: {tl}")
    return out


def run(config_path: str, provider: str | None, model: str | None, rerank: bool | None) -> str:
    import torch

    app = build_app(config_path, provider, model, rerank)
    cfg = app.cfg
    rcfg = load_config(cfg["retrieval_config"])
    queries = {q["id"]: q for q in yaml.safe_load(resolve(rcfg["paths"]["smoke_queries"]).read_text(encoding="utf-8"))["queries"]}
    missing = [q for q in cfg["examples"]["queries"] if q not in queries]
    if missing:
        raise SystemExit(f"unknown query ids in examples.queries: {missing}")

    print("loading retrieval models", file=sys.stderr)
    load_s = app.retrieve.load()
    answers: list[tuple[str, str, Answer]] = []
    for qid in cfg["examples"]["queries"]:
        print(f"answering {qid}", file=sys.stderr)
        q = queries[qid]
        answers.append((qid, q["expect"], app.answerer.answer(q["text"])))

    llm = app.answerer.provider
    r = app.retrieve
    gate = cfg["gate"]
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none"
    out = [
        "# Answer examples (Phase 3)",
        "",
        f"{len(answers)} smoke queries answered end to end. Not an evaluation: no gold answers, no metrics "
        "(Phase 4). Generated "
        f"{date.today().isoformat()} on {platform.processor() or platform.machine()}, GPU: {gpu}.",
        "",
        f"LLM: {llm.name} `{llm.model}`"
        + (f" (num_ctx {cfg['provider']['ollama']['num_ctx']}, temperature {cfg['provider']['ollama']['temperature']}, "
           f"seed {cfg['provider']['ollama']['seed']})" if llm.name == "ollama" else "")
        + f". Retrieval: {r.retriever}{'+rerank' if r.rerank else ''}, k={r.k}; version expansion adds at most "
        f"{cfg['versions']['max_added_chunks']} chunks. Score gate: "
        + (f"on (min rerank score {gate['min_rerank_score']})" if gate["enabled"] else "off")
        + f". Invalid citations: {cfg['postcheck']['invalid_citations']}. Retrieval model load: {load_s:.1f} s (once). "
        "The first LLM call includes loading the model into memory.",
        "",
        "| query | lang | result | citations valid/invalid | sources (retrieved + added) | warnings | retrieve s | rerank s | generate s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for qid, _, a in answers:
        valid = sum(c.valid for c in a.citations)
        added = sum(1 for c in a.context if c.retrieved_rank is None)
        t = a.times
        out.append(
            f"| {qid} | {a.language} | {'refused: ' + (a.refusal_reason or '') if a.refused else 'answered'} | "
            f"{valid}/{len(a.citations) - valid} | {len(a.context) - added} + {added} | {len(a.warnings)} | "
            f"{t['retrieve_s']:.2f} | {t.get('rerank_s', 0):.2f} | {t.get('generate_s', 0):.1f} |"
        )
    for qid, expect, a in answers:
        out += _section(qid, expect, a, app)
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="configs/answer.yaml")
    parser.add_argument("--provider", choices=PROVIDERS)
    parser.add_argument("--model")
    parser.add_argument("--no-rerank", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        report = run(args.config, args.provider, args.model, False if args.no_rerank else None)
    except ProviderError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    out = resolve(load_config(args.config)["examples"]["output"])
    out.write_text(report, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

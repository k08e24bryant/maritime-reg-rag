"""Answer the example questions (smoke query ids in examples.queries) -> reports/answer_examples.md.

Not an evaluation (no gold answers; that is Phase 4): a readable record of answers, sources,
version labels, warnings, the citation check, latency per stage, and the LLM (profile + model id)
behind every answer. --per-llm writes reports/answer_examples_<llm>.md, so runs with different
LLMs sit side by side; the retrieval fingerprint per question shows whether they saw the same context.
--merge with --only re-runs those questions and replaces only their rows and sections in the
existing report (the other questions keep their earlier results, noted in the report).
A truncated answer (output limit reached) is reported as TRUNCATED and never counts as answered.

Usage: uv run maritime-answer-examples [--llm groq|gemini|openai|anthropic] [--model ID]
       [--only QUERY_ID ... [--merge]] [--per-llm | --output PATH] [--no-rerank]
       (a local LLM needs: --llm ollama --allow-local)
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import platform
import re
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

from maritime_rag.answer.cli import App, build_app, latency_line, source_rows, token_line
from maritime_rag.answer.pipeline import Answer
from maritime_rag.answer.providers import ProviderError
from maritime_rag.config import load_config, resolve


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _quote(text: str) -> list[str]:
    return [f"> {line}" if line.strip() else ">" for line in text.splitlines()]


def fingerprint(ans: Answer) -> str:
    """Short hash of the context chunk ids in order: equal across reports = identical retrieval."""
    return hashlib.sha256(" ".join(c.chunk_id for c in ans.context).encode()).hexdigest()[:8]


def llm_label(ans: Answer, app: App) -> str:
    llm = app.answerer.provider
    if ans.generation is None:
        return f"{llm.name} `{llm.model}` (not called)"
    return f"{ans.generation.provider} `{ans.generation.model}`"


def _section(qid: str, expect: str, ans: Answer, app: App) -> list[str]:
    out = ["", f"## {qid}: {ans.question}", "", f"Expect (hint written with the query): {expect}", ""]
    if ans.truncated:
        limit = ans.generation.max_output_tokens if ans.generation else "?"
        status = f"**TRUNCATED** at the {limit}-token output limit; not counted as an answer"
    else:
        status = f"refused ({ans.refusal_reason})" if ans.refused else "answered"
    out += [f"**Answer** ({status}, language: {ans.language}, LLM: {llm_label(ans, app)})", ""] + _quote(ans.text)
    if ans.disclaimer:
        out += ["", f"_{ans.disclaimer}_"]
    if ans.warnings:
        out += ["", "**Warnings**", ""] + [f"- {w}" for w in ans.warnings]
    if ans.raw_text is not None and ans.raw_text != ans.text:
        summary = "Truncated model output (not used)" if ans.truncated else "Model output before the post-check"
        out += ["", f"<details><summary>{summary}</summary>", ""]
        out += _quote(ans.raw_text) + ["", "</details>"]
    out += ["", ("**Sources**" if not ans.refused else "**Retrieved (not used for an answer)**")
            + f" (retrieval fingerprint `{fingerprint(ans)}`)", "",
            "| # | where | file, pages | status | cited | origin |", "|---|---|---|---|---|---|"]
    for s in source_rows(ans, app.names):
        out.append(f"| {s.n} | {_cell(s.where)} | {_cell(s.file_pages)} | {_cell(s.status)} | "
                   f"{'yes' if s.cited else 'no'} | {_cell(s.origin)} |")
    if ans.siblings_cut:
        out += ["", f"Token budget cut {len(ans.siblings_cut)} same-Pasal chunk(s): {', '.join(ans.siblings_cut)}"]
    if ans.hits_dropped:
        out += ["", f"Dropped {len(ans.hits_dropped)} low-ranked hit(s) to fit the top Pasal: {', '.join(ans.hits_dropped)}"]
    if ans.raw_text is not None and not ans.truncated:
        valid = sum(c.valid for c in ans.citations)
        flagged = sum(1 for c in ans.citations if c.valid and c.flag)
        normalized = sum(1 for c in ans.citations if c.valid and c.normalized)
        out += ["", f"**Citation check**: {valid} valid ({flagged} flagged, {normalized} normalized), "
                    f"{len(ans.citations) - valid} invalid"]
        out += [f"- invalid `{c.raw}`: {c.problem}" for c in ans.citations if not c.valid]
        out += [f"- flagged `{c.raw}`: {c.flag}" for c in ans.citations if c.valid and c.flag]
        out += [f"- normalized `{c.raw}` -> `{c.canonical}`: {', '.join(c.normalized)}"
                for c in ans.citations if c.valid and c.normalized]
    out += ["", f"**Latency**: {latency_line(ans)}"]
    if tl := token_line(ans):
        out.append(f"**Tokens**: {tl}")
    return out


def _llm_settings(app: App) -> str:
    llm = app.answerer.provider
    prof = app.cfg["llm"]["profiles"][llm.name]
    parts = [f"type {prof['type']}"]
    if prof["type"] == "ollama":
        parts += [f"num_ctx {prof['num_ctx']}", f"temperature {prof['temperature']}", f"seed {prof['seed']}"]
    else:
        parts.append(f"temperature {prof.get('temperature') if prof.get('temperature') is not None else 'provider default'}")
        if prof.get("extra"):
            parts.append(", ".join(f"{k} {v}" for k, v in prof["extra"].items()))
        if prof.get("min_interval_s"):
            parts.append(f"min {prof['min_interval_s']} s between calls")
        if prof.get("tokens_per_minute"):
            parts.append(f"budget {prof['tokens_per_minute']} tokens/min")
    return f"LLM profile `{llm.name}`: `{llm.model}` ({', '.join(parts)})"


def _resources(app: App, ram_mb: float, vram_mb: float, device: str) -> str:
    llm = app.answerer.provider
    prof_type = app.cfg["llm"]["profiles"][llm.name]["type"]
    rr = app.retrieve.searcher.loaded_reranker
    local = [f"e5 encoder ({device})"] + ([f"reranker {rr.model_id} ({rr.device})"] if rr else [])
    where = ("Ollama runs in its own process, so its memory is not in these numbers"
             if prof_type == "ollama" else "the LLM runs remotely; nothing else runs locally")
    return (f"Local models: {', '.join(local)}; {where}. Peak RAM of this process (psutil, peak working set): "
            f"{ram_mb:.0f} MB; peak VRAM (torch.cuda.max_memory_allocated): {vram_mb:.0f} MB.")


TABLE_HEAD = [
    "| query | lang | result | LLM model | citations valid/invalid | sources (retrieved + added) | retrieval fingerprint "
    "| warnings | retrieve s | rerank s | generate s | tokens in/out |",
    "|---|---|---|---|---|---|---|---|---|---|---|---|",
]


def summary_row(qid: str, a: Answer) -> str:
    valid = sum(c.valid for c in a.citations)
    added = sum(1 for c in a.context if c.retrieved_rank is None)
    t, g = a.times, a.generation
    result = "**TRUNCATED**" if a.truncated else a.result
    cites = "-" if a.truncated else f"{valid}/{len(a.citations) - valid}"
    return (
        f"| {qid} | {a.language} | {result} | {f'`{g.model}`' if g else '-'} | {cites} | "
        f"{len(a.context) - added} + {added} | `{fingerprint(a)}` | {len(a.warnings)} | {t['retrieve_s']:.2f} | "
        f"{t.get('rerank_s', 0):.2f} | {t.get('generate_s', 0):.1f} | {f'{g.prompt_tokens}/{g.output_tokens}' if g else '-'} |"
    )


def split_report(text: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Summary rows and sections per query id from an existing report."""
    rows: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].split(":", 1)[0].strip()
            sections[current] = [line]
        elif current is not None:
            sections[current].append(line)
        elif (m := re.match(r"\| (\S+) \| ", line)) and m[1] != "query":
            rows[m[1]] = line
    for lines in sections.values():
        while lines and not lines[-1].strip():
            lines.pop()
    return rows, sections


def run(config_path: str, llm_profile: str | None, model: str | None, rerank: bool | None,
        only: list[str] | None, allow_local: bool = False, merge_into: str | None = None) -> tuple[str, App]:
    """merge_into: text of an existing report whose rows/sections for the re-run ids are replaced."""
    import torch

    from maritime_rag.retrieval.build import peak_ram_mb
    from maritime_rag.retrieval.dense import resolve_device

    app = build_app(config_path, llm_profile, model, rerank, allow_local)
    cfg = app.cfg
    rcfg = load_config(cfg["retrieval_config"])
    queries = {q["id"]: q for q in yaml.safe_load(resolve(rcfg["paths"]["smoke_queries"]).read_text(encoding="utf-8"))["queries"]}
    ids = only or cfg["examples"]["queries"]
    missing = [q for q in ids if q not in queries]
    if missing:
        raise SystemExit(f"unknown query ids: {missing}; known: {', '.join(queries)}")

    print("loading retrieval models", file=sys.stderr)
    load_s = app.retrieve.load()
    answers: list[tuple[str, str, Answer]] = []
    for qid in ids:
        print(f"answering {qid}", file=sys.stderr)
        q = queries[qid]
        answers.append((qid, q["expect"], app.answerer.answer(q["text"])))

    rows = {qid: summary_row(qid, a) for qid, _, a in answers}
    sections = {qid: _section(qid, expect, a, app)[1:] for qid, expect, a in answers}  # [1:]: leading blank
    merged_note = []
    if merge_into is not None:
        old_rows, old_sections = split_report(merge_into)
        kept = [q for q in old_rows if q not in rows]
        rows, sections = old_rows | rows, old_sections | sections
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        merged_note = ["", f"Merged report: {', '.join(ids)} re-run {stamp} with the settings below; "
                           f"{', '.join(kept) or 'no other questions'} kept from the previous run (their own LLM "
                           "model and tokens are in their rows)."]
    order = [q for q in cfg["examples"]["queries"] if q in rows] + [q for q in rows if q not in cfg["examples"]["queries"]]

    r = app.retrieve
    gate = cfg["gate"]
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none"
    vram = torch.cuda.max_memory_allocated() / 2**20 if torch.cuda.is_available() else 0.0
    gens = [a.generation for _, _, a in answers if a.generation]
    tokens = sum((g.prompt_tokens or 0) + (g.output_tokens or 0) for g in gens)
    truncated = sum(1 for _, _, a in answers if a.truncated)
    out = [
        "# Answer examples (Phase 3)",
        "",
        f"{len(order)} smoke queries answered end to end. Not an evaluation: no gold answers, no metrics "
        f"(Phase 4). Generated {date.today().isoformat()} on {platform.processor() or platform.machine()}, GPU: {gpu}.",
        *merged_note,
        "",
        _llm_settings(app) + f". This run: {len(gens)} LLM calls, {tokens} tokens in total, "
        f"{sum(g.retries for g in gens)} retries, {sum(g.wait_s for g in gens):.1f} s rate-limit wait"
        + (f", {truncated} TRUNCATED (not counted as answers)" if truncated else "") + ".",
        "",
        f"Retrieval: {r.retriever}{'+rerank' if r.rerank else ''}, k={r.k}; version expansion adds at most "
        f"{cfg['versions']['max_added_chunks']} chunks; same-Pasal chunks are added within "
        f"{cfg['versions']['max_context_tokens']} context tokens. Score gate: "
        + (f"on (min rerank score {gate['min_rerank_score']})" if gate["enabled"] else "off")
        + f". Invalid citations: {cfg['postcheck']['invalid_citations']}. Retrieval model load: {load_s:.1f} s (once).",
        "",
        _resources(app, peak_ram_mb(), vram, resolve_device(rcfg["dense"]["device"])),
        "",
        *TABLE_HEAD,
    ]
    out += [rows[q] for q in order]
    for q in order:
        out += [""] + sections[q]
    return "\n".join(out) + "\n", app


def output_path(cfg: dict, llm_name: str, per_llm: bool, output: str | None) -> Path:
    if output:
        return resolve(output)
    return resolve(cfg["examples"]["output_per_llm"].format(llm=llm_name) if per_llm else cfg["examples"]["output"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="configs/answer.yaml")
    parser.add_argument("--llm", "--provider", dest="llm", help="LLM profile (default: llm.default)")
    parser.add_argument("--allow-local", action="store_true", help="required with --llm ollama")
    parser.add_argument("--model", help="override the profile's model id")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--only", nargs="+", metavar="QUERY_ID", help="answer only these smoke query ids")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--per-llm", action="store_true", help="write reports/answer_examples_<llm>.md")
    where.add_argument("--output", help="write the report to this path")
    parser.add_argument("--merge", action="store_true",
                        help="with --only: replace only those questions in the existing report")
    args = parser.parse_args()
    if args.merge and not args.only:
        parser.error("--merge needs --only QUERY_ID ...")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("maritime_rag.answer.providers").setLevel(logging.INFO)  # tokens + last-60-s usage per call
    cfg = load_config(args.config)
    merge_into = None
    if args.merge:
        target = output_path(cfg, args.llm or cfg["llm"]["default"], args.per_llm, args.output)
        if not target.exists():
            parser.error(f"--merge: {target} does not exist; run all questions first")
        merge_into = target.read_text(encoding="utf-8")
    try:
        report, app = run(args.config, args.llm, args.model, False if args.no_rerank else None, args.only,
                          args.allow_local, merge_into)
    except ProviderError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    out = output_path(app.cfg, app.answerer.provider.name, args.per_llm, args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

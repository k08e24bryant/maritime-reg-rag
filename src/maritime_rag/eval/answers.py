"""Phase 4 Step 3: answer evaluation on the frozen gold set (docs/eval_plan.md, section 3).

Commands, in order:
  contexts   local (e5 + reranker, no LLM): retrieve once per question with the configuration
             selected in Step 2, build the answer context (version + same-Pasal + Penjelasan->body
             expansion) and store hits + context fingerprint -> data/eval/cache/contexts.json
  budget     one tiny probe per LLM (rate-limit headers), then the token and cost estimate for
             Step 3 + Step 4 from the stored contexts; warns above answers.cost_estimate.stop_above_usd
  run        --llm groq | groq-qwen: answer every question from the stored contexts (no retrieval
             models needed). Each answer is appended to data/eval/cache/answers_<llm>.jsonl, keyed by
             (question, context fingerprint, model, prompt version); cached answers are never asked
             again. A quota / spend-limit / API error stops the run cleanly; re-run to resume.
  report     automatic metrics for all LLMs -> reports/eval_answers.json and .md

The score gate is forced off (plan). Both LLMs answer from the same stored context: `run` checks
that the context rebuilt from the cached hits has the stored fingerprint before any LLM call.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from maritime_rag.answer.pipeline import Answer, Answerer, Retrieval
from maritime_rag.answer.prompt import LanguageDetector, build_messages
from maritime_rag.answer.providers import Message, ProviderError, make_provider
from maritime_rag.answer.versions import CURRENT, ContextChunk
from maritime_rag.config import load_config, load_env_file, resolve
from maritime_rag.eval.questions import OUT_OF_SCOPE, load_gold_csv
from maritime_rag.retrieval.corpus import Corpus, Hit, load_corpus

log = logging.getLogger(__name__)

# Step 2 configuration name -> (retriever, rerank) of the answer pipeline
SELECTION_TO_PIPELINE = {"hybrid_rerank": ("hybrid", True), "hybrid": ("hybrid", False),
                         "dense": ("dense", False), "bm25": ("bm25", False)}
QUOTA_HINTS = ("429", "402", "quota", "spend", "limit", "billing", "insufficient")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(context: list[ContextChunk]) -> str:
    """Same as maritime_rag.answer.examples.fingerprint: context chunk ids in order."""
    return hashlib.sha256(" ".join(c.chunk_id for c in context).encode()).hexdigest()[:8]


def prompt_version(acfg: dict[str, Any], profile: dict[str, Any]) -> str:
    """Everything besides the context that shapes a generation: prompt, messages, post-check,
    and the profile's generation settings."""
    keys = {k: profile.get(k) for k in ("model", "temperature", "extra", "max_output_tokens", "max_tokens_param")}
    blob = json.dumps({"prompt": acfg["prompt"], "messages": acfg["messages"], "postcheck": acfg["postcheck"],
                       "short_names": acfg.get("short_names"), "profile": keys}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:10]


@dataclass
class Setup:
    ecfg: dict[str, Any]
    acfg: dict[str, Any]  # answer config with the gate forced off
    corpus: Corpus
    questions: list[dict[str, Any]]
    detect: LanguageDetector


def setup(config_path: str) -> Setup:
    ecfg = load_config(config_path)
    acfg = copy.deepcopy(load_config(ecfg["answers"]["answer_config"]))
    acfg["gate"]["enabled"] = False  # plan: gate off for Step 3
    load_env_file(acfg["env_file"])
    rcfg = load_config(acfg["retrieval_config"])
    corpus = load_corpus(resolve(rcfg["paths"]["chunks_file"]))
    gold = resolve(ecfg["paths"]["gold_csv"])
    if not gold.exists():
        sys.exit(f"{gold} not found (Step 1)")
    return Setup(ecfg, acfg, corpus, load_gold_csv(gold), LanguageDetector(resolve(rcfg["paths"]["stopwords"])))


def answerer_for(s: Setup, provider: Any) -> Answerer:
    def no_retrieval(question: str) -> Retrieval:
        raise RuntimeError("Step 3 answers only from stored contexts")

    return Answerer(s.acfg, s.corpus, no_retrieval, provider, s.detect)


# --- contexts ----------------------------------------------------------------------------------

def stored_retrieval(entry: dict[str, Any], by_id: dict[str, dict]) -> Retrieval:
    hits = [Hit(cid, score, rank, entry["retriever"], by_id[cid]) for cid, score, rank in entry["hits"]]
    return Retrieval(hits, entry["reranked"], dict(entry["times"]))


def build_contexts(s: Setup) -> dict[str, Any]:
    from maritime_rag.answer.pipeline import SearcherRetrieve
    from maritime_rag.retrieval.search import Searcher

    a = s.ecfg["answers"]
    selection = json.loads(resolve(a["selection_from"]).read_text(encoding="utf-8"))["selection"]["selected"]
    if selection not in SELECTION_TO_PIPELINE:
        sys.exit(f"selected retrieval {selection!r} has no answer-pipeline equivalent")
    retriever, rerank = SELECTION_TO_PIPELINE[selection]
    rcfg = load_config(s.acfg["retrieval_config"])
    searcher = Searcher(rcfg, corpus=s.corpus)
    retrieve = SearcherRetrieve(searcher, retriever, s.acfg["retrieval"]["k"], rerank)
    print(f"loading retrieval models for {selection}", file=sys.stderr)
    retrieve.load()
    answerer = answerer_for(s, provider=None)
    entries = {}
    for q in s.questions:
        r = retrieve(q["question"])
        context, sib = answerer.context_for(r.hits)
        entries[q["id"]] = {
            "question": q["question"], "retriever": f"{retriever}{'+rerank' if rerank else ''}", "reranked": r.reranked,
            "hits": [[h.chunk_id, h.score, h.rank] for h in r.hits], "times": r.times,
            "top_score": r.hits[0].score if r.hits else None,
            "context_ids": [c.chunk_id for c in context], "fingerprint": fingerprint(context),
            "siblings_cut": sib.cut, "hits_dropped": sib.dropped,
        }
    meta = {
        "created": datetime.now().isoformat(timespec="minutes"),
        "selected_retrieval": selection, "k": s.acfg["retrieval"]["k"],
        "gold_sha256": sha256_file(resolve(s.ecfg["paths"]["gold_csv"])), "chunks_sha256": s.corpus.sha256,
        "versions": s.acfg["versions"],
    }
    return {"meta": meta, "questions": entries}


def load_contexts(s: Setup) -> dict[str, Any]:
    path = resolve(s.ecfg["answers"]["contexts"])
    if not path.exists():
        sys.exit(f"{path} not found: run `maritime-eval-answers contexts` first")
    data = json.loads(path.read_text(encoding="utf-8"))
    m = data["meta"]
    if m["gold_sha256"] != sha256_file(resolve(s.ecfg["paths"]["gold_csv"])):
        sys.exit("the gold file changed since the contexts were built")
    if m["chunks_sha256"] != s.corpus.sha256:
        sys.exit("chunks.jsonl changed since the contexts were built (re-ingested?)")
    return data


def verify_contexts(s: Setup, data: dict[str, Any]) -> None:
    """Rebuild every context from the stored hits; it must match the stored fingerprint."""
    answerer = answerer_for(s, provider=None)
    by_id = s.corpus.by_id()
    stale = []
    for qid, e in data["questions"].items():
        context, _ = answerer.context_for(stored_retrieval(e, by_id).hits)
        if fingerprint(context) != e["fingerprint"]:
            stale.append(qid)
    if stale:
        sys.exit(f"contexts no longer reproduce for {stale} (code or versions config changed); "
                 "rebuild with `maritime-eval-answers contexts --force` (all answers will be re-asked)")


# --- run -----------------------------------------------------------------------------------------

def cache_path(s: Setup, llm: str) -> Path:
    return resolve(s.ecfg["answers"]["cache_dir"]) / f"answers_{llm}.jsonl"


def cache_key(qid: str, fp: str, model: str, pv: str) -> str:
    return f"{qid}|{fp}|{model}|{pv}"


def read_cache(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def serialize(ans: Answer, q: dict[str, Any], llm: str, model: str, fp: str, pv: str) -> dict[str, Any]:
    g = ans.generation
    by_source = {i: cc for i, cc in enumerate(ans.context, start=1)}
    return {
        "key": cache_key(q["id"], fp, model, pv), "id": q["id"], "slice": q["slice"], "llm": llm, "model": model,
        "fingerprint": fp, "prompt_version": pv, "time": datetime.now().isoformat(timespec="seconds"),
        "language": ans.language, "result": ans.result, "refused": ans.refused, "refusal_reason": ans.refusal_reason,
        "text": ans.text, "raw_text": ans.raw_text, "warnings": ans.warnings, "disclaimer": ans.disclaimer,
        "citations": [{"raw": c.raw, "valid": c.valid, "chunk_id": by_source[c.source].chunk_id if c.valid else None,
                       "problem": c.problem, "flag": c.flag, "normalized": c.normalized, "canonical": c.canonical}
                      for c in ans.citations],
        "cited": [{"chunk_id": by_source[i].chunk_id, "status": by_source[i].status, "status_by": by_source[i].status_by}
                  for i in sorted(ans.cited)],
        "context": [{"chunk_id": c.chunk_id, "status": c.status, "status_by": c.status_by,
                     "retrieved_rank": c.retrieved_rank, "added_by": c.added_by} for c in ans.context],
        "times": ans.times,
        "generation": None if g is None else {
            "provider": g.provider, "model": g.model, "prompt_tokens": g.prompt_tokens, "output_tokens": g.output_tokens,
            "reasoning_tokens": g.reasoning_tokens, "latency_s": g.latency_s, "wait_s": g.wait_s, "retries": g.retries,
            "finish_reason": g.finish_reason, "cost_usd": g.cost_usd},
    }


def run_llm(s: Setup, llm: str, provider: Any = None, out: Any = sys.stdout) -> int:
    """Answer every uncached question. Returns the number of new answers. Stops cleanly on errors."""
    data = load_contexts(s)
    verify_contexts(s, data)
    profile = s.acfg["llm"]["profiles"][llm]
    model, pv = profile["model"], prompt_version(s.acfg, profile)
    path = cache_path(s, llm)
    cached = read_cache(path)
    keys = {r["key"] for r in cached}
    todo = [q for q in s.questions if cache_key(q["id"], data["questions"][q["id"]]["fingerprint"], model, pv) not in keys]
    print(f"{llm} ({model}, prompt version {pv}): {len(s.questions) - len(todo)} cached, {len(todo)} to ask", file=out)
    if not todo:
        return 0
    if provider is None:
        provider = make_provider(s.acfg["llm"], llm, calls_file=resolve(s.acfg["logging"]["calls_file"]))
        provider.check()
    answerer = answerer_for(s, provider)
    by_id = s.corpus.by_id()
    path.parent.mkdir(parents=True, exist_ok=True)
    new = 0
    try:
        for q in todo:
            e = data["questions"][q["id"]]
            ans = answerer.answer(q["question"], stored_retrieval(e, by_id))
            fp = fingerprint(ans.context)
            if fp != e["fingerprint"]:  # verified above; guards against nondeterminism
                raise RuntimeError(f"{q['id']}: context fingerprint {fp} != stored {e['fingerprint']}")
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(serialize(ans, q, llm, model, e["fingerprint"], pv), ensure_ascii=False) + "\n")
            new += 1
            g = ans.generation
            cost = f", ${g.cost_usd:.5f}" if g and g.cost_usd is not None else ""
            print(f"  {q['id']}: {ans.result}{f' ({g.prompt_tokens}+{g.output_tokens} tokens{cost})' if g else ''}", file=out)
    except ProviderError as err:
        kind = "quota / spend limit" if any(h in str(err).lower() for h in QUOTA_HINTS) else "provider error"
        print(f"stopped ({kind}) after {new} new answers: {err}\nre-run the same command to resume from the cache",
              file=out)
    except KeyboardInterrupt:
        print(f"interrupted after {new} new answers; re-run to resume", file=out)
    finally:
        total = sum((r.get("generation") or {}).get("cost_usd") or 0.0 for r in read_cache(path))
        p = provider
        print(f"this run: {getattr(p, 'calls', 0)} calls (incl. probe), {getattr(p, 'prompt_tokens', 0)} prompt + "
              f"{getattr(p, 'output_tokens', 0)} output tokens, est. ${getattr(p, 'cost_usd', 0.0):.4f}; "
              f"all cached {llm} answers: est. ${total:.4f}", file=out)
    return new


# --- budget --------------------------------------------------------------------------------------

def answer_messages(s: Setup, data: dict[str, Any]) -> dict[str, list[Message]]:
    answerer = answerer_for(s, provider=None)
    by_id = s.corpus.by_id()
    out = {}
    for q in s.questions:
        context, _ = answerer.context_for(stored_retrieval(data["questions"][q["id"]], by_id).hits)
        out[q["id"]] = build_messages(q["question"], s.detect(q["question"]), context, answerer.names,
                                      answerer.index, s.acfg)
    return out


def estimate_cost(s: Setup, data: dict[str, Any], prices: dict[str, Any]) -> dict[str, Any]:
    """Step 3 + Step 4 tokens and USD per LLM (answers by the LLM itself, cross-judging by the other)."""
    c = s.ecfg["answers"]["cost_estimate"]
    msgs = answer_messages(s, data)
    by_id = s.corpus.by_id()
    llms = s.ecfg["answers"]["llms"]
    tok = lambda chars: chars / c["chars_per_token"]  # noqa: E731
    answer_in = {q["id"]: tok(sum(len(m["content"]) for m in msgs[q["id"]])) for q in s.questions}
    in_scope = [q for q in s.questions if q["slice"] != OUT_OF_SCOPE]
    judge_in = {q["id"]: c["judge_prompt_overhead_tokens"] + tok(len(q["question"]) + len(q["reference_answer"]) + sum(
        len(by_id[g]["text"]) for g in q["gold_chunk_ids"])) + 0.5 * answer_in[q["id"]] + c["answer_output_tokens"]
        for q in in_scope}  # cited sources assumed half the context
    out: dict[str, Any] = {}
    for i, llm in enumerate(llms):
        other = llms[(i + 1) % len(llms)] if len(llms) > 1 else llm
        p = prices.get(llm)
        a_in, a_out = sum(answer_in.values()), c["answer_output_tokens"] * len(s.questions)
        j_in, j_out = sum(judge_in.values()), c["judge_output_tokens"] * len(in_scope)  # judging `other`'s answers
        usd = None if p is None else (a_in * p["input"] + a_out * p["output"] + j_in * p["input"] + j_out * p["output"]) / 1e6
        out[llm] = {"answer_calls": len(s.questions), "answer_tokens": [round(a_in), a_out],
                    "judge_calls": len(in_scope), "judges_answers_of": other, "judge_tokens": [round(j_in), j_out],
                    "usd": usd}
    out["total_usd"] = sum(v["usd"] or 0.0 for k, v in out.items() if isinstance(v, dict))
    return out


# --- report --------------------------------------------------------------------------------------

def _median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def _p90(xs: list[float]) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))]


def metrics_for(records: list[dict[str, Any]], s: Setup, data: dict[str, Any]) -> dict[str, Any]:
    by_q = {q["id"]: q for q in s.questions}
    by_id = s.corpus.by_id()
    ok_reasons = set(s.ecfg["answers"]["correct_refusal_reasons"])
    out_recs = [r for r in records if r["slice"] == OUT_OF_SCOPE]
    in_recs = [r for r in records if r["slice"] != OUT_OF_SCOPE]
    answered = [r for r in in_recs if not r["refused"]]
    cites = [c for r in answered for c in r["citations"]]
    valid = [c for c in cites if c["valid"]]

    def context_hit(r: dict[str, Any]) -> bool:
        gold = set(by_q[r["id"]]["gold_chunk_ids"])
        return bool(gold & set(data["questions"][r["id"]]["context_ids"]))

    amended = [r for r in in_recs if r["slice"] == "amended"]

    def current_gold(qid: str) -> set[str]:
        return {g for g in by_q[qid]["gold_chunk_ids"]
                if by_id[g].get("amends_doc") and not by_id[g].get("superseded_by")}

    uu17_cited = [r for r in answered if any(c["chunk_id"].startswith("uu_17_2008-") for c in r["cited"])]
    gens = [r["generation"] for r in records if r.get("generation")]
    reasons: dict[str, int] = {}
    for r in in_recs:
        if r["refused"]:
            reasons[r["refusal_reason"]] = reasons.get(r["refusal_reason"], 0) + 1
    return {
        "n": {"total": len(records), "in_scope": len(in_recs), "out_of_scope": len(out_recs), "answered": len(answered)},
        "refusal_accuracy": [sum(r["refused"] and r["refusal_reason"] in ok_reasons for r in out_recs), len(out_recs)],
        "false_refusals": [sum(r["refused"] for r in in_recs), len(in_recs)],
        "false_refusal_reasons": reasons,
        "truncated": sum(r["result"] == "TRUNCATED" for r in records),
        "citations": {"parsed": len(cites), "valid": len(valid), "normalized": sum(bool(c["normalized"]) for c in valid),
                      "answers_with_invalid": sum(any(not c["valid"] for c in r["citations"]) for r in answered),
                      "answers_with_flagged_ayat": sum(any(c["flag"] for c in r["citations"]) for r in answered)},
        "context_hit": [sum(context_hit(r) for r in in_recs), len(in_recs)],
        "amended": {
            "n": len(amended),
            "answered": sum(not r["refused"] for r in amended),
            "cites_current_version": sum(bool(current_gold(r["id"]) & {c["chunk_id"] for c in r["cited"]})
                                         for r in amended if not r["refused"]),
            "cites_superseded_text": sum(any(c["status"] != CURRENT for c in r["cited"]) for r in amended),
        },
        "cipta_kerja_warning_when_uu17_cited": [sum(any("UU 11/2020" in w for w in r["warnings"]) for r in uu17_cited),
                                                len(uu17_cited)],
        "latency_generate_s": {"median": _median([g["latency_s"] for g in gens]), "p90": _p90([g["latency_s"] for g in gens])},
        "rate_limit_wait_s": sum(g.get("wait_s") or 0.0 for g in gens),
        "tokens": {"prompt": sum(g["prompt_tokens"] or 0 for g in gens), "output": sum(g["output_tokens"] or 0 for g in gens),
                   "reasoning": sum(g.get("reasoning_tokens") or 0 for g in gens)},
        "cost_usd": sum(g.get("cost_usd") or 0.0 for g in gens),
        "per_slice": {sl: {"n": sum(r["slice"] == sl for r in records),
                           "answered": sum(r["slice"] == sl and not r["refused"] for r in records),
                           "context_hit": sum(r["slice"] == sl and context_hit(r) for r in in_recs)}
                      for sl in s.ecfg["slices"]},
    }


def current_records(s: Setup, llm: str, data: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Latest cached answer per question for the current context, model and prompt version."""
    profile = s.acfg["llm"]["profiles"][llm]
    model, pv = profile["model"], prompt_version(s.acfg, profile)
    want = {cache_key(q["id"], data["questions"][q["id"]]["fingerprint"], model, pv) for q in s.questions}
    rows = read_cache(cache_path(s, llm))
    latest = {r["key"]: r for r in rows if r["key"] in want}
    order = {q["id"]: i for i, q in enumerate(s.questions)}
    return sorted(latest.values(), key=lambda r: order[r["id"]]), sum(r["key"] not in want for r in rows)


def _frac(pair: list[int]) -> str:
    k, n = pair
    return f"{k}/{n}" + (f" ({k / n:.0%})" if n else "")


def render_md(res: dict[str, Any]) -> str:
    llms = list(res["llms"])
    m = {llm: res["llms"][llm]["metrics"] for llm in llms}
    head = "| metric | " + " | ".join(f"{llm} (`{res['llms'][llm]['model']}`)" for llm in llms) + " |"
    sep = "|---|" + "---|" * len(llms)

    def row(name: str, f) -> str:
        return f"| {name} | " + " | ".join(f(m[llm]) for llm in llms) + " |"

    out = [
        "# Answer evaluation (Phase 4, Step 3)",
        "",
        f"{res['meta']['questions']} gold questions; both LLMs answer from the same stored context per question "
        f"(retrieval `{res['meta']['selected_retrieval']}`, k={res['meta']['k']}, version + same-Pasal + "
        "Penjelasan->body expansion; score gate off). Rules: `docs/eval_plan.md` section 3 and post-hoc change 1. "
        "Counts are k/n; n is small.",
        "",
        head, sep,
        row("answers complete", lambda x: f"{x['n']['total']}/{res['meta']['questions']}"),
        row("refusal accuracy (out-of-scope refused)", lambda x: _frac(x["refusal_accuracy"])),
        row("false refusals (in-scope refused, any reason)", lambda x: _frac(x["false_refusals"])),
        row("false-refusal reasons", lambda x: ", ".join(f"{k} {v}" for k, v in x["false_refusal_reasons"].items()) or "-"),
        row("truncated", lambda x: str(x["truncated"])),
        row("citations valid / parsed", lambda x: f"{x['citations']['valid']}/{x['citations']['parsed']}"),
        row("valid citations normalized", lambda x: str(x["citations"]["normalized"])),
        row("answers with an invalid citation", lambda x: str(x["citations"]["answers_with_invalid"])),
        row("answers with a flagged ayat", lambda x: str(x["citations"]["answers_with_flagged_ayat"])),
        row("context hit (gold chunk in context)", lambda x: _frac(x["context_hit"])),
        row("amended: answered", lambda x: f"{x['amended']['answered']}/{x['amended']['n']}"),
        row("amended: cites the current version", lambda x: f"{x['amended']['cites_current_version']}/{x['amended']['answered']}"),
        row("amended: cites superseded text", lambda x: str(x["amended"]["cites_superseded_text"])),
        row("Cipta Kerja warning when UU 17/2008 cited", lambda x: _frac(x["cipta_kerja_warning_when_uu17_cited"])),
        row("generate latency median / p90 (s)",
            lambda x: f"{x['latency_generate_s']['median'] or 0:.1f} / {x['latency_generate_s']['p90'] or 0:.1f}"),
        row("rate-limit wait (s)", lambda x: f"{x['rate_limit_wait_s']:.0f}"),
        row("tokens prompt / output (reasoning)",
            lambda x: f"{x['tokens']['prompt']} / {x['tokens']['output']} ({x['tokens']['reasoning']})"),
        row("estimated cost (USD)", lambda x: f"{x['cost_usd']:.4f}"),
        "",
        "## Per slice (answered / n; context hit)",
        "",
        "| slice | " + " | ".join(llms) + " |",
        "|---|" + "---|" * len(llms),
    ]
    for sl in next(iter(m.values()))["per_slice"]:
        out.append(f"| {sl} | " + " | ".join(
            f"{m[llm]['per_slice'][sl]['answered']}/{m[llm]['per_slice'][sl]['n']}; {m[llm]['per_slice'][sl]['context_hit']}"
            for llm in llms) + " |")
    out += ["", "Correctness and faithfulness are judged in Step 4 (LLM-as-judge, validated by hand)."]
    return "\n".join(out) + "\n"


def report(s: Setup) -> dict[str, Any]:
    data = load_contexts(s)
    res: dict[str, Any] = {"meta": {"generated": datetime.now().isoformat(timespec="minutes"),
                                    "questions": len(s.questions), **{k: data["meta"][k] for k in
                                                                      ("selected_retrieval", "k", "gold_sha256",
                                                                       "chunks_sha256")}},
                           "llms": {}}
    for llm in s.ecfg["answers"]["llms"]:
        records, stale = current_records(s, llm, data)
        profile = s.acfg["llm"]["profiles"][llm]
        res["llms"][llm] = {"model": profile["model"], "prompt_version": prompt_version(s.acfg, profile),
                            "stale_cache_rows": stale, "missing": [q["id"] for q in s.questions
                                                                   if q["id"] not in {r["id"] for r in records}],
                            "metrics": metrics_for(records, s, data)}
    return res


# --- CLI -----------------------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["contexts", "budget", "run", "report"])
    parser.add_argument("--config", default="configs/eval.yaml")
    parser.add_argument("--llm", help="run: LLM profile (groq | groq-qwen)")
    parser.add_argument("--force", action="store_true", help="contexts: overwrite existing contexts")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    s = setup(args.config)
    a = s.ecfg["answers"]

    if args.command == "contexts":
        path = resolve(a["contexts"])
        if path.exists() and not args.force:
            sys.exit(f"{path} exists; answers are keyed to it. Pass --force to rebuild (answers are then re-asked).")
        data = build_contexts(s)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        cut = sum(bool(e["siblings_cut"]) for e in data["questions"].values())
        dropped = sum(bool(e["hits_dropped"]) for e in data["questions"].values())
        print(f"wrote {path}: {len(data['questions'])} contexts ({data['meta']['selected_retrieval']}); "
              f"{cut} with same-Pasal chunks cut by the budget, {dropped} with low-ranked hits dropped")
    elif args.command == "budget":
        data = load_contexts(s)
        verify_contexts(s, data)
        prices = {}
        for llm in a["llms"]:
            prof = s.acfg["llm"]["profiles"][llm]
            prices[llm] = prof.get("price_usd_per_mtok")
            p = make_provider(s.acfg["llm"], llm, calls_file=resolve(s.acfg["logging"]["calls_file"]))
            try:
                p.check()
            except ProviderError as e:
                sys.exit(f"{llm}: {e}")
            hdr = p.last_probe.ratelimit if p.last_probe else {}
            print(f"{llm} ({prof['model']}): " + ", ".join(f"{k.removeprefix('x-ratelimit-')} {v}" for k, v in sorted(hdr.items()))
                  + f"; price per 1M tokens: {prices[llm]}")
        est = estimate_cost(s, data, prices)
        print(f"\nestimate (chars/token {a['cost_estimate']['chars_per_token']}, {a['cost_estimate']['answer_output_tokens']} "
              "output tokens per answer, cited sources = half the context for the judge):")
        for llm in a["llms"]:
            e = est[llm]
            print(f"  {llm}: answers {e['answer_calls']} calls, {e['answer_tokens'][0]} in + {e['answer_tokens'][1]} out; "
                  f"judging {e['judges_answers_of']}: {e['judge_calls']} calls, {e['judge_tokens'][0]} in + "
                  f"{e['judge_tokens'][1]} out; est. ${e['usd']:.3f}")
        print(f"  total Step 3 + Step 4: est. ${est['total_usd']:.3f}")
        if est["total_usd"] > a["cost_estimate"]["stop_above_usd"]:
            print(f"ABOVE ${a['cost_estimate']['stop_above_usd']}: do not run without approval")
            sys.exit(1)
        print(f"below the ${a['cost_estimate']['stop_above_usd']} stop line")
    elif args.command == "run":
        if args.llm not in a["llms"]:
            sys.exit(f"--llm must be one of {a['llms']}")
        logging.getLogger("maritime_rag.answer.providers").setLevel(logging.INFO)  # tokens + cost per call
        try:
            run_llm(s, args.llm)
        except ProviderError as e:  # before the first answer (key, model check, probe)
            sys.exit(f"error: {e}")
    else:
        res = report(s)
        out_json, out_md = resolve(a["output_json"]), resolve(a["output_md"])
        out_json.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        out_md.write_text(render_md(res), encoding="utf-8")
        for llm, v in res["llms"].items():
            if v["missing"]:
                print(f"warning: {llm} has no answer yet for {len(v['missing'])} question(s); run it first")
        print(f"wrote {out_json} and {out_md}")


if __name__ == "__main__":
    main()

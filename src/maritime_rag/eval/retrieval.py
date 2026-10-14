"""Phase 4 Step 2: retrieval evaluation on the frozen gold set (docs/eval_plan.md, section 2).

Five configurations (bm25 with / without the heading prefix, dense, hybrid, hybrid+rerank),
each returning its top `depth` chunks without version or sibling expansion. Hit@1, Hit@5 and
MRR@10 over in-scope questions, overall and per slice, with percentile bootstrap 95% CIs.
The configuration is selected by the plan's fixed rule; the score-gate threshold is proposed by
its fixed rule. Local only, no LLM.

Usage: uv run maritime-eval-retrieval   -> reports/eval_retrieval.json and .md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from maritime_rag.config import load_config, resolve
from maritime_rag.eval.questions import OUT_OF_SCOPE, load_gold_csv

Ranker = Callable[[str], list[tuple[str, float]]]  # question -> [(chunk_id, score)] best first

LABELS = {
    "bm25": "BM25 (heading prefix)",
    "bm25_noheading": "BM25 (no heading)",
    "dense": "dense (e5)",
    "hybrid": "hybrid (RRF)",
    "hybrid_rerank": "hybrid + rerank (bge)",
}


def first_gold_rank(ranked: list[str], gold: list[str]) -> int | None:
    """1-based rank of the first gold chunk in the ranking, None if absent."""
    golds = set(gold)
    return next((i for i, cid in enumerate(ranked, start=1) if cid in golds), None)


def per_question_metrics(rank: int | None, hit_at: list[int], depth: int) -> dict[str, float]:
    out = {f"hit@{k}": float(rank is not None and rank <= k) for k in hit_at}
    out[f"mrr@{depth}"] = 1.0 / rank if rank is not None and rank <= depth else 0.0
    return out


def bootstrap_ci(values: list[float], resamples: int, ci: float, seed: int) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean, resampling questions with replacement."""
    if not values:
        return (float("nan"), float("nan"))
    arr = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = arr[rng.integers(0, len(arr), size=(resamples, len(arr)))].mean(axis=1)
    alpha = (1 - ci) / 2
    return float(np.quantile(means, alpha)), float(np.quantile(means, 1 - alpha))


@dataclass
class Summary:
    n: int
    mean: dict[str, float]
    ci: dict[str, tuple[float, float]] = field(default_factory=dict)


def summarize(rows: list[dict[str, float]], metrics: list[str], boot: dict[str, Any], seed: int) -> Summary:
    mean = {m: float(np.mean([r[m] for r in rows])) if rows else float("nan") for m in metrics}
    ci = {m: bootstrap_ci([r[m] for r in rows], boot["resamples"], boot["ci"], seed) for m in metrics}
    return Summary(len(rows), mean, ci)


def select_config(overall: dict[str, Summary], rcfg: dict[str, Any], depth: int) -> tuple[str, str]:
    """The plan's fixed rule. Returns (config, explanation)."""
    hit5 = {c: s.mean["hit@5"] for c, s in overall.items()}
    best = max(hit5.values())
    margin = rcfg["selection_margin"]
    within = [c for c in overall if hit5[c] >= best - margin - 1e-12]
    simplicity = rcfg["simplicity"]
    mrr = f"mrr@{depth}"
    key = lambda c: (simplicity[c], -hit5[c], 0 if c == "bm25" else 1, -overall[c].mean[mrr])  # noqa: E731
    chosen = min(within, key=key)
    why = (f"best Hit@5 = {best:.3f}; within {margin} of it: {', '.join(sorted(within, key=key))}; "
           f"simplest: {chosen} (simplicity order {simplicity}; BM25 tie keeps the heading; then MRR)")
    return chosen, why


def propose_gate(top1_in: list[float], top1_out: list[float], thresholds: list[float], max_in: int) -> dict[str, Any]:
    rows = []
    for t in thresholds:
        refused_in = sum(s < t for s in top1_in)
        refused_out = sum(s < t for s in top1_out)
        rows.append({"threshold": t, "in_scope_refused": refused_in,
                     "out_of_scope_refused": refused_out, "out_of_scope_n": len(top1_out)})
    ok = [r for r in rows if r["in_scope_refused"] <= max_in]
    return {"table": rows, "proposed": max((r["threshold"] for r in ok), default=None),
            "rule": f"largest candidate refusing at most {max_in} in-scope question(s)"}


def build_rankers(cfg: dict[str, Any], depth: int, first_stage: int) -> tuple[dict[str, Ranker], Any]:
    """Real retrievers. Models load lazily on first use (e5 for dense/hybrid, bge for rerank)."""
    from maritime_rag.retrieval.bm25 import BM25Retriever
    from maritime_rag.retrieval.search import Searcher
    from maritime_rag.retrieval.tokenize import Tokenizer, load_stopwords

    searcher = Searcher(cfg)
    tok = Tokenizer(load_stopwords(resolve(cfg["paths"]["stopwords"])), cfg["bm25"]["min_token_len"])
    bm25_plain = BM25Retriever(searcher.corpus, tok, cfg["bm25"] | {"include_heading": False})

    def ranked(hits) -> list[tuple[str, float]]:
        return [(h.chunk_id, h.score) for h in hits]

    rankers: dict[str, Ranker] = {
        "bm25": lambda q: ranked(searcher.retriever("bm25").search(q, depth)),
        "bm25_noheading": lambda q: ranked(bm25_plain.search(q, depth)),
        "dense": lambda q: ranked(searcher.retriever("dense").search(q, depth)),
        "hybrid": lambda q: ranked(searcher.retriever("hybrid").search(q, depth)),
        "hybrid_rerank": lambda q: ranked(
            searcher.reranker().rerank(q, searcher.retriever("hybrid").search(q, max(first_stage, depth)), depth)),
    }
    return rankers, searcher


def evaluate(questions: list[dict[str, Any]], rankers: dict[str, Ranker], ecfg: dict[str, Any], seed: int,
             progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    r = ecfg["retrieval"]
    depth, hit_at = r["depth"], r["hit_at"]
    metrics = [f"hit@{k}" for k in hit_at] + [f"mrr@{depth}"]
    in_scope = [q for q in questions if q["slice"] != OUT_OF_SCOPE]
    out_scope = [q for q in questions if q["slice"] == OUT_OF_SCOPE]
    slices = sorted({q["slice"] for q in in_scope}, key=list(ecfg["slices"]).index)
    results: dict[str, Any] = {"configs": {}, "per_question": {}}
    overall: dict[str, Summary] = {}
    top1: dict[str, dict[str, float]] = {}

    for name in r["configs"]:
        if progress:
            progress(name)
        t0 = time.perf_counter()
        rows, per_q = [], {}
        for q in questions:
            ranking = rankers[name](q["question"])
            if name == "hybrid_rerank":
                top1[q["id"]] = ranking[0][1] if ranking else 0.0
            if q["slice"] == OUT_OF_SCOPE:
                continue
            rank = first_gold_rank([cid for cid, _ in ranking], q["gold_chunk_ids"])
            m = per_question_metrics(rank, hit_at, depth)
            rows.append(m | {"slice": q["slice"]})
            per_q[q["id"]] = {"rank": rank, "top": [cid for cid, _ in ranking[:5]]}
        seconds = time.perf_counter() - t0
        overall[name] = summarize(rows, metrics, r["bootstrap"], seed)
        results["configs"][name] = {
            "label": LABELS[name],
            "overall": _as_dict(overall[name]),
            "per_slice": {s: _as_dict(summarize([x for x in rows if x["slice"] == s], metrics, r["bootstrap"], seed))
                          for s in slices},
            "seconds": seconds,
        }
        results["per_question"][name] = per_q

    chosen, why = select_config(overall, r, depth)
    results["selection"] = {"selected": chosen, "explanation": why}
    if "hybrid_rerank" in r["configs"]:
        results["gate"] = propose_gate([top1[q["id"]] for q in in_scope], [top1[q["id"]] for q in out_scope],
                                       r["gate_thresholds"], r["gate_max_in_scope_refusals"])
        results["gate"]["top1_rerank_score"] = top1
    results["n"] = {"in_scope": len(in_scope), "out_of_scope": len(out_scope),
                    "per_slice": {s: sum(q["slice"] == s for q in in_scope) for s in slices}}
    results["metrics"] = metrics
    return results


def _as_dict(s: Summary) -> dict[str, Any]:
    return {"n": s.n, "mean": s.mean, "ci95": {m: list(v) for m, v in s.ci.items()}}


def _fmt(summary: dict[str, Any], m: str) -> str:
    lo, hi = summary["ci95"][m]
    return f"{summary['mean'][m]:.3f} [{lo:.2f}, {hi:.2f}]"


def render_md(res: dict[str, Any], meta: dict[str, Any]) -> str:
    metrics = res["metrics"]
    n = res["n"]
    out = [
        "# Retrieval evaluation (Phase 4, Step 2)",
        "",
        f"Gold: `{meta['gold_csv']}` (sha256 `{meta['gold_sha256'][:12]}`), {n['in_scope']} in-scope questions "
        f"({', '.join(f'{s} {c}' for s, c in n['per_slice'].items())}) and {n['out_of_scope']} out-of-scope. "
        f"Rules: `docs/eval_plan.md` section 2, fixed before this run. Generated {meta['generated']} on "
        f"{meta['machine']}.",
        "",
        "Every configuration returns its top 10 with no version or sibling expansion. A hit means at least "
        "one gold chunk in the top k. Values are the mean with a percentile bootstrap 95% CI "
        f"({meta['resamples']} resamples over questions, seed {meta['seed']}). **n is small**: with "
        f"{n['in_scope']} questions a proportion's CI spans roughly +/-0.15, so overlapping CIs mean the "
        "configurations are not distinguishable on this set.",
        "",
        "## Overall (in-scope)",
        "",
        "| configuration | " + " | ".join(metrics) + " | time (s) |",
        "|---|" + "---|" * len(metrics) + "---|",
    ]
    for name, c in res["configs"].items():
        out.append(f"| {c['label']} | " + " | ".join(_fmt(c["overall"], m) for m in metrics) + f" | {c['seconds']:.1f} |")
    sel = res["selection"]
    out += ["", f"**Selected: {res['configs'][sel['selected']]['label']}** (`{sel['selected']}`). {sel['explanation']}."]
    out += ["", "## Per slice (Hit@5; CIs for context only)", "",
            "| configuration | " + " | ".join(f"{s} (n={c})" for s, c in n["per_slice"].items()) + " |",
            "|---|" + "---|" * len(n["per_slice"])]
    for name, c in res["configs"].items():
        out.append(f"| {c['label']} | " + " | ".join(_fmt(c["per_slice"][s], "hit@5") for s in n["per_slice"]) + " |")
    if "gate" in res:
        g = res["gate"]
        out += ["", "## Score gate (proposal only; enabling it stays a manual decision)", "",
                f"Top-1 bge-reranker score of hybrid+rerank. Rule: {g['rule']}.", "",
                "| threshold | in-scope refused | out-of-scope refused |", "|---|---|---|"]
        out += [f"| {r['threshold']} | {r['in_scope_refused']} of {n['in_scope']} | "
                f"{r['out_of_scope_refused']} of {r['out_of_scope_n']} |" for r in g["table"]]
        out += ["", f"Proposed `gate.min_rerank_score`: **{g['proposed']}**."]
    sel_q = res["per_question"][sel["selected"]]
    misses = sorted(q for q, v in sel_q.items() if v["rank"] is None or v["rank"] > 5)
    out += ["", f"## Misses of the selected configuration (gold not in top 5): {len(misses)}", ""]
    out += [f"- {q}: gold rank {sel_q[q]['rank'] or '>10'}; top 5 = {', '.join(sel_q[q]['top'])}" for q in misses]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="configs/eval.yaml")
    args = parser.parse_args()
    ecfg = load_config(args.config)
    r = ecfg["retrieval"]
    rcfg = load_config(r["retrieval_config"])
    gold_path = resolve(ecfg["paths"]["gold_csv"])
    if not gold_path.exists():
        sys.exit(f"{gold_path} not found: run `maritime-eval-questions validate` first")
    questions = load_gold_csv(gold_path)
    rankers, searcher = build_rankers(rcfg, r["depth"], r["rerank_first_stage"])
    unknown = sorted({g for q in questions for g in q["gold_chunk_ids"]} - set(searcher.corpus.ids))
    if unknown:
        sys.exit(f"gold chunk ids not in the corpus (re-ingested?): {unknown}")

    res = evaluate(questions, rankers, ecfg, rcfg["seed"], progress=lambda n: print(f"evaluating {n}", file=sys.stderr))
    meta = {
        "gold_csv": ecfg["paths"]["gold_csv"],
        "gold_sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(),
        "chunks_sha256": searcher.corpus.sha256,
        "generated": datetime.now().isoformat(timespec="minutes"),
        "machine": platform.processor() or platform.machine(),
        "seed": rcfg["seed"],
        "resamples": r["bootstrap"]["resamples"],
        "reranker": searcher.loaded_reranker.model_id if searcher.loaded_reranker else None,
        "dense_model": rcfg["dense"]["model"],
    }
    out_json, out_md = resolve(r["output_json"]), resolve(r["output_md"])
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"meta": meta} | res, indent=2, ensure_ascii=False), encoding="utf-8")
    out_md.write_text(render_md(res, meta), encoding="utf-8")
    print(f"wrote {out_json} and {out_md}; selected: {res['selection']['selected']}")


if __name__ == "__main__":
    main()

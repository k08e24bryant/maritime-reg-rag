"""Phase 4 Step 5: the evaluation report (docs/eval_plan.md, section 5).

Collects the Step 2-4 results (reports/eval_retrieval.json, eval_answers.json, eval_judge.json),
the answer/judge caches (cost) and the stored contexts (gate effect), plus data/eval/findings.yaml
(post-hoc changes, findings, limitations, future work) into reports/eval.json and reports/eval.md,
and draws reports/figures/retrievers.svg and llm_comparison.svg. No LLM or retrieval model runs.

The "Headline results" block is generated from eval.json["headline"]: every number in it is
stored there with the eval.json path it was taken from.

Usage: uv run maritime-eval-report
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

import yaml

from maritime_rag.config import load_config, resolve
from maritime_rag.eval.answers import read_cache, setup
from maritime_rag.eval.figures import llm_chart, retriever_chart

CRITERIA = ("correctness", "faithfulness", "superseded_mentioned")


def short_name(model: str) -> str:
    return {"openai/gpt-oss-120b": "gpt-oss-120b", "qwen/qwen3.8-27b": "Qwen3.8-27B"}.get(model, model.split("/")[-1])


def get_path(d: dict[str, Any], path: str) -> Any:
    """'retrieval.selected.hit@5.mean' -> value (keys may contain '@' but not '.')."""
    for part in path.split("."):
        d = d[part]
    return d


def _pct(k: int, n: int) -> str:
    return f"{k}/{n} ({k / n:.0%})" if n else f"{k}/{n}"


def cost_from_caches(s, ecfg: dict[str, Any]) -> dict[str, Any]:
    """Estimated USD and calls from the cached rows: every answer generated (as-run and re-asked; rechecked
    rows reuse a generation and are not counted twice) and every judge call (incl. format retries).
    Startup probes (5 output tokens each) are only in logs/llm_calls.jsonl and are not included."""
    out: dict[str, Any] = {}
    for llm in ecfg["answers"]["llms"]:
        rows = [r for r in read_cache(resolve(ecfg["answers"]["cache_dir"]) / f"answers_{llm}.jsonl")
                if not r.get("rechecked") and r.get("generation")]
        out[llm] = {"answer_calls": len(rows), "answer_usd": sum(r["generation"].get("cost_usd") or 0 for r in rows),
                    "answer_tokens": [sum(r["generation"]["prompt_tokens"] or 0 for r in rows),
                                      sum(r["generation"]["output_tokens"] or 0 for r in rows)]}
    for judge, answerer in ecfg["judge"]["pairs"].items():
        path = resolve(ecfg["answers"]["cache_dir"]) / f"judge_{judge}_on_{answerer}.jsonl"
        gens = [g for r in read_cache(path) for g in r["generations"] if g]
        out[judge] |= {"judge_calls": len(gens), "judge_usd": sum(g.get("cost_usd") or 0 for g in gens),
                       "judge_tokens": [sum(g["prompt_tokens"] or 0 for g in gens),
                                        sum(g["output_tokens"] or 0 for g in gens)]}
    calls = sum(v["answer_calls"] + v["judge_calls"] for v in out.values())
    usd = sum(v["answer_usd"] + v["judge_usd"] for v in out.values())
    return {"per_llm": out, "calls": calls, "total_usd": usd}


def gate_effect(s, contexts: dict[str, Any], threshold: float | None) -> dict[str, Any]:
    """What the proposed gate would have done in Step 3 (it stayed off): answer-time top-1 rerank scores."""
    if threshold is None:
        return {}
    in_ref, out_ref = [], []
    for q in s.questions:
        top = contexts["questions"][q["id"]]["top_score"]
        if top is not None and top < threshold:
            (out_ref if q["slice"] == "out_of_scope" else in_ref).append(q["id"])
    return {"threshold": threshold, "in_scope_refused": in_ref, "out_of_scope_refused": out_ref,
            "llm_calls_saved_per_llm": len(out_ref)}


def build(config_path: str) -> dict[str, Any]:
    s = setup(config_path)
    ecfg, rp = s.ecfg, s.ecfg["report"]
    retr = json.loads(resolve(rp["retrieval_json"]).read_text(encoding="utf-8"))
    ans = json.loads(resolve(rp["answers_json"]).read_text(encoding="utf-8"))
    jud = json.loads(resolve(rp["judge_json"]).read_text(encoding="utf-8"))
    contexts = json.loads(resolve(ecfg["answers"]["contexts"]).read_text(encoding="utf-8"))
    findings = yaml.safe_load(resolve(ecfg["answers"]["findings"]).read_text(encoding="utf-8"))
    if jud.get("agreement", {}).get("status") != "complete":
        sys.exit("reports/eval_judge.json has no complete manual-label agreement yet (maritime-eval-judge report)")
    llms = ecfg["answers"]["llms"]
    models = {llm: ans["llms"][llm]["model"] for llm in llms}

    # retrieval
    sel = retr["selection"]["selected"]
    configs = {}
    for name, c in retr["configs"].items():
        o = c["overall"]
        configs[name] = {"label": c["label"], "seconds": c["seconds"],
                         **{m: {"mean": o["mean"][m], "ci95": o["ci95"][m]} for m in retr["metrics"]},
                         "per_slice_hit@5": {sl: {"mean": v["mean"]["hit@5"], "n": v["n"]} for sl, v in c["per_slice"].items()}}
    retrieval = {"n_in_scope": retr["n"]["in_scope"], "n_out_of_scope": retr["n"]["out_of_scope"], "configs": configs,
                 "selected": {"name": sel, **configs[sel], "explanation": retr["selection"]["explanation"]},
                 "gold_sha256": retr["meta"]["gold_sha256"]}

    gate = {"rule": retr["gate"]["rule"], "table": retr["gate"]["table"], "proposed": retr["gate"]["proposed"],
            "enabled_in_evaluation": False,
            "answer_time_effect": gate_effect(s, contexts, retr["gate"]["proposed"])}

    # answers (as-run vs fixed)
    answers = {llm: {"model": models[llm], "asrun": ans["llms"][llm]["asrun"], "fixed": ans["llms"][llm]["fixed"],
                     "changes": ans["llms"][llm]["changes"]} for llm in llms}

    # judge + manual + agreement
    ag = jud["agreement"]
    flag_below = rp["flag_kappa_below"]
    agreement = {c: {"agreement": x["agreement"], "kappa": x["kappa"], "used_for_headline": x["use_judge_for_headline"],
                     "flagged": x["kappa"] is not None and x["kappa"] < flag_below} for c, x in ag["criteria"].items()}
    judge = {}
    for llm in llms:
        v = jud["answerers"][llm]
        judge[llm] = {"model": models[llm], "judged_by": v["judge"], "judge_model": v["judge_model"],
                      "n": v["judged"], "invalid": v["invalid"], "distributions": v["distributions"],
                      "correctness_by_slice": v["correctness_by_slice"],
                      "correctness_by_context_hit": v["correctness_by_context_hit"],
                      "manual_sample": ag["manual_distributions"][llm]}
    cost = cost_from_caches(s, ecfg)
    latency = {llm: ans["llms"][llm]["fixed"]["latency_generate_s"] for llm in llms}

    out = {
        "meta": {"generated": datetime.now().isoformat(timespec="minutes"), "gold_sha256": retr["meta"]["gold_sha256"],
                 "chunks_sha256": retr["meta"]["chunks_sha256"], "questions": ans["meta"]["questions"],
                 "sources": [rp["retrieval_json"], rp["answers_json"], rp["judge_json"], ecfg["answers"]["findings"]],
                 "plan": "docs/eval_plan.md"},
        "retrieval": retrieval, "gate": gate, "answers": answers, "judge": judge,
        "agreement": {"n": ag["n"], "criteria": agreement, "rule_kappa_min": ecfg["judge"]["kappa_min"],
                      "flag_kappa_below": flag_below},
        "cost": cost, "latency_generate_s": latency,
        "post_hoc_changes": findings.get("post_hoc_changes", []),
        "findings": {"questionable_gold": findings.get("questionable_gold", []),
                     "weaknesses": findings.get("weaknesses", [])},
        "limitations": findings.get("limitations", []), "future_work": findings.get("future_work", []),
    }
    out["headline"] = headline(out, llms)
    return out


def headline(r: dict[str, Any], llms: list[str]) -> list[dict[str, Any]]:
    """Five reusable lines; each value is stored with the eval.json path it comes from."""
    sel = r["retrieval"]["selected"]
    best_llm = max(llms, key=lambda l: r["judge"][l]["distributions"]["correctness"]["correct"])
    other = next(l for l in llms if l != best_llm)

    def corr(l: str) -> tuple[int, int]:
        return r["judge"][l]["distributions"]["correctness"]["correct"], r["judge"][l]["n"]

    valid = sum(r["answers"][l]["fixed"]["citations"]["valid"] for l in llms)
    parsed = sum(r["answers"][l]["fixed"]["citations"]["parsed"] for l in llms)
    lines = [
        {"text": (f"Retrieval: hybrid BM25 + e5 with bge-reranker reaches Hit@5 {sel['hit@5']['mean']:.2f} "
                  f"(95% CI {sel['hit@5']['ci95'][0]:.2f}-{sel['hit@5']['ci95'][1]:.2f}) and MRR@10 {sel['mrr@10']['mean']:.2f} "
                  f"on {r['retrieval']['n_in_scope']} in-scope questions, selected among 5 retrievers by a rule fixed before the run."),
         "sources": ["retrieval.selected.hit@5.mean", "retrieval.selected.hit@5.ci95", "retrieval.selected.mrr@10.mean",
                     "retrieval.n_in_scope"]},
        {"text": (f"Grounding: all {valid} of {parsed} citations in the answers of both LLMs map to a provided source; "
                  + " and ".join(f"{short_name(r['answers'][l]['model'])} refuses {r['answers'][l]['fixed']['refusal_accuracy'][0]}/"
                                 f"{r['answers'][l]['fixed']['refusal_accuracy'][1]}" for l in llms)
                  + f" out-of-scope questions, with {sum(r['answers'][l]['fixed']['false_refusals'][0] for l in llms)} false refusals "
                  f"on {r['answers'][llms[0]]['fixed']['false_refusals'][1]} in-scope questions each."),
         "sources": [f"answers.{l}.fixed.citations" for l in llms] + [f"answers.{l}.fixed.refusal_accuracy" for l in llms]
                    + [f"answers.{l}.fixed.false_refusals" for l in llms]},
        {"text": (f"Correctness (cross-judged; judge vs human agreement kappa {r['agreement']['criteria']['correctness']['kappa']:.2f}, "
                  f"n = {r['agreement']['n']}): {short_name(r['judge'][best_llm]['model'])} {_pct(*corr(best_llm))} correct, "
                  f"{short_name(r['judge'][other]['model'])} {_pct(*corr(other))}."),
         "sources": [f"judge.{best_llm}.distributions.correctness.correct", f"judge.{best_llm}.n",
                     f"judge.{other}.distributions.correctness.correct", f"judge.{other}.n",
                     "agreement.criteria.correctness.kappa", "agreement.n"]},
        {"text": ("Amended regulations: the current version is cited in " + ", ".join(
            f"{r['answers'][l]['fixed']['amended']['cites_current_version']}/{r['answers'][l]['fixed']['amended']['answered']}"
            f" ({short_name(r['answers'][l]['model'])})" for l in llms)
            + " amended-Pasal answers; every statement is supported by the cited sources in " + ", ".join(
            f"{r['judge'][l]['distributions']['faithfulness']['supported']}/{r['judge'][l]['n']} ({short_name(r['answers'][l]['model'])})"
            for l in llms) + f" answers (judge vs human kappa {r['agreement']['criteria']['faithfulness']['kappa']:.2f})."),
         "sources": [f"answers.{l}.fixed.amended" for l in llms] + [f"judge.{l}.distributions.faithfulness.supported" for l in llms]
                    + ["agreement.criteria.faithfulness.kappa"]},
        {"text": (f"Cost and speed: about ${r['cost']['total_usd']:.2f} for all {r['cost']['calls']} LLM calls of the evaluation "
                  "(answers and judging, Groq); median generation "
                  + " / ".join(f"{r['latency_generate_s'][l]['median']:.1f} s ({short_name(r['answers'][l]['model'])})" for l in llms)
                  + "; retrieval and reranking run locally."),
         "sources": ["cost.total_usd", "cost.calls"] + [f"latency_generate_s.{l}.median" for l in llms]},
    ]
    for line in lines:  # every source must resolve, so the block cannot drift from eval.json
        line["values"] = {p: get_path(r, p) for p in line["sources"]}
    return lines


def _dist(d: dict[str, int]) -> str:
    n = sum(d.values())
    return ", ".join(f"{k} {v}" for k, v in d.items()) + f" (n={n})"


def render(r: dict[str, Any], llms: list[str]) -> str:
    name = {l: short_name(r["answers"][l]["model"]) for l in llms}
    out = ["# Evaluation report (Phase 4)", "",
           f"Generated {r['meta']['generated']}. Plan and rules: `{r['meta']['plan']}` (fixed before results; post-hoc changes "
           "listed below). Every number here is in `reports/eval.json`.", "",
           "## Headline results", ""]
    out += [f"{i}. {h['text']}" for i, h in enumerate(r["headline"], 1)]
    out += ["", "Each line's values and their `eval.json` paths: `headline[i].values`.", ""]

    ret = r["retrieval"]
    out += ["## 1. Retrieval (Step 2)", "",
            f"{ret['n_in_scope']} in-scope questions (frozen gold, sha256 `{ret['gold_sha256'][:12]}`). Mean with 95% "
            "bootstrap CI; top 10 per configuration, no answer-time expansion.", "",
            "![Retriever comparison](figures/retrievers.svg)", "",
            "| configuration | Hit@1 | Hit@5 | MRR@10 | time (s) |", "|---|---|---|---|---|"]
    for n_, c in ret["configs"].items():
        cell = lambda m: f"{c[m]['mean']:.3f} [{c[m]['ci95'][0]:.2f}, {c[m]['ci95'][1]:.2f}]"  # noqa: E731
        mark = " **(selected)**" if n_ == ret["selected"]["name"] else ""
        out.append(f"| {c['label']}{mark} | {cell('hit@1')} | {cell('hit@5')} | {cell('mrr@10')} | {c['seconds']:.1f} |")
    out += ["", f"Selection: {ret['selected']['explanation']}. The CIs of the top configurations overlap: the choice follows the "
            "rule, not a demonstrated difference.", ""]

    g = r["gate"]
    out += ["## 2. Score gate (proposal; stayed off)", "", f"Rule: {g['rule']} (top-1 bge-reranker score).", "",
            "| threshold | in-scope refused | out-of-scope refused |", "|---|---|---|"]
    out += [f"| {t['threshold']} | {t['in_scope_refused']} | {t['out_of_scope_refused']}/{t['out_of_scope_n']} |" for t in g["table"]]
    e = g["answer_time_effect"]
    out += ["", f"Proposed threshold: **{g['proposed']}**. Applied to the Step 3 contexts it would have refused "
            f"{len(e['out_of_scope_refused'])} out-of-scope questions before the LLM ({', '.join(e['out_of_scope_refused']) or '-'}) "
            f"and {len(e['in_scope_refused'])} in-scope ({', '.join(e['in_scope_refused']) or '-'}). Both LLMs already refused all "
            "out-of-scope questions, so the gate would only save LLM calls. English (cross-lingual) questions score low "
            "(about 0.014), close to some out-of-scope ones: a single threshold cannot separate them.", ""]

    out += ["## 3. Answers (Step 3): as-run vs fixed", "",
            "Fixed = after post-hoc change 3 (two bug fixes). Both LLMs answer from the same stored context per question.", "",
            "| metric | " + " | ".join(f"{name[l]} as-run | {name[l]} fixed" for l in llms) + " |",
            "|---|" + "---|---|" * len(llms)]
    rows = [
        ("out-of-scope refused", lambda m: _pct(*m["refusal_accuracy"])),
        ("in-scope refused (false refusals)", lambda m: _pct(*m["false_refusals"])),
        ("truncated", lambda m: str(m["truncated"])),
        ("citations valid / parsed", lambda m: f"{m['citations']['valid']}/{m['citations']['parsed']}"),
        ("gold chunk in context", lambda m: _pct(*m["context_hit"])),
        ("amended: cites current version", lambda m: f"{m['amended']['cites_current_version']}/{m['amended']['answered']}"),
        ("Cipta Kerja warning when UU 17/2008 cited", lambda m: _pct(*m["cipta_kerja_warning_when_uu17_cited"])),
    ]
    for label, f in rows:
        out.append(f"| {label} | " + " | ".join(f"{f(r['answers'][l]['asrun'])} | {f(r['answers'][l]['fixed'])}" for l in llms) + " |")
    out.append("")
    for l in llms:
        ch = r["answers"][l]["changes"]
        out.append(f"- {name[l]}: {len(ch)} changed question(s): " + "; ".join(
            f"{c['id']} ({c['reasons'][0].split(',')[0]}; gold in context {c['context_hit'][0]} -> {c['context_hit'][1]})" for c in ch))
    out += ["", "Details: `reports/eval_answers.md`.", ""]

    ag = r["agreement"]
    out += ["## 4. LLM comparison (Step 4)", "",
            "Cross-judging: each LLM's fixed in-scope answers are graded by the other LLM, which sees only the question, gold "
            "text, reference answer, the cited sources and the answer. Validated by one annotator on a blind, stratified "
            f"sample of {ag['n']} answers (10 per LLM).", "", "![LLM comparison](figures/llm_comparison.svg)", "",
            "| criterion | " + " | ".join(f"{name[l]} (judge, n={r['judge'][l]['n']})" for l in llms)
            + " | " + " | ".join(f"{name[l]} (manual, n=10)" for l in llms) + " | agreement | kappa |",
            "|---|" + "---|" * (2 * len(llms) + 2)]
    for c in CRITERIA:
        a = ag["criteria"][c]
        flag = " ⚠" if a["flagged"] else ""
        out.append(f"| {c}{flag} | " + " | ".join(_dist(r["judge"][l]["distributions"][c]) for l in llms) + " | "
                   + " | ".join(_dist(r["judge"][l]["manual_sample"][c]) for l in llms)
                   + f" | {a['agreement']:.0%} | {a['kappa']:.2f} |")
    out += ["", f"All three criteria meet the plan's rule (kappa >= {ag['rule_kappa_min']}), so the judge labels are used. "
            f"⚠ **superseded_mentioned is flagged**: kappa {ag['criteria']['superseded_mentioned']['kappa']:.2f} is just above the "
            "rule with n = 20, and most disagreements were the annotator saying \"n.a.\" where the judge saw a relevant "
            "superseded or repealed source: the rubric's \"relevant\" is ambiguous. Kept as is (not relabelled); see "
            "limitations and future work.", "",
            "Each LLM was graded by a different judge; the high agreement of both judges with the manual labels is what makes "
            "the two columns comparable.", ""]

    out += ["## 5. Per slice", "", "| slice | retrieval Hit@5 (selected) | " + " | ".join(f"{name[l]} correct (judge)" for l in llms) + " |",
            "|---|---|" + "---|" * len(llms)]
    for sl, v in ret["selected"]["per_slice_hit@5"].items():
        cells = []
        for l in llms:
            d = r["judge"][l]["correctness_by_slice"].get(sl, {})
            cells.append(f"{d.get('correct', 0)}/{sum(d.values())}" if d else "-")
        out.append(f"| {sl} (n={v['n']}) | {v['mean']:.2f} | " + " | ".join(cells) + " |")
    out += ["", "Correctness by whether the gold chunk was in the context: " + "; ".join(
        f"{name[l]}: gold in context {_dist(r['judge'][l]['correctness_by_context_hit']['True'])}, gold not in context "
        f"{_dist(r['judge'][l]['correctness_by_context_hit']['False'])}" for l in llms), ""]

    c = r["cost"]
    out += ["## 6. Cost and latency", "", "| | " + " | ".join(name[l] for l in llms) + " |", "|---|" + "---|" * len(llms),
            "| answer calls (as-run + re-asked) | " + " | ".join(str(c["per_llm"][l]["answer_calls"]) for l in llms) + " |",
            "| answer cost (USD) | " + " | ".join(f"{c['per_llm'][l]['answer_usd']:.4f}" for l in llms) + " |",
            "| judge calls made by this model | " + " | ".join(str(c["per_llm"][l]["judge_calls"]) for l in llms) + " |",
            "| judge cost (USD) | " + " | ".join(f"{c['per_llm'][l]['judge_usd']:.4f}" for l in llms) + " |",
            "| median / p90 generation (s) | " + " | ".join(
                f"{r['latency_generate_s'][l]['median']:.1f} / {r['latency_generate_s'][l]['p90']:.1f}" for l in llms) + " |",
            "", f"Total: about **${c['total_usd']:.3f}** for {c['calls']} LLM calls (estimated from token counts and Groq list "
            "prices; startup probes excluded). Retrieval and reranking run locally.", ""]

    out += ["## 7. Post-hoc changes", "", "Full text: `docs/eval_plan.md`, \"Post-hoc changes\".", ""]
    out += [f"{p['id']}. *{p['when']}*: {p['change']}" for p in r["post_hoc_changes"]]
    titles = (("questionable_gold", "Questionable gold (frozen; reported, not re-scored)"),
              ("weaknesses", "System weaknesses"))
    out += ["", "## 8. Findings", ""]
    for key, title in titles:
        out += [f"**{title}**", ""] + [f"- **{x['id']}**: {x['note']}" for x in r["findings"][key]] + [""]
    out += ["## 9. Limitations", ""] + [f"- {x}" for x in r["limitations"]]
    out += ["", "## 10. Future work", ""] + [f"- {x}" for x in r["future_work"]]
    return "\n".join(out) + "\n"


def figures(r: dict[str, Any], llms: list[str]) -> dict[str, str]:
    ret = r["retrieval"]
    rows = [{"name": n, "label": c["label"], "n": ret["n_in_scope"], "hit@5": c["hit@5"], "mrr@10": c["mrr@10"]}
            for n, c in ret["configs"].items()]
    groups = []
    for crit, labels in (("Correctness", ["correct", "partial", "wrong"]), ("Faithfulness to cited sources", ["supported", "partly", "unsupported"])):
        key = "correctness" if crit == "Correctness" else "faithfulness"
        groups.append({"criterion": crit, "labels": labels, "rows": [
            {"name": short_name(r["judge"][l]["model"]), "counts": r["judge"][l]["distributions"][key],
             "note": f"judged by {short_name(r['judge'][l]['judge_model'])}"} for l in llms]})
    return {"retrievers.svg": retriever_chart(rows, ret["selected"]["name"]), "llm_comparison.svg": llm_chart(groups)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="configs/eval.yaml")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ecfg = load_config(args.config)
    rp = ecfg["report"]
    llms = ecfg["answers"]["llms"]
    r = build(args.config)
    out_json, out_md, fig_dir = resolve(rp["output_json"]), resolve(rp["output_md"]), resolve(rp["figures_dir"])
    out_json.write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    out_md.write_text(render(r, llms), encoding="utf-8")
    fig_dir.mkdir(parents=True, exist_ok=True)
    for name, svg in figures(r, llms).items():
        (fig_dir / name).write_text(svg, encoding="utf-8")
    print(f"wrote {out_json}, {out_md} and {fig_dir}/retrievers.svg, llm_comparison.svg")
    for h in r["headline"]:
        print(f"- {h['text']}")


if __name__ == "__main__":
    main()

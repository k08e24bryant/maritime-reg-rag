"""Phase 4 Step 2 with fake rankers: metrics, bootstrap, the plan's selection rule, gate proposal."""

from __future__ import annotations

import copy

import pytest

from maritime_rag.config import load_config
from maritime_rag.eval.retrieval import (
    Summary,
    bootstrap_ci,
    evaluate,
    first_gold_rank,
    per_question_metrics,
    propose_gate,
    render_md,
    select_config,
)

ECFG = load_config("configs/eval.yaml")
R = ECFG["retrieval"]


def test_rank_and_metrics() -> None:
    assert first_gold_rank(["a", "b", "c"], ["c", "x"]) == 3
    assert first_gold_rank(["a", "b"], ["x"]) is None
    assert per_question_metrics(3, [1, 5], 10) == {"hit@1": 0.0, "hit@5": 1.0, "mrr@10": pytest.approx(1 / 3)}
    assert per_question_metrics(None, [1, 5], 10) == {"hit@1": 0.0, "hit@5": 0.0, "mrr@10": 0.0}
    assert per_question_metrics(7, [1, 5], 10)["mrr@10"] == pytest.approx(1 / 7)


def test_bootstrap_is_seeded_and_brackets_the_mean() -> None:
    values = [1.0] * 30 + [0.0] * 10
    lo, hi = bootstrap_ci(values, 2000, 0.95, seed=42)
    assert (lo, hi) == bootstrap_ci(values, 2000, 0.95, seed=42)
    assert lo < 0.75 < hi and hi - lo > 0.15  # n = 40: wide
    assert bootstrap_ci([1.0] * 5, 500, 0.95, seed=1) == (1.0, 1.0)


def _overall(hit5: dict[str, float], mrr: dict[str, float] | None = None) -> dict[str, Summary]:
    return {c: Summary(40, {"hit@1": 0.0, "hit@5": h, "mrr@10": (mrr or {}).get(c, 0.5)}) for c, h in hit5.items()}


def test_selection_rule_prefers_the_simpler_config_within_margin() -> None:
    hit5 = {"bm25": 0.70, "bm25_noheading": 0.65, "dense": 0.74, "hybrid": 0.80, "hybrid_rerank": 0.81}
    assert select_config(_overall(hit5), R, 10)[0] == "hybrid"  # 0.80 within 0.02 of 0.81, simpler
    hit5["hybrid"] = 0.78
    assert select_config(_overall(hit5), R, 10)[0] == "hybrid_rerank"  # 0.03 behind: not within margin
    hit5 = {"bm25": 0.80, "bm25_noheading": 0.81, "dense": 0.70, "hybrid": 0.81, "hybrid_rerank": 0.82}
    assert select_config(_overall(hit5), R, 10)[0] == "bm25_noheading"  # both BM25 within; higher Hit@5 wins
    hit5["bm25_noheading"] = 0.80
    assert select_config(_overall(hit5), R, 10)[0] == "bm25"  # BM25 tie keeps the heading prefix


def test_gate_proposal_rule() -> None:
    g = propose_gate([0.9, 0.4, 0.03, 0.008], [0.0, 0.001, 0.02, 0.2], [0.005, 0.01, 0.02, 0.05, 0.1], 1)
    assert [r["in_scope_refused"] for r in g["table"]] == [0, 1, 1, 2, 2]
    assert [r["out_of_scope_refused"] for r in g["table"]] == [2, 2, 2, 3, 3]
    assert g["proposed"] == 0.02
    assert propose_gate([0.001], [0.0], [0.005], 0)["proposed"] is None


def test_evaluate_end_to_end_with_fake_rankers() -> None:
    questions = [
        {"id": "F01", "slice": "factual_id", "question": "q1", "gold_chunk_ids": ["c1"]},
        {"id": "F02", "slice": "factual_id", "question": "q2", "gold_chunk_ids": ["c2", "c9"]},
        {"id": "A01", "slice": "amended", "question": "q3", "gold_chunk_ids": ["c3"]},
        {"id": "O01", "slice": "out_of_scope", "question": "q4", "gold_chunk_ids": []},
    ]
    perfect = {"q1": ["c1"], "q2": ["c9"], "q3": ["c3"], "q4": ["c5"]}
    weak = {"q1": ["x", "c1"], "q2": ["x"], "q3": ["x", "x", "x", "x", "x", "c3"], "q4": ["c5"]}

    def ranker(table: dict[str, list[str]], score: float):
        return lambda q: [(cid, score if q != "q4" else 0.0) for cid in table[q]]

    rankers = {"bm25": ranker(weak, 1.0), "bm25_noheading": ranker(weak, 1.0), "dense": ranker(weak, 1.0),
               "hybrid": ranker(perfect, 1.0), "hybrid_rerank": ranker(perfect, 0.9)}
    cfg = copy.deepcopy(ECFG)
    cfg["retrieval"]["bootstrap"]["resamples"] = 200
    res = evaluate(questions, rankers, cfg, seed=42)
    assert res["n"] == {"in_scope": 3, "out_of_scope": 1, "per_slice": {"factual_id": 2, "amended": 1}}
    bm25 = res["configs"]["bm25"]["overall"]["mean"]
    assert bm25["hit@1"] == 0.0 and bm25["hit@5"] == pytest.approx(1 / 3) and bm25["mrr@10"] == pytest.approx((0.5 + 0 + 1 / 6) / 3)
    assert res["configs"]["hybrid"]["overall"]["mean"]["hit@1"] == 1.0
    assert res["selection"]["selected"] == "hybrid"  # rerank ties it; hybrid is simpler
    assert res["per_question"]["bm25"]["A01"]["rank"] == 6
    assert res["gate"]["top1_rerank_score"]["O01"] == 0.0 and res["gate"]["proposed"] == 0.1
    md = render_md(res, {"gold_csv": "g.csv", "gold_sha256": "ab" * 32, "generated": "now", "machine": "m",
                         "resamples": 200, "seed": 42})
    assert "**Selected: hybrid (RRF)**" in md and "Misses of the selected configuration" in md

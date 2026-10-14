# Retrieval evaluation (Phase 4, Step 2)

Gold: `data/eval/questions_gold.csv` (sha256 `046a3c591e3f`), 44 in-scope questions (factual_id 24, which_pasal 7, amended 8, english 5) and 10 out-of-scope. Rules: `docs/eval_plan.md` section 2, fixed before this run. Generated 2026-10-14T11:45 on Intel64 Family 6 Model 154 Stepping 3, GenuineIntel.

Every configuration returns its top 10 with no version or sibling expansion. A hit means at least one gold chunk in the top k. Values are the mean with a percentile bootstrap 95% CI (2000 resamples over questions, seed 42). **n is small**: with 44 questions a proportion's CI spans roughly +/-0.15, so overlapping CIs mean the configurations are not distinguishable on this set.

## Overall (in-scope)

| configuration | hit@1 | hit@5 | mrr@10 | time (s) |
|---|---|---|---|---|
| BM25 (heading prefix) | 0.341 [0.20, 0.48] | 0.636 [0.50, 0.77] | 0.451 [0.33, 0.58] | 0.2 |
| BM25 (no heading) | 0.318 [0.18, 0.45] | 0.659 [0.52, 0.80] | 0.429 [0.31, 0.55] | 0.1 |
| dense (e5) | 0.705 [0.57, 0.84] | 0.841 [0.73, 0.93] | 0.752 [0.63, 0.86] | 15.8 |
| hybrid (RRF) | 0.500 [0.36, 0.64] | 0.795 [0.66, 0.91] | 0.628 [0.51, 0.74] | 1.5 |
| hybrid + rerank (bge) | 0.659 [0.52, 0.80] | 0.886 [0.80, 0.98] | 0.746 [0.63, 0.85] | 24.6 |

**Selected: hybrid + rerank (bge)** (`hybrid_rerank`). best Hit@5 = 0.886; within 0.02 of it: hybrid_rerank; simplest: hybrid_rerank (simplicity order {'bm25': 0, 'bm25_noheading': 0, 'dense': 1, 'hybrid': 2, 'hybrid_rerank': 3}; BM25 tie keeps the heading; then MRR).

## Per slice (Hit@5; CIs for context only)

| configuration | factual_id (n=24) | which_pasal (n=7) | amended (n=8) | english (n=5) |
|---|---|---|---|---|
| BM25 (heading prefix) | 0.667 [0.50, 0.83] | 0.571 [0.14, 0.86] | 0.750 [0.38, 1.00] | 0.400 [0.00, 0.80] |
| BM25 (no heading) | 0.708 [0.54, 0.88] | 0.571 [0.14, 0.86] | 0.750 [0.38, 1.00] | 0.400 [0.00, 0.80] |
| dense (e5) | 0.792 [0.62, 0.96] | 1.000 [1.00, 1.00] | 0.875 [0.62, 1.00] | 0.800 [0.40, 1.00] |
| hybrid (RRF) | 0.792 [0.62, 0.96] | 1.000 [1.00, 1.00] | 0.750 [0.38, 1.00] | 0.600 [0.20, 1.00] |
| hybrid + rerank (bge) | 0.875 [0.75, 1.00] | 1.000 [1.00, 1.00] | 0.875 [0.62, 1.00] | 0.800 [0.40, 1.00] |

## Score gate (proposal only; enabling it stays a manual decision)

Top-1 bge-reranker score of hybrid+rerank. Rule: largest candidate refusing at most 1 in-scope question(s).

| threshold | in-scope refused | out-of-scope refused |
|---|---|---|
| 0.005 | 0 of 44 | 4 of 10 |
| 0.01 | 0 of 44 | 4 of 10 |
| 0.02 | 2 of 44 | 5 of 10 |
| 0.05 | 2 of 44 | 8 of 10 |
| 0.1 | 3 of 44 | 10 of 10 |

Proposed `gate.min_rerank_score`: **0.01**.

## Misses of the selected configuration (gold not in top 5): 5

- A01: gold rank >10; top 5 = pm_93_2013-0098, pp_20_2010-0104, uu_17_2008-0037, uu_17_2008-0036, pp_20_2010-0112
- E03: gold rank >10; top 5 = uu_17_2008-0451, pp_31_2021-0149, pm_59_2021-0061, pp_31_2021-0045, pp_31_2021-0223
- F07: gold rank >10; top 5 = pp_61_2009-0114, pp_61_2009-0132, pp_61_2009-0116, pp_61_2009-0123, uu_17_2008-0113
- F13: gold rank >10; top 5 = pm_93_2013-0117, pp_20_2010-0191, pm_59_2021-0002, uu_17_2008-0055, pm_93_2013-0118
- F24: gold rank >10; top 5 = pm_5_2024-0001, pm_5_2024-0008, pp_31_2021-0036, pm_5_2024-0005, uu_17_2008-0056

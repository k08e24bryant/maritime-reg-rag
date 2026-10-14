# LLM-as-judge (Phase 4, Step 4)

Cross-judging: each LLM's fixed Step 3 answers (in-scope, answered) are graded by the other LLM. The judge sees only the question, the gold text, the reference answer, the cited sources and the answer (`docs/eval_plan.md` section 4, post-hoc change 2). Rubric version `06f7ccc59d`.

## Answers of groq-qwen (judged by groq, `openai/gpt-oss-120b`)

44/44 judged, 0 invalid judge outputs. Judge tokens 63077 in / 8087 out, est. $0.0143.

- correctness: correct 40 (91%), partial 2 (5%), wrong 2 (5%)
- faithfulness: supported 39 (89%), partly 5 (11%), unsupported 0 (0%)
- superseded_mentioned: yes 10 (23%), no 9 (20%), n.a. 25 (57%)

Correctness by slice: factual_id: correct 22 (92%), partial 1 (4%), wrong 1 (4%); which_pasal: correct 6 (86%), partial 1 (14%), wrong 0 (0%); amended: correct 7 (88%), partial 0 (0%), wrong 1 (12%); english: correct 5 (100%), partial 0 (0%), wrong 0 (0%)

Correctness by context hit: gold in context: correct 38 (95%), partial 2 (5%), wrong 0 (0%); gold NOT in context: correct 2 (50%), partial 0 (0%), wrong 2 (50%)

## Answers of groq (judged by groq-qwen, `qwen/qwen3.8-27b`)

44/44 judged, 0 invalid judge outputs. Judge tokens 52258 in / 3503 out, est. $0.0558.

- correctness: correct 33 (75%), partial 8 (18%), wrong 3 (7%)
- faithfulness: supported 41 (93%), partly 2 (5%), unsupported 1 (2%)
- superseded_mentioned: yes 4 (9%), no 7 (16%), n.a. 33 (75%)

Correctness by slice: factual_id: correct 18 (75%), partial 5 (21%), wrong 1 (4%); which_pasal: correct 7 (100%), partial 0 (0%), wrong 0 (0%); amended: correct 3 (38%), partial 3 (38%), wrong 2 (25%); english: correct 5 (100%), partial 0 (0%), wrong 0 (0%)

Correctness by context hit: gold in context: correct 31 (78%), partial 8 (20%), wrong 1 (2%); gold NOT in context: correct 2 (50%), partial 0 (0%), wrong 2 (50%)

## Agreement with the manual labels

n = 20 (kappa is unstable at this n).

| criterion | agreement | Cohen's kappa | judge used for headline (kappa >= rule) |
|---|---|---|---|
| correctness | 95% | 0.87 | yes |
| faithfulness | 100% | 1.00 | yes |
| superseded_mentioned | 75% | 0.47 | yes |

Manual labels on the sample: groq: correctness correct 7 (70%), partial 2 (20%), wrong 1 (10%), faithfulness supported 9 (90%), partly 1 (10%), superseded_mentioned n.a. 8 (80%), yes 2 (20%); groq-qwen: correctness correct 9 (90%), wrong 1 (10%), faithfulness supported 8 (80%), partly 2 (20%), superseded_mentioned n.a. 8 (80%), yes 1 (10%), no 1 (10%)

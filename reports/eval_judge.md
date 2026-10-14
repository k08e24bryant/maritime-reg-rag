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

Status: incomplete. Problems: M01: correctness is 'empty'; M01: faithfulness is 'empty'; M01: superseded_mentioned is 'empty'; M02: correctness is 'empty'; M02: faithfulness is 'empty'; M02: superseded_mentioned is 'empty'; M03: correctness is 'empty'; M03: faithfulness is 'empty'; M03: superseded_mentioned is 'empty'; M04: correctness is 'empty'; M04: faithfulness is 'empty'; M04: superseded_mentioned is 'empty'; M05: correctness is 'empty'; M05: faithfulness is 'empty'; M05: superseded_mentioned is 'empty'; M06: correctness is 'empty'; M06: faithfulness is 'empty'; M06: superseded_mentioned is 'empty'; M07: correctness is 'empty'; M07: faithfulness is 'empty'; M07: superseded_mentioned is 'empty'; M08: correctness is 'empty'; M08: faithfulness is 'empty'; M08: superseded_mentioned is 'empty'; M09: correctness is 'empty'; M09: faithfulness is 'empty'; M09: superseded_mentioned is 'empty'; M10: correctness is 'empty'; M10: faithfulness is 'empty'; M10: superseded_mentioned is 'empty'; M11: correctness is 'empty'; M11: faithfulness is 'empty'; M11: superseded_mentioned is 'empty'; M12: correctness is 'empty'; M12: faithfulness is 'empty'; M12: superseded_mentioned is 'empty'; M13: correctness is 'empty'; M13: faithfulness is 'empty'; M13: superseded_mentioned is 'empty'; M14: correctness is 'empty'; M14: faithfulness is 'empty'; M14: superseded_mentioned is 'empty'; M15: correctness is 'empty'; M15: faithfulness is 'empty'; M15: superseded_mentioned is 'empty'; M16: correctness is 'empty'; M16: faithfulness is 'empty'; M16: superseded_mentioned is 'empty'; M17: correctness is 'empty'; M17: faithfulness is 'empty'; M17: superseded_mentioned is 'empty'; M18: correctness is 'empty'; M18: faithfulness is 'empty'; M18: superseded_mentioned is 'empty'; M19: correctness is 'empty'; M19: faithfulness is 'empty'; M19: superseded_mentioned is 'empty'; M20: correctness is 'empty'; M20: faithfulness is 'empty'; M20: superseded_mentioned is 'empty'

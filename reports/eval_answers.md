# Answer evaluation (Phase 4, Step 3)

54 gold questions; both LLMs answer from the same stored context per question (retrieval `hybrid_rerank`, k=5, version + same-Pasal + Penjelasan->body expansion; score gate off). Rules: `docs/eval_plan.md` section 3 and post-hoc changes 1 and 3. Counts are k/n; n is small.

**As-run** = the original Step 3 run (commit ea06e6e, `reports/eval_answers_asrun.md`). **Fixed** = after post-hoc change 3: bug 1 (the same-Pasal budget dropped retrieved hits even when that could not make room; contexts rebuilt, only changed contexts re-asked) and bug 2 (a bracketed prose note was rewritten as a citation; post-check re-applied to the cached outputs, no new LLM calls).

- groq: `openai/gpt-oss-120b`, prompt version `545e28f41d`; as-run metrics recomputed from the cache match the saved as-run report.
- groq-qwen: `qwen/qwen3.8-27b`, prompt version `56e657a18b`; as-run metrics recomputed from the cache match the saved as-run report.

| metric | groq as-run | groq fixed | groq-qwen as-run | groq-qwen fixed |
|---|---|---|---|---|
| answers complete | 54 | 54 | 54 | 54 |
| refusal accuracy (out-of-scope refused) | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) | 10/10 (100%) |
| false refusals (in-scope refused, any reason) | 0/44 (0%) | 0/44 (0%) | 0/44 (0%) | 0/44 (0%) |
| false-refusal reasons | - | - | - | - |
| truncated | 0 | 0 | 0 | 0 |
| citations valid / parsed | 83/83 | 82/82 | 133/133 | 136/136 |
| valid citations normalized | 3 | 3 | 1 | 0 |
| answers with an invalid citation | 0 | 0 | 0 | 0 |
| answers with a flagged ayat | 0 | 0 | 1 | 1 |
| context hit (gold chunk in context) | 39/44 (89%) | 40/44 (91%) | 39/44 (89%) | 40/44 (91%) |
| amended: answered | 8/8 | 8/8 | 8/8 | 8/8 |
| amended: cites the current version | 7/8 | 7/8 | 7/8 | 7/8 |
| amended: cites superseded text | 2 | 1 | 2 | 2 |
| Cipta Kerja warning when UU 17/2008 cited | 10/10 (100%) | 10/10 (100%) | 12/12 (100%) | 13/13 (100%) |
| generate latency median / p90 (s) | 1.1 / 4.0 | 1.1 / 4.0 | 0.7 / 1.2 | 0.7 / 1.3 |
| rate-limit wait (s) | 5 | 5 | 19 | 19 |
| tokens prompt / output (reasoning) | 151918 / 8650 (2437) | 154431 / 8704 (2515) | 143047 / 8944 (0) | 145458 / 9448 (0) |
| estimated cost of these answers (USD) | 0.0280 | 0.0284 | 0.1502 | 0.1542 |

## Questions that changed (as-run -> fixed)

**groq**: 3 question(s)

| id | slice | why | result | gold in context | cited |
|---|---|---|---|---|---|
| F01 | factual_id | context: bug 1, hits no longer dropped (uu_17_2008-0075, uu_17_2008-0069) | answered -> answered | True -> True | uu_17_2008-0070 -> uu_17_2008-0070 |
| F05 | factual_id | context: bug 1, hits no longer dropped (uu_17_2008-0233, pm_59_2021-0005) | answered -> answered | False -> True | pm_59_2021-0112, pm_59_2021-0104 -> pm_59_2021-0104, uu_17_2008-0233 |
| A07 | amended | context: bug 1, hits no longer dropped (pm_50_2021-0008, uu_66_2024-0073, uu_17_2008-0216) | answered -> answered | True -> True | uu_17_2008-0008, uu_66_2024-0072 -> uu_66_2024-0072 |

**groq-qwen**: 4 question(s)

| id | slice | why | result | gold in context | cited |
|---|---|---|---|---|---|
| F01 | factual_id | context: bug 1, hits no longer dropped (uu_17_2008-0075, uu_17_2008-0069) | answered -> answered | True -> True | uu_17_2008-0070 -> uu_17_2008-0070 |
| F05 | factual_id | context: bug 1, hits no longer dropped (uu_17_2008-0233, pm_59_2021-0005) | answered -> answered | False -> True | pm_59_2021-0104 -> pm_59_2021-0104, uu_17_2008-0233 |
| F10 | factual_id | post-check: bug 2, bracketed note no longer rewritten as a citation | answered -> answered | True -> True | pp_31_2021-0244, pp_61_2009-0078 -> pp_31_2021-0244 |
| A07 | amended | context: bug 1, hits no longer dropped (pm_50_2021-0008, uu_66_2024-0073, uu_17_2008-0216) | answered -> answered | True -> True | uu_66_2024-0072 -> uu_66_2024-0072, uu_66_2024-0073 |

## Per slice, fixed (answered / n; gold in context)

| slice | groq | groq-qwen |
|---|---|---|
| factual_id | 24/24; 21 | 24/24; 21 |
| which_pasal | 7/7; 7 | 7/7; 7 |
| amended | 8/8; 7 | 8/8; 7 |
| english | 5/5; 5 | 5/5; 5 |
| out_of_scope | 0/10; 0 | 0/10; 0 |

## Questionable gold (no question changed; reported, not re-scored)

- **F07**: Gold is PP 31/2021 Pasal 73 only. UU 17/2008 Pasal 104 states the same conditions for building a special terminal, and both LLMs answered from it (Qwen also cited the revoked PP 61/2009 Pasal 111 and said it was revoked). A legally sound answer that misses the gold chunk.
- **F13**: The same list of special goods (kayu gelondongan, barang curah, rel, ternak) is in PM 93/2013 Pasal 96 (retrieved at rank 1), UU 17/2008 Pasal 45 and PP 31/2021 Pasal 23, not only in the gold PP 20/2010 Pasal 185.
- **A01**: UU 17/2008 Pasal 28 ayat (1) also answers who grants the licence (the Minister, for inter-provincial routes; retrieved at rank 4). The amended-slice target, PM 74/2016 Pasal 71 (application to the Head of BKPM), is not in the context, so the amendment is not tested.

## System weaknesses seen in the answers

- **F24**: Answering from a neighbouring Pasal instead of refusing: the gold (PM 5/2024 Pasal 10, the operator's obligations) is not in the context, and both LLMs present PM 5/2024 Pasal 4 (the programme's principles) as the operator's obligations. Faithful to what they cite, but it answers a different question.
- **F05**: Same pattern in the as-run answers: the gold UU 17/2008 Pasal 224 had been dropped from the context (bug 1), and both LLMs answered with the crew-recruitment requirements of PM 59/2021 Pasal 99. The fixed run tests whether restoring the gold changes the answer.

Correctness and faithfulness are judged in Step 4 (LLM-as-judge, validated by hand).

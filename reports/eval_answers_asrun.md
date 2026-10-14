# Answer evaluation (Phase 4, Step 3)

54 gold questions; both LLMs answer from the same stored context per question (retrieval `hybrid_rerank`, k=5, version + same-Pasal + Penjelasan->body expansion; score gate off). Rules: `docs/eval_plan.md` section 3 and post-hoc change 1. Counts are k/n; n is small.

| metric | groq (`openai/gpt-oss-120b`) | groq-qwen (`qwen/qwen3.8-27b`) |
|---|---|---|
| answers complete | 54/54 | 54/54 |
| refusal accuracy (out-of-scope refused) | 10/10 (100%) | 10/10 (100%) |
| false refusals (in-scope refused, any reason) | 0/44 (0%) | 0/44 (0%) |
| false-refusal reasons | - | - |
| truncated | 0 | 0 |
| citations valid / parsed | 83/83 | 133/133 |
| valid citations normalized | 3 | 1 |
| answers with an invalid citation | 0 | 0 |
| answers with a flagged ayat | 0 | 1 |
| context hit (gold chunk in context) | 39/44 (89%) | 39/44 (89%) |
| amended: answered | 8/8 | 8/8 |
| amended: cites the current version | 7/8 | 7/8 |
| amended: cites superseded text | 2 | 2 |
| Cipta Kerja warning when UU 17/2008 cited | 10/10 (100%) | 12/12 (100%) |
| generate latency median / p90 (s) | 1.1 / 4.0 | 0.7 / 1.2 |
| rate-limit wait (s) | 5 | 19 |
| tokens prompt / output (reasoning) | 151918 / 8650 (2437) | 143047 / 8944 (0) |
| estimated cost (USD) | 0.0280 | 0.1502 |

## Per slice (answered / n; context hit)

| slice | groq | groq-qwen |
|---|---|---|
| factual_id | 24/24; 20 | 24/24; 20 |
| which_pasal | 7/7; 7 | 7/7; 7 |
| amended | 8/8; 7 | 8/8; 7 |
| english | 5/5; 5 | 5/5; 5 |
| out_of_scope | 0/10; 0 | 0/10; 0 |

Correctness and faithfulness are judged in Step 4 (LLM-as-judge, validated by hand).

# Phase 4 evaluation plan

Written 2026-10-14, **before any Phase 4 result exists**. The metrics, slices, selection rules
and thresholds below are fixed. If something has to change after results are seen, it is added
under "Post-hoc changes" at the end with the date and the reason, and the original rule is still
reported. Nothing above that section is edited after the first result.

## 1. Question set

### Slices

| slice | target n | what it tests |
|---|---|---|
| `factual_id` | ~25 | a fact stated in one Pasal (or a few sibling chunks), asked in Indonesian |
| `which_pasal` | ~7 | "which Pasal / regulation governs X": the answer is a location, not a fact |
| `amended` | ~8 | a Pasal amended inside the corpus: PM 93/2013 -> PM 74/2016 / PM 23/2022, PM 59/2021 -> PM 3/2026, UU 17/2008 -> UU 66/2024, including at least one repealed ("dihapus") Pasal |
| `english` | ~5 | English question over Indonesian sources (cross-lingual); 2 of them on the UNCTAD Overview |
| `out_of_scope` | 10 | nothing in the corpus answers it; the expected result is the "not found" message |

"In-scope" means every slice except `out_of_scope`.

### How questions are made

- **Selected from specific chunks**, spread across the documents in proportion to their size,
  with a minimum of one question per regulation, and some on the formerly OCR-noisy documents
  (UU 66/2024, PP 31/2021).
- **Paraphrased**: a question must not copy distinctive wording from its gold chunk. Shared
  legal terms of art (e.g. "Surat Persetujuan Berlayar", "pelayaran-rakyat") are allowed; copied
  phrases are not. The draft export shows, per question, the longest run of consecutive words
  shared with the gold chunk text (column `auto_check`), so copying is visible in review.
- **Out-of-scope**: the questions must not be answerable from the corpus. Some are near the
  domain (they share words with maritime regulation), so a keyword match is not enough to
  answer them. Absence is checked by a keyword search of `chunks.jsonl` when drafting.

### Gold labels

- `gold_chunk_ids`: every chunk that contains (part of) the answer. Rules:
  - siblings (other chunks of the same Pasal) are included only if they contain part of the answer;
  - `amended` slice: both the current version (the amending document's chunk) and the
    superseded base chunk of the same Pasal. Retrieving either counts as a retrieval hit,
    because version expansion adds the current version to the context. The answer metrics
    below check that the *current* version is cited. The current-version chunks are derived
    from metadata (the gold chunks that have `amends_doc` and are not superseded);
  - repealed Pasal: the repealing chunk ("Pasal X dihapus") and the base chunk;
  - `out_of_scope`: empty.
- `reference_answer`: a short answer written from the gold chunk text, in the question's language.

### Review (by the project owner, not the system)

The draft is exported to `data/eval/questions_draft.xlsx`. Each row gets a decision:
`keep`, `edit` (with `corrected_question` and/or `corrected_gold`), or `delete`.
`maritime-eval-questions validate` turns the reviewed file into `data/eval/questions_gold.csv`.
After that file exists, questions and gold are frozen: no question is edited, added or removed
because of a result.

## 2. Retrieval evaluation (local, no LLM)

**Configurations**: `bm25` with the heading prefix (current default), `bm25` without it,
`dense` (e5), `hybrid` (RRF of bm25-with-heading + dense, as configured), and `hybrid+rerank`
(bge-reranker-v2-m3 over the top 20). Every configuration returns its top 10, without version
or sibling expansion (that is answer-time context, evaluated in section 3).

**Metrics** (in-scope questions only; out-of-scope questions have no gold):
- Hit@1, Hit@5: share of questions with at least one gold chunk in the top 1 / top 5.
- MRR@10: mean of 1 / rank of the first gold chunk in the top 10 (0 if none).
- Reported overall and per slice, each with a **bootstrap 95% CI**: 2000 resamples of the
  questions with replacement, percentile interval, seed = `seed` in `configs/retrieval.yaml`
  (42). With ~40 in-scope questions the intervals are wide (about +/- 0.15 for a proportion
  near 0.7). Per-slice CIs, with n = 5-25, are wider still and are shown for context only.

**Selection rule** (fixed):
1. Rank the configurations by overall in-scope Hit@5 (point estimate).
2. The selected configuration is the simplest one whose Hit@5 is within 0.02 of the best.
   Simplicity order: `bm25` (either variant) < `dense` < `hybrid` < `hybrid+rerank`.
3. Between the two BM25 variants, the higher Hit@5 wins; a tie keeps the heading prefix
   (the current default).
4. Remaining ties: higher MRR@10, then the simpler configuration.

The selected configuration is used in sections 3-4. The CIs are reported next to the choice:
the choice follows the rule, and overlapping CIs are stated, not hidden.

**Gate calibration** (roadmap item; reported, not enabled automatically). Using the
`hybrid+rerank` top-1 reranker score, candidate thresholds are 0.005, 0.01, 0.02, 0.05 and 0.1.
The proposed `gate.min_rerank_score` is the largest candidate that refuses at most 1 in-scope
question. Its out-of-scope refusal rate is reported. Enabling the gate stays a manual decision.

## 3. Answer evaluation

- **Retrieval**: the selected configuration, plus version and same-Pasal expansion as configured
  in `configs/answer.yaml`. The context is computed **once per question** and shared by both
  LLMs (same retrieval fingerprint), so the LLMs are compared on identical context.
- **LLMs**: `groq` (`openai/gpt-oss-120b`) and `groq-qwen` (`qwen/qwen3.8-27b`). No local LLM.
- **Budget and caching**: before the first call, Groq's daily request and token limits are read
  from the response headers and a budget plan is printed. Every answer is cached by
  (question id, retrieval fingerprint, model id, prompt version). A cached answer is never asked
  again, so runs resume across days.

**Automatic metrics** (per LLM):
- **Refusal accuracy**: share of `out_of_scope` questions refused (`no_hits`, `gate`,
  `model_not_found`, `no_valid_citation`). A truncated answer is not a correct refusal.
- **False-refusal rate**: share of in-scope questions refused for any reason, including truncated.
- **Truncation count**: answers stopped by the output limit (never counted as answers).
- **Citation validity**: valid / parsed citations over answered questions; also the share of
  citations that were normalized (no brackets / page filled), and answers with a flagged ayat.
- **Context hit**: the context given to the LLM contains a gold chunk. Correctness (section 4)
  is also reported separately for questions with and without a context hit, to separate
  retrieval errors from generation errors.
- **Amended slice**: cites a current version (a gold current-version chunk among the valid
  citations); cites superseded text (the automatic warning fired); Cipta Kerja warning present
  whenever UU 17/2008 is cited.
- **Latency**: median and p90 of the generation time; rate-limit waiting is reported separately.

## 4. LLM-as-judge, validated by hand

- **Cross-judging**: gpt-oss judges Qwen's answers and Qwen judges gpt-oss's, so no model
  grades itself. Only in-scope answered questions are judged; refusals and truncations are
  already scored by section 3.
- **The judge sees**: the question, the gold chunk text, the reference answer, the sources
  given to the answering LLM (with their status), and the answer.
- **The judge answers** in JSON: `correctness`, `faithfulness`, `superseded_mentioned`, plus a
  one-sentence rationale. Judge outputs are cached like answers (keyed by answer hash, judge
  model, rubric version).
- **Rubric** (also the instructions for manual labels):
  - `correctness` vs the gold chunk text and the reference answer:
    `correct` = all key points of the reference, nothing contradicting the gold text;
    `partial` = some key points missing, or a minor error that does not change the main answer;
    `wrong` = contradicts the gold text, answers a different question, or the main point is missing.
  - `faithfulness` vs the sources given to the LLM (not the gold):
    `supported` = every statement follows from the cited sources;
    `partly` = mostly supported, but at least one statement is not in the sources
    (an added qualifier, a duty attributed to the wrong party, an inference stated as fact);
    `unsupported` = the main claims are not in the sources.
  - `superseded_mentioned`: `n.a.` if no SUPERSEDED/REPEALED source relevant to the question is
    in the context; otherwise `yes` if the answer says the old version was amended or repealed
    (and by which document), else `no`.
- **Manual validation**: a stratified sample of 20 judged answers (10 per LLM, spread across
  slices in proportion, seed 42) is exported to `data/eval/manual_labels.xlsx` **without** the
  judge labels. Each criterion is a dropdown.
- **Agreement**: % agreement and Cohen's kappa (unweighted), per criterion, between the
  manual and judge labels. With n = 20, kappa is unstable; it is reported with that caveat.
- **Rule**: if kappa < 0.40 for a criterion, the judge's labels for that criterion are not used
  for the headline LLM comparison. The manual labels on the sample are reported instead,
  marked as n = 20.

## 5. Report

`reports/eval.json` (all numbers), `reports/eval.md` (tables, the selection decision, gate
proposal, LLM comparison, limitations) and `reports/figures/` (retriever comparison with CIs,
LLM comparison).

**Limitations stated in advance**:
- n is small.
- Questions are drafted by the system's author (an LLM) from chunks, which favours retrievable
  phrasing even after paraphrasing.
- One human annotator.
- The judges are the same two models being compared (cross-judged, not independent).
- Groq outputs are not fully deterministic.
- fp16 retrieval jitter can swap near-tied hits.
- The corpus lacks consolidated text and Cipta Kerja amendments.

## Gold review log (before any result)

2026-10-14, review of `data/eval/questions_draft.xlsx` by the project owner;
`maritime-eval-questions validate` wrote `data/eval/questions_gold.csv` (55 questions,
3 edited, 0 deleted). No retrieval or answer result existed at that point.

- **A04**: question premise fixed. The repealed PM 93/2013 Pasal 18 was about a report to the
  Director General (a request for approval), not a general prior duty; the question now asks
  whether that approval route still exists.
- **F17, F18**: gold extended with the general sanction rules of PP 31/2021, Pasal 223
  (`pp_31_2021-0241`, warning -> freeze -> revocation steps) and Pasal 222
  (`pp_31_2021-0240`, direct freeze/revocation), which answer the same questions.
- **F24, A05**: reference answers extended (edited in place).

Found in the same review, to apply before the freeze (a re-run of `validate`):

- **F12**: its only gold, PP 61/2009 Pasal 122 (5-year special-terminal permit), is revoked by
  PP 31/2021 Pasal 233 ayat (1) huruf b. Delete F12.
- **F07**: its second gold, PP 61/2009 Pasal 111 (`pp_61_2009-0114`), is revoked by the same
  provision; the current rule is PP 31/2021 Pasal 73. Gold becomes `pp_31_2021-0082` only, and
  the reference answer drops the PP 61/2009 note.
- Checked: no other gold chunk is in PP 31/2021's revocation lists (PP 20/2010 Pasal 182 and
  185; PP 61/2009 Pasal 6, 20 and 28 are still in force).
- Checked: PP 31/2021 Pasal 220-224 (general administrative sanctions) carry
  "BAB VIII MANAJEMEN KEAMANAN KAPAL". The source PDF has no other BAB heading between Pasal 170
  and 225, so this is the regulation's own structure, not a chunker error. No change; chunk ids
  are unchanged.

## Post-hoc changes

Decided 2026-10-14, **after the retrieval results** (`reports/eval_retrieval.md`) and **before
any answer or judge result**. The rules above are unchanged; these change the answer-time context
and the judge input only. The retrieval evaluation and its selection are not re-run or re-scored.

1. **Penjelasan -> body expansion at answer time** (motivated by miss E03: the Penjelasan of UU
   17/2008 Pasal 219 was retrieved at rank 1, but its body, which holds the answer, was not). When a
   Penjelasan chunk is in the answer context, the body chunk(s) of the same Pasal are added before
   it. This uses the same token budget (`versions.max_context_tokens`) and the same priority rules
   as sibling expansion: top-2 retrieved hits first, cuts logged. Answer context only; retrieval
   rankings, retrieval metrics and the selected configuration are unchanged.
2. **Judge input** (section 4): the judge sees only the question, the gold chunk text, the reference
   answer, **the sources the answer actually cited** (with their status), and the answer. It does
   not see the full context. `faithfulness` is therefore judged against the cited sources:
   `supported` = every statement follows from the sources it cites; `partly` = at least one
   statement is not in the cited sources (even if it may be elsewhere in the context);
   `unsupported` = the main claims are not in the cited sources. `correctness` and
   `superseded_mentioned` are unchanged; for `superseded_mentioned`, "relevant superseded source" is
   judged from the gold chunks and the cited sources' status.

3. **Two bug fixes found in the Step 3 answers** (decided 2026-10-14, **after the Step 3 answer
   results**, before any judge result). Step 3 is reported **both as-run and fixed**: the as-run
   state is preserved in commit ea06e6e and `reports/eval_answers_asrun.md`/`.json`, and
   `reports/eval_answers.md` shows both side by side, with every changed question and why.
   - **Bug 1, same-Pasal budget**: to fit the chunks of the top-2 retrieved Pasal, lower-ranked hits
     were dropped even when dropping could not make enough room. In F01, F05 and A07, UU 17/2008
     Pasal 1 (definitions, 7 chunks) was a top-2 Pasal. Its chunks were cut anyway, and 2-3 hits were
     lost per question, including **F05's gold** (UU 17/2008 Pasal 224, retrieval rank 4). Fix:
     lower-ranked hits are dropped only if the drops make the priority chunks fit; otherwise none is
     dropped. The contexts are rebuilt (`contexts --force`); only questions whose context
     fingerprint changed are re-asked.
   - **Bug 2, bracketed notes**: a bracket naming a regulation was always parsed as a citation, so
     Qwen's F10 note "[Keterangan: Pasal 75 PP 61/2009 ... telah dicabut oleh PP 31/2021.]" was
     rewritten to "[PP 61/2009, Pasal 75, p. 38]" and lost its message. Fix: a bracket is a citation
     only if almost nothing but document, Pasal, ayat, huruf and page remains, and it has no sentence
     verb. Re-applied to the cached outputs with `recheck` (no LLM calls); only Qwen F10 changes
     among the 108 as-run answers.
   - Prompt, rubric and gold are unchanged. Step 4 judges the fixed answers.

Not changed (future work, see `docs/roadmap.md`): no retrieval change, e.g. demoting REPEALED or
revoked chunks in the ranking. Motivating example: F07, where the revoked PP 61/2009 Pasal 111 ranks
first and the current PP 31/2021 Pasal 73, with near-identical text, is not in the top 10.

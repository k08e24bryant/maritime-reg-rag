# Roadmap and carried-over decisions

Decisions made while reviewing Phase 1 that later phases must implement.

## Phase 2: indexing (BM25 + embeddings)

- **Embedding text.** Embed `heading + "\n" + text`, where `heading` is the stored breadcrumb
  ("UU 17/2008 tentang Pelayaran > BAB V ANGKUTAN DI PERAIRAN > ... > Pasal 28 ayat (5)-(6)").
  Use the e5 `passage: ` prefix. The stored `text` and the cited text stay the original document
  text; the context exists only in the embedding input. This is what makes the 133 chunks under
  25 tokens (genuinely short Pasal) retrievable, so they are kept as-is.
- Keep the 400-token chunk cap; heading + prefix must still fit e5's 512-token limit.

## Phase 3: answering with citations

- **Citations**: `doc + Pasal/ayat (or section) + source_file + physical page_start-page_end`.
  Pages are physical PDF pages (1-based) of `source_file`. PP 31/2021 has a separate Penjelasan
  file, so cite its `source_file`, not just the doc.
- **Amendments (no consolidated text):**
  - If a retrieved chunk has `superseded_by`, also fetch the newest amending chunk
    (`amends_doc == chunk.doc_id` or the same base doc, `amends_pasal == chunk.pasal`, doc =
    `superseded_by[-1]`). Show the newest version first, and label the older one
    "superseded by <doc>".
  - If it has `partially_amended_by`, show it with a note that some ayat/huruf (or its
    Penjelasan) was changed by <doc>, and include that amending chunk.
  - `amendment_kind == "delete"`: the Pasal is repealed; say so instead of quoting old text as law.
  - If it has `may_be_amended_by_out_of_corpus` (all UU 17/2008 chunks: UU 11/2020 and
    UU 6/2023, Cipta Kerja), show a warning that the cited text may have been changed by those
    laws, which are not in the corpus.
- Never present superseded text as current law.
- Implemented in Phase 3 (`maritime_rag.answer.versions`). Also added: PP 20/2010 and PP 61/2009
  are `partially_revoked` by PP 31/2021 with no per-Pasal links, so their chunks carry a "this
  Pasal may no longer apply" note and a warning when cited.
- Open for Phase 4: calibrate `gate.min_rerank_score` (reranker score as the "nothing relevant"
  signal), and decide whether the reranker stays on by default.

### Phase 3 status (2026-10-14)

- **LLMs** (`configs/answer.yaml` -> `llm.profiles`): `groq` (default, `openai/gpt-oss-120b`) and
  `groq-qwen` (`qwen/qwen3.8-27b`, preview; `qwen/qwen3.6-27b` does not exist on Groq). Both share
  Groq's free tier (8000 tokens/min, about one question per minute).
  - `gemini` (`gemini-3.8-flash`) is kept but **unreliable on the free tier**: probes took
    53-81 s for 5 tokens, with 503s, and the examples run timed out at 300 s twice. It is not
    part of the Phase 3 results. `gemini-2.5-flash` is still listed but refused for new accounts.
  - `ollama` (local) is refused unless run with `--llm ollama --allow-local` (the laptop
    shut down from low RAM). e5 and the reranker run locally: peak RAM 3.4-3.7 GB, VRAM 1.8 GB.
- **Context**: hybrid+rerank top 5, then version expansion, then same-Pasal (sibling) expansion
  within `versions.max_context_tokens` (2800 e5 tokens, about 5850 Groq prompt tokens). Siblings of
  the top-2 retrieved Pasal come first. 2500 had cut PM 93/2013 Pasal 69 ayat (3)-(7) from q02.
- **Smoke results** (`reports/llm_comparison_phase3.md`, final runs, identical retrieval for
  both LLMs):
  - 5/5 in-scope queries answered by both models; the out-of-scope query refused by both;
  - 59 valid citations, 1 invalid (a checker false negative, see below);
  - no truncation.
- **Fixed during Phase 3**:
  - 【】 brackets;
  - citations without brackets or page are normalized when they map unambiguously (rescued
    gpt-oss q02, which wrote "(PM 93/2013, Pasal 69 ayat 2)");
  - rule 5 now uses a template with placeholders (Qwen had copied the old example sentence;
    gone in the final run);
  - truncated answers (output limit) are never counted as answers (Qwen max output 2048);
  - Groq pacing counts prompt + the full output limit, as Groq does.
- **Known limits** (Phase 3 smoke, n = 6):
  - **Rule 5** (mention a relevant superseded source): gpt-oss 0 of 2, Qwen 2 of 2. Measure it
    on the amended-Pasal slice.
  - **Ayat range across sibling chunks**: "Pasal 69 ayat 7-8" is rejected when ayat (7) and (8)
    sit in two chunks of the same Pasal (a false negative). Fix candidate: accept a range covered
    by the union of provided sibling chunks.
  - **Citation precision**: facts from one provided Pasal cited to another provided Pasal of the
    same document (gpt-oss q06) pass the check; only the manual/judge labels can see this.
  - **Paraphrase drift** (e.g. a duty attributed to the wrong party, "salah satu" vs
    "dan/atau") is not caught automatically; this is what the faithfulness label measures.
  - **Ayat check** only flags ayat numbers absent from the chunk text; a real ayat cited for the
    wrong claim (Qwen q09: sanction in ayat (6) cited as ayat (5)) needs the manual ayat label.

## Phase 4: evaluation

- **Amended-Pasal slice.** Build a question set on Pasal that were amended inside the corpus
  (UU 17/2008 by UU 66/2024; PM 93/2013 by PM 74/2016 and PM 23/2022; PM 59/2021 by
  PM 3/2026). Score that:
  - the answer cites the newest version,
  - superseded text is labelled as such, not quoted as current,
  - repealed Pasal ("dihapus") are reported as repealed,
  - UU 17/2008 citations carry the Cipta Kerja warning.
  Report this slice separately from the overall score.
- Include questions whose answer is absent from the corpus (expect "not found"), and some on
  the formerly OCR-noisy documents (UU 66/2024, PP 31/2021) to check OCR fixes in retrieval.
- **Manual labeling plan** (per answer, by a human reader of the cited sources):
  - **faithfulness**: supported / partly / unsupported. Every statement must follow from the
    cited text. Example of "partly": q04 (Groq gpt-oss) added "memenuhi standar operasional",
    which PM 3/2026 Pasal 3 does not say. Not fixed by prompting in Phase 3.
  - **ayat accuracy**: whether each cited ayat actually holds the claim. The automatic
    post-check only flags a cited ayat number that does not appear in the chunk text (e.g.
    "(4)"). It cannot see a real ayat cited for the wrong claim (q04 cited Pasal 3A ayat (1)
    for the 2-year validity in ayat (4)).
  - **mentions replaced versions**: when a SUPERSEDED/REPEALED source is relevant, the answer
    names it (prompt rule 5); unrelated superseded sources are not required.
- **LLM comparison**: run `maritime-answer-examples --llm <profile> --per-llm` for each profile
  (groq gpt-oss and groq-qwen; gemini only if its free tier becomes responsive). Compare answers only for questions whose
  retrieval fingerprint is equal across the reports (fp16 jitter can swap near-tied hits).
- Calibrate `gate.min_rerank_score` and decide whether the reranker stays on by default.
- Check that `versions.max_context_tokens` (sibling budget) rarely cuts or drops hits: count
  `siblings_cut` and `hits_dropped` per run.
- Count answers refused only for citation format (zero parseable citations, draft otherwise
  fine) before deciding on an automatic re-ask.

## Future work (not in the Phase 4 evaluation)

- **Retrieval-time handling of REPEALED / revoked chunks.** F07 (Phase 4 retrieval): the revoked
  PP 61/2009 Pasal 111 ranks first, and the current PP 31/2021 Pasal 73, with near-identical text,
  is not in the top 10. Options: demote chunks labelled REPEALED by a revocation list, or map a
  revoked Pasal to its successor (no explicit link exists; text similarity within the revoking
  document). Deliberately not done during Phase 4 (docs/eval_plan.md, post-hoc changes).
- **Cross-lingual gate.** English questions get low bge-reranker scores (E03/E04 about 0.014), in
  the range of some out-of-scope questions; a single score threshold cannot separate them.

## Data follow-ups

- PP 31/2021: swap the 2021 scan for the born-digital copy from peraturan.go.id (body +
  separate Penjelasan file). The manual overrides for the scan then report as stale; remove them.
- PM 74/2016 and PM 5/2024 stay on their embedded OCR layer (decision: leave as is).
- **Per-Pasal revocation (done, before Phase 4 Step 3)**: `maritime_rag.revocations` reads
  revocation lists from closing provisions at load time. PP 31/2021 Pasal 233 ayat (1) revokes
  123 Pasal: PP 20/2010 80 (78 whole; Pasal 40 ayat (1) and Pasal 43 ayat (1)-(2) only) and
  PP 61/2009 43. These chunks (147, body and Penjelasan) are labelled REPEALED by PP 31/2021, or
  get an "ayat (n) revoked" note. Unlisted Pasal of the two documents keep a softer note.
  - Labels only: chunks.jsonl, chunk ids, text and the index are unchanged.
  - The PP 20/2010 list names Pasal 138 twice and omits 128 (probably a source typo for 128). It is
    parsed as written.
  - Other closing provisions in the corpus revoke whole regulations that are not in the corpus.
  - `maritime-search` / `maritime-smoke` status strings (`retrieval.search.version_status`) do not
    show these revocations yet; the answer pipeline does.

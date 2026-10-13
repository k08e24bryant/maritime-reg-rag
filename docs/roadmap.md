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

## Data follow-ups

- PP 31/2021: swap the 2021 scan for the born-digital copy from peraturan.go.id (body +
  separate Penjelasan file). The manual overrides for the scan then report as stale; remove them.
- PM 74/2016 and PM 5/2024 stay on their embedded OCR layer (decision: leave as is).

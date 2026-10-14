# maritime-reg-rag

Retrieval-augmented Q&A over public Indonesian maritime/logistics regulations (UU, PP,
Permenhub) and the UNCTAD *Review of Maritime Transport 2025: Overview*. Every answer cites
its source: document + Pasal/section + page.

## Setup

```bash
uv sync
```

Re-OCR (UU 66/2024 is a scan with a poor OCR layer) and the OCR quality metric need two
external resources, both kept in the gitignored `.cache/`:

```bash
# Tesseract 5 (Windows: winget install UB-Mannheim.TesseractOCR); path in configs/ingest.yaml -> ocr.tesseract_cmd
mkdir -p .cache/tessdata .cache/wordlists
curl -L -o .cache/tessdata/ind.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/ind.traineddata
cp -r "<tesseract install dir>/tessdata/configs" "<tesseract install dir>/tessdata/pdf.ttf" .cache/tessdata/
curl -L -o .cache/wordlists/00-indonesian-wordlist.lst https://raw.githubusercontent.com/geovedi/indonesian-wordlist/master/00-indonesian-wordlist.lst
```

## Data

Raw PDFs are not committed. `data/manifest.csv` lists every document with its official
source URL. Download each file into `data/raw/` under the name in the `file` column, e.g.

```bash
curl -L -o data/raw/uu_17_2008.pdf "https://peraturan.bpk.go.id/Download/28451/UU%20Nomor%2017%20Tahun%202008.pdf"
```

An optional `penjelasan_file` column names a separate Penjelasan PDF (e.g. the TLN published
next to the Lembaran Negara body on peraturan.go.id). The UNCTAD entry points to the report
landing page; download the *Overview* PDF from there as `data/raw/unctad_rmt_2025.pdf`.
`reports/validation.md` records the SHA-256 of each file used for the committed stats.

## Phase 1: ingestion

```bash
uv run maritime-ingest            # config: configs/ingest.yaml, manual fixes: configs/overrides.yaml
uv run maritime-ocr-quality       # optional: --candidate DOC_ID=PATH[,PATH] to score a replacement
uv run pytest
```

Output:
- `data/processed/chunks.jsonl`: one chunk per Pasal (long Pasal split by ayat), plus
  preamble, Penjelasan, and Lampiran chunks. UNCTAD is chunked by section heading.
  Metadata covers doc_id, title, number, year, bab, pasal, ayat, source_file, page_start,
  page_end, and text_layer. Amendment metadata: amends_doc, amends_pasal, amendment_kind,
  superseded_by, partially_amended_by, may_be_amended_by_out_of_corpus.
- `reports/validation.md`: manifest check, OCR-layer pages, and near-empty pages.
- `reports/ingest_stats.md`: chunks per document, token distribution, amendment links,
  manual overrides, and Pasal parsing issues.
- `reports/ocr_quality.md`: wordlist hit rate before and after re-OCR or replacement.

Page numbers are physical PDF pages (1-based) of `source_file`, so a citation opens at the
right page in any viewer. Decisions for later phases are in `docs/roadmap.md`.

## Phase 3: answers with citations

The LLM is a named profile in `configs/answer.yaml` (`llm.profiles`), chosen with `--llm`:
- `groq` (default): `openai/gpt-oss-120b` via Groq's OpenAI-compatible API, key `GROQ_API_KEY`.
- `groq-qwen`: `qwen/qwen3.8-27b` on Groq (preview model, same key), a second LLM for comparison.
- `gemini`: `gemini-3.8-flash` via Google's OpenAI-compatible API, key `GEMINI_API_KEY`
  (unreliable on the free tier: frequent timeouts).
- `openai`, `anthropic`: keys `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`.
- `ollama`: a local LLM (`qwen2.5:7b-instruct`). Refused unless run with `--llm ollama --allow-local`.

Keys go in a local `.env` (gitignored; shell variables take precedence). Before loading any
model, the CLI checks the key, that the configured model id is listed by the provider's
`/models` endpoint (a missing one fails with the available ids), and sends one 5-token probe
request: a model can be listed but refused (Gemini retires models for new accounts). HTTP 429/503
are retried with exponential backoff, honouring Retry-After, and each cloud profile paces its
calls for the free tier (`min_interval_s`, `tokens_per_minute`). Nothing falls back silently to
another LLM. With a cloud LLM only the e5 encoder and the reranker run locally.

```bash
uv run maritime-ask "Apa persyaratan untuk memperoleh izin usaha perusahaan angkutan laut?"   # groq
uv run maritime-ask "Can a foreign-flagged ship carry cargo between Indonesian domestic ports?" --no-rerank
uv run maritime-answer-examples --llm groq --per-llm   # -> reports/answer_examples_groq.md
uv run maritime-answer-examples --llm gemini --only q02_amended_pm74 q10_out_of_scope --output reports/answer_examples_gemini_trial.md
```

Each report names the LLM profile and model id on every answer, plus a retrieval fingerprint
(hash of the context chunk ids) per question, so per-LLM reports can be checked for identical
retrieval before comparing answers. It also records peak RAM/VRAM of the local models.

Pipeline (config: `configs/answer.yaml`): hybrid retrieval (+ reranker, on by default for now) ->
version expansion -> prompt -> LLM -> citation post-check.
- **Version expansion** adds the newest wording of a superseded Pasal, the repeal of a repealed
  one, and the amending chunks of a partly amended one, even when retrieval missed them. Every
  source is labelled CURRENT, SUPERSEDED by <doc> or REPEALED by <doc>. A relevant superseded
  or repealed source must be mentioned in the answer.
- **Same-Pasal expansion**: a long Pasal is split by ayat into several chunks; when one is
  retrieved, the others are added in ayat order within `versions.max_context_tokens`. Siblings
  of the top-2 retrieved Pasal come first (lower-ranked hits may be dropped to fit them); cuts
  and drops are logged and shown in the report.
- **Citations** are `[<doc>, Pasal X ayat Y, p. N]`. The post-check maps each one to a provided
  source (doc, Pasal, Penjelasan, ayat, page). Citations that do not match are flagged (or dropped).
  A citation whose ayat number does not appear in the cited chunk's text gets a warning.
  An answer with no valid citation is replaced by the fixed "not found" message.
- **Warnings**: cited UU 17/2008 text (Cipta Kerja amendments are not in the corpus), cited
  PP 20/2010 or PP 61/2009 text (partly revoked by PP 31/2021, not linked per Pasal), and cited
  superseded text.
- An optional reranker-score gate (off) refuses before the LLM call; its threshold comes from Phase 4.
- Every LLM call is logged to `logs/llm_calls.jsonl`: profile, model id, tokens, latency, retries,
  wait, and calls/tokens in the last 60 s (to watch free-tier limits).

## Phase 5: demo (FastAPI + Gradio)

```bash
uv run maritime-demo            # config: configs/demo.yaml; needs GROQ_API_KEY in .env
```

One server, models loaded once: the Gradio UI at <http://127.0.0.1:7860/ui> and a JSON API with
interactive docs at <http://127.0.0.1:7860/docs>.

- **UI**: ask in Indonesian or English, pick the LLM (`groq` = gpt-oss-120b, `groq-qwen` = Qwen3.8-27B)
  and the reranker, and see the answer with citations, warnings (amended / repealed / Cipta Kerja), the
  sources given to the model with their version status, latency, tokens and estimated cost. Any source
  can be opened in full. The *Evaluation* tab shows the Phase 4 headline results and figures.
- **API**: `POST /ask {"question": "...", "llm": "groq", "rerank": true}` returns the same content as
  JSON; `GET /sources/{chunk_id}` returns one chunk; `GET /health`, `GET /examples`. An invalid question
  returns 422, an LLM provider error 503 (no fallback).
- Only the cloud profiles are offered; the local Ollama profile is never used by the demo. The server
  binds to 127.0.0.1 and has no authentication: keep it local.

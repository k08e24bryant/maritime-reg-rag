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

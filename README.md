# maritime-reg-rag

Retrieval-augmented Q&A over public Indonesian maritime/logistics regulations (UU, PP,
Permenhub) and the UNCTAD *Review of Maritime Transport*. Every answer cites its source:
document + Pasal/section + page.

## Setup

```bash
uv sync
```

## Data

Raw PDFs are not committed. `data/manifest.csv` lists every document with its official
source URL. Download each file into `data/raw/` under the name in the `file` column, e.g.

```bash
curl -L -o data/raw/uu_17_2008.pdf "https://peraturan.bpk.go.id/Download/28451/UU%20Nomor%2017%20Tahun%202008.pdf"
```

The UNCTAD entry points to the report landing page; download the *Overview* PDF from there
as `data/raw/unctad_rmt_2025.pdf`. `reports/validation.md` records the SHA-256 of each file
used for the committed stats.

## Phase 1: ingestion

```bash
uv run maritime-ingest            # config: configs/ingest.yaml
uv run pytest
```

Output:
- `data/processed/chunks.jsonl`: one chunk per Pasal (long Pasal split by ayat), plus
  preamble, Penjelasan, and Lampiran chunks. UNCTAD is chunked by section heading.
  Metadata covers doc_id, title, number, year, bab, pasal, ayat, page_start, and page_end.
- `reports/validation.md`: manifest check, OCR-layer pages, and near-empty pages.
- `reports/ingest_stats.md`: chunks per document, token distribution, and Pasal parsing issues.

Page numbers are physical PDF pages (1-based), so a citation opens at the right page in any viewer.

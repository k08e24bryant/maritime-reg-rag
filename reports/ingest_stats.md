# Ingestion stats

Total chunks: **1892**

## Chunks per document

| doc | text layer | chunks | preamble | body | penjelasan | lampiran | report | Pasal (body) | median tok | max tok |
|---|---|---|---|---|---|---|---|---|---|---|
| uu_17_2008 | born_digital | 474 | 2 | 363 | 109 | 0 | 0 | 355 | 66 | 399 |
| uu_66_2024 | tesseract_reocr | 116 | 2 | 82 | 32 | 0 | 0 | 65 | 86 | 397 |
| pp_31_2021 | born_digital | 321 | 1 | 255 | 65 | 0 | 0 | 234 | 112 | 399 |
| pp_20_2010 | born_digital | 252 | 1 | 217 | 34 | 0 | 0 | 210 | 122 | 398 |
| pp_61_2009 | born_digital | 205 | 1 | 171 | 33 | 0 | 0 | 168 | 88 | 387 |
| pm_93_2013 | born_digital | 144 | 3 | 141 | 0 | 0 | 0 | 119 | 167 | 400 |
| pm_74_2016 | ocr_embedded | 26 | 3 | 23 | 0 | 0 | 0 | 13 | 288 | 389 |
| pm_23_2022 | born_digital | 15 | 2 | 13 | 0 | 0 | 0 | 11 | 94 | 349 |
| pm_59_2021 | born_digital | 151 | 2 | 144 | 0 | 5 | 0 | 138 | 94 | 395 |
| pm_3_2026 | born_digital | 12 | 2 | 10 | 0 | 0 | 0 | 9 | 234 | 356 |
| pm_50_2021 | born_digital | 77 | 2 | 75 | 0 | 0 | 0 | 70 | 142 | 400 |
| pm_72_2017 | born_digital | 48 | 3 | 45 | 0 | 0 | 0 | 29 | 232 | 400 |
| pm_5_2024 | ocr_embedded | 21 | 1 | 20 | 0 | 0 | 0 | 19 | 109 | 393 |
| unctad_rmt_2025 | born_digital | 30 | 0 | 0 | 0 | 0 | 30 | - | 291 | 389 |

## Token length distribution (tokenizer = embedding model, cap = 400)

| stat | min | p25 | median | p75 | p95 | max | mean |
|---|---|---|---|---|---|---|---|
| tokens | 5 | 52.0 | 100.5 | 190.25 | 363.0 | 400 | 135.5 |

| tokens | chunks |
|---|---|
| 0-24 | 124 |
| 25-49 | 296 |
| 50-99 | 520 |
| 100-199 | 505 |
| 200-299 | 226 |
| 300-399 | 216 |
| 400-511 | 5 |
| 512+ | 0 |

Chunks over the cap: 0

## Amendment links

Amending chunks (inside Pasal I of an amending regulation) by kind, and how many older chunks
each amending document marks as superseded or partially amended.

| amending doc | kinds | older chunks marked |
|---|---|---|
| uu_66_2024 | 2 delete, 20 insert, 4 penjelasan, 50 replace | 66 |
| pm_74_2016 | 21 replace | 19 |
| pm_23_2022 | 2 delete, 1 insert, 8 replace | 11 |
| pm_3_2026 | 5 insert, 2 replace | 2 |

Chunks with superseded_by: 95; with partially_amended_by: 3.
uu_17_2008: 472 chunks flagged may_be_amended_by_out_of_corpus = ['UU 11/2020', 'UU 6/2023'].

## Manual overrides (configs/overrides.yaml)

- applied: uu_17_2008 penjelasan p163: 'Pasar 96' -> Pasal 96 (typo 'Pasar' in the source PDF; Penjelasan of Pasal 96 was merged into Pasal 95)

## Pasal parsing issues

### uu_17_2008

- dropped 254 trivial Penjelasan entries ('Cukup jelas.')

### uu_66_2024

- amending regulation layout (Pasal I / Pasal II)
- dropped 45 trivial Penjelasan entries ('Cukup jelas.')

### pp_31_2021

- dropped 172 trivial Penjelasan entries ('Cukup jelas.')

### pp_20_2010

- dropped 178 trivial Penjelasan entries ('Cukup jelas.')

### pp_61_2009

- dropped 137 trivial Penjelasan entries ('Cukup jelas.')

### pm_93_2013

- no issues

### pm_74_2016

- amending regulation layout (Pasal I / Pasal II)

### pm_23_2022

- amending regulation layout (Pasal I / Pasal II)

### pm_59_2021

- no issues

### pm_3_2026

- amending regulation layout (Pasal I / Pasal II)

### pm_50_2021

- no issues

### pm_72_2017

- no issues

### pm_5_2024

- no issues


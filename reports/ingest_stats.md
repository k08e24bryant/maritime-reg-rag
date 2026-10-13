# Ingestion stats

Total chunks: **1905**

## Chunks per document

| doc | chunks | preamble | body | penjelasan | lampiran | report | Pasal (body) | median tok | max tok |
|---|---|---|---|---|---|---|---|---|---|
| uu_17_2008 | 474 | 2 | 363 | 109 | 0 | 0 | 355 | 66 | 399 |
| uu_66_2024 | 116 | 2 | 84 | 30 | 0 | 0 | 65 | 98 | 389 |
| pp_31_2021 | 334 | 1 | 257 | 76 | 0 | 0 | 230 | 116 | 400 |
| pp_20_2010 | 252 | 1 | 217 | 34 | 0 | 0 | 210 | 122 | 398 |
| pp_61_2009 | 205 | 1 | 171 | 33 | 0 | 0 | 168 | 88 | 387 |
| pm_93_2013 | 144 | 3 | 141 | 0 | 0 | 0 | 119 | 167 | 400 |
| pm_74_2016 | 26 | 3 | 23 | 0 | 0 | 0 | 13 | 288 | 389 |
| pm_23_2022 | 15 | 2 | 13 | 0 | 0 | 0 | 11 | 94 | 349 |
| pm_59_2021 | 151 | 2 | 144 | 0 | 5 | 0 | 138 | 94 | 395 |
| pm_3_2026 | 12 | 2 | 10 | 0 | 0 | 0 | 9 | 234 | 356 |
| pm_50_2021 | 77 | 2 | 75 | 0 | 0 | 0 | 70 | 142 | 400 |
| pm_72_2017 | 48 | 3 | 45 | 0 | 0 | 0 | 29 | 232 | 400 |
| pm_5_2024 | 21 | 1 | 20 | 0 | 0 | 0 | 19 | 109 | 393 |
| unctad_rmt_2025 | 30 | 0 | 0 | 0 | 0 | 30 | - | 291 | 389 |

## Token length distribution (tokenizer = embedding model, cap = 400)

| stat | min | p25 | median | p75 | p95 | max | mean |
|---|---|---|---|---|---|---|---|
| tokens | 5 | 52.0 | 102 | 193.0 | 363.0 | 400 | 136.5 |

| tokens | chunks |
|---|---|
| 0-24 | 133 |
| 25-49 | 291 |
| 50-99 | 513 |
| 100-199 | 506 |
| 200-299 | 234 |
| 300-399 | 222 |
| 400-511 | 6 |
| 512+ | 0 |

Chunks over the cap: 0

## Pasal parsing issues

### uu_17_2008

- dropped 253 trivial Penjelasan entries ('Cukup jelas.')

### uu_66_2024

- repaired OCR-misread headers (2):
  - body p15: 'Pasal 268' Pasal 268 read as Pasal 26B
  - penjelasan p45: 'Pasal 268' Pasal 268 read as Pasal 26B
- dropped 47 trivial Penjelasan entries ('Cukup jelas.')

### pp_31_2021

- repaired OCR-misread headers (2):
  - body p22: 'Pasal 15' Pasal 15 read as Pasal 16
  - body p51: 'Pasal 56' Pasal 56 read as Pasal 66
- rejected header candidates (2):
  - penjelasan p158: 'Pasal 8' (follows an unfinished sentence (cross-reference))
  - penjelasan p165: 'Pasal 27' (Pasal 27 breaks the increasing sequence)
- dropped 129 trivial Penjelasan entries ('Cukup jelas.')

### pp_20_2010

- dropped 178 trivial Penjelasan entries ('Cukup jelas.')

### pp_61_2009

- dropped 137 trivial Penjelasan entries ('Cukup jelas.')

### pm_93_2013

- no issues

### pm_74_2016

- no issues

### pm_23_2022

- no issues

### pm_59_2021

- no issues

### pm_3_2026

- no issues

### pm_50_2021

- no issues

### pm_72_2017

- no issues

### pm_5_2024

- no issues


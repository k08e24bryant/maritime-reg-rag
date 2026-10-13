# OCR quality

Metric: share of word tokens (>= 3 letters, lowercased, hyphenated words split) found in `00-indonesian-wordlist.lst` (79,888 entries). Legal abbreviations and names are never all in a wordlist, so born-digital regulations set the ceiling.

Born-digital baseline: median 97.4%, range 89.0% to 98.4% over 9 regulations.

| doc | OCR-layer pages | before (embedded OCR) | after: Tesseract re-OCR | after: replacement candidate |
|---|---|---|---|---|
| uu_66_2024 | 60/60 | 94.5% (9,056/9,581) | 96.2% (9,289/9,655) | - |
| pp_31_2021 | 213/213 | 90.7% (25,906/28,564) | - | 95.4% (27,081/28,380): pp31-2021bt.pdf `9705c744f68e`, pp31-2021pjl.pdf `d2ba1346a385` |
| pm_74_2016 | 23/23 | 94.6% (3,631/3,839) | - | - |
| pm_5_2024 | 9/9 | 97.5% (1,704/1,748) | - | - |

Baseline per document:

- uu_17_2008: 97.4% (30,297/31,103)
- pp_20_2010: 97.5% (20,513/21,042)
- pp_61_2009: 98.4% (13,939/14,170)
- pm_93_2013: 97.4% (17,309/17,778)
- pm_23_2022: 97.8% (1,108/1,133)
- pm_59_2021: 95.3% (11,604/12,176)
- pm_3_2026: 98.0% (1,429/1,458)
- pm_50_2021: 97.3% (10,163/10,443)
- pm_72_2017: 89.0% (5,330/5,986)

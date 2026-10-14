# LLM comparison, Phase 3 smoke runs: gpt-oss-120b vs qwen3.8-27b (Groq)

Smoke-level only: 6 hand-written queries, one run each, judged by reading every answer against
the chunk text. This is not the Phase 4 evaluation (no gold set, no metrics, n = 6).

- Final runs (2026-10-14), after the citation-format fix (unbracketed/page-less citations
  normalized), the rule 5 template (placeholders, no copyable example), and the q02 sibling
  budget fix (2800 tokens, top-2 Pasal first):
  - `reports/answer_examples_groq.md`: `openai/gpt-oss-120b`, reasoning_effort low, max output 1024;
  - `reports/answer_examples_groq-qwen.md`: `qwen/qwen3.8-27b`, reasoning hidden, max output 2048.
    q02 was re-run with `--merge` after a truncation at 1024; q04-q10 are from the same day's
    earlier run with identical settings apart from that output limit.
- **Identical retrieval: yes.** All 6 retrieval fingerprints match between the two reports
  (`101b6814`, `3fcc9de3`, `b54ea0a7`, `4e2cbbbb`, `76cf6726`, `5759aab1`).
- Gemini (`gemini-3.8-flash`) is not compared: it is unreliable on the free tier (timeouts at 300 s).

Columns: **cit.** = valid / invalid citations after the post-check (normalized ones in brackets),
**rule 5** = a relevant SUPERSEDED/REPEALED source is mentioned (n/a = none relevant),
**faithful** = supported / partly / unsupported (every statement follows from the provided sources).

| query | fingerprint | gpt-oss: result | cit. | rule 5 | faithful | qwen: result | cit. | rule 5 | faithful |
|---|---|---|---|---|---|---|---|---|---|
| q02 izin usaha angkutan laut | = | answered | 7 (4 norm.) / 1* | no | partly | answered | 15 / 0 | yes | supported |
| q04 bongkar muat | = | answered | 8 / 0 | no | partly | answered | 13 / 0 | yes | partly |
| q06 tarif jasa kapal | = | answered | 1 / 0 | n/a | supported | answered | 1 / 0 | n/a | supported |
| q09 cabotage (EN) | = | answered | 2 (1 norm.) / 0 | n/a | supported | answered | 4 (1 norm.) / 0 | n/a | partly |
| q05 UNCTAD (EN) | = | answered | 2 / 0 | n/a | supported | answered | 3 / 0 | n/a | supported |
| q10 out of scope | = | refused (correct) | 0 / 0 | n/a | n/a | refused (correct) | 0 / 0 | n/a | n/a |

\* The one invalid citation is a checker false negative: "PM 93/2013, Pasal 69 ayat 7‑8" is
correct, but ayat (7) and (8) sit in two sibling chunks (ayat 3-7 and ayat 8), and the check only
accepts an ayat range that fits inside one chunk. It was flagged as unverified in the answer.

## Did the Phase 3 fixes work?

- **Citation-format fix rescued gpt-oss q02.** In the previous run gpt-oss wrote
  "(PM 93/2013, Pasal 69 ayat 2)" with no brackets or page, and the answer was refused. This time
  4 such citations were normalized to `[PM 93/2013, Pasal 69 ayat (2), p. 44]` etc. and the
  answer stands. No answer was refused for citation format in either run.
- **The template stopped Qwen copying the example.** The previous run's leaked "Pasal 71 PM
  93/2013 tidak relevan di sini" is gone. Qwen now writes the rule 5 sentence from real values:
  "Pasal 71 dari PM 93/2013 tentang tata cara permohonan izin usaha telah diubah oleh PM 74/2016"
  (with one typo, "Pasangal"), and in q04 it names the deleted ayat (7). No placeholder or
  template text appears in any answer.
- **Truncation**: none in these runs (Qwen q02 used 906 of 2048 output tokens).
- **Sibling budget**: q02 now has PM 93/2013 Pasal 69 ayat (1)-(8) in context, and both models
  list the technical requirements (ayat 3) that were missing before.

## Per question

**q02** (Apa persyaratan untuk memperoleh izin usaha perusahaan angkutan laut?)
- gpt-oss: the most complete answer: administrative and technical requirements, ownership
  proof, the leasing rules (ayat 7-8), the application procedure, and the evaluation and issuing
  steps from PM 74/2016 Pasal 71. Two minor errors against the text: the tug option is "kapal
  tunda >= 150 TK dan/atau tongkang", but the text requires the tug *with* a barge; and it drops
  option (c), the tug >= GT 175 (partly). It never says that PM 93/2013 Pasal 71 was replaced,
  although it uses the PM 74 wording (rule 5: no).
- qwen: precise, with every letter of ayat (2) and (3) cited separately, and the ownership proof.
  It names the amendment ("... telah diubah oleh PM 74/2016") but does not give the new
  procedure (where to apply).

**q04** (kewajiban perusahaan bongkar muat, persyaratan tenaga kerja)
- Both are correct on the PM 3/2026 text: cooperation with the port operator or BUP (Pasal 3 ayat
  4), and the competence evidence and validity rules in Pasal 3A.
- Both attribute the competence-upgrade duty and its cost to the stevedoring company, but
  Pasal 3A ayat (7)-(8) puts it on the "badan usaha penyedia tenaga kerja bongkar muat" (partly).
- gpt-oss does not mention that PM 59/2021 Pasal 3 was amended. Qwen does (ayat 7 deleted, ayat 8
  changed; it omits the change to ayat 4). Qwen cites the superseded PM 59/2021 Pasal 3 to
  describe it, which correctly triggers the "cites text no longer in force" warning.

**q06** (jenis tarif jasa kapal)
- Both list PM 72/2017 Pasal 4 ayat (1) a-f correctly.
- gpt-oss adds the sub-types from Pasal 8 but cites only Pasal 4. The facts are in the provided
  sources, but the citation for them is imprecise.

**q09** (cabotage, English question over Indonesian sources)
- Both answer "No", citing UU 17/2008 Pasal 8, with the Cipta Kerja warning.
- Qwen adds PP 20/2010 Pasal 23 with the partly-revoked note. It also adds "applies regardless of
  whether the ship is foreign-flagged or if the operating company is foreign", a muddled
  inference that is not in the text (partly).

**q05** (UNCTAD): both correct (2.2 % volume, 5.9 % ton-miles, Cape of Good Hope rerouting). Qwen's
added haul figures (4,831 -> 5,245 miles) are in the cited Foreword.

**q10** (aviation fares): both refuse with the fixed message. Every reranker score was 0.000.

## Totals (6 queries)

| | gpt-oss-120b | qwen3.8-27b |
|---|---|---|
| in-scope answered (of 5) | 5 | 5 |
| out-of-scope refused (of 1) | 1 | 1 |
| truncated | 0 | 0 |
| valid / invalid citations | 22 / 1 (checker false negative) | 37 / 0 |
| citations normalized (no brackets / no page) | 5 | 1 |
| rule 5 where relevant (q02, q04) | 0 of 2 | 2 of 2 |
| faithfulness: supported / partly | 3 / 2 | 3 / 2 |
| tokens (prompt + output, 6 calls) | 22,551 | 21,462 |
| generate latency per call | 0.7-2.5 s | 0.5-2.4 s |

Reading: both models are viable on this set. gpt-oss is more complete but less format-disciplined
(it relies on normalization) and skipped rule 5 both times. Qwen follows the citation format and
rule 5, is more literal, and is not more faithful. Both share the same paraphrase drift on q04.
n = 6: Phase 4 decides on the gold set.

## Earlier runs (same day, before the fixes)

- Run 1 (2500-token budget, old citation parser): gpt-oss q02 refused for citation format; Qwen
  copied the rule 5 example ("tidak relevan di sini") in q04; both lacked PM 93 Pasal 69 ayat (3).
- Run 2 (fixes 1-2): Qwen q02 hit its 1024-token output limit and was counted as answered (now
  TRUNCATED, and re-run with 2048).

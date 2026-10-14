"""Phase 4 Step 3 with a fake LLM: stored contexts, cache keys, resume after a quota error, metrics."""

from __future__ import annotations

import copy
import io
import json

import pytest

from maritime_rag.answer.prompt import LanguageDetector
from maritime_rag.answer.providers import Generation, ProviderError
from maritime_rag.config import load_config, resolve
from maritime_rag.eval.answers import (
    Setup,
    answerer_for,
    cache_path,
    estimate_cost,
    fingerprint,
    metrics_for,
    prompt_version,
    read_cache,
    render_md,
    report,
    run_llm,
    sha256_file,
)
from maritime_rag.eval.questions import write_gold_csv
from maritime_rag.retrieval.corpus import Corpus, Hit

ECFG = load_config("configs/eval.yaml")
ACFG = load_config(ECFG["answers"]["answer_config"])
STOPWORDS = resolve(load_config(ACFG["retrieval_config"])["paths"]["stopwords"])


def _chunk(cid: str, pasal: str, text: str, **kw) -> dict:
    doc = cid.rsplit("-", 1)[0]
    t, n, y = {"pm_93_2013": ("PM", "93", 2013), "pm_74_2016": ("PM", "74", 2016), "uu_17_2008": ("UU", "17", 2008)}[doc]
    return {"chunk_id": cid, "doc_id": doc, "doc_type": t, "number": n, "year": y, "title": "T", "part": "body",
            "pasal": pasal, "ayat": None, "heading": f"{doc} > Pasal {pasal}", "source_file": f"{doc}.pdf",
            "page_start": 5, "page_end": 5, "text": text, "section": None, "subsection": None, "status": "in_force",
            "doc_amends": [], "amends_doc": None, "amends_pasal": None, "amendment_kind": None, "superseded_by": [],
            "partially_amended_by": [], "may_be_amended_by_out_of_corpus": [], "n_tokens": 50} | kw


CHUNKS = [
    _chunk("pm_93_2013-0001", "71", "Pasal 71 (1) Izin diberikan oleh Direktur Jenderal.", superseded_by=["pm_74_2016"]),
    _chunk("pm_74_2016-0001", "71", "Pasal 71 (1) Izin diajukan kepada Kepala BKPM.", amends_doc="pm_93_2013",
           amends_pasal="71", amendment_kind="replace"),
    _chunk("uu_17_2008-0001", "8", "Pasal 8 (1) Angkutan laut dalam negeri dengan kapal berbendera Indonesia.",
           may_be_amended_by_out_of_corpus=["UU 11/2020", "UU 6/2023"]),
]
QUESTIONS = [
    {"id": "A01", "slice": "amended", "lang": "id", "question": "Ke mana izin usaha angkutan laut diajukan?",
     "gold_chunk_ids": "pm_74_2016-0001;pm_93_2013-0001", "reference_answer": "Kepala BKPM.", "review": "keep", "notes": ""},
    {"id": "F01", "slice": "factual_id", "lang": "id", "question": "Kapal apa yang dipakai angkutan laut dalam negeri?",
     "gold_chunk_ids": "uu_17_2008-0001", "reference_answer": "Kapal berbendera Indonesia.", "review": "keep", "notes": ""},
    {"id": "O01", "slice": "out_of_scope", "lang": "id", "question": "Berapa harga tiket pesawat ke Bali?",
     "gold_chunk_ids": "", "reference_answer": "Tidak ada.", "review": "keep", "notes": ""},
]
HITS = {"A01": ["pm_93_2013-0001"], "F01": ["uu_17_2008-0001"], "O01": ["uu_17_2008-0001"]}
REPLIES = {
    "Ke mana izin usaha angkutan laut diajukan?": "Kepada Kepala BKPM (PM 74/2016, Pasal 71 ayat 1).",
    "Kapal apa yang dipakai angkutan laut dalam negeri?": "Kapal berbendera Indonesia [UU 17/2008, Pasal 8 ayat (1), p. 5].",
    "Berapa harga tiket pesawat ke Bali?": "Informasi tersebut tidak ditemukan dalam dokumen yang tersedia.",
}


class FakeLLM:
    name, model = "groq", "openai/gpt-oss-120b"

    def __init__(self, fail_at: int | None = None) -> None:
        self.fail_at, self.n = fail_at, 0
        self.calls = self.prompt_tokens = self.output_tokens = 0
        self.cost_usd = 0.0

    def check(self) -> None:
        pass

    def generate(self, messages):
        self.n += 1
        if self.fail_at is not None and self.n == self.fail_at:
            raise ProviderError("Groq returned HTTP 429 and asks to wait 3600 s (quota likely exhausted)")
        question = messages[-1]["content"].rsplit("QUESTION: ", 1)[1]
        self.calls += 1
        self.prompt_tokens += 1000
        self.output_tokens += 100
        self.cost_usd += 0.001
        return Generation(REPLIES[question], "groq", self.model, 1000, 100, 0.5, finish_reason="stop",
                          max_output_tokens=1024, cost_usd=0.001)


@pytest.fixture
def s(tmp_path) -> Setup:
    gold = tmp_path / "gold.csv"
    write_gold_csv(QUESTIONS, gold)
    ecfg = copy.deepcopy(ECFG)
    ecfg["paths"]["gold_csv"] = str(gold)
    ecfg["answers"] |= {"contexts": str(tmp_path / "contexts.json"), "cache_dir": str(tmp_path / "cache")}
    acfg = copy.deepcopy(ACFG)
    acfg["gate"]["enabled"] = False
    questions = [q | {"gold_chunk_ids": [g for g in q["gold_chunk_ids"].split(";") if g]} for q in QUESTIONS]
    setup = Setup(ecfg, acfg, Corpus(copy.deepcopy(CHUNKS), "sha-x"), questions, LanguageDetector(STOPWORDS))
    # what `contexts` would store, without retrieval models
    answerer, by_id = answerer_for(setup, None), setup.corpus.by_id()
    entries = {}
    for q in questions:
        hits = [Hit(c, 0.9, r, "hybrid+rerank", by_id[c]) for r, c in enumerate(HITS[q["id"]], 1)]
        context, sib = answerer.context_for(hits)
        entries[q["id"]] = {"question": q["question"], "retriever": "hybrid+rerank", "reranked": True,
                            "hits": [[h.chunk_id, h.score, h.rank] for h in hits], "times": {"retrieve_s": 0.1},
                            "top_score": 0.9, "context_ids": [c.chunk_id for c in context],
                            "fingerprint": fingerprint(context), "siblings_cut": sib.cut, "hits_dropped": sib.dropped}
    meta = {"created": "now", "selected_retrieval": "hybrid_rerank", "k": 5, "gold_sha256": sha256_file(gold),
            "chunks_sha256": "sha-x", "versions": acfg["versions"]}
    (tmp_path / "contexts.json").write_text(json.dumps({"meta": meta, "questions": entries}), encoding="utf-8")
    return setup


def test_run_caches_and_resumes_after_quota_error(s: Setup) -> None:
    out = io.StringIO()
    assert run_llm(s, "groq", FakeLLM(fail_at=2), out) == 1  # A01 answered, F01 hits the quota
    assert "stopped (quota / spend limit) after 1 new answers" in out.getvalue()
    rows = read_cache(cache_path(s, "groq"))
    assert [r["id"] for r in rows] == ["A01"]
    llm = FakeLLM()
    assert run_llm(s, "groq", llm, io.StringIO()) == 2 and llm.calls == 2  # A01 not asked again
    assert run_llm(s, "groq", FakeLLM(), io.StringIO()) == 0
    rows = read_cache(cache_path(s, "groq"))
    a01 = rows[0]
    pv = prompt_version(s.acfg, s.acfg["llm"]["profiles"]["groq"])
    assert a01["key"] == f"A01|{a01['fingerprint']}|openai/gpt-oss-120b|{pv}"
    assert a01["result"] == "answered" and a01["citations"][0]["normalized"]  # unbracketed citation normalized
    assert a01["cited"] == [{"chunk_id": "pm_74_2016-0001", "status": "CURRENT", "status_by": None}]
    assert [c["chunk_id"] for c in a01["context"]] == ["pm_74_2016-0001", "pm_93_2013-0001"]
    assert rows[2]["refusal_reason"] == "model_not_found" and rows[2]["generation"]["cost_usd"] == 0.001


def test_changed_prompt_or_stale_context_is_not_reused(s: Setup) -> None:
    run_llm(s, "groq", FakeLLM(), io.StringIO())
    s.acfg["prompt"]["system"] += "\n7. New rule."
    llm = FakeLLM()
    assert run_llm(s, "groq", llm, io.StringIO()) == 3  # new prompt version: everything re-asked
    s.acfg["versions"]["max_added_chunks"] = 0  # the context no longer reproduces
    with pytest.raises(SystemExit, match="contexts no longer reproduce"):
        run_llm(s, "groq", FakeLLM(), io.StringIO())


def test_recheck_reapplies_postcheck_without_llm_calls(s: Setup) -> None:
    from maritime_rag.eval.answers import current_records, recheck_llm

    run_llm(s, "groq", FakeLLM(), io.StringIO())
    path = cache_path(s, "groq")
    rows = read_cache(path)
    rows[0]["postcheck_version"] = "1"  # pretend A01 was checked by the old parser
    rows[0]["text"] = "old text"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    out = io.StringIO()
    assert recheck_llm(s, "groq", out) == 1
    data = json.loads(resolve(s.ecfg["answers"]["contexts"]).read_text(encoding="utf-8"))
    latest = {r["id"]: r for r in current_records(s, "groq", data)[0]}
    assert latest["A01"]["rechecked"] and latest["A01"]["text"] != "old text"
    assert latest["A01"]["generation"]["cost_usd"] == 0.001  # the stored generation is kept
    assert recheck_llm(s, "groq", io.StringIO()) == 0  # idempotent


def test_metrics_and_report(s: Setup) -> None:
    run_llm(s, "groq", FakeLLM(), io.StringIO())
    data = json.loads(resolve(s.ecfg["answers"]["contexts"]).read_text(encoding="utf-8"))
    m = metrics_for(read_cache(cache_path(s, "groq")), s, data)
    assert m["refusal_accuracy"] == [1, 1] and m["false_refusals"] == [0, 2] and m["truncated"] == 0
    assert m["citations"] == {"parsed": 2, "valid": 2, "normalized": 1, "answers_with_invalid": 0,
                              "answers_with_flagged_ayat": 0}
    assert m["context_hit"] == [2, 2]
    assert m["amended"] == {"n": 1, "answered": 1, "cites_current_version": 1, "cites_superseded_text": 0}
    assert m["cipta_kerja_warning_when_uu17_cited"] == [1, 1]
    assert m["tokens"] == {"prompt": 3000, "output": 300, "reasoning": 0} and m["cost_usd"] == pytest.approx(0.003)
    s.ecfg["answers"]["llms"] = ["groq"]
    s.ecfg["answers"]["asrun_report"] = str(cache_path(s, "groq").parent / "none.json")
    res = report(s)
    v = res["llms"]["groq"]
    assert v["missing"] == [] and v["rows_not_current"] == 0 and v["changes"] == []
    assert v["asrun"] == v["fixed"]  # nothing re-run yet: as-run and fixed are the same answers
    md = render_md(res)
    assert "| refusal accuracy (out-of-scope refused) | 1/1 (100%) | 1/1 (100%) |" in md


def test_report_lists_changed_contexts_side_by_side(s: Setup) -> None:
    run_llm(s, "groq", FakeLLM(), io.StringIO())
    ctx_path = resolve(s.ecfg["answers"]["contexts"])
    data = json.loads(ctx_path.read_text(encoding="utf-8"))
    # as-run: F01 had a hit dropped (bug 1); fixed: the rebuilt context keeps two hits
    data["questions"]["F01"]["hits_dropped"] = ["pm_93_2013-0001"]
    ctx_path.with_name("contexts_asrun.json").write_text(json.dumps(data), encoding="utf-8")
    by_id = s.corpus.by_id()
    hits = [Hit(c, 0.9, r, "hybrid+rerank", by_id[c]) for r, c in enumerate(["uu_17_2008-0001", "pm_93_2013-0001"], 1)]
    context, sib = answerer_for(s, None).context_for(hits)
    data["questions"]["F01"] |= {"hits": [[h.chunk_id, h.score, h.rank] for h in hits], "hits_dropped": [],
                                 "context_ids": [c.chunk_id for c in context], "fingerprint": fingerprint(context)}
    ctx_path.write_text(json.dumps(data), encoding="utf-8")
    llm = FakeLLM()
    assert run_llm(s, "groq", llm, io.StringIO()) == 1 and llm.calls == 1  # only F01 re-asked
    s.ecfg["answers"]["llms"] = ["groq"]
    res = report(s)
    ch = res["llms"]["groq"]["changes"]
    assert [c["id"] for c in ch] == ["F01"]
    assert ch[0]["reasons"] == ["context: bug 1, hits no longer dropped (pm_93_2013-0001)"]
    md = render_md(res)
    assert "| metric | groq as-run | groq fixed |" in md and "| F01 | factual_id | context: bug 1" in md


def test_cost_estimate_uses_prices_and_cross_judging(s: Setup) -> None:
    data = json.loads(resolve(s.ecfg["answers"]["contexts"]).read_text(encoding="utf-8"))
    prices = {"groq": {"input": 0.15, "output": 0.60}, "groq-qwen": {"input": 0.80, "output": 4.00}}
    est = estimate_cost(s, data, prices)
    assert est["groq"]["judges_answers_of"] == "groq-qwen" and est["groq-qwen"]["judges_answers_of"] == "groq"
    assert est["groq"]["answer_calls"] == 3 and est["groq"]["judge_calls"] == 2  # in-scope answers only
    assert est["groq-qwen"]["usd"] > est["groq"]["usd"] > 0
    assert est["total_usd"] == pytest.approx(est["groq"]["usd"] + est["groq-qwen"]["usd"])

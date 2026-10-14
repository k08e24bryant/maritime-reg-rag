"""Phase 3 answer pipeline with a fake LLM provider: version expansion, citations, refusals, warnings."""

from __future__ import annotations

import copy
import json

import pytest

from maritime_rag.answer.citations import DocMatcher, parse_citations, rewrite, validate
from maritime_rag.answer.pipeline import Answerer, Retrieval
from maritime_rag.answer.prompt import LanguageDetector, build_messages
from maritime_rag.answer.providers import Generation, LoggingProvider, ProviderError, make_provider
from maritime_rag.answer.versions import (
    CURRENT,
    REPEALED,
    SUPERSEDED,
    DocNames,
    VersionIndex,
    build_context,
    cite_as,
    describe,
)
from maritime_rag.config import load_config, resolve
from maritime_rag.retrieval.corpus import Corpus, Hit, load_corpus

CFG = load_config("configs/answer.yaml")
STOPWORDS = resolve(load_config(CFG["retrieval_config"])["paths"]["stopwords"])
NOT_FOUND = CFG["messages"]["not_found"]

_DOCS = {  # doc_id -> (doc_type, number, year, title, source_file)
    "uu_17_2008": ("UU", "17", 2008, "Pelayaran", "uu_17_2008.pdf"),
    "uu_66_2024": ("UU", "66", 2024, "Perubahan Ketiga atas UU 17/2008", "uu_66_2024.pdf"),
    "pm_93_2013": ("PM", "93", 2013, "Penyelenggaraan dan Pengusahaan Angkutan Laut", "pm_93_2013.pdf"),
    "pm_74_2016": ("PM", "74", 2016, "Perubahan atas PM 93/2013", "pm_74_2016.pdf"),
    "pm_23_2022": ("PM", "23", 2022, "Perubahan Kedua atas PM 93/2013", "pm_23_2022.pdf"),
    "pp_20_2010": ("PP", "20", 2010, "Angkutan di Perairan", "pp_20_2010.pdf"),
    "pp_31_2021": ("PP", "31", 2021, "Penyelenggaraan Bidang Pelayaran", "pp_31_2021.pdf"),
    "unctad_rmt_2025": ("Report", None, 2025, "Review of Maritime Transport 2025: Overview", "unctad_rmt_2025.pdf"),
}


def _chunk(cid: str, pasal: str | None, pages: tuple[int, int], text: str, part: str = "body", **kw) -> dict:
    doc = cid.rsplit("-", 1)[0]
    doc_type, number, year, title, source_file = _DOCS[doc]
    base = {
        "chunk_id": cid, "doc_id": doc, "doc_type": doc_type, "number": number, "year": year, "title": title,
        "part": part, "pasal": pasal, "ayat": None, "section": None, "subsection": None,
        "heading": f"{doc} > {'Penjelasan > ' if part == 'penjelasan' else ''}Pasal {pasal}",
        "source_file": source_file, "page_start": pages[0], "page_end": pages[1], "text": text,
        "status": "in_force", "doc_amends": [], "amends_doc": None, "amends_pasal": None, "amendment_kind": None,
        "superseded_by": [], "partially_amended_by": [], "may_be_amended_by_out_of_corpus": [], "n_tokens": 50,
    }
    return base | kw


OOC = ["UU 11/2020", "UU 6/2023"]
CHUNKS = [
    _chunk("pm_93_2013-0084", "71", (46, 47), "Izin usaha angkutan laut diberikan oleh Direktur Jenderal ...",
           ayat="1-8", superseded_by=["pm_74_2016"]),
    _chunk("pm_93_2013-0085", "71", (47, 47), "(9) ... (10) ...", ayat="9-10", superseded_by=["pm_74_2016"]),
    _chunk("pm_93_2013-0020", "18", (12, 12), "Kapal asing dapat ...", superseded_by=["pm_23_2022"]),
    _chunk("pm_74_2016-0010", "71", (11, 12), "Izin usaha angkutan laut diberikan melalui OSS ...", ayat="1-6",
           amends_doc="pm_93_2013", amends_pasal="71", amendment_kind="replace"),
    _chunk("pm_74_2016-0011", "71", (12, 13), "(7) ... (13) ...", ayat="7-13",
           amends_doc="pm_93_2013", amends_pasal="71", amendment_kind="replace"),
    _chunk("pm_23_2022-0005", "18", (3, 3), "3. Pasal 18 dihapus.",
           amends_doc="pm_93_2013", amends_pasal="18", amendment_kind="delete"),
    _chunk("uu_17_2008-0010", "8", (10, 10), "(1) Kegiatan angkutan laut dalam negeri dilakukan oleh perusahaan "
           "angkutan laut nasional dengan menggunakan kapal berbendera Indonesia ...", ayat="1-2",
           may_be_amended_by_out_of_corpus=OOC),
    _chunk("uu_17_2008-0207", "198", (82, 82), "Pasal 198 (1) ... perairan wajib pandu ...",
           partially_amended_by=["uu_66_2024"], may_be_amended_by_out_of_corpus=OOC),
    _chunk("uu_17_2008-0442", "195", (185, 186), "Pasal 195 huruf b ...", part="penjelasan",
           partially_amended_by=["uu_66_2024"], may_be_amended_by_out_of_corpus=OOC),
    _chunk("uu_66_2024-0048", "198", (27, 27), "33. Ketentuan ayat (1) ... Pasal 198 diubah ...",
           amends_doc="uu_17_2008", amends_pasal="198", amendment_kind="insert"),
    _chunk("uu_66_2024-0047", "195", (26, 27), "32. Penjelasan Pasal 195 huruf b diubah ...",
           amends_doc="uu_17_2008", amends_pasal="195", amendment_kind="penjelasan"),
    _chunk("uu_66_2024-0102", "195", (60, 60), "Pasal 195 Huruf b Yang dimaksud ...", part="penjelasan",
           amends_doc="uu_17_2008", amends_pasal="195"),
    _chunk("pp_20_2010-0084", "86", (40, 40), "Kegiatan bongkar muat dilakukan oleh badan usaha ...",
           status="partially_revoked"),
    _chunk("pp_31_2021-0001", "1", (2, 2), "Dalam Peraturan Pemerintah ini yang dimaksud dengan ...",
           doc_amends=["pp_20_2010", "pp_61_2009"]),
    _chunk("unctad_rmt_2025-0006", None, (9, 10), "Seaborne trade grew by 2.2 per cent in 2024 ...", part="report",
           section="1. International maritime trade"),
]


@pytest.fixture
def corpus() -> Corpus:
    return Corpus(copy.deepcopy(CHUNKS), "sha-test")


@pytest.fixture
def index(corpus: Corpus) -> VersionIndex:
    return VersionIndex(corpus)


@pytest.fixture
def names(corpus: Corpus) -> DocNames:
    return DocNames(corpus, CFG["short_names"])


def hits(corpus: Corpus, *ids: str, scores: list[float] | None = None) -> list[Hit]:
    by_id = corpus.by_id()
    return [Hit(cid, (scores or [1.0] * len(ids))[r - 1], r, "hybrid", by_id[cid]) for r, cid in enumerate(ids, 1)]


class FakeProvider:
    name, model = "fake", "fake-model"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[dict]] = []

    def check(self) -> None:
        pass

    def generate(self, messages):
        self.calls.append(messages)
        return Generation(self.reply, self.name, self.model, 100, 20, 0.01)


def answerer(corpus: Corpus, reply: str, ids: tuple[str, ...], cfg: dict | None = None,
             reranked: bool = False, scores: list[float] | None = None) -> tuple[Answerer, FakeProvider]:
    provider = FakeProvider(reply)

    def retrieve(question: str) -> Retrieval:
        return Retrieval(hits(corpus, *ids, scores=scores), reranked, {"retrieve_s": 0.0})

    return Answerer(cfg or CFG, corpus, retrieve, provider, LanguageDetector(STOPWORDS)), provider


# --- version expansion ---------------------------------------------------------------------------

def test_superseded_pm93_pasal71_fetches_pm74_replacement_first(corpus: Corpus, index: VersionIndex, names: DocNames) -> None:
    ctx = build_context(hits(corpus, "pm_93_2013-0084"), index, max_added=8)
    assert [c.chunk_id for c in ctx] == ["pm_74_2016-0010", "pm_74_2016-0011", "pm_93_2013-0084"]
    assert [c.status for c in ctx] == [CURRENT, CURRENT, SUPERSEDED]
    assert ctx[2].status_by == "pm_74_2016" and ctx[2].retrieved_rank == 1
    assert ctx[0].retrieved_rank is None and ctx[1].retrieved_rank is None  # added, not retrieved
    old = describe(ctx[2], ctx, names, index)
    assert old.startswith("SUPERSEDED by PM 74/2016") and "SOURCE 1, SOURCE 2" in old and "not" in old
    new = describe(ctx[0], ctx, names, index)
    assert new.startswith("CURRENT") and "PM 93/2013 Pasal 71" in new and "SOURCE 3" in new


def test_expanded_chunk_retrieved_later_is_not_duplicated(corpus: Corpus, index: VersionIndex) -> None:
    ctx = build_context(hits(corpus, "pm_93_2013-0084", "pm_93_2013-0085", "pm_74_2016-0010"), index, 8)
    ids = [c.chunk_id for c in ctx]
    assert ids == ["pm_74_2016-0010", "pm_74_2016-0011", "pm_93_2013-0084", "pm_93_2013-0085"]
    assert ctx[0].retrieved_rank == 3  # was added by expansion, then also retrieved


def test_repealed_pasal_is_labelled_repealed(corpus: Corpus, index: VersionIndex, names: DocNames) -> None:
    ctx = build_context(hits(corpus, "pm_93_2013-0020"), index, 8)
    assert [c.chunk_id for c in ctx] == ["pm_23_2022-0005", "pm_93_2013-0020"]
    assert ctx[1].status == REPEALED
    assert describe(ctx[1], ctx, names, index).startswith("REPEALED by PM 23/2022")
    assert "repeals PM 93/2013 Pasal 18" in describe(ctx[0], ctx, names, index)


def test_partial_amendment_both_directions(corpus: Corpus, index: VersionIndex, names: DocNames) -> None:
    ctx = build_context(hits(corpus, "uu_17_2008-0207"), index, 8)
    assert [c.chunk_id for c in ctx] == ["uu_66_2024-0048", "uu_17_2008-0207"]
    base = describe(ctx[1], ctx, names, index)
    assert base.startswith("CURRENT") and "partly amended by UU 66/2024 (SOURCE 1 prevails" in base
    # retrieving only the amending chunk brings in the base Pasal it changed (still in force)
    ctx = build_context(hits(corpus, "uu_66_2024-0048"), index, 8)
    assert [c.chunk_id for c in ctx] == ["uu_66_2024-0048", "uu_17_2008-0207"]


def test_penjelasan_amendment_fetches_new_penjelasan(corpus: Corpus, index: VersionIndex) -> None:
    ctx = build_context(hits(corpus, "uu_17_2008-0442"), index, 8)
    assert [c.chunk_id for c in ctx] == ["uu_66_2024-0102", "uu_17_2008-0442"]
    ctx = build_context(hits(corpus, "uu_66_2024-0047"), index, 8)  # "Penjelasan Pasal 195 diubah" instruction
    assert "uu_66_2024-0102" in [c.chunk_id for c in ctx]


def test_expansion_cap(corpus: Corpus, index: VersionIndex) -> None:
    ctx = build_context(hits(corpus, "pm_93_2013-0084"), index, max_added=1)
    assert [c.chunk_id for c in ctx] == ["pm_74_2016-0010", "pm_93_2013-0084"]


# --- citations -----------------------------------------------------------------------------------

def test_parse_citation_formats(names: DocNames) -> None:
    text = (
        "Izin melalui OSS [PM 74/2016, Pasal 71 ayat (2), p. 11]. Juga [Permenhub No. 74 Tahun 2016, Pasal 71 "
        "ayat (1)-(3), hlm. 12; UU 17/2008, Penjelasan Pasal 195, pp. 185-186]. Trade [UNCTAD RMT 2025, "
        "1. International maritime trade, p. 9]. Lihat [PP 31/2021, Pasal 5]. [sic]"
    )
    cits = parse_citations(text, DocMatcher(names))
    assert [c.doc_id for c in cits] == ["pm_74_2016", "pm_74_2016", "uu_17_2008", "unctad_rmt_2025", "pp_31_2021"]
    assert (cits[0].pasal, cits[0].ayat, cits[0].pages) == ("71", [2], (11, 11))
    assert (cits[1].ayat, cits[1].pages) == ([1, 2, 3], (12, 12))
    assert cits[2].penjelasan and cits[2].pages == (185, 186)
    assert cits[1].bracket == cits[2].bracket  # two citations in one bracket
    assert cits[4].pages is None  # "PP 31" is a document, not page 31
    assert cits[0].raw == "PM 74/2016, Pasal 71 ayat (2), p. 11"


def test_validate_maps_citations_to_context(corpus: Corpus, index: VersionIndex, names: DocNames) -> None:
    ctx = build_context(hits(corpus, "pm_93_2013-0084", "uu_17_2008-0442", "unctad_rmt_2025-0006"), index, 8)
    text = (
        "[PM 74/2016, Pasal 71 ayat (2), p. 11] [PM 74/2016, Pasal 71 ayat (9), p. 13] "  # 9 is in 0011 (7-13)
        "[PM 74/2016, Pasal 71, p. 30] [PM 74/2016, Pasal 72, p. 11] [PM 23/2022, Pasal 18, p. 3] "
        "[PM 93/2013, Pasal 71 ayat (12), p. 46] [UU 17/2008, Penjelasan Pasal 195, p. 185] "
        "[UU 17/2008, Pasal 195, p. 185] [UNCTAD RMT 2025, 1. International maritime trade, p. 10] [PM 74/2016, Pasal 71]"
    )
    cits = parse_citations(text, DocMatcher(names))
    validate(cits, ctx, require_page=True)
    ids = [ctx[c.source - 1].chunk_id if c.valid else c.problem for c in cits]
    assert ids[0] == "pm_74_2016-0010"
    assert ids[1] == "pm_74_2016-0011"
    assert "page 30" in ids[2]
    assert "Pasal 72" in ids[3]
    assert ids[4] == "document not among the provided sources"
    assert "ayat [12]" in ids[5]  # PM 93/2013 Pasal 71 chunks cover ayat 1-10
    assert ids[6] == "uu_17_2008-0442"
    assert ids[7] == "uu_17_2008-0442"  # plain Pasal falls back to the Penjelasan chunk of that Pasal
    assert ids[8] == "unctad_rmt_2025-0006"
    assert ids[9] == "no page"


def test_rewrite_flag_and_drop() -> None:
    from maritime_rag.answer.citations import Citation

    text = "A [X, Pasal 1, p. 1]. B [Y, Pasal 2, p. 2; Z, Pasal 3, p. 3]."
    s1, s2 = text.index("[X"), text.index("[Y")
    cits = [
        Citation("X, Pasal 1, p. 1", (s1, text.index("]") + 1), "x", "1", [], False, (1, 1), source=1),
        Citation("Y, Pasal 2, p. 2", (s2, len(text) - 1), "y", "2", [], False, (2, 2), source=None, problem="bad"),
        Citation("Z, Pasal 3, p. 3", (s2, len(text) - 1), "z", "3", [], False, (3, 3), source=2),
    ]
    marker = CFG["messages"]["unverified_marker"]
    assert rewrite(text, cits, "flag", marker) == "A [X, Pasal 1, p. 1]. B [Z, Pasal 3, p. 3][unverified citation: Y, Pasal 2, p. 2]."
    assert rewrite(text, cits, "drop", marker) == "A [X, Pasal 1, p. 1]. B [Z, Pasal 3, p. 3]."


# --- pipeline with a fake provider -----------------------------------------------------------------

def test_answer_with_valid_citations(corpus: Corpus) -> None:
    reply = ("Izin usaha angkutan laut kini diberikan melalui OSS [PM 74/2016, Pasal 71 ayat (1), p. 11]. "
             "Pasal 71 PM 93/2013 telah diubah dengan PM 74/2016.")
    a, provider = answerer(corpus, reply, ("pm_93_2013-0084",))
    ans = a.answer("Apa persyaratan untuk memperoleh izin usaha perusahaan angkutan laut?")
    assert not ans.refused and ans.language == "id"
    assert ans.text == reply and ans.cited == {1} and ans.warnings == []
    assert ans.disclaimer == CFG["messages"]["disclaimer"]["id"]
    prompt = provider.calls[0][1]["content"]
    assert "cite as: [PM 74/2016, Pasal 71, p. 11-12]" in prompt
    assert "status: SUPERSEDED by PM 74/2016" in prompt
    assert "Indonesian" in provider.calls[0][0]["content"]


def test_citing_superseded_text_warns(corpus: Corpus) -> None:
    reply = "Izin diberikan oleh Direktur Jenderal [PM 93/2013, Pasal 71 ayat (1), p. 46]."
    ans = answerer(corpus, reply, ("pm_93_2013-0084",))[0].answer("Siapa yang memberikan izin usaha angkutan laut?")
    assert not ans.refused
    assert any("SUPERSEDED by PM 74/2016" in w for w in ans.warnings)


def test_out_of_corpus_warning_for_uu17_citation(corpus: Corpus) -> None:
    reply = "Domestic sea transport must use Indonesian-flagged ships [UU 17/2008, Pasal 8 ayat (1), p. 10]."
    a, provider = answerer(corpus, reply, ("uu_17_2008-0010",))
    ans = a.answer("Can a foreign-flagged ship carry cargo between Indonesian domestic ports?")
    assert ans.language == "en" and not ans.refused
    assert len(ans.warnings) == 1 and "UU 11/2020, UU 6/2023" in ans.warnings[0]
    assert ans.warnings[0].startswith("UU 17/2008 may have been amended")
    assert "English" in provider.calls[0][0]["content"]


def test_partly_revoked_document_is_flagged(corpus: Corpus, index: VersionIndex, names: DocNames) -> None:
    ctx = build_context(hits(corpus, "pp_20_2010-0084"), index, 8)
    assert ctx[0].status == CURRENT and ctx[0].partly_revoked_by == ["pp_31_2021"]
    assert "partly revoked by PP 31/2021" in describe(ctx[0], ctx, names, index)
    reply = "Bongkar muat dilakukan oleh badan usaha [PP 20/2010, Pasal 86, p. 40]."
    ans = answerer(corpus, reply, ("pp_20_2010-0084",))[0].answer("Siapa yang melakukan kegiatan bongkar muat?")
    assert ans.warnings == [CFG["messages"]["partly_revoked"]["id"].format(doc="PP 20/2010", by="PP 31/2021")]


def test_refusal_when_model_says_not_found(corpus: Corpus) -> None:
    a, _ = answerer(corpus, NOT_FOUND["id"], ("pm_93_2013-0084",))
    ans = a.answer("Berapa tarif tiket pesawat Jakarta ke Bali pada musim liburan?")
    assert ans.refused and ans.refusal_reason == "model_not_found"
    assert ans.text == NOT_FOUND["id"] and ans.disclaimer is None and ans.warnings == []


def test_refusal_in_english_and_no_hits_skips_llm(corpus: Corpus) -> None:
    a, provider = answerer(corpus, "should not be called", ())
    ans = a.answer("How much does a flight from Jakarta to Bali cost in the holidays?")
    assert ans.refused and ans.refusal_reason == "no_hits" and ans.text == NOT_FOUND["en"]
    assert provider.calls == []


def test_invalid_citations_flagged_or_dropped(corpus: Corpus) -> None:
    reply = ("Izin melalui OSS [PM 74/2016, Pasal 71 ayat (1), p. 11]. "
             "Berlaku sejak 2020 [PM 74/2016, Pasal 99, p. 40].")
    a, _ = answerer(corpus, reply, ("pm_93_2013-0084",))
    ans = a.answer("Bagaimana izin usaha angkutan laut diberikan?")
    assert not ans.refused
    assert "[unverified citation: PM 74/2016, Pasal 99, p. 40]" in ans.text
    assert any("Pasal 99" in w for w in ans.warnings)
    cfg = copy.deepcopy(CFG)
    cfg["postcheck"]["invalid_citations"] = "drop"
    ans = answerer(corpus, reply, ("pm_93_2013-0084",), cfg)[0].answer("Bagaimana izin usaha angkutan laut diberikan?")
    assert "Pasal 99" not in ans.text and ans.text.endswith("Berlaku sejak 2020.")


def test_no_valid_citation_returns_refusal(corpus: Corpus) -> None:
    for reply in ("Izin diberikan oleh Menteri.", "Izin diberikan oleh Menteri [PM 50/2021, Pasal 3, p. 4]."):
        ans = answerer(corpus, reply, ("pm_93_2013-0084",))[0].answer("Siapa yang memberi izin usaha angkutan laut?")
        assert ans.refused and ans.refusal_reason == "no_valid_citation" and ans.text == NOT_FOUND["id"]
        assert ans.raw_text == reply  # kept for inspection


def test_score_gate(corpus: Corpus) -> None:
    cfg = copy.deepcopy(CFG)
    cfg["gate"] = {"enabled": True, "min_rerank_score": 0.1}
    a, provider = answerer(corpus, "unused", ("pm_93_2013-0084",), cfg, reranked=True, scores=[0.02])
    ans = a.answer("Berapa tarif tiket pesawat?")
    assert ans.refused and ans.refusal_reason == "gate" and provider.calls == []
    a, _ = answerer(corpus, "unused", ("pm_93_2013-0084",), cfg, reranked=False)
    with pytest.raises(ValueError, match="reranker"):
        a.answer("Berapa tarif tiket pesawat?")
    cfg["gate"]["min_rerank_score"] = None
    with pytest.raises(ValueError, match="min_rerank_score"):
        answerer(corpus, "unused", (), cfg)


def test_gate_off_by_default() -> None:
    assert CFG["gate"]["enabled"] is False


def test_language_detection() -> None:
    detect = LanguageDetector(STOPWORDS)
    assert detect("Can a foreign-flagged ship carry cargo between Indonesian domestic ports?") == "en"
    assert detect("Apa saja kewajiban perusahaan bongkar muat?") == "id"
    assert detect("How much did seaborne trade volumes grow in 2024 and why did ton-miles increase?") == "en"


def test_prompt_lists_sources_in_context_order(corpus: Corpus, index: VersionIndex, names: DocNames) -> None:
    ctx = build_context(hits(corpus, "pm_93_2013-0084", "unctad_rmt_2025-0006"), index, 8)
    user = build_messages("q?", "en", ctx, names, index, CFG)[1]["content"]
    assert user.index("SOURCE 1\n") < user.index("SOURCE 4\n")
    assert f"cite as: {cite_as(ctx[3].chunk, names)}" in user
    assert "cite as: [UNCTAD RMT 2025, 1. International maritime trade, p. 9-10]" in user
    assert user.endswith("QUESTION: q?")


# --- providers -------------------------------------------------------------------------------------

def test_missing_api_key_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        make_provider(CFG["provider"], "openai")
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        make_provider(CFG["provider"], "anthropic")
    with pytest.raises(ProviderError, match="unknown provider"):
        make_provider(CFG["provider"], "gemini")
    for name, env in (("groq", "GROQ_API_KEY"), ("google", "GOOGLE_API_KEY")):
        monkeypatch.delenv(env, raising=False)
        with pytest.raises(ProviderError, match=env):
            make_provider(CFG["provider"], name)


def test_openai_compatible_providers_use_their_own_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    import maritime_rag.answer.providers as providers

    sent = []

    def fake_post(url, payload, headers, timeout, who):
        sent.append((url, payload, headers, who))
        return {"model": payload["model"], "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 1}}

    monkeypatch.setattr(providers, "_post", fake_post)
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setenv("GOOGLE_API_KEY", "gg")
    msgs = [{"role": "user", "content": "hi"}]
    g = make_provider(CFG["provider"], "groq").generate(msgs)
    assert (g.provider, g.text, g.prompt_tokens) == ("groq", "ok", 7)
    g = make_provider(CFG["provider"], "google").generate(msgs)
    assert g.provider == "google"
    (groq_url, groq_payload, groq_headers, _), (gem_url, gem_payload, gem_headers, who) = sent
    assert groq_url == "https://api.groq.com/openai/v1/chat/completions" and groq_headers["Authorization"] == "Bearer gk"
    assert "max_completion_tokens" in groq_payload
    assert gem_url.startswith("https://generativelanguage.googleapis.com/") and gem_headers["Authorization"] == "Bearer gg"
    assert gem_payload["max_tokens"] == CFG["provider"]["google"]["max_output_tokens"] and who == "Google Gemini"


def test_env_file_loader(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from maritime_rag.config import load_env_file

    env = tmp_path / ".env"
    lines = ["# comment", "MRAG_A=one", 'MRAG_B="two words"', "MRAG_C=", "export MRAG_D=four # note", "MRAG_E=keep"]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k in ("MRAG_A", "MRAG_B", "MRAG_C", "MRAG_D"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MRAG_E", "shell")
    assert load_env_file(env) == ["MRAG_A", "MRAG_B", "MRAG_D"]
    assert (os.environ["MRAG_A"], os.environ["MRAG_B"], os.environ["MRAG_D"]) == ("one", "two words", "four")
    assert "MRAG_C" not in os.environ and os.environ["MRAG_E"] == "shell"  # empty skipped, shell wins
    for k in ("MRAG_A", "MRAG_B", "MRAG_D"):
        monkeypatch.delenv(k)
    assert load_env_file(tmp_path / "missing.env") == []


def test_unreachable_ollama_is_a_clear_error() -> None:
    cfg = copy.deepcopy(CFG["provider"])
    cfg["ollama"]["base_url"] = "http://127.0.0.1:9"  # nothing listens on the discard port
    cfg["ollama"]["timeout_s"] = 5
    provider = make_provider(cfg, "ollama")
    with pytest.raises(ProviderError, match="not reachable.*ollama serve"):
        provider.check()
    with pytest.raises(ProviderError, match="not reachable.*ollama serve"):
        provider.generate([{"role": "user", "content": "hi"}])


def test_logging_provider_writes_tokens_and_latency(tmp_path) -> None:
    log_file = tmp_path / "calls.jsonl"
    gen = LoggingProvider(FakeProvider("hello"), log_file).generate([{"role": "user", "content": "hi"}])
    assert gen.text == "hello"
    row = json.loads(log_file.read_text(encoding="utf-8"))
    assert row["prompt_tokens"] == 100 and row["output_tokens"] == 20 and "text" not in row and "latency_s" in row


# --- real corpus (needs data/processed/chunks.jsonl; no models) ------------------------------------

CHUNKS_FILE = resolve(load_config(CFG["retrieval_config"])["paths"]["chunks_file"])


@pytest.mark.skipif(not CHUNKS_FILE.exists(), reason="needs chunks.jsonl (maritime-ingest)")
def test_real_corpus_pm93_pasal71_expands_to_pm74() -> None:
    corpus = load_corpus(CHUNKS_FILE)
    index = VersionIndex(corpus)
    ctx = build_context(hits(corpus, "pm_93_2013-0084", "pm_59_2021-0138"), index, 8)
    by_id = {c.chunk_id: c for c in ctx}
    assert {"pm_74_2016-0010", "pm_74_2016-0011"} <= set(by_id)
    assert by_id["pm_93_2013-0084"].status == SUPERSEDED and by_id["pm_93_2013-0084"].status_by == "pm_74_2016"
    assert by_id["pm_74_2016-0010"].status == CURRENT
    # PM 59/2021 Pasal 132 (bongkar muat) -> PM 3/2026 Pasal 132
    new_132 = [c for c in ctx if c.chunk["doc_id"] == "pm_3_2026" and c.chunk["pasal"] == "132"]
    assert new_132 and by_id["pm_59_2021-0138"].status == SUPERSEDED

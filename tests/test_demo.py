"""Phase 5 demo with a fake retrieval and a fake LLM: API responses, errors, sources, UI formatting."""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from maritime_rag.answer.prompt import LanguageDetector
from maritime_rag.answer.providers import Generation, ProviderError
from maritime_rag.answer.pipeline import Retrieval
from maritime_rag.config import load_config, resolve
from maritime_rag.demo.api import create_app
from maritime_rag.demo.service import DemoConfig, DemoService
from maritime_rag.demo.ui import build_ui, format_answer
from maritime_rag.retrieval.corpus import Corpus, Hit

ACFG = load_config("configs/answer.yaml")
STOPWORDS = resolve(load_config(ACFG["retrieval_config"])["paths"]["stopwords"])


def _chunk(cid: str, pasal: str, text: str, **kw) -> dict:
    doc = cid.rsplit("-", 1)[0]
    t, n, y = {"pm_93_2013": ("PM", "93", 2013), "pm_74_2016": ("PM", "74", 2016)}[doc]
    return {"chunk_id": cid, "doc_id": doc, "doc_type": t, "number": n, "year": y, "title": "T", "part": "body",
            "pasal": pasal, "ayat": None, "heading": f"{doc} > Pasal {pasal}", "source_file": f"{doc}.pdf",
            "page_start": 11, "page_end": 12, "text": text, "section": None, "subsection": None, "status": "in_force",
            "doc_amends": [], "amends_doc": None, "amends_pasal": None, "amendment_kind": None, "superseded_by": [],
            "partially_amended_by": [], "may_be_amended_by_out_of_corpus": [], "n_tokens": 50} | kw


CORPUS = Corpus([
    _chunk("pm_93_2013-0001", "71", "Pasal 71 (1) Izin diberikan oleh Direktur Jenderal.", superseded_by=["pm_74_2016"]),
    _chunk("pm_74_2016-0001", "71", "Pasal 71 (1) Izin diajukan kepada Kepala BKPM.", amends_doc="pm_93_2013",
           amends_pasal="71", amendment_kind="replace"),
], "sha")


class FakeLLM:
    name, model = "groq", "openai/gpt-oss-120b"

    def __init__(self, reply: str) -> None:
        self.reply = reply

    def check(self) -> None:
        pass

    def generate(self, messages):
        if self.reply == "FAIL":
            raise ProviderError("Groq returned HTTP 429 and asks to wait 3600 s (quota likely exhausted)")
        return Generation(self.reply, "groq", self.model, 900, 60, 0.4, finish_reason="stop", cost_usd=0.0001)


def make_service(reply: str) -> DemoService:
    by_id = CORPUS.by_id()

    def retrieve(question: str, rerank: bool) -> Retrieval:
        hits = [Hit("pm_93_2013-0001", 0.9, 1, "hybrid", by_id["pm_93_2013-0001"])]
        return Retrieval(hits, rerank, {"retrieve_s": 0.05} | ({"rerank_s": 0.1} if rerank else {}))

    dcfg = DemoConfig(["groq", "groq-qwen"], "groq", True, 500, ["Ke mana izin diajukan?"])
    acfg = copy.deepcopy(ACFG)
    acfg["gate"]["enabled"] = False
    return DemoService(dcfg, acfg, copy.deepcopy(CORPUS), retrieve, lambda name: FakeLLM(reply), LanguageDetector(STOPWORDS),
                       {"retriever": "hybrid", "k": 5})


REPLY = "Permohonan diajukan kepada Kepala BKPM [PM 74/2016, Pasal 71 ayat (1), p. 11]."


def test_ask_returns_answer_sources_and_version_labels() -> None:
    client = TestClient(create_app(make_service(REPLY)))
    r = client.post("/ask", json={"question": "Ke mana permohonan izin usaha angkutan laut diajukan?"})
    assert r.status_code == 200
    body = r.json()
    assert not body["refused"] and body["answer"] == REPLY and body["disclaimer"]
    assert [(s["chunk_id"], s["status"], s["cited"]) for s in body["sources"]] == [
        ("pm_74_2016-0001", "CURRENT", True), ("pm_93_2013-0001", "SUPERSEDED by PM 74/2016", False)]
    assert body["citations"] == {"valid": 1, "invalid": 0, "normalized": 0}
    assert body["llm"]["model"] == "openai/gpt-oss-120b" and body["cost_usd"] == 0.0001
    assert body["retrieval"]["rerank"] is True and "rerank_s" in body["latency_s"]
    r = client.post("/ask", json={"question": "Ke mana izin diajukan?", "rerank": False})
    assert r.json()["retrieval"]["rerank"] is False and "rerank_s" not in r.json()["latency_s"]


def test_errors_are_explicit() -> None:
    client = TestClient(create_app(make_service(REPLY)))
    assert client.post("/ask", json={"question": "   "}).status_code == 422
    assert client.post("/ask", json={"question": "x" * 501}).status_code == 422
    assert client.post("/ask", json={"question": "Ke mana izin diajukan?", "llm": "ollama"}).status_code == 422
    failing = TestClient(create_app(make_service("FAIL")))
    r = failing.post("/ask", json={"question": "Ke mana izin diajukan?"})
    assert r.status_code == 503 and "quota" in r.json()["detail"]


def test_refusal_sources_health_and_redirect() -> None:
    client = TestClient(create_app(make_service("Informasi tersebut tidak ditemukan dalam dokumen yang tersedia.")))
    body = client.post("/ask", json={"question": "Berapa harga tiket pesawat ke Bali?"}).json()
    assert body["refused"] and body["refusal_reason"] == "model_not_found" and body["disclaimer"] is None
    src = client.get("/sources/pm_74_2016-0001").json()
    assert src["where"] == "PM 74/2016 Pasal 71" and src["pages"] == "p. 11-12" and "Kepala BKPM" in src["text"]
    assert client.get("/sources/nope-1").status_code == 404
    health = client.get("/health").json()
    assert health["status"] == "ok" and health["chunks"] == 2 and health["loaded_llms"] == ["groq"]
    assert client.get("/examples").json() == ["Ke mana izin diajukan?"]
    assert client.get("/", follow_redirects=False).headers["location"] == "/ui"


def test_ui_formatting_and_mount() -> None:
    import gradio as gr

    service = make_service(REPLY)
    res = service.ask("Ke mana izin diajukan?")
    answer, warnings, table, stats, choices = format_answer(res)
    assert answer.startswith(REPLY) and service.acfg["messages"]["disclaimer"]["id"] in answer
    assert table[0][:4] == [1, "PM 74/2016 Pasal 71 (pm_74_2016.pdf p. 11-12)", "CURRENT", "yes"]
    assert table[1][2] == "SUPERSEDED by PM 74/2016"
    assert "openai/gpt-oss-120b" in stats and "citations 1 valid / 0 invalid" in stats
    assert choices[0] == ("1. PM 74/2016 Pasal 71", "pm_74_2016-0001")
    refused = format_answer(make_service("Informasi tersebut tidak ditemukan dalam dokumen yang tersedia.").ask("Tiket pesawat?"))
    assert "Refused: the model found no answer" in refused[0]
    ui = build_ui(service, eval_report=None, figures=[])
    app = gr.mount_gradio_app(create_app(service), ui, path="/ui")
    assert TestClient(app).get("/health").status_code == 200


@pytest.mark.parametrize("q", ["", "x" * 600])
def test_validate_rejects_bad_questions(q: str) -> None:
    from maritime_rag.demo.service import InvalidQuestion

    with pytest.raises(InvalidQuestion):
        make_service(REPLY).validate(q)

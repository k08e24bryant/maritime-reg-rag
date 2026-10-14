"""JSON API of the demo (FastAPI). Interactive docs at /docs.

POST /ask             {"question", "llm"?, "rerank"?} -> answer, sources with version status, warnings,
                      citation check, latency, tokens, estimated cost
GET  /sources/{id}    the full text and location of one chunk (to open a cited source)
GET  /health, /examples
Errors: 422 invalid question or LLM; 503 the LLM provider failed (quota, network); never a fallback.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from maritime_rag.answer.providers import ProviderError
from maritime_rag.demo.service import DemoService, InvalidQuestion


class AskRequest(BaseModel):
    question: str = Field(..., description="Question in Indonesian or English")
    llm: str | None = Field(None, description="LLM profile, e.g. groq or groq-qwen (default from configs/demo.yaml)")
    rerank: bool | None = Field(None, description="Use the bge reranker (default from configs/demo.yaml)")


class Source(BaseModel):
    n: int
    chunk_id: str
    cite: str
    where: str
    file_pages: str
    status: str
    cited: bool
    origin: str


class AskResponse(BaseModel):
    question: str
    language: str
    answer: str
    refused: bool
    refusal_reason: str | None
    disclaimer: str | None
    warnings: list[str]
    sources: list[Source]
    citations: dict[str, int]
    llm: dict[str, Any]
    retrieval: dict[str, Any]
    latency_s: dict[str, float]
    tokens: dict[str, int | None] | None
    cost_usd: float | None


def create_app(service: DemoService, ui_path: str = "/ui") -> FastAPI:
    app = FastAPI(title="Maritime regulation RAG", version="0.1.0",
                  description="Answers about Indonesian maritime regulations and the UNCTAD Review of Maritime "
                              "Transport, with citations (document, Pasal/ayat, page) and version labels. Not legal advice.")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(ui_path)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return service.health()

    @app.get("/examples")
    def examples() -> list[str]:
        return service.cfg.examples

    @app.post("/ask", response_model=AskResponse)
    def ask(req: AskRequest) -> dict[str, Any]:
        try:
            return service.ask(req.question, req.llm, req.rerank)
        except InvalidQuestion as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        except ProviderError as e:
            raise HTTPException(status_code=503, detail=f"LLM provider error: {e}") from None

    @app.get("/sources/{chunk_id}")
    def source(chunk_id: str) -> dict[str, Any]:
        try:
            return service.source(chunk_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown chunk {chunk_id!r}") from None

    return app

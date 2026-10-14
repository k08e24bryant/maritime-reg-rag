"""Prompt construction: question language, numbered SOURCES with status and "cite as" lines."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from maritime_rag.answer.providers import Message
from maritime_rag.answer.versions import ContextChunk, DocNames, VersionIndex, cite_as, describe

LANGUAGE_NAMES = {"id": "Indonesian (Bahasa Indonesia)", "en": "English"}


class LanguageDetector:
    """Indonesian vs English by stopword counts (the BM25 stopword lists); ties -> Indonesian."""

    def __init__(self, stopwords_path: Path) -> None:
        data = yaml.safe_load(stopwords_path.read_text(encoding="utf-8"))
        self.id = frozenset(w.lower() for w in data["indonesian"])
        self.en = frozenset(w.lower() for w in data["english"])

    def __call__(self, text: str) -> str:
        words = re.findall(r"[a-z]+", unicodedata.normalize("NFKD", text).lower())
        en = sum(w in self.en for w in words)
        id_ = sum(w in self.id for w in words)
        return "en" if en > id_ else "id"


def render_source(n: int, cc: ContextChunk, context: list[ContextChunk], names: DocNames, index: VersionIndex) -> str:
    c = cc.chunk
    return "\n".join([
        f"SOURCE {n}",
        f"cite as: {cite_as(c, names)}",
        f"document: {names(c['doc_id'])} - {names.titles.get(c['doc_id'], '')} (file {c['source_file']})",
        f"location: {c['heading']}",
        f"status: {describe(cc, context, names, index)}",
        "text:",
        "<<<",
        c["text"].strip(),
        ">>>",
    ])


def build_messages(
    question: str,
    language: str,
    context: list[ContextChunk],
    names: DocNames,
    index: VersionIndex,
    cfg: dict[str, Any],
) -> list[Message]:
    """cfg = configs/answer.yaml."""
    system = cfg["prompt"]["system"].format(
        language=LANGUAGE_NAMES[language], not_found=cfg["messages"]["not_found"][language]
    )
    sources = "\n\n".join(render_source(i, cc, context, names, index) for i, cc in enumerate(context, start=1))
    user = f"SOURCES\n\n{sources}\n\nQUESTION: {question.strip()}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

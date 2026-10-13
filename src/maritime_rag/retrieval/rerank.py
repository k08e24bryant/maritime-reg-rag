"""Optional second stage: cross-encoder reranking (BAAI/bge-reranker-v2-m3) of the top-N hits."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from maritime_rag.retrieval.corpus import Hit, indexed_text


@dataclass
class RerankTiming:
    n_pairs: int
    seconds: float


def reranker_model_id(cfg: dict[str, Any], choice: str | None = None) -> str:
    """Resolve "default" / "small" (or a literal model id) to a Hugging Face model id."""
    key = choice or cfg["model"]
    return cfg["models"].get(key, key)


class CrossEncoderReranker:
    def __init__(self, cfg: dict[str, Any], cache_folder: Path, include_heading: bool, choice: str | None = None) -> None:
        import torch
        from sentence_transformers import CrossEncoder

        device = "cuda" if torch.cuda.is_available() else "cpu"
        kwargs = {"dtype": torch.float16} if device == "cuda" and cfg["fp16"] else {}
        self.model_id = reranker_model_id(cfg, choice)
        self.model = CrossEncoder(
            self.model_id, device=device, max_length=cfg["max_length"], cache_folder=str(cache_folder), model_kwargs=kwargs
        )
        self.device = device
        self.batch_size: int = cfg["batch_size"]
        self.include_heading = include_heading
        self.last_timing: RerankTiming | None = None

    def rerank(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        if not hits:
            return []
        pairs = [(query, indexed_text(h.chunk, self.include_heading)) for h in hits]
        t0 = time.perf_counter()
        scores = self.model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
        if self.device == "cuda":
            import torch

            torch.cuda.synchronize()
        self.last_timing = RerankTiming(len(pairs), time.perf_counter() - t0)
        order = sorted(range(len(hits)), key=lambda i: (-float(scores[i]), hits[i].rank))[:k]
        return [
            replace(
                hits[i],
                score=float(scores[i]),
                rank=r,
                retriever=f"{hits[i].retriever}+rerank",
                stage_scores={**hits[i].stage_scores, "first_stage_score": hits[i].score, "first_stage_rank": hits[i].rank},
            )
            for r, i in enumerate(order, start=1)
        ]

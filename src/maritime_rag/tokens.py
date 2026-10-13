"""Token counting with the embedding model's tokenizer."""

from __future__ import annotations

from functools import lru_cache

from tokenizers import Tokenizer

from maritime_rag.pasal_splitter import TokenCounter


def load_token_counter(name: str) -> TokenCounter:
    tokenizer = Tokenizer.from_pretrained(name)

    @lru_cache(maxsize=200_000)
    def count(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=False).ids)

    return count

"""LLM providers behind one interface: generate(messages) -> Generation.

Ollama (default), OpenAI, Anthropic, and the OpenAI-compatible APIs of Groq and Google (Gemini),
over HTTP with the standard library (no SDKs). API keys come from environment variables, which
the CLIs also read from .env.
A missing API key, an unreachable server or an API error raises ProviderError; there is never
a silent fallback to another provider or model. Every call is logged (tokens, latency).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": ...}
PROVIDERS = ("ollama", "openai", "anthropic", "groq", "google")


class ProviderError(RuntimeError):
    """The LLM could not be called (missing key, server unreachable, API error)."""


@dataclass
class Generation:
    text: str
    provider: str
    model: str
    prompt_tokens: int | None
    output_tokens: int | None
    latency_s: float
    load_s: float | None = None  # Ollama: time spent loading the model into memory


class Provider(Protocol):
    name: str
    model: str

    def generate(self, messages: list[Message]) -> Generation: ...

    def check(self) -> None:
        """Fail fast (ProviderError) when the provider cannot serve the model; no generation."""
        ...


def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float, who: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", **headers}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(body).get("error", body)
        except json.JSONDecodeError:
            detail = body
        if isinstance(detail, dict):
            detail = detail.get("message", detail)
        raise ProviderError(f"{who} returned HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        reason = getattr(e, "reason", e)
        raise ProviderError(f"{who} is not reachable at {url}: {reason}") from None


def _api_key(cfg: dict[str, Any], who: str) -> str:
    key = os.environ.get(cfg["api_key_env"], "").strip()
    if not key:
        raise ProviderError(f"{who}: environment variable {cfg['api_key_env']} is not set")
    return key


class OllamaProvider:
    name = "ollama"

    def __init__(self, cfg: dict[str, Any], max_output_tokens: int, model: str | None = None) -> None:
        self.cfg = cfg
        self.model = model or cfg["model"]
        self.max_output_tokens = max_output_tokens

    def check(self) -> None:
        url = f"{self.cfg['base_url'].rstrip('/')}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                tags = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            raise ProviderError(f"Ollama is not reachable at {url}: {reason} (start it with: ollama serve)") from None
        names = {m.get("name") for m in tags.get("models", [])} | {m.get("model") for m in tags.get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            raise ProviderError(f"Ollama model {self.model!r} is not pulled (run: ollama pull {self.model})")

    def generate(self, messages: list[Message]) -> Generation:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.cfg["temperature"],
                "seed": self.cfg["seed"],
                "num_ctx": self.cfg["num_ctx"],
                "num_predict": self.max_output_tokens,
            },
        }
        t0 = time.perf_counter()
        try:
            data = _post(f"{self.cfg['base_url'].rstrip('/')}/api/chat", payload, {}, self.cfg["timeout_s"], "Ollama")
        except ProviderError as e:
            if "not found" in str(e):
                raise ProviderError(f"{e} (pull it with: ollama pull {self.model})") from None
            if "not reachable" in str(e):
                raise ProviderError(f"{e} (is Ollama running? start it with: ollama serve)") from None
            raise
        latency = time.perf_counter() - t0
        prompt_tokens = data.get("prompt_eval_count")
        if prompt_tokens is not None and prompt_tokens >= self.cfg["num_ctx"]:
            log.warning("prompt filled the Ollama context (%d >= num_ctx %d); it was likely truncated",
                        prompt_tokens, self.cfg["num_ctx"])
        load_ns = data.get("load_duration")
        return Generation(
            text=data["message"]["content"],
            provider=self.name,
            model=self.model,
            prompt_tokens=prompt_tokens,
            output_tokens=data.get("eval_count"),
            latency_s=latency,
            load_s=load_ns / 1e9 if load_ns is not None else None,
        )


class OpenAIProvider:
    """OpenAI chat completions, and any API compatible with it (Groq, Google Gemini)."""

    name = "openai"
    label = "OpenAI"

    def __init__(self, cfg: dict[str, Any], max_output_tokens: int, model: str | None = None) -> None:
        self.cfg = cfg
        self.model = model or cfg["model"]
        self.max_output_tokens = cfg.get("max_output_tokens") or max_output_tokens
        self.key = _api_key(cfg, self.label)

    def check(self) -> None:  # the key is checked in __init__; the model only on the first call
        pass

    def generate(self, messages: list[Message]) -> Generation:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            cfg_tokens_param(self.cfg): self.max_output_tokens,
        }
        if self.cfg.get("temperature") is not None:
            payload["temperature"] = self.cfg["temperature"]
        t0 = time.perf_counter()
        data = _post(
            f"{self.cfg['base_url'].rstrip('/')}/chat/completions",
            payload,
            {"Authorization": f"Bearer {self.key}"},
            self.cfg["timeout_s"],
            self.label,
        )
        usage = data.get("usage") or {}
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            log.warning("%s output hit the token limit (%d); the answer is cut off", self.label, self.max_output_tokens)
        return Generation(
            text=choice["message"].get("content") or "",
            provider=self.name,
            model=data.get("model", self.model),
            prompt_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_s=time.perf_counter() - t0,
        )


def cfg_tokens_param(cfg: dict[str, Any]) -> str:
    """Name of the output-limit field: OpenAI and Groq take max_completion_tokens, Gemini max_tokens."""
    return cfg.get("max_tokens_param", "max_completion_tokens")


class GroqProvider(OpenAIProvider):
    name = "groq"
    label = "Groq"


class GoogleProvider(OpenAIProvider):
    name = "google"
    label = "Google Gemini"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, cfg: dict[str, Any], max_output_tokens: int, model: str | None = None) -> None:
        self.cfg = cfg
        self.model = model or cfg["model"]
        self.max_output_tokens = max_output_tokens
        self.key = _api_key(cfg, "Anthropic")

    def check(self) -> None:  # the key is checked in __init__; the model only on the first call
        pass

    def generate(self, messages: list[Message]) -> Generation:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_output_tokens,
            "messages": [m for m in messages if m["role"] != "system"],
        }
        if system:
            payload["system"] = system
        if self.cfg.get("temperature") is not None:
            payload["temperature"] = self.cfg["temperature"]
        t0 = time.perf_counter()
        data = _post(
            f"{self.cfg['base_url'].rstrip('/')}/v1/messages",
            payload,
            {"x-api-key": self.key, "anthropic-version": self.cfg["api_version"]},
            self.cfg["timeout_s"],
            "Anthropic",
        )
        usage = data.get("usage") or {}
        return Generation(
            text="".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"),
            provider=self.name,
            model=data.get("model", self.model),
            prompt_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            latency_s=time.perf_counter() - t0,
        )


class LoggingProvider:
    """Wraps a provider: logs tokens and latency of every call, and appends them to a JSONL file."""

    def __init__(self, inner: Provider, calls_file: Path | None) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model
        self.calls_file = calls_file

    def check(self) -> None:
        self.inner.check()

    def generate(self, messages: list[Message]) -> Generation:
        gen = self.inner.generate(messages)
        log.info("%s %s: %s prompt + %s output tokens in %.2f s",
                 gen.provider, gen.model, gen.prompt_tokens, gen.output_tokens, gen.latency_s)
        if self.calls_file is not None:
            self.calls_file.parent.mkdir(parents=True, exist_ok=True)
            row = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds")} | asdict(gen)
            row.pop("text")
            with self.calls_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        return gen


def make_provider(
    cfg: dict[str, Any], name: str | None = None, model: str | None = None, calls_file: Path | None = None
) -> Provider:
    """cfg = the `provider` section of configs/answer.yaml."""
    name = name or cfg["default"]
    classes = {
        "ollama": OllamaProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "groq": GroqProvider,
        "google": GoogleProvider,
    }
    if name not in classes:
        raise ProviderError(f"unknown provider {name!r}; choose from {PROVIDERS}")
    return LoggingProvider(classes[name](cfg[name], cfg["max_output_tokens"], model), calls_file)

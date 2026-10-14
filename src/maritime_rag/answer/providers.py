"""LLM providers behind one interface: generate(messages) -> Generation.

Named profiles in configs/answer.yaml (llm.profiles) pick an implementation by `type`:
  ollama     local Ollama, native /api/chat (needed for num_ctx; its /v1 API ignores it)
  openai     any OpenAI-compatible chat completions API: OpenAI, Gemini, Groq, ...
  anthropic  Anthropic Messages API
HTTP uses the standard library (no SDKs). API keys come from environment variables, which the
CLIs also read from .env. Before any work, check() verifies the server and that the exact
model id is listed, and cloud profiles with `probe: true` send one tiny generation request: a
model can be listed yet refuse requests (e.g. Gemini models retired for new accounts).
The local Ollama profile only runs when explicitly allowed (--llm ollama --allow-local).

Rate limits: HTTP 429 (and other configured statuses) are retried with exponential backoff,
honouring Retry-After; a profile can also set a minimum interval between calls and a
tokens-per-minute budget. A missing key, an unknown model, an unreachable server or an
exhausted quota raises ProviderError; there is never a silent fallback to another LLM.
Every call is logged with its tokens, latency, estimated cost (profile `price_usd_per_mtok`),
and the calls/tokens of the last 60 seconds.

Token accounting follows Groq's: measured 2026-10-14, the remaining-tokens header dropped by
prompt + max_completion_tokens (not the tokens actually used) on a fresh budget, so each call
counts as prompt + max(output, max_output_tokens) in the 60-second window. Reasoning tokens are
part of completion_tokens; they are also logged separately when the API reports them.
"""

from __future__ import annotations

import email.utils
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": ...}
USER_AGENT = "maritime-reg-rag/0.1"
PROBE_MESSAGES: list[Message] = [{"role": "user", "content": "Reply with: OK"}]
PROBE_MAX_TOKENS = 5

# indirection so tests can run without real waiting
_sleep = time.sleep
_now = time.monotonic


class ProviderError(RuntimeError):
    """The LLM could not be called (missing key, unknown model, unreachable, quota, API error)."""


@dataclass
class Generation:
    text: str
    provider: str  # profile name: ollama | gemini | groq | ...
    model: str  # model id as reported by the API
    prompt_tokens: int | None
    output_tokens: int | None
    latency_s: float  # the successful request
    load_s: float | None = None  # Ollama: time spent loading the model into memory
    retries: int = 0  # requests retried after 429/503
    wait_s: float = 0.0  # backoff + throttling before the successful request
    finish_reason: str | None = None
    reasoning_tokens: int | None = None  # part of output_tokens, when the API reports it
    ratelimit_remaining_tokens: int | None = None  # x-ratelimit-remaining-tokens after the call
    max_output_tokens: int | None = None  # the limit sent with the request
    ratelimit: dict[str, str] = field(default_factory=dict)  # x-ratelimit-* response headers
    cost_usd: float | None = None  # estimated from the profile's prices (None = no price configured)

    @property
    def truncated(self) -> bool:
        """The output limit cut the answer off."""
        return self.finish_reason in {"length", "max_tokens"}


class Provider(Protocol):
    name: str
    model: str

    def generate(self, messages: list[Message]) -> Generation: ...

    def check(self) -> None:
        """Fail fast (ProviderError) when the provider cannot serve the model; no generation."""
        ...


@dataclass
class RetryPolicy:
    max_retries: int = 5
    base_delay_s: float = 2.0
    max_delay_s: float = 90.0  # a longer Retry-After means the quota is gone: fail, don't sleep
    statuses: tuple[int, ...] = (429, 503)

    @classmethod
    def from_cfg(cls, cfg: dict[str, Any] | None) -> RetryPolicy:
        cfg = cfg or {}
        return cls(
            max_retries=cfg.get("max_retries", cls.max_retries),
            base_delay_s=cfg.get("base_delay_s", cls.base_delay_s),
            max_delay_s=cfg.get("max_delay_s", cls.max_delay_s),
            statuses=tuple(cfg.get("statuses", cls.statuses)),
        )


@dataclass
class Response:
    data: dict[str, Any]
    retries: int = 0
    backoff_s: float = 0.0
    latency_s: float = 0.0
    headers: dict[str, str] = field(default_factory=dict)


def _retry_after(err: urllib.error.HTTPError, body: str) -> float | None:
    """Seconds the server asks to wait: Retry-After (seconds or HTTP date), else Gemini's retryDelay."""
    value = err.headers.get("Retry-After") if err.headers else None
    if value:
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(value)
            except (TypeError, ValueError):
                when = None
            if when is not None:
                return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    if m := re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body):
        return float(m[1])
    return None


def _error_detail(body: str) -> str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()[:500]
    if isinstance(data, list) and data:  # Gemini's OpenAI endpoint may wrap errors in a list
        data = data[0]
    detail = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(detail, dict):
        detail = detail.get("message", detail)
    return str(detail)[:500]


def _request(
    url: str,
    payload: dict[str, Any] | None,
    headers: dict[str, str],
    timeout: float,
    who: str,
    retry: RetryPolicy | None = None,
) -> Response:
    """POST (payload) or GET (None) JSON, retrying the policy's statuses with backoff."""
    retry = retry or RetryPolicy(max_retries=0)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    # Cloudflare in front of Groq rejects urllib's default "Python-urllib" agent (HTTP 403, error 1010)
    hdrs = {"User-Agent": USER_AGENT, **headers}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    retries, backoff = 0, 0.0
    while True:
        req = urllib.request.Request(url, data=data, headers=hdrs)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                out = json.loads(resp.read().decode("utf-8"))
                raw_headers = getattr(resp, "headers", None)
                resp_headers = {k.lower(): v for k, v in raw_headers.items()} if raw_headers else {}
            return Response(out, retries, backoff, time.perf_counter() - t0, resp_headers)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            detail = _error_detail(body)
            if e.code not in retry.statuses:
                raise ProviderError(f"{who} returned HTTP {e.code}: {detail}") from None
            asked = _retry_after(e, body)
            if asked is not None and asked > retry.max_delay_s:
                raise ProviderError(
                    f"{who} returned HTTP {e.code} and asks to wait {asked:.0f} s (more than "
                    f"retry.max_delay_s {retry.max_delay_s:.0f} s; quota likely exhausted): {detail}"
                ) from None
            if retries >= retry.max_retries:
                raise ProviderError(f"{who} returned HTTP {e.code} after {retries} retries: {detail}") from None
            delay = asked if asked is not None else min(retry.base_delay_s * 2**retries, retry.max_delay_s)
            retries += 1
            log.warning("%s HTTP %d, retry %d/%d in %.1f s%s", who, e.code, retries, retry.max_retries, delay,
                        " (Retry-After)" if asked is not None else "")
            _sleep(delay)
            backoff += delay
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            if isinstance(e, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(reason):
                raise ProviderError(f"{who} did not answer within {timeout:.0f} s ({url}); the service may be "
                                    "overloaded: retry later or raise timeout_s") from None
            raise ProviderError(f"{who} is not reachable at {url}: {reason}") from None


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _api_key(cfg: dict[str, Any], who: str) -> str:
    key = os.environ.get(cfg["api_key_env"], "").strip()
    if not key:
        raise ProviderError(f"{who}: environment variable {cfg['api_key_env']} is not set (put it in .env)")
    return key


class OllamaProvider:
    def __init__(self, name: str, cfg: dict[str, Any], max_output_tokens: int, model: str | None,
                 retry: RetryPolicy) -> None:
        self.name = name
        self.cfg = cfg
        self.model = model or cfg["model"]
        self.max_output_tokens = cfg.get("max_output_tokens") or max_output_tokens
        self.base = cfg["base_url"].rstrip("/")

    def check(self) -> None:
        try:
            tags = _request(f"{self.base}/api/tags", None, {}, 10, "Ollama").data
        except ProviderError as e:
            raise ProviderError(f"{e} (start it with: ollama serve)") from None
        names = {m.get("name") for m in tags.get("models", [])} | {m.get("model") for m in tags.get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            raise ProviderError(f"Ollama model {self.model!r} is not pulled (run: ollama pull {self.model}); "
                                f"available: {', '.join(sorted(n for n in names if n)) or 'none'}")

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
        try:
            r = _request(f"{self.base}/api/chat", payload, {}, self.cfg["timeout_s"], "Ollama")
        except ProviderError as e:
            if "not found" in str(e):
                raise ProviderError(f"{e} (pull it with: ollama pull {self.model})") from None
            if "not reachable" in str(e):
                raise ProviderError(f"{e} (is Ollama running? start it with: ollama serve)") from None
            raise
        data = r.data
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
            latency_s=r.latency_s,
            load_s=load_ns / 1e9 if load_ns is not None else None,
            finish_reason=data.get("done_reason"),
        )


def _model_ids(listing: dict[str, Any]) -> set[str]:
    """Ids from an OpenAI-style /models listing; Gemini prefixes them with "models/"."""
    ids = {str(m.get("id")) for m in listing.get("data", []) if m.get("id")}
    return ids | {i.removeprefix("models/") for i in ids}


class OpenAICompatibleProvider:
    """OpenAI chat completions and the APIs compatible with it (Gemini, Groq); one instance per profile."""

    def __init__(self, name: str, cfg: dict[str, Any], max_output_tokens: int, model: str | None,
                 retry: RetryPolicy) -> None:
        self.name = name
        self.label = cfg.get("label", name)
        self.cfg = cfg
        self.model = model or cfg["model"]
        self.max_output_tokens = cfg.get("max_output_tokens") or max_output_tokens
        self.base = cfg["base_url"].rstrip("/")
        self.retry = retry
        self.key = _api_key(cfg, self.label)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"}

    def check(self) -> None:
        """The configured model id must be listed by the provider's /models endpoint."""
        listing = _request(f"{self.base}/models", None, self._headers(), 30, self.label, self.retry).data
        ids = _model_ids(listing)
        if self.model not in ids:
            shown = sorted(i for i in ids if not i.startswith("models/"))
            raise ProviderError(
                f"{self.label}: model {self.model!r} is not listed by {self.base}/models. "
                f"Available ids: {', '.join(shown) or 'none'}"
            )

    def generate(self, messages: list[Message], max_tokens: int | None = None) -> Generation:
        limit = max_tokens or self.max_output_tokens
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            self.cfg.get("max_tokens_param", "max_completion_tokens"): limit,
            **(self.cfg.get("extra") or {}),
        }
        if self.cfg.get("temperature") is not None:
            payload["temperature"] = self.cfg["temperature"]
        r = _request(f"{self.base}/chat/completions", payload, self._headers(), self.cfg["timeout_s"],
                     self.label, self.retry)
        usage = r.data.get("usage") or {}
        choice = r.data["choices"][0]
        if choice.get("finish_reason") == "length" and max_tokens is None:
            log.warning("%s output hit the token limit (%d); the answer is cut off", self.label, self.max_output_tokens)
        return Generation(
            text=choice["message"].get("content") or "",
            provider=self.name,
            model=r.data.get("model", self.model),
            prompt_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_s=r.latency_s,
            retries=r.retries,
            wait_s=r.backoff_s,
            finish_reason=choice.get("finish_reason"),
            reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            ratelimit_remaining_tokens=_int(r.headers.get("x-ratelimit-remaining-tokens")),
            max_output_tokens=limit,
            ratelimit={k: v for k, v in r.headers.items() if k.startswith("x-ratelimit")},
        )


class AnthropicProvider:
    def __init__(self, name: str, cfg: dict[str, Any], max_output_tokens: int, model: str | None,
                 retry: RetryPolicy) -> None:
        self.name = name
        self.cfg = cfg
        self.model = model or cfg["model"]
        self.max_output_tokens = cfg.get("max_output_tokens") or max_output_tokens
        self.base = cfg["base_url"].rstrip("/")
        self.retry = retry
        self.key = _api_key(cfg, "Anthropic")

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.key, "anthropic-version": self.cfg["api_version"]}

    def check(self) -> None:
        listing = _request(f"{self.base}/v1/models?limit=1000", None, self._headers(), 30, "Anthropic", self.retry)
        ids = {m.get("id") for m in listing.data.get("data", []) if m.get("id")}
        if self.model not in ids:
            raise ProviderError(f"Anthropic: model {self.model!r} is not listed by /v1/models. "
                                f"Available ids: {', '.join(sorted(ids)) or 'none'}")

    def generate(self, messages: list[Message], max_tokens: int | None = None) -> Generation:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_output_tokens,
            "messages": [m for m in messages if m["role"] != "system"],
        }
        if system:
            payload["system"] = system
        if self.cfg.get("temperature") is not None:
            payload["temperature"] = self.cfg["temperature"]
        r = _request(f"{self.base}/v1/messages", payload, self._headers(), self.cfg["timeout_s"], "Anthropic",
                     self.retry)
        usage = r.data.get("usage") or {}
        return Generation(
            text="".join(b.get("text", "") for b in r.data.get("content", []) if b.get("type") == "text"),
            provider=self.name,
            model=r.data.get("model", self.model),
            prompt_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            latency_s=r.latency_s,
            retries=r.retries,
            wait_s=r.backoff_s,
            finish_reason=r.data.get("stop_reason"),
        )


@dataclass
class Limits:
    """Client-side pacing for free tiers: min seconds between calls, and a tokens-per-minute budget."""

    min_interval_s: float = 0.0
    tokens_per_minute: int | None = None


@dataclass
class _Window:
    calls: deque[tuple[float, int]] = field(default_factory=deque)  # (time, prompt + output tokens)

    def trim(self, now: float) -> None:
        while self.calls and now - self.calls[0][0] >= 60.0:
            self.calls.popleft()

    def tokens(self) -> int:
        return sum(t for _, t in self.calls)


@dataclass
class Price:
    """USD per 1M tokens. Reasoning tokens are billed as output (they are part of completion_tokens)."""

    input: float
    output: float

    @classmethod
    def from_cfg(cls, cfg: dict[str, Any] | None) -> Price | None:
        return cls(float(cfg["input"]), float(cfg["output"])) if cfg else None

    def cost(self, prompt_tokens: int | None, output_tokens: int | None) -> float:
        return ((prompt_tokens or 0) * self.input + (output_tokens or 0) * self.output) / 1e6


def estimate_tokens(messages: list[Message]) -> int:
    """Rough prompt size before the call (~4 characters per token); usage from the API replaces it."""
    return sum(len(m["content"]) for m in messages) // 4 + 8 * len(messages)


class LoggingProvider:
    """Wraps a provider: paces calls (Limits), then logs tokens, latency and the last-60-s usage
    of every call, and appends them to a JSONL file."""

    def __init__(self, inner: Provider, calls_file: Path | None, limits: Limits | None = None,
                 probe: bool = False, price: Price | None = None) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model
        self.calls_file = calls_file
        self.limits = limits or Limits()
        self.probe = probe
        self.price = price
        self.window = _Window()
        self.last_call: float | None = None
        self.last_probe: Generation | None = None
        # totals since this provider was created (including the probe)
        self.calls = 0
        self.prompt_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    def check(self) -> None:
        """Model id listed, then (probe) one tiny request: a listed model can still be unusable."""
        self.inner.check()
        if not self.probe:
            return
        try:
            gen = self.inner.generate(PROBE_MESSAGES, max_tokens=PROBE_MAX_TOKENS)
        except ProviderError as e:
            raise ProviderError(f"{self.name}: model {self.model!r} is listed, but a test request failed: {e}") from None
        finally:
            self.last_call = _now()
        self._record(gen, probe=True)
        self.last_probe = gen

    def _throttle(self, messages: list[Message]) -> float:
        waited = 0.0
        if self.last_call is not None and self.limits.min_interval_s > 0:
            gap = self.limits.min_interval_s - (_now() - self.last_call)
            if gap > 0:
                _sleep(gap)
                waited += gap
        tpm = self.limits.tokens_per_minute
        if tpm:
            need = estimate_tokens(messages) + getattr(self.inner, "max_output_tokens", 0)
            if need > tpm:
                log.warning("%s: this call may need ~%d tokens, more than the %d tokens/min limit",
                            self.name, need, tpm)
            self.window.trim(_now())
            while self.window.calls and self.window.tokens() + need > tpm:
                gap = max(60.0 - (_now() - self.window.calls[0][0]) + 0.5, 0.0)
                log.info("%s: waiting %.1f s for the tokens-per-minute budget (%d used in the last 60 s)",
                         self.name, gap, self.window.tokens())
                _sleep(gap)
                waited += gap
                self.window.trim(_now())
        return waited

    def generate(self, messages: list[Message]) -> Generation:
        waited = self._throttle(messages)
        try:
            gen = self.inner.generate(messages)
        finally:
            self.last_call = _now()
        gen.wait_s += waited
        self._record(gen)
        return gen

    def _record(self, gen: Generation, probe: bool = False) -> None:
        if self.price is not None:
            gen.cost_usd = self.price.cost(gen.prompt_tokens, gen.output_tokens)
        self.calls += 1
        self.prompt_tokens += gen.prompt_tokens or 0
        self.output_tokens += gen.output_tokens or 0
        self.cost_usd += gen.cost_usd or 0.0
        now = self.last_call if self.last_call is not None else _now()
        self.window.trim(now)
        # count what the provider reserves: prompt + the full output limit (Groq), not just what was used
        reserved = max(gen.output_tokens or 0, gen.max_output_tokens or 0)
        self.window.calls.append((now, (gen.prompt_tokens or 0) + reserved))
        calls_60s, tokens_60s = len(self.window.calls), self.window.tokens()
        reasoning = f" ({gen.reasoning_tokens} reasoning)" if gen.reasoning_tokens is not None else ""
        remaining = (f"; provider reports {gen.ratelimit_remaining_tokens} tokens left"
                     if gen.ratelimit_remaining_tokens is not None else "")
        cost = f", est. ${gen.cost_usd:.5f}" if gen.cost_usd is not None else ""
        log.info("%s%s %s: %s prompt + %s output%s tokens%s in %.1f s (waited %.1f s, %d retries)%s; "
                 "last 60 s: %d calls, %d tokens counted%s", "probe " if probe else "", gen.provider, gen.model,
                 gen.prompt_tokens, gen.output_tokens, reasoning, cost, gen.latency_s, gen.wait_s, gen.retries,
                 " TRUNCATED" if gen.truncated and not probe else "", calls_60s, tokens_60s, remaining)
        if self.calls_file is not None:
            self.calls_file.parent.mkdir(parents=True, exist_ok=True)
            row = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "probe": probe} | asdict(gen)
            row.pop("text")
            row.pop("ratelimit")
            row["truncated"] = gen.truncated
            row |= {"calls_last_60s": calls_60s, "tokens_last_60s": tokens_60s}
            with self.calls_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")


_TYPES = {"ollama": OllamaProvider, "openai": OpenAICompatibleProvider, "anthropic": AnthropicProvider}


def profiles(cfg: dict[str, Any]) -> list[str]:
    """Profile names in the `llm` section of configs/answer.yaml."""
    return list(cfg["profiles"])


class LocalLLMRefused(ProviderError):
    """A local LLM profile was selected without an explicit --llm <name> --allow-local."""


def make_provider(
    cfg: dict[str, Any],
    name: str | None = None,
    model: str | None = None,
    calls_file: Path | None = None,
    allow_local: bool = False,
) -> LoggingProvider:
    """cfg = the `llm` section of configs/answer.yaml; name = a profile (default: llm.default).

    A local profile (type ollama) needs both an explicit name and allow_local=True, so neither
    the config default nor a forgotten flag can start an LLM on this machine."""
    explicit = name is not None
    name = name or cfg["default"]
    if name not in cfg["profiles"]:
        raise ProviderError(f"unknown LLM profile {name!r}; choose from {', '.join(profiles(cfg))}")
    prof = cfg["profiles"][name]
    if prof["type"] not in _TYPES:
        raise ProviderError(f"profile {name!r} has unknown type {prof['type']!r}; choose from {', '.join(_TYPES)}")
    if prof["type"] == "ollama" and not (explicit and allow_local):
        raise LocalLLMRefused(
            f"profile {name!r} runs the LLM on this machine and is disabled by default. Use a cloud "
            f"profile (--llm groq or --llm gemini), or run it deliberately with: --llm {name} --allow-local"
        )
    inner = _TYPES[prof["type"]](name, prof, cfg["max_output_tokens"], model, RetryPolicy.from_cfg(cfg.get("retry")))
    limits = Limits(prof.get("min_interval_s") or 0.0, prof.get("tokens_per_minute"))
    probe = bool(prof.get("probe")) and prof["type"] != "ollama"  # an Ollama probe would load the model locally
    return LoggingProvider(inner, calls_file, limits, probe, Price.from_cfg(prof.get("price_usd_per_mtok")))

"""LLM providers without network: profiles, key/model checks, 429 retry, client-side pacing, logging."""

from __future__ import annotations

import copy
import email.message
import io
import json
import os
import urllib.error

import pytest

import maritime_rag.answer.providers as providers
from maritime_rag.answer.providers import (
    PROBE_MAX_TOKENS,
    Generation,
    Limits,
    LocalLLMRefused,
    LoggingProvider,
    ProviderError,
    make_provider,
)
from maritime_rag.config import load_config, load_env_file

LLM = load_config("configs/answer.yaml")["llm"]
MSGS = [{"role": "user", "content": "hi"}]


class FakeResponse:
    def __init__(self, data: dict) -> None:
        self.headers = data.pop("_headers", {})
        self.body = json.dumps(data).encode()

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        pass


def http_error(code: int, body: str = "{}", retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://x", code, "err", headers, io.BytesIO(body.encode()))


class FakeServer:
    """Replaces urlopen: pops scripted responses (dict = 200 JSON, HTTPError = raised), records requests."""

    def __init__(self, *script) -> None:
        self.script = list(script)
        self.requests: list = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(round(s, 2))
        self.t += s


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(providers, "_now", c.now)
    monkeypatch.setattr(providers, "_sleep", c.sleep)
    return c


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")


def serve(monkeypatch: pytest.MonkeyPatch, *script) -> FakeServer:
    server = FakeServer(*script)
    monkeypatch.setattr(providers.urllib.request, "urlopen", server)
    return server


def completion(content: str = "ok", model: str = "m", prompt: int = 7, output: int = 1,
               finish: str = "stop", reasoning: int | None = None, remaining: int | None = None) -> dict:
    usage = {"prompt_tokens": prompt, "completion_tokens": output}
    if reasoning is not None:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning}
    out = {"model": model, "choices": [{"message": {"content": content}, "finish_reason": finish}], "usage": usage}
    if remaining is not None:
        out["_headers"] = {"x-ratelimit-remaining-tokens": str(remaining)}
    return out


# --- profiles --------------------------------------------------------------------------------------

def test_profiles_in_config() -> None:
    p = LLM["profiles"]
    assert {"ollama", "gemini", "groq"} <= set(p)
    assert LLM["default"] == "groq"
    assert (p["gemini"]["type"], p["gemini"]["api_key_env"], p["gemini"]["model"]) == ("openai", "GEMINI_API_KEY", "gemini-3.8-flash")
    assert p["gemini"]["probe"] and p["groq"]["probe"] and not p["ollama"].get("probe")
    assert p["gemini"]["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert (p["groq"]["type"], p["groq"]["api_key_env"], p["groq"]["model"]) == ("openai", "GROQ_API_KEY", "openai/gpt-oss-120b")
    assert p["groq"]["base_url"] == "https://api.groq.com/openai/v1" and p["groq"]["max_output_tokens"] == 1024
    q = p["groq-qwen"]
    assert (q["type"], q["base_url"], q["api_key_env"], q["model"]) == (
        "openai", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "qwen/qwen3.8-27b")
    assert q["probe"] and q["extra"] == {"reasoning_format": "hidden"} and q["tokens_per_minute"] == 8000
    assert p["ollama"]["type"] == "ollama"


def test_missing_key_and_unknown_profile_are_clear_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("gemini", "groq", "openai", "anthropic"):
        env = LLM["profiles"][name]["api_key_env"]
        monkeypatch.delenv(env, raising=False)
        with pytest.raises(ProviderError, match=f"{env} is not set"):
            make_provider(LLM, name)
    with pytest.raises(ProviderError, match="unknown LLM profile 'mistral'.*gemini.*groq"):
        make_provider(LLM, "mistral")


def test_openai_compatible_requests(monkeypatch: pytest.MonkeyPatch, keys: None, clock: Clock) -> None:
    server = serve(monkeypatch, completion(model="openai/gpt-oss-120b"), completion(model="gemini-3.8-flash"))
    g = make_provider(LLM, "groq").generate(MSGS)
    assert (g.provider, g.model, g.text, g.prompt_tokens) == ("groq", "openai/gpt-oss-120b", "ok", 7)
    g = make_provider(LLM, "gemini").generate(MSGS)
    assert (g.provider, g.model) == ("gemini", "gemini-3.8-flash")
    groq, gem = server.requests
    assert groq.full_url == "https://api.groq.com/openai/v1/chat/completions"
    assert groq.get_header("Authorization") == "Bearer groq-key"
    assert groq.get_header("User-agent") == providers.USER_AGENT  # Groq's Cloudflare blocks "Python-urllib"
    body = json.loads(groq.data)
    assert body["max_completion_tokens"] == LLM["profiles"]["groq"]["max_output_tokens"]
    assert body["reasoning_effort"] == "low" and "temperature" not in body
    assert gem.full_url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert gem.get_header("Authorization") == "Bearer gem-key"
    assert json.loads(gem.data)["max_tokens"] == LLM["profiles"]["gemini"]["max_output_tokens"]


def test_model_id_checked_against_models_endpoint(monkeypatch: pytest.MonkeyPatch, keys: None) -> None:
    gemini_listing = {"data": [{"id": "models/gemini-3.8-flash"}, {"id": "models/gemini-2.5-pro"}]}
    server = serve(monkeypatch, gemini_listing)
    make_provider(LLM, "gemini").inner.check()  # "models/" prefix is accepted (listing only, no probe)
    assert server.requests[0].full_url == "https://generativelanguage.googleapis.com/v1beta/openai/models"
    serve(monkeypatch, {"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "openai/gpt-oss-20b"}]})
    with pytest.raises(ProviderError, match="'openai/gpt-oss-120b' is not listed.*llama-3.3-70b-versatile, openai/gpt-oss-20b"):
        make_provider(LLM, "groq").check()


def test_probe_catches_listed_but_unusable_model(monkeypatch: pytest.MonkeyPatch, keys: None, clock: Clock) -> None:
    listing = {"data": [{"id": "models/gemini-2.5-flash"}, {"id": "models/gemini-3.8-flash"}]}
    retired = json.dumps([{"error": {"code": 404, "message": "models/gemini-2.5-flash is no longer available to new "
                                     "users. Please update your code to use models/gemini-3.8-flash"}}])
    serve(monkeypatch, listing, http_error(404, retired))
    with pytest.raises(ProviderError, match="'gemini-2.5-flash' is listed, but a test request failed.*HTTP 404.*gemini-3.8-flash"):
        make_provider(LLM, "gemini", model="gemini-2.5-flash").check()

    server = serve(monkeypatch, listing, completion(model="gemini-3.8-flash", prompt=4, output=1), completion())
    llm = make_provider(LLM, "gemini")
    llm.check()
    probe = json.loads(server.requests[1].data)
    assert probe["max_tokens"] == PROBE_MAX_TOKENS and len(probe["messages"]) == 1
    llm.generate(MSGS)  # the probe counts as a call: min_interval_s applies before the first answer
    assert clock.sleeps == [LLM["profiles"]["gemini"]["min_interval_s"]]


def test_local_llm_needs_explicit_profile_and_allow_local(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(LocalLLMRefused, match="--llm ollama --allow-local"):
        make_provider(LLM, "ollama")
    cfg = copy.deepcopy(LLM)
    cfg["default"] = "ollama"
    with pytest.raises(LocalLLMRefused):  # a config default is not an explicit choice
        make_provider(cfg, allow_local=True)
    llm = make_provider(LLM, "ollama", allow_local=True)
    assert llm.name == "ollama" and not llm.probe  # an Ollama probe would load the model locally


def test_ollama_check_lists_pulled_models(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {"models": [{"name": "qwen2.5:7b-instruct", "model": "qwen2.5:7b-instruct"}]})
    make_provider(LLM, "ollama", allow_local=True).check()
    serve(monkeypatch, {"models": [{"name": "qwen2.5:7b-instruct", "model": "qwen2.5:7b-instruct"}]})
    with pytest.raises(ProviderError, match="ollama pull qwen2.5:3b-instruct.*available: qwen2.5:7b-instruct"):
        make_provider(LLM, "ollama", model="qwen2.5:3b-instruct", allow_local=True).check()


def test_timeout_is_reported_as_timeout(monkeypatch: pytest.MonkeyPatch, keys: None) -> None:
    serve(monkeypatch, TimeoutError("The read operation timed out"))
    with pytest.raises(ProviderError, match="did not answer within 300 s"):
        make_provider(LLM, "gemini").generate(MSGS)


def test_unreachable_ollama_is_a_clear_error() -> None:
    cfg = copy.deepcopy(LLM)
    cfg["profiles"]["ollama"] |= {"base_url": "http://127.0.0.1:9", "timeout_s": 5}  # nothing listens on port 9
    provider = make_provider(cfg, "ollama", allow_local=True)
    with pytest.raises(ProviderError, match="not reachable.*ollama serve"):
        provider.check()
    with pytest.raises(ProviderError, match="not reachable.*ollama serve"):
        provider.generate(MSGS)


# --- rate limits -----------------------------------------------------------------------------------

def test_429_retries_with_retry_after_then_backoff(monkeypatch: pytest.MonkeyPatch, keys: None, clock: Clock) -> None:
    serve(monkeypatch, http_error(429, retry_after="3"), http_error(429), completion())
    g = make_provider(LLM, "groq").generate(MSGS)
    assert g.text == "ok" and g.retries == 2
    assert clock.sleeps == [3.0, 4.0]  # Retry-After, then base 2 s * 2^1
    assert g.wait_s == pytest.approx(7.0)


def test_gemini_retry_delay_in_body(monkeypatch: pytest.MonkeyPatch, keys: None, clock: Clock) -> None:
    body = json.dumps([{"error": {"code": 429, "message": "Resource exhausted",
                                  "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12s"}]}}])
    serve(monkeypatch, http_error(429, body), completion())
    assert make_provider(LLM, "gemini").generate(MSGS).retries == 1
    assert clock.sleeps == [12.0]


def test_rate_limit_failures_are_clear(monkeypatch: pytest.MonkeyPatch, keys: None, clock: Clock) -> None:
    serve(monkeypatch, http_error(429, retry_after="3600"))
    with pytest.raises(ProviderError, match="wait 3600 s.*quota likely exhausted"):
        make_provider(LLM, "groq").generate(MSGS)
    cfg = copy.deepcopy(LLM)
    cfg["retry"]["max_retries"] = 2
    serve(monkeypatch, http_error(429), http_error(429), http_error(429))
    with pytest.raises(ProviderError, match="HTTP 429 after 2 retries"):
        make_provider(cfg, "groq").generate(MSGS)
    body = json.dumps([{"error": {"code": 400, "message": "API key not valid"}}])
    serve(monkeypatch, http_error(400, body))
    with pytest.raises(ProviderError, match="HTTP 400: API key not valid"):  # not retried
        make_provider(LLM, "gemini").generate(MSGS)


class ScriptedLLM:
    name, model, max_output_tokens = "fake", "fake-1", 0

    def __init__(self, prompt: int = 100, output: int = 20) -> None:
        self.prompt, self.output = prompt, output

    def check(self) -> None:
        pass

    def generate(self, messages):
        return Generation("x", self.name, self.model, self.prompt, self.output, 0.5)


def test_min_interval_between_calls(clock: Clock) -> None:
    llm = LoggingProvider(ScriptedLLM(), None, Limits(min_interval_s=6.5))
    llm.generate(MSGS)
    clock.t += 2.0
    g = llm.generate(MSGS)
    assert clock.sleeps == [4.5] and g.wait_s == pytest.approx(4.5)


def test_tokens_per_minute_budget(clock: Clock) -> None:
    llm = LoggingProvider(ScriptedLLM(prompt=600, output=100), None, Limits(tokens_per_minute=1000))
    big = [{"role": "user", "content": "x" * 1200}]  # ~308 estimated tokens
    llm.generate(big)  # 700 tokens in the window
    clock.t += 10.0
    llm.generate(big)  # 700 + 308 > 1000: wait until the first call is 60 s old
    assert clock.sleeps == [50.5]


def test_reasoning_tokens_truncation_and_remaining_budget_are_recorded(
        monkeypatch: pytest.MonkeyPatch, keys: None, clock: Clock, tmp_path) -> None:
    serve(monkeypatch, completion(prompt=5000, output=2048, finish="length", reasoning=1500, remaining=900))
    log_file = tmp_path / "calls.jsonl"
    llm = make_provider(LLM, "groq-qwen", calls_file=log_file)
    g = llm.generate(MSGS)
    assert g.truncated and g.reasoning_tokens == 1500 and g.ratelimit_remaining_tokens == 900
    assert g.max_output_tokens == LLM["profiles"]["groq-qwen"]["max_output_tokens"] == 2048
    row = json.loads(log_file.read_text(encoding="utf-8"))
    assert row["truncated"] is True and row["reasoning_tokens"] == 1500 and row["ratelimit_remaining_tokens"] == 900


def test_window_counts_the_reserved_output_limit(monkeypatch: pytest.MonkeyPatch, keys: None, clock: Clock) -> None:
    # Groq reserves prompt + max_completion_tokens; a short answer must not free the rest early
    serve(monkeypatch, completion(prompt=3000, output=100), completion(prompt=3000, output=100))
    llm = make_provider(LLM, "groq")  # max_output_tokens 1024, 8000 tokens/min
    llm.generate(MSGS)
    assert llm.window.tokens() == 3000 + 1024
    clock.t += 5
    llm.generate([{"role": "user", "content": "x" * 12000}])  # ~3008 + 1024 more: 8056 > 8000 -> wait
    assert clock.sleeps and clock.sleeps[-1] == pytest.approx(55.5)


def test_logging_records_tokens_and_last_minute_usage(tmp_path, clock: Clock) -> None:
    log_file = tmp_path / "calls.jsonl"
    llm = LoggingProvider(ScriptedLLM(), log_file)
    llm.generate(MSGS)
    clock.t += 5
    llm.generate(MSGS)
    clock.t += 70  # the first two calls leave the 60-s window
    llm.generate(MSGS)
    rows = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert [(r["calls_last_60s"], r["tokens_last_60s"]) for r in rows] == [(1, 120), (2, 240), (1, 120)]
    assert rows[0]["prompt_tokens"] == 100 and rows[0]["output_tokens"] == 20 and "text" not in rows[0]
    assert {"latency_s", "retries", "wait_s", "provider", "model"} <= set(rows[0])


# --- .env ------------------------------------------------------------------------------------------

def test_env_file_loader(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
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

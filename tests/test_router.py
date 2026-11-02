from __future__ import annotations

import pytest

from zerocode.config import Config
from zerocode.errors import ConfigError, ProviderError, RateLimitError
from zerocode.router import Router
from zerocode.types import Completion, Usage


class FakeClient:
    def __init__(self, *, error: Exception | None = None, provider: str = ""):
        self.error = error
        self.provider = provider
        self.calls = 0

    def stream(self, provider, model, messages, tools, callbacks=None):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return Completion(
            content="ok",
            provider=self.provider or provider.name,
            model=model.id,
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2, requests=1),
        )

    def close(self):
        return None


class FailOnceClient(FakeClient):
    def stream(self, provider, model, messages, tools, callbacks=None):
        self.calls += 1
        if self.calls == 1:
            raise RateLimitError("temporary quota", retryable=True, retry_after=1)
        return Completion(
            content="ok",
            provider=provider.name,
            model=model.id,
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2, requests=1),
        )


def test_auto_prefers_keyless_kilo():
    router = Router(Config(model="auto"))
    try:
        assert router.preview("auto")[0] == "kilo/kilo-auto/free"
    finally:
        router.close()


def test_provider_falls_back_to_free_model(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    router = Router(Config(model="glm-5.3", provider="zai"))
    try:
        assert router.preview("glm-5.3", "zai")[0] == "zai/glm-4.7-flash"
        assert router.preview("glm-5.3-flash", "zai")[0] == "zai/glm-4.7-flash"
    finally:
        router.close()


def test_paid_model_allowed_without_free_only(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    config = Config(model="glm-5.3", provider="zai", free_only=False)
    router = Router(config)
    try:
        assert router.preview("glm-5.3", "zai")[0] == "zai/glm-5.3"
    finally:
        router.close()


def test_provider_without_key_has_no_candidates():
    router = Router(Config(model="glm-5.3", provider="zai"))
    try:
        assert router.preview("glm-5.3", "zai") == []
    finally:
        router.close()


def test_unknown_provider_raises():
    router = Router(Config())
    try:
        with pytest.raises(ConfigError):
            router.resolve_candidates("auto", "unknown")
    finally:
        router.close()


def test_complete_falls_back_after_rate_limit():
    config = Config(model="auto", free_only=True, fallback=True)
    clients = {"kilo": FailOnceClient()}
    router = Router(config, clients=clients)
    try:
        completion = router.complete([{"role": "user", "content": "hi"}])
    finally:
        router.close()
    assert completion.provider == "kilo"
    assert clients["kilo"].calls == 2
    assert router.last is completion


def test_complete_reports_all_failures():
    config = Config(model="auto", free_only=True, fallback=True)
    clients = {"kilo": FakeClient(error=RateLimitError("quota", retryable=True))}
    router = Router(config, clients=clients)
    try:
        with pytest.raises(Exception) as exc_info:
            router.complete([{"role": "user", "content": "hi"}])
    finally:
        router.close()
    assert "kilo/kilo-auto/free" in str(exc_info.value)
    assert "kilo/cohere/north-mini-code:free" in str(exc_info.value)


def test_auto_router_prefers_coding_models_for_code_tasks():
    router = Router(Config(model="auto", free_only=True))
    try:
        candidates = router.resolve_candidates("auto")
        ranked = router._rank_auto_candidates(
            candidates,
            [{"role": "user", "content": "Code ce projet Python, corrige les bugs et ajoute des tests."}],
        )
        assert ranked[0][0].name == "kilo"
        assert ranked[0][1].id == "cohere/north-mini-code:free"
    finally:
        router.close()


def test_auto_router_prefers_fast_model_for_simple_requests():
    router = Router(Config(model="auto", free_only=True))
    try:
        candidates = router.resolve_candidates("auto")
        ranked = router._rank_auto_candidates(
            candidates,
            [{"role": "user", "content": "Salut, presente-toi en une phrase."}],
        )
        assert ranked[0][0].name == "kilo"
        assert ranked[0][1].id == "nvidia/nemotron-3.5-lightning:free"
    finally:
        router.close()


def test_context_window_uses_candidates():
    router = Router(Config(model="auto"))
    try:
        assert 32_000 <= router.context_window("auto") <= 256_000
    finally:
        router.close()


def test_vision_filter_rejects_text_only_models():
    from zerocode.types import ModelSpec, ProviderSpec

    spec = ProviderSpec(
        name="demo",
        label="Demo",
        base_url="https://example.com/v1",
        api_key_envs=(),
        keyless=True,
        models=(
            ModelSpec("texte", "Texte", context=1_000),
            ModelSpec("vision", "Vision", context=1_000, vision=True),
        ),
    )
    router = Router(Config(model="texte", provider="demo"), providers={"demo": spec})
    try:
        assert router.resolve_candidates("vision", "demo", needs_vision=True)[0][1].id == "vision"
        with pytest.raises(ConfigError) as exc_info:
            router.resolve_candidates("texte", "demo", needs_vision=True)
        assert "images" in str(exc_info.value)
    finally:
        router.close()

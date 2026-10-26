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


def test_complete_falls_back_after_rate_limit(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    config = Config(model="auto", free_only=True, fallback=True)
    clients = {
        "kilo": FakeClient(error=RateLimitError("quota", retryable=True, retry_after=30)),
        "nvidia": FakeClient(provider="nvidia"),
    }
    router = Router(config, clients=clients)
    try:
        completion = router.complete([{"role": "user", "content": "hi"}])
    finally:
        router.close()
    assert completion.provider == "nvidia"
    assert clients["kilo"].calls == 1
    assert clients["nvidia"].calls == 1
    assert router.last is completion


def test_complete_reports_all_failures(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    config = Config(model="auto", free_only=True, fallback=True)
    clients = {
        "kilo": FakeClient(error=RateLimitError("quota", retryable=True)),
        "nvidia": FakeClient(error=ProviderError("down", retryable=True)),
    }
    router = Router(config, clients=clients)
    try:
        with pytest.raises(Exception) as exc_info:
            router.complete([{"role": "user", "content": "hi"}])
    finally:
        router.close()
    assert "kilo/kilo-auto/free" in str(exc_info.value)
    assert "nvidia" in str(exc_info.value)


def test_context_window_uses_candidates():
    router = Router(Config(model="auto"))
    try:
        assert 32_000 <= router.context_window("auto") <= 256_000
    finally:
        router.close()

from __future__ import annotations

import json

import httpx
import pytest

from zerocode.catalog import PROVIDERS
from zerocode.config import Config
from zerocode.errors import AuthError
from zerocode.providers import OpenAICompatibleClient
from zerocode.types import StreamCallbacks


def sse(*payloads: dict | str) -> bytes:
    lines = []
    for payload in payloads:
        if payload == "[DONE]":
            lines.append("data: [DONE]")
        else:
            lines.append("data: " + json.dumps(payload))
    return ("\n\n".join(lines) + "\n\n").encode()


def make_client(handler):
    return OpenAICompatibleClient(
        Config(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_stream_content_tool_call_and_usage(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    provider = PROVIDERS["nvidia"]
    model = provider.model("z-ai/glm-5.3-flash")
    assert model is not None
    seen = {"body": None}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                {"choices": [{"delta": {"content": "Bon"}}]},
                {"choices": [{"delta": {"content": "jour"}}]},
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "function": {
                                            "name": "read",
                                            "arguments": '{"path": "README.md"}',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 4,
                        "total_tokens": 14,
                    },
                },
                "[DONE]",
            ),
        )

    text: list[str] = []
    tool_calls = []
    client = make_client(handler)
    try:
        completion = client.stream(
            provider,
            model,
            [{"role": "user", "content": "salut"}],
            callbacks=StreamCallbacks(
                on_text=text.append,
                on_tool_call=tool_calls.append,
            ),
        )
    finally:
        client.close()

    assert completion.content == "Bonjour"
    assert "".join(text) == "Bonjour"
    assert completion.finish_reason == "tool_calls"
    assert completion.tool_calls[0].name == "read"
    assert completion.tool_calls[0].arguments == {"path": "README.md"}
    assert tool_calls[0].id == "call_1"
    assert completion.usage.total_tokens == 14
    assert completion.usage.estimated is False
    assert seen["body"]["model"] == model.api_id
    assert seen["body"]["stream"] is True


def test_missing_key_raises_auth_error(monkeypatch):
    provider = PROVIDERS["nvidia"]
    model = provider.model("z-ai/glm-5.3-flash")
    assert model is not None
    client = make_client(lambda request: httpx.Response(500))
    try:
        with pytest.raises(AuthError):
            client.stream(provider, model, [{"role": "user", "content": "salut"}])
    finally:
        client.close()


def test_auth_error_from_http_status(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "bad-key")
    provider = PROVIDERS["nvidia"]
    model = provider.model("z-ai/glm-5.3-flash")
    assert model is not None
    client = make_client(
        lambda request: httpx.Response(
            401,
            json={"error": {"message": "invalid key"}},
        )
    )
    try:
        with pytest.raises(AuthError) as exc_info:
            client.stream(provider, model, [{"role": "user", "content": "salut"}])
    finally:
        client.close()
    assert "invalid key" in str(exc_info.value)


def test_body_is_sanitized_once_after_parameter_error(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    provider = PROVIDERS["nvidia"]
    model = provider.model("z-ai/glm-5.3-flash")
    assert model is not None
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "max_completion_tokens is required, max_tokens is unsupported"
                    }
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                {"choices": [{"delta": {"content": "OK"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                "[DONE]",
            ),
        )

    client = make_client(handler)
    try:
        completion = client.stream(provider, model, [{"role": "user", "content": "salut"}])
    finally:
        client.close()

    assert completion.content == "OK"
    assert len(requests) == 2
    assert "max_tokens" in requests[0]
    assert "max_tokens" not in requests[1]
    assert "max_completion_tokens" in requests[1]


def test_keyless_provider_does_not_require_key():
    provider = PROVIDERS["kilo"]
    model = provider.model("kilo-auto/free")
    assert model is not None

    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                {"choices": [{"delta": {"content": "ok"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                "[DONE]",
            ),
        )

    client = make_client(handler)
    try:
        completion = client.stream(provider, model, [{"role": "user", "content": "salut"}])
    finally:
        client.close()
    assert completion.content == "ok"

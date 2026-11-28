from __future__ import annotations

import json

import httpx
import pytest

from zerocode import cloud_client
from zerocode.config import Config
from zerocode.errors import ProviderError
from zerocode.types import StreamCallbacks


def test_cloud_url_requires_https_except_local_development() -> None:
    assert cloud_client._validate_url("https://cloud.example/") == "https://cloud.example"
    assert cloud_client._validate_url("http://localhost:8000") == "http://localhost:8000"
    with pytest.raises(Exception):
        cloud_client._validate_url("http://cloud.example")
    with pytest.raises(Exception):
        cloud_client._validate_url("https://user:password@cloud.example")


def test_cloud_router_streams_text_and_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = {
        "mode": "cloud",
        "base_url": "https://cloud.example",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
    }
    monkeypatch.setattr(cloud_client, "load_cloud_auth", lambda: dict(auth))
    original_client = httpx.Client
    received: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/client/config":
            return httpx.Response(
                200,
                json={
                    "config_version": 1,
                    "maintenance_mode": False,
                    "feature_flags": {"cloud_ai": True},
                    "models": [{"alias": "auto"}],
                },
                request=request,
            )
        if request.url.path == "/v1/chat/completions":
            payload = json.loads(request.content)
            received.append(payload)
            assert payload["stream"] is True
            assert payload["stream_options"] == {"include_usage": True}
            events = [
                {
                    "model": "cloud-model-alias",
                    "choices": [{"delta": {"content": "Bonjour"}, "finish_reason": None}],
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_01",
                                        "function": {
                                            "name": "read",
                                            "arguments": "{\"path\":\"README.md\"}",
                                        },
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
                },
            ]
            body = "".join("data: " + json.dumps(item) + "\n\n" for item in events) + "data: [DONE]\n\n"
            return httpx.Response(
                200,
                content=body.encode(),
                headers={"Content-Type": "text/event-stream", "X-ZeroCode-Task": "coding"},
                request=request,
            )
        return httpx.Response(404, request=request)

    client = original_client(
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(30, connect=5),
        follow_redirects=False,
    )
    monkeypatch.setattr(cloud_client.httpx, "Client", lambda *args, **kwargs: client)
    streamed: list[str] = []
    router = cloud_client.CloudRouter(Config())
    try:
        result = router.complete(
            [{"role": "user", "content": "fix the code"}],
            [{"type": "function", "function": {"name": "read"}}],
            callbacks=StreamCallbacks(on_text=streamed.append),
        )
    finally:
        router.close()

    assert result.content == "Bonjour"
    assert result.tool_calls[0].name == "read"
    assert result.tool_calls[0].arguments == {"path": "README.md"}
    assert result.usage.total_tokens == 16
    assert router.last_task == "coding"
    assert streamed == ["Bonjour"]
    assert received[0]["tools"]


def test_cloud_maintenance_policy_blocks_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = {
        "mode": "cloud",
        "base_url": "https://cloud.example",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
    }
    monkeypatch.setattr(cloud_client, "load_cloud_auth", lambda: dict(auth))
    original_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "maintenance_mode": True,
                "feature_flags": {"cloud_ai": True},
                "models": [],
            },
            request=request,
        )

    client = original_client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(cloud_client.httpx, "Client", lambda *args, **kwargs: client)
    router = cloud_client.CloudRouter(Config())
    try:
        with pytest.raises(ProviderError, match="maintenance"):
            router.complete([{"role": "user", "content": "hello"}])
    finally:
        router.close()

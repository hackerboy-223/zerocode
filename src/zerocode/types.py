from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

FREE_TIERS = frozenset({"free", "trial", "local"})


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    label: str
    context: int = 128_000
    max_output: int = 8_192
    tier: str = "free"
    tools: bool = True
    reasoning: bool = False
    notes: str = ""
    upstream_id: str | None = None

    @property
    def api_id(self) -> str:
        return self.upstream_id or self.id

    @property
    def is_free(self) -> bool:
        return self.tier in FREE_TIERS


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    name: str
    label: str
    base_url: str
    models: tuple[ModelSpec, ...]
    api_key_envs: tuple[str, ...] = ()
    signup_url: str = ""
    docs_url: str = ""
    keyless: bool = False
    enabled_by_default: bool = True
    headers: tuple[tuple[str, str], ...] = ()
    notes: str = ""

    def model(self, model_id: str) -> ModelSpec | None:
        for spec in self.models:
            if model_id in (spec.id, spec.api_id):
                return spec
        return None

    @property
    def requires_key(self) -> bool:
        return not self.keyless and bool(self.api_key_envs)

    @property
    def free_models(self) -> tuple[ModelSpec, ...]:
        return tuple(spec for spec in self.models if spec.is_free)


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0
    estimated: bool = False

    def add(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        self.requests += other.requests
        self.estimated = self.estimated or other.estimated

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "requests": self.requests,
            "estimated": self.estimated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Usage:
        data = data or {}
        return cls(
            prompt_tokens=int(data.get("prompt_tokens", 0) or 0),
            completion_tokens=int(data.get("completion_tokens", 0) or 0),
            total_tokens=int(data.get("total_tokens", 0) or 0),
            requests=int(data.get("requests", 0) or 0),
            estimated=bool(data.get("estimated", False)),
        )


@dataclass(slots=True)
class Completion:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    provider: str = ""
    model: str = ""
    usage: Usage = field(default_factory=Usage)


@dataclass(slots=True)
class StreamCallbacks:
    on_text: Callable[[str], None] | None = None
    on_reasoning: Callable[[str], None] | None = None
    on_tool_call: Callable[[ToolCall], None] | None = None

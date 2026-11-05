from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

import httpx

from .catalog import PROVIDERS
from .config import Config, load_key_store, validate_config
from .errors import AuthError, ProviderError, RateLimitError
from .tokens import estimate_messages, estimate_tokens
from .types import Completion, ModelSpec, ProviderSpec, StreamCallbacks, ToolCall, Usage
from .version import __version__

DEFAULT_TIMEOUT = httpx.Timeout(connect=15.0, read=600.0, write=30.0, pool=15.0)
OPTIONAL_BODY_KEYS = (
    "stream_options",
    "reasoning_effort",
    "thinking",
    "temperature",
    "tool_choice",
    "max_tokens",
)


def resolve_api_key(provider: ProviderSpec, config: Config | None = None) -> str | None:
    for env_name in provider.api_key_envs:
        value = os.environ.get(env_name)
        if value and value.strip():
            return value.strip()
    store = load_key_store()
    for name in (provider.name, *provider.api_key_envs):
        value = store.get(name)
        if value:
            return value
    return None


def provider_enabled(provider: ProviderSpec, config: Config) -> bool:
    override = config.provider_config(provider.name)
    if override.get("enabled") is False:
        return False
    if override.get("enabled") is True:
        return True
    if provider.enabled_by_default:
        return True
    return bool(provider.name == "ollama" and os.environ.get("OLLAMA_BASE_URL"))


def provider_available(provider: ProviderSpec, config: Config) -> bool:
    if not provider_enabled(provider, config):
        return False
    if provider.keyless:
        return True
    return resolve_api_key(provider, config) is not None


def applied_providers(config: Config) -> dict[str, ProviderSpec]:
    # Validate even directly constructed Config objects before attaching API credentials.
    validate_config(config)
    ollama_env = os.environ.get("OLLAMA_BASE_URL")
    if ollama_env:
        overrides = dict(config.providers)
        overrides["ollama"] = {
            **config.provider_config("ollama"),
            "base_url": ollama_env,
        }
        validate_config(replace(config, providers=overrides))
    result: dict[str, ProviderSpec] = {}
    for name, provider in PROVIDERS.items():
        override = config.provider_config(name)
        base_url = override.get("base_url")
        if name == "ollama" and os.environ.get("OLLAMA_BASE_URL"):
            base_url = os.environ["OLLAMA_BASE_URL"]
        if base_url:
            provider = replace(provider, base_url=base_url)
        result[name] = provider
    return result


class OpenAICompatibleClient:
    """Client synchrone pour les API qui suivent le protocole OpenAI."""

    def __init__(self, config: Config, *, http_client: httpx.Client | None = None) -> None:
        self.config = config
        if http_client is not None:
            # Callers injecting a client cannot silently re-enable credential-bearing redirects.
            http_client.follow_redirects = False
        self._http = http_client or httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )

    def close(self) -> None:
        self._http.close()

    def stream(
        self,
        provider: ProviderSpec,
        model: ModelSpec,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        callbacks: StreamCallbacks | None = None,
    ) -> Completion:
        callbacks = callbacks or StreamCallbacks()
        key = resolve_api_key(provider, self.config)
        if provider.requires_key and not key:
            envs = ", ".join(provider.api_key_envs)
            raise AuthError(
                f"Cle API absente. Definis {envs} ou lance `zerocode setup`.",
                provider=provider.name,
                model=model.id,
            )
        body = self._build_body(provider, model, messages, tools)
        return self._request(
            provider,
            model,
            messages,
            body,
            callbacks,
            allow_sanitize=True,
        )

    def _build_body(
        self,
        provider: ProviderSpec,
        model: ModelSpec,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model.api_id,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": self.config.temperature,
            "max_tokens": min(self.config.max_tokens, model.max_output),
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        api_id = model.api_id.lower()
        if model.reasoning and any(
            marker in api_id
            for marker in ("glm-4.6", "glm-4.7", "glm-5", "glm-5.3")
        ):
            body["thinking"] = {"type": "enabled"}
            if "glm-5" in api_id:
                body["reasoning_effort"] = self.config.reasoning_effort
        elif self.config.show_reasoning and model.reasoning and any(
            marker in api_id
            for marker in ("deepseek-r1", "qwq", "o1", "o3", "r1")
        ):
            body["reasoning_effort"] = self.config.reasoning_effort
        return body

    def _headers(self, provider: ProviderSpec) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": f"zerocode/{__version__}",
        }
        key = resolve_api_key(provider, self.config)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        for name, value in provider.headers:
            headers[name] = value.replace("zerocode/0.1.0", f"zerocode/{__version__}")
        return headers

    def _request(
        self,
        provider: ProviderSpec,
        model: ModelSpec,
        messages: list[dict[str, Any]],
        body: dict[str, Any],
        callbacks: StreamCallbacks,
        *,
        allow_sanitize: bool,
        allow_retry: bool = True,
    ) -> Completion:
        url = f"{provider.base_url.rstrip('/')}/chat/completions"
        try:
            with self._http.stream(
                "POST",
                url,
                headers=self._headers(provider),
                json=body,
            ) as response:
                if response.status_code >= 300:
                    raw = response.read()
                    text = raw.decode("utf-8", errors="replace")
                    sanitized = (
                        self._sanitize_body(body, response.status_code, text)
                        if allow_sanitize
                        else None
                    )
                    if sanitized is not None:
                        return self._request(
                            provider,
                            model,
                            messages,
                            sanitized,
                            callbacks,
                            allow_sanitize=False,
                            allow_retry=allow_retry,
                        )
                    if allow_retry and response.status_code in (502, 503, 504):
                        time.sleep(0.2)
                        return self._request(
                            provider,
                            model,
                            messages,
                            body,
                            callbacks,
                            allow_sanitize=allow_sanitize,
                            allow_retry=False,
                        )
                    raise self._http_error(provider, model, response, text)
                return self._consume(provider, model, messages, response, callbacks)
        except (AuthError, ProviderError):
            raise
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Delai depasse pendant la reponse du fournisseur.",
                provider=provider.name,
                model=model.id,
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            if allow_retry:
                time.sleep(0.2)
                return self._request(
                    provider,
                    model,
                    messages,
                    body,
                    callbacks,
                    allow_sanitize=allow_sanitize,
                    allow_retry=False,
                )
            raise ProviderError(
                f"Erreur reseau: {exc.__class__.__name__}.",
                provider=provider.name,
                model=model.id,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Erreur reseau: {exc.__class__.__name__}.",
                provider=provider.name,
                model=model.id,
                retryable=True,
            ) from exc

    def _http_error(
        self,
        provider: ProviderSpec,
        model: ModelSpec,
        response: httpx.Response,
        text: str,
    ) -> ProviderError:
        message = _error_message(text)
        retry_after = _retry_after(response.headers)
        status = response.status_code
        if status in (401, 403):
            return AuthError(
                message or "Cle refusee.",
                provider=provider.name,
                model=model.id,
                status=status,
            )
        if status == 429:
            return RateLimitError(
                message or "Quota atteint.",
                provider=provider.name,
                model=model.id,
                status=status,
                retryable=True,
                retry_after=retry_after,
            )
        retryable = status in (408, 409, 425) or status >= 500
        return ProviderError(
            message or "Requete refusee.",
            provider=provider.name,
            model=model.id,
            status=status,
            retryable=retryable,
            retry_after=retry_after,
        )

    def _sanitize_body(
        self,
        body: dict[str, Any],
        status: int,
        text: str,
    ) -> dict[str, Any] | None:
        if status not in (400, 404, 422):
            return None
        lowered = text.lower()
        new_body = dict(body)
        changed = False
        if "max_completion_tokens" in lowered and "max_tokens" in new_body:
            new_body["max_completion_tokens"] = new_body.pop("max_tokens")
            changed = True
        for key in OPTIONAL_BODY_KEYS:
            if key in new_body and key in lowered:
                new_body.pop(key)
                changed = True
        return new_body if changed else None

    def _consume(
        self,
        provider: ProviderSpec,
        model: ModelSpec,
        messages: list[dict[str, Any]],
        response: httpx.Response,
        callbacks: StreamCallbacks,
    ) -> Completion:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_parts: dict[int, dict[str, str]] = {}
        usage: Usage | None = None
        finish_reason = "stop"
        think_parser = _ThinkStreamParser()

        def _emit_text(chunk_text: str) -> None:
            if not chunk_text:
                return
            content_parts.append(chunk_text)
            if callbacks.on_text:
                callbacks.on_text(chunk_text)

        def _emit_reasoning(chunk_reasoning: str) -> None:
            if not chunk_reasoning:
                return
            reasoning_parts.append(chunk_reasoning)
            if callbacks.on_reasoning:
                callbacks.on_reasoning(chunk_reasoning)

        for raw_line in response.iter_lines():
            line = raw_line if isinstance(raw_line, str) else raw_line.decode("utf-8", "replace")
            if not line:
                continue
            stripped = line.strip()
            if stripped.startswith(":") or stripped.startswith("event:"):
                continue
            payload = stripped[5:].strip() if stripped.startswith("data:") else stripped
            if not payload or payload == "[DONE]":
                if payload == "[DONE]":
                    break
                continue
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if not isinstance(chunk, dict):
                continue
            if chunk.get("error"):
                message = _error_message(json.dumps(chunk))
                raise ProviderError(
                    message or "Erreur renvoyee dans le flux.",
                    provider=provider.name,
                    model=model.id,
                    retryable=True,
                )
            if isinstance(chunk.get("usage"), dict):
                usage = _usage_from_openai(chunk["usage"])
            for choice in chunk.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    delta = choice.get("message") if isinstance(choice.get("message"), dict) else {}
                text = _delta_text(delta.get("content"))
                if text:
                    for is_reasoning, piece in think_parser.feed(text):
                        if is_reasoning:
                            _emit_reasoning(piece)
                        else:
                            _emit_text(piece)
                reasoning = _reasoning_text(delta)
                if reasoning:
                    _emit_reasoning(reasoning)
                self._collect_tool_deltas(delta, tool_parts)
                if choice.get("finish_reason"):
                    finish_reason = str(choice["finish_reason"])

        for is_reasoning, piece in think_parser.flush():
            if is_reasoning:
                _emit_reasoning(piece)
            else:
                _emit_text(piece)

        tool_calls: list[ToolCall] = []
        for index in sorted(tool_parts):
            item = tool_parts[index]
            name = item.get("name", "").strip()
            if not name:
                continue
            raw_arguments = item.get("arguments", "").strip()
            arguments: dict[str, Any]
            if raw_arguments:
                try:
                    parsed = json.loads(raw_arguments)
                    arguments = parsed if isinstance(parsed, dict) else {"value": parsed}
                except json.JSONDecodeError:
                    arguments = {"__raw__": raw_arguments}
            else:
                arguments = {}
            call = ToolCall(
                id=item.get("id") or f"call_{index + 1}",
                name=name,
                arguments=arguments,
            )
            tool_calls.append(call)
            if callbacks.on_tool_call:
                callbacks.on_tool_call(call)

        content = "".join(content_parts)
        reasoning = "".join(reasoning_parts)
        if usage is None or (usage.total_tokens == 0 and usage.prompt_tokens == 0):
            prompt_tokens = estimate_messages(messages)
            completion_tokens = estimate_tokens(content + reasoning)
            usage = Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                requests=1,
                estimated=True,
            )
        else:
            usage.requests = 1
            if usage.total_tokens == 0:
                usage.total_tokens = usage.prompt_tokens + usage.completion_tokens

        if tool_calls and finish_reason in {"stop", "null", ""}:
            finish_reason = "tool_calls"
        return Completion(
            content=content,
            reasoning=reasoning,
            tool_calls=tool_calls,
            finish_reason=finish_reason or "stop",
            provider=provider.name,
            model=model.id,
            usage=usage,
        )

    @staticmethod
    def _collect_tool_deltas(
        delta: dict[str, Any],
        tool_parts: dict[int, dict[str, str]],
    ) -> None:
        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            for position, raw_call in enumerate(tool_calls):
                if not isinstance(raw_call, dict):
                    continue
                index = raw_call.get("index", position)
                if not isinstance(index, int):
                    index = position
                item = tool_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
                call_id = raw_call.get("id")
                if call_id:
                    item["id"] = str(call_id)
                function = raw_call.get("function")
                if isinstance(function, dict):
                    name = function.get("name")
                    if name:
                        item["name"] = str(name)
                    arguments = function.get("arguments")
                    if arguments is not None:
                        item["arguments"] += str(arguments)

        legacy = delta.get("function_call")
        if isinstance(legacy, dict):
            item = tool_parts.setdefault(0, {"id": "", "name": "", "arguments": ""})
            if legacy.get("name"):
                item["name"] = str(legacy["name"])
            if legacy.get("arguments") is not None:
                item["arguments"] += str(legacy["arguments"])


def build_clients(config: Config, providers: dict[str, ProviderSpec] | None = None) -> dict[str, OpenAICompatibleClient]:
    providers = providers or applied_providers(config)
    client = OpenAICompatibleClient(config)
    return {name: client for name in providers}


def fetch_models(
    provider: ProviderSpec,
    config: Config,
    *,
    timeout: float = 25.0,
) -> list[dict[str, Any]]:
    headers = {"User-Agent": f"zerocode/{__version__}", "Accept": "application/json"}
    for name, value in provider.headers:
        headers[name] = value.replace("zerocode/0.1.0", f"zerocode/{__version__}")
    key = resolve_api_key(provider, config)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    url = f"{provider.base_url.rstrip('/')}/models"
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        response = client.get(url, headers=headers)
        if response.status_code >= 300:
            raise ProviderError(
                _error_message(response.text) or "Impossible de lister les modeles.",
                provider=provider.name,
                status=response.status_code,
            )
        data = response.json()
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def discover_free_models(
    config: Config,
    provider_names: Iterable[str] = ("kilo", "openrouter", "opencode-zen"),
) -> list[dict[str, Any]]:
    providers = applied_providers(config)
    result: list[dict[str, Any]] = []
    for name in provider_names:
        provider = providers.get(name)
        if provider is None or not provider_available(provider, config):
            continue
        try:
            rows = fetch_models(provider, config)
        except (ProviderError, httpx.HTTPError, ValueError):
            continue
        for row in rows:
            model_id = str(row.get("id") or row.get("name") or "")
            if not model_id:
                continue
            pricing = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
            prompt = _price_zero(pricing.get("prompt"))
            completion = _price_zero(pricing.get("completion"))
            has_pricing = "prompt" in pricing and "completion" in pricing
            free_id = (
                model_id.endswith(":free")
                or model_id.endswith("-free")
                or "auto/free" in model_id
            )
            if not (free_id or (has_pricing and prompt and completion)):
                continue
            result.append(
                {
                    "provider": name,
                    "id": model_id,
                    "context": row.get("context_length") or row.get("context") or 0,
                    "pricing": pricing,
                }
            )
    return result


def _price_zero(value: Any) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def _delta_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _reasoning_text(delta: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("reasoning_content", "reasoning", "thinking"):
        value = delta.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            text = value.get("text") or value.get("content")
            if isinstance(text, str):
                parts.append(text)
    details = delta.get("reasoning_details")
    if isinstance(details, list):
        for item in details:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
    return "".join(parts)


def _usage_from_openai(data: dict[str, Any]) -> Usage:
    prompt = _as_int(data.get("prompt_tokens"))
    completion = _as_int(data.get("completion_tokens"))
    total = _as_int(data.get("total_tokens"))
    if total == 0:
        total = prompt + completion
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        requests=1,
        estimated=False,
    )


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _error_message(text: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return " ".join(text.split())[:500]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail") or error.get("type")
            if message:
                return str(message)[:500]
        if isinstance(error, str):
            return error[:500]
        message = data.get("message") or data.get("detail")
        if message:
            return str(message)[:500]
    return " ".join(text.split())[:500]


def _retry_after(headers: httpx.Headers) -> float | None:
    for name in ("retry-after", "x-ratelimit-reset-requests"):
        value = headers.get(name)
        if not value:
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return None


class _ThinkStreamParser:
    """Extrait les blocs <think>...</think> et <thinking>...</thinking> dans un flux SSE."""

    _OPEN_TAGS = ("<thinking>", "<think>")
    _CLOSE_TAGS = ("</thinking>", "</think>")

    def __init__(self) -> None:
        self._in_think = False
        self._buffer = ""
        self._strip_leading_ws = False

    def feed(self, chunk: str) -> list[tuple[bool, str]]:
        if not chunk:
            return []
        self._buffer += chunk
        output: list[tuple[bool, str]] = []
        while self._buffer:
            if not self._in_think:
                idx, tag = self._find_tag(self._buffer, self._OPEN_TAGS)
                if idx != -1:
                    before = self._buffer[:idx]
                    if before:
                        output.append((False, self._clean_piece(before)))
                    self._buffer = self._buffer[idx + len(tag) :]
                    self._in_think = True
                    self._strip_leading_ws = True
                    continue
                hold = self._partial_suffix_len(self._buffer, self._OPEN_TAGS)
                emit = self._buffer[: len(self._buffer) - hold] if hold else self._buffer
                self._buffer = self._buffer[len(self._buffer) - hold :] if hold else ""
                if emit:
                    cleaned = self._clean_piece(emit)
                    if cleaned:
                        output.append((False, cleaned))
                break
            else:
                idx, tag = self._find_tag(self._buffer, self._CLOSE_TAGS)
                if idx != -1:
                    inside = self._buffer[:idx]
                    if inside:
                        cleaned = self._clean_piece(inside)
                        if cleaned:
                            output.append((True, cleaned))
                    self._buffer = self._buffer[idx + len(tag) :]
                    self._in_think = False
                    self._strip_leading_ws = True
                    continue
                hold = self._partial_suffix_len(self._buffer, self._CLOSE_TAGS)
                emit = self._buffer[: len(self._buffer) - hold] if hold else self._buffer
                self._buffer = self._buffer[len(self._buffer) - hold :] if hold else ""
                if emit:
                    cleaned = self._clean_piece(emit)
                    if cleaned:
                        output.append((True, cleaned))
                break
        return output

    def flush(self) -> list[tuple[bool, str]]:
        if not self._buffer:
            return []
        remaining = self._clean_piece(self._buffer)
        self._buffer = ""
        if not remaining:
            return []
        return [(self._in_think, remaining)]

    def _clean_piece(self, text: str) -> str:
        if not self._strip_leading_ws:
            return text
        stripped = text.lstrip("\r\n ")
        if stripped:
            self._strip_leading_ws = False
        return stripped

    @staticmethod
    def _find_tag(buffer: str, tags: tuple[str, ...]) -> tuple[int, str]:
        lower = buffer.lower()
        best_idx = -1
        best_tag = ""
        for tag in tags:
            pos = lower.find(tag)
            if pos != -1 and (best_idx == -1 or pos < best_idx):
                best_idx = pos
                best_tag = tag
        return best_idx, best_tag

    @staticmethod
    def _partial_suffix_len(buffer: str, tags: tuple[str, ...]) -> int:
        lower = buffer.lower()
        max_hold = 0
        for tag in tags:
            for length in range(1, len(tag)):
                if lower.endswith(tag[:length]) and length > max_hold:
                    max_hold = length
        return max_hold

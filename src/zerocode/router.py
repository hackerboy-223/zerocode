from __future__ import annotations

import time
from typing import Any

from .catalog import AUTO_CHAIN, PROVIDERS, model_chain
from .config import Config
from .errors import AllProvidersFailed, AuthError, ConfigError, ProviderError, RateLimitError
from .providers import (
    applied_providers,
    build_clients,
    provider_enabled,
    resolve_api_key,
)
from .types import Completion, ModelSpec, ProviderSpec, StreamCallbacks


class Router:
    """Choisit un modele gratuit disponible et bascule en cas d'echec."""

    def __init__(
        self,
        config: Config,
        *,
        clients: dict[str, Any] | None = None,
        ui: Any | None = None,
        providers: dict[str, ProviderSpec] | None = None,
    ) -> None:
        self.config = config
        self.providers = providers or applied_providers(config)
        self.clients = clients or build_clients(config, self.providers)
        self.ui = ui
        self.last: Completion | None = None
        self.last_provider: ProviderSpec | None = None
        self.last_model: ModelSpec | None = None
        self._cooldown: dict[str, float] = {}

    def close(self) -> None:
        seen: set[int] = set()
        for client in self.clients.values():
            if id(client) in seen:
                continue
            seen.add(id(client))
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def resolve_candidates(
        self,
        model: str | None = None,
        provider: str | None = None,
        *,
        needs_tools: bool = True,
    ) -> list[tuple[ProviderSpec, ModelSpec]]:
        requested = (model or self.config.model).strip()
        wanted_provider = (provider or self.config.provider or "").strip() or None

        if ":" in requested:
            prefix, rest = requested.split(":", 1)
            if prefix in self.providers:
                wanted_provider = prefix
                requested = rest

        chain = model_chain(requested)
        raw: list[tuple[ProviderSpec, ModelSpec]] = []

        if chain:
            for provider_name, model_id in chain:
                spec = self.providers.get(provider_name)
                if spec is None:
                    continue
                model_spec = spec.model(model_id)
                if model_spec is not None:
                    raw.append((spec, model_spec))
        else:
            raw.extend(self._exact_matches(requested))

        if wanted_provider is not None:
            provider_spec = self.providers.get(wanted_provider)
            if provider_spec is None:
                raise ConfigError(f"Fournisseur inconnu: {wanted_provider}.")
            filtered = [
                (spec, model_spec)
                for spec, model_spec in raw
                if spec.name == wanted_provider
            ]
            if not filtered:
                exact = provider_spec.model(requested)
                if exact is not None:
                    filtered = [(provider_spec, exact)]
            if self.config.free_only:
                filtered = [
                    (spec, model_spec)
                    for spec, model_spec in filtered
                    if model_spec.is_free
                ]
                if not filtered:
                    free_models = [
                        item
                        for item in provider_spec.models
                        if item.is_free and (item.tools or not needs_tools)
                    ]
                    if free_models:
                        filtered = [(provider_spec, free_models[0])]
            elif not filtered:
                exact = provider_spec.model(requested)
                if exact is not None:
                    filtered = [(provider_spec, exact)]
                elif provider_spec.models:
                    filtered = [(provider_spec, provider_spec.models[0])]
            raw = filtered
        elif self.config.fallback:
            for provider_name, model_id in AUTO_CHAIN:
                spec = self.providers.get(provider_name)
                if spec is None:
                    continue
                model_spec = spec.model(model_id)
                if model_spec is not None:
                    raw.append((spec, model_spec))

        result: list[tuple[ProviderSpec, ModelSpec]] = []
        seen: set[tuple[str, str]] = set()
        for spec, model_spec in raw:
            key = (spec.name, model_spec.id)
            if key in seen:
                continue
            seen.add(key)
            if not self._provider_available(spec):
                continue
            if self.config.free_only and not model_spec.is_free:
                continue
            if needs_tools and not model_spec.tools:
                continue
            result.append((spec, model_spec))

        if not result:
            raise ConfigError(self._no_candidate_message(requested, wanted_provider))
        return result

    def preview(
        self,
        model: str | None = None,
        provider: str | None = None,
    ) -> list[str]:
        try:
            candidates = self.resolve_candidates(model, provider, needs_tools=True)
        except ConfigError:
            return []
        return [f"{spec.name}/{model_spec.id}" for spec, model_spec in candidates]

    def context_window(self, model: str | None = None) -> int:
        try:
            candidates = self.resolve_candidates(model, needs_tools=False)[:4]
        except ConfigError:
            return 128_000
        contexts = [model_spec.context for _, model_spec in candidates if model_spec.context > 0]
        if not contexts:
            return 128_000
        return max(32_000, min(contexts))

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        model: str | None = None,
        provider: str | None = None,
        callbacks: StreamCallbacks | None = None,
    ) -> Completion:
        callbacks = callbacks or StreamCallbacks()
        candidates = self.resolve_candidates(model, provider, needs_tools=bool(tools))
        failures: list[tuple[str, Exception]] = []

        for spec, model_spec in candidates:
            key = f"{spec.name}/{model_spec.id}"
            if self._is_cooling(key):
                continue
            client = self.clients.get(spec.name)
            if client is None:
                failures.append((key, ConfigError("Client indisponible.")))
                continue
            try:
                completion = client.stream(spec, model_spec, messages, tools, callbacks)
                self.last = completion
                self.last_provider = spec
                self.last_model = model_spec
                return completion
            except ProviderError as exc:
                self._set_cooldown(key, exc)
                failures.append((key, exc))
                self._warn(f"{key}: {self._short_error(exc)}")
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001 - on doit pouvoir basculer
                self._set_cooldown(key, ProviderError(str(exc), retryable=True))
                failures.append((key, exc))
                self._warn(f"{key}: {exc.__class__.__name__}: {exc}")

        if not failures:
            raise ConfigError(
                "Tous les candidats sont temporairement en indisponibilite (quota ou delai). "
                "Reessaie dans quelques minutes ou lance `zerocode doctor`."
            )
        raise AllProvidersFailed(failures)

    def _exact_matches(self, requested: str) -> list[tuple[ProviderSpec, ModelSpec]]:
        result: list[tuple[ProviderSpec, ModelSpec]] = []
        for spec in self.providers.values():
            model_spec = spec.model(requested)
            if model_spec is not None:
                result.append((spec, model_spec))
        if result:
            return result
        needle = requested.lower()
        for spec in self.providers.values():
            for model_spec in spec.models:
                if needle in model_spec.id.lower() or needle in model_spec.label.lower():
                    result.append((spec, model_spec))
        return result

    def _provider_available(self, spec: ProviderSpec) -> bool:
        if not provider_enabled(spec, self.config):
            return False
        if spec.keyless:
            return True
        return resolve_api_key(spec, self.config) is not None

    def _no_candidate_message(self, requested: str, provider: str | None) -> str:
        scope = f" chez {provider}" if provider else ""
        lines = [
            f"Aucun modele disponible pour {requested!r}{scope}.",
            "Verifie que le modele existe et qu'une cle gratuite est configuree.",
            "Commandes utiles:",
            "  zerocode models --free",
            "  zerocode setup",
        ]
        if self.config.free_only:
            lines.append("Le mode gratuit est actif (--no-free-only pour autoriser les modeles payants).")
        return "\n".join(lines)

    def _is_cooling(self, key: str) -> bool:
        until = self._cooldown.get(key)
        return bool(until and until > time.monotonic())

    def _set_cooldown(self, key: str, error: ProviderError) -> None:
        now = time.monotonic()
        if isinstance(error, RateLimitError):
            delay = error.retry_after or 180.0
            delay = max(30.0, min(delay, 900.0))
        elif isinstance(error, AuthError) or error.status == 404:
            delay = 3_600.0
        elif error.retryable:
            delay = 45.0
        else:
            delay = 300.0
        self._cooldown[key] = now + delay

    def _warn(self, message: str) -> None:
        if self.ui is not None:
            warn = getattr(self.ui, "warn", None)
            if callable(warn):
                warn(message)

    @staticmethod
    def _short_error(error: Exception) -> str:
        text = " ".join(str(error).split())
        return text[:220]


def default_chain(config: Config) -> list[str]:
    router = Router(config)
    try:
        return router.preview("auto")
    finally:
        router.close()


def all_provider_names() -> list[str]:
    return list(PROVIDERS)

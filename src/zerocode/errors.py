from __future__ import annotations

from collections.abc import Iterable


class ZeroCodeError(Exception):
    """Erreur de base, destinee a etre affichee sans trace technique."""


class ConfigError(ZeroCodeError):
    """Configuration invalide ou incomplete."""


class ToolError(ZeroCodeError):
    """Une action d'outil a echoue."""


class PermissionDenied(ToolError):
    """L'utilisateur ou la configuration a refuse une action."""


class ProviderError(ZeroCodeError):
    """Erreur renvoyee par un fournisseur de modele."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        model: str = "",
        status: int | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after

    def __str__(self) -> str:
        prefix = f"{self.provider}/{self.model}: " if self.provider or self.model else ""
        if self.status is not None:
            return f"{prefix}HTTP {self.status}: {super().__str__()}"
        return f"{prefix}{super().__str__()}"


class AuthError(ProviderError):
    """Cle absente, invalide ou refusee."""


class RateLimitError(ProviderError):
    """Quota ou limite de debit atteint."""


class AllProvidersFailed(ZeroCodeError):
    """Tous les candidats du routeur ont echoue."""

    def __init__(self, failures: Iterable[tuple[str, Exception]]) -> None:
        self.failures = list(failures)
        details = "\n".join(f"- {name}: {exc}" for name, exc in self.failures)
        super().__init__(
            "Aucun fournisseur disponible pour cette requete.\n"
            f"{details}\n"
            "Conseil: lance `zerocode doctor`, puis `zerocode setup` pour ajouter une cle gratuite."
        )

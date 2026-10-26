from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import PermissionDenied, ToolError
from ..types import ToolCall

Handler = Callable[[dict[str, Any], "ToolContext"], str]


@dataclass
class ToolContext:
    cwd: Path
    allow_outside: bool = False
    command_timeout: int = 120
    max_output_chars: int = 30_000
    todos: list[dict[str, Any]] = field(default_factory=list)

    def resolve_path(self, raw: str, *, for_write: bool = False) -> Path:
        text = str(raw or "").strip()
        if not text:
            raise ToolError("Le chemin est vide.")
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = self.cwd / path
        path = path.resolve()
        if not self.allow_outside:
            try:
                path.relative_to(self.cwd)
            except ValueError as exc:
                raise ToolError(
                    f"Chemin hors du repertoire de travail refuse: {path}. "
                    "Active allow_outside_cwd pour l'autoriser."
                ) from exc
        if for_write:
            if ".git" in path.parts:
                raise ToolError("Ecriture dans .git refusee.")
            if path.name in {"id_rsa", "id_ed25519"}:
                raise ToolError("Ecriture dans une cle privee refusee.")
        return path

    def display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.cwd))
        except ValueError:
            return str(path)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    approval: str = "ask"

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class PermissionManager:
    mode: str = "ask"
    interactive: bool = True

    def allow(self, tool: Tool, args: dict[str, Any], ui: Any | None = None) -> bool:
        if tool.approval == "never":
            return True
        if self.mode == "allow":
            return True
        if self.mode == "deny":
            return False
        if not self.interactive or ui is None:
            return False
        confirm = getattr(ui, "confirm_tool", None)
        if not callable(confirm):
            return False
        return bool(confirm(tool.name, args))


class ToolRegistry:
    def __init__(
        self,
        context: ToolContext,
        permissions: PermissionManager,
        ui: Any | None = None,
    ) -> None:
        self.context = context
        self.permissions = permissions
        self.ui = ui
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Outil deja enregistre: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    def execute(self, call: ToolCall) -> str:
        tool = self._tools.get(call.name)
        if tool is None:
            return f"ERREUR: outil inconnu '{call.name}'."
        try:
            _validate_arguments(tool.parameters, call.arguments)
        except ToolError as exc:
            return f"ERREUR: {exc}"
        if not self.permissions.allow(tool, call.arguments, self.ui):
            return "Action refusee par l'utilisateur."
        try:
            result = tool.handler(call.arguments, self.context)
        except PermissionDenied as exc:
            return f"Action refusee: {exc}"
        except ToolError as exc:
            return f"ERREUR: {exc}"
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - le modele doit voir l'erreur
            return f"ERREUR: {exc.__class__.__name__}: {exc}"
        if not isinstance(result, str):
            return f"ERREUR: l'outil {tool.name} a renvoye un type invalide."
        return result


def _validate_arguments(schema: dict[str, Any], args: dict[str, Any]) -> None:
    if not isinstance(args, dict):
        raise ToolError("Les arguments doivent etre un objet JSON.")
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    for name in required:
        if name not in args:
            raise ToolError(f"Argument obligatoire manquant: {name}.")
    allowed = set(properties)
    for name in args:
        if name not in allowed:
            raise ToolError(f"Argument inconnu: {name}.")
    for name, value in args.items():
        prop = properties.get(name) or {}
        expected = prop.get("type")
        if expected == "string" and not isinstance(value, str):
            raise ToolError(f"L'argument {name} doit etre une chaine.")
        if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            raise ToolError(f"L'argument {name} doit etre un entier.")
        if expected == "boolean" and not isinstance(value, bool):
            raise ToolError(f"L'argument {name} doit etre un booleen.")
        if expected == "array" and not isinstance(value, list):
            raise ToolError(f"L'argument {name} doit etre une liste.")
        if expected == "object" and not isinstance(value, dict):
            raise ToolError(f"L'argument {name} doit etre un objet.")

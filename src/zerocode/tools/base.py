from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import PermissionDenied, ToolError
from ..security import check_dangerous_command, redact_secrets
from ..types import ToolCall

Handler = Callable[[dict[str, Any], "ToolContext"], str]

SECRET_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")
SAFE_ENV_NAMES = {".env.example", ".env.sample", ".env.template", ".env.dist"}
FORCE_KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)


def is_secret_path(path: Path) -> bool:
    name = path.name.lower()
    if name in SAFE_ENV_NAMES:
        return False
    if name in SECRET_NAMES or name.startswith(".env."):
        return True
    if any(name.endswith(suffix) for suffix in SECRET_SUFFIXES):
        return True
    parts = {part.lower() for part in path.parts}
    return bool(parts & {".ssh", ".aws", ".gnupg"})


@dataclass
class ToolContext:
    cwd: Path
    allow_outside: bool = False
    command_timeout: int = 120
    max_output_chars: int = 30_000
    protect_secrets: bool = True
    allow_secrets: bool = False
    todos: list[dict[str, Any]] = field(default_factory=list)
    request_sudo_password: Callable[[str], str | None] | None = None
    show_diff: Callable[[str, str], None] | None = None
    checkpoint: Callable[[Path, str | None, str], None] | None = None
    stream_output: Callable[[str, str], None] | None = None
    _active_process: Any = field(default=None, repr=False, compare=False)
    _process_interrupted: bool = field(default=False, repr=False, compare=False)

    def attach_process(self, process: Any) -> None:
        self._active_process = process
        self._process_interrupted = False

    def detach_process(self, process: Any) -> None:
        if self._active_process is process:
            self._active_process = None

    def process_interrupted(self) -> bool:
        return self._process_interrupted

    def terminate_active_process(self, *, user: bool = True, grace: float = 2.0) -> None:
        process = self._active_process
        if process is None or process.poll() is not None:
            return
        if user:
            self._process_interrupted = True
        _signal_process_group(process, signal.SIGTERM)
        if grace > 0:
            threading.Thread(
                target=_force_kill_after,
                args=(process, grace),
                daemon=True,
            ).start()

    def kill_active_process(self) -> None:
        process = self._active_process
        if process is None or process.poll() is not None:
            return
        _signal_process_group(process, FORCE_KILL_SIGNAL)

    def check_secret(self, path: Path) -> None:
        if not self.protect_secrets or self.allow_secrets:
            return
        if is_secret_path(path):
            raise ToolError(
                f"Fichier de secrets protege: {self.display_path(path)}. "
                "Utilise --allow-secrets pour l'autoriser explicitement."
            )

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
            return path.resolve().relative_to(self.cwd).as_posix()
        except ValueError:
            return path.as_posix()


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


def _auto_approve(tool: Tool, args: dict[str, Any], context: ToolContext | None) -> bool:
    if context is None:
        return False
    if tool.name in {"write", "edit"}:
        try:
            path = context.resolve_path(str(args.get("path", "")), for_write=True)
            context.check_secret(path)
        except ToolError:
            return False
        if tool.name == "write":
            return not path.exists()
        return path.is_file()
    if tool.name == "bash":
        from .shell import is_safe_auto_command

        return is_safe_auto_command(str(args.get("command", "")), context)
    return False


@dataclass
class PermissionManager:
    mode: str = "ask"
    interactive: bool = True

    def allow(
        self,
        tool: Tool,
        args: dict[str, Any],
        ui: Any | None = None,
        context: ToolContext | None = None,
    ) -> bool:
        if tool.approval == "never":
            return True
        if self.mode == "allow":
            return True
        if self.mode == "deny":
            return False
        if tool.approval == "auto" and _auto_approve(tool, args, context):
            return True
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
        if ui is not None and hasattr(ui, "request_sudo_password"):
            context.request_sudo_password = ui.request_sudo_password
        if ui is not None and hasattr(ui, "show_diff"):
            context.show_diff = ui.show_diff
        if ui is not None and hasattr(ui, "stream_tool_output"):
            context.stream_output = ui.stream_tool_output
        self.read_only = False
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Outil deja enregistre: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        return [
            tool.schema()
            for tool in self._tools.values()
            if not self.read_only or tool.approval == "never"
        ]

    def names(self) -> list[str]:
        return list(self._tools)

    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    def execute(self, call: ToolCall) -> str:
        tool = self._tools.get(call.name)
        if tool is None:
            return f"ERREUR: outil inconnu '{call.name}'."
        if self.read_only and tool.approval != "never":
            return f"Action refusee: l'outil {call.name} est indisponible en mode plan (lecture seule)."
        try:
            _validate_arguments(tool.parameters, call.arguments)
        except ToolError as exc:
            return f"ERREUR: {exc}"
        if tool.name == "bash":
            blocked_reason = check_dangerous_command(str(call.arguments.get("command", "")))
            if blocked_reason is not None:
                return f"Action refusee (securite): {blocked_reason}"
        if not self.permissions.allow(tool, call.arguments, self.ui, self.context):
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
        if self.context.protect_secrets and not self.context.allow_secrets:
            result = redact_secrets(result)
        return result


def _signal_process_group(process: Any, sig: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        elif hasattr(os, "killpg"):
            os.killpg(process.pid, sig)
        elif sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except OSError:
        with contextlib.suppress(OSError):
            if sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()


def _force_kill_after(process: Any, grace: float) -> None:
    time.sleep(grace)
    if process.poll() is None:
        _signal_process_group(process, FORCE_KILL_SIGNAL)


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

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import re
import secrets
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

from .checkpoints import CheckpointStore
from .cloud_client import create_router
from .config import (
    delete_key,
    load_config,
    load_key_store,
    mask_key,
    save_hooks,
    save_mcp_servers,
    store_key,
    validate_config,
)
from .errors import ConfigError, ZeroCodeError
from .hooks import HookManager
from .mcp import MCPManager, register_mcp_tools
from .prompts import MAX_INSTRUCTIONS_CHARS, remember_project_instruction
from .providers import (
    applied_providers,
    build_clients,
    provider_available,
    provider_enabled,
)
from .router import Router
from .security import redact_secrets
from .session import SessionStore
from .skills import all_skills
from .tools import PermissionManager, ToolContext, build_registry
from .tools.subagent import SPECIALIST_ROLES, roles_catalog
from .types import Completion, Usage
from .version import __version__


class DesktopBridgeUI:
    """Pont JSONL entre l'agent Python et l'interface desktop locale."""

    interactive = True

    def __init__(self, stream: Any | None = None, *, request_timeout: float = 900.0) -> None:
        self.stream = stream or sys.stdout
        self.request_timeout = request_timeout
        self.show_reasoning = False
        self._context: ToolContext | None = None
        self._checkpoints: CheckpointStore | None = None
        self._session_id_getter: Any = None
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._interrupt = threading.Event()

    def bind_runtime(
        self,
        context: ToolContext,
        checkpoints: CheckpointStore | None = None,
        session_id_getter: Any = None,
    ) -> None:
        self._context = context
        self._checkpoints = checkpoints
        self._session_id_getter = session_id_getter

    @staticmethod
    def _redact_payload(value: Any) -> Any:
        """Masque les secrets connus avant toute exposition dans l'interface."""
        if isinstance(value, str):
            return redact_secrets(value)
        if isinstance(value, dict):
            return {key: DesktopBridgeUI._redact_payload(item) for key, item in value.items()}
        if isinstance(value, list):
            return [DesktopBridgeUI._redact_payload(item) for item in value]
        if isinstance(value, tuple):
            return [DesktopBridgeUI._redact_payload(item) for item in value]
        return value

    def emit(self, event: str, **data: Any) -> None:
        payload = self._redact_payload({"type": event, **data})
        with self._write_lock:
            self.stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
            self.stream.flush()

    def receive(self, message: dict[str, Any]) -> bool:
        """Réveille une demande d'autorisation en attente."""
        kind = message.get("type")
        request_id = str(message.get("request_id") or "")
        if not request_id:
            return False

        if kind == "permission_response":
            response: Any = {"allowed": message.get("allowed") is True}
        elif kind == "sudo_confirmation_response":
            response = {"allowed": message.get("allowed") is True}
        elif kind == "sudo_password_response":
            password = message.get("password")
            response = {"password": password if isinstance(password, str) else None}
        else:
            return False

        with self._pending_lock:
            pending = self._pending.get(request_id)
            if pending is None:
                return False
            pending["response"] = response
            pending["event"].set()
        return True

    def _request(self, event_name: str, payload: dict[str, Any], *, default: Any = None) -> Any:
        request_id = secrets.token_urlsafe(18)
        ready = threading.Event()
        pending: dict[str, Any] = {"event": ready}
        with self._pending_lock:
            self._pending[request_id] = pending

        self.emit(event_name, request_id=request_id, **payload)
        try:
            remaining = self.request_timeout
            while remaining > 0:
                if ready.wait(min(0.1, remaining)):
                    response = pending.get("response") or {}
                    return response
                if self.interrupted():
                    return default
                remaining -= 0.1
            self.emit("warning", message="Demande d'autorisation expirée.")
            return default
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def interrupted(self) -> bool:
        return self._interrupt.is_set()

    def request_interrupt(self) -> None:
        self._interrupt.set()

    def reset_interrupt(self) -> None:
        self._interrupt.clear()

    def stream_text(self, delta: str) -> None:
        if self.interrupted():
            raise KeyboardInterrupt
        if delta:
            self.emit("text_delta", delta=delta)

    def stream_reasoning(self, delta: str) -> None:
        if delta:
            self.emit("reasoning_delta", delta=delta)

    def end_assistant(self) -> None:
        self.emit("assistant_end")

    def tool_start(self, name: str, arguments: dict[str, Any]) -> None:
        self.emit("tool_start", name=name, arguments=arguments)

    def tool_result(self, name: str, result: str) -> None:
        self.emit("tool_result", name=name, result=result)
        if name == "todo_write" and self._context is not None:
            self.todos(list(self._context.todos))
        if (
            name in {"write", "edit", "multi_edit"}
            and self._checkpoints is not None
            and callable(self._session_id_getter)
        ):
            session_id = str(self._session_id_getter() or "")
            if session_id:
                self.emit("checkpoints_changed", checkpoints=self._checkpoints.pending(session_id))

    def stream_tool_output(self, name: str, chunk: str) -> None:
        if chunk:
            self.emit("tool_output", name=name, chunk=chunk)

    def show_diff(self, path: str, diff: str) -> None:
        self.emit("diff", path=path, diff=diff)

    def subagent_event(self, payload: dict[str, Any]) -> None:
        """Publie le cycle de vie d'un sous-agent (start, tool, end)."""
        self.emit("subagent", **payload)

    def warn(self, message: str) -> None:
        self.emit("warning", message=message)

    def error(self, message: str) -> None:
        self.emit("error", message=message)

    def info(self, message: str) -> None:
        self.emit("info", message=message)

    def success(self, message: str) -> None:
        self.emit("success", message=message)

    def todos(self, todos: list[dict[str, Any]]) -> None:
        self.emit("todos", todos=todos)

    def usage(self, usage: Usage, completion: Completion | None = None) -> None:
        self.emit(
            "usage",
            usage=usage.as_dict(),
            model=completion.model if completion is not None else None,
            provider=completion.provider if completion is not None else None,
        )

    def confirm_tool(self, name: str, arguments: dict[str, Any]) -> bool:
        response = self._request(
            "permission_request",
            {"tool": name, "arguments": arguments},
            default={"allowed": False},
        )
        return bool(response.get("allowed")) if isinstance(response, dict) else False

    def confirm_sudo_command(self, command: str) -> bool:
        response = self._request(
            "sudo_confirmation_request",
            {"command": command},
            default={"allowed": False},
        )
        return bool(response.get("allowed")) if isinstance(response, dict) else False

    def request_sudo_password(self, command: str) -> str | None:
        response = self._request(
            "sudo_password_request",
            {"command": command},
            default={"password": None},
        )
        password = response.get("password") if isinstance(response, dict) else None
        return password if isinstance(password, str) and password else None



def _visible_history(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    visible: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        if role != "user" and role != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, list):
            text_parts = [
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            img_count = sum(
                1
                for part in content
                if isinstance(part, dict) and part.get("type") in {"image_url", "input_image"}
            )
            joined = " ".join(part for part in text_parts if part.strip())
            if img_count and not joined:
                joined = f"[{img_count} image(s) jointe(s)]"
            elif img_count:
                joined = f"{joined}\n[{img_count} image(s) jointe(s)]"
            content = joined
        text = redact_secrets(str(content or "").strip())
        if text:
            visible.append({"role": str(role), "content": text})
    return visible


def _session_summaries(store: SessionStore, cwd: Path) -> list[dict[str, str]]:
    workspace = str(cwd.resolve())
    return [
        {
            "id": str(item["id"]),
            "title": str(item.get("title") or "Nouvelle conversation"),
            "updated_at": str(item.get("updated_at") or ""),
        }
        for item in store.list()
        if item.get("cwd") == workspace
    ][:12]


def _desktop_permission_manager(config: Any) -> PermissionManager:
    """Le bureau ne doit jamais hériter silencieusement du mode autonome du CLI."""
    mode = str(getattr(config, "permissions", "ask") or "ask")
    if mode == "allow":
        mode = "ask"
        config.permissions = mode
    # The desktop workspace is the only writable boundary; never inherit CLI
    # switches that expose files outside it or disable secret-file protection.
    config.allow_outside_cwd = False
    config.protect_secrets = True
    config.allow_secrets = False
    return PermissionManager(mode=mode, interactive=True)


def _build_runtime(cwd: Path, session_ref: str | None, model: str | None):
    config = load_config(cwd, {})
    if model:
        config.model = model

    store = SessionStore()
    session = store.load(session_ref) if session_ref else store.latest(cwd)
    if session is None:
        session = store.new(cwd, config.model, config.provider)
    else:
        if Path(session.cwd).expanduser().resolve() != cwd:
            raise ConfigError("Cette session appartient à un autre dossier de travail.")
        if model is None:
            config.model = session.model
        if config.provider is None and session.provider:
            config.provider = session.provider

    session.cwd = str(cwd)
    session.model = config.model
    session.provider = config.provider

    ui = DesktopBridgeUI()
    router = create_router(config, ui=ui)
    hooks = HookManager(config.hooks, cwd)
    context = ToolContext(
        cwd=cwd,
        run_hook=hooks.run,
        allow_outside=config.allow_outside_cwd,
        command_timeout=config.command_timeout,
        protect_secrets=config.protect_secrets,
        allow_secrets=config.allow_secrets,
        diff_view=config.diff_view,
        diff_context_lines=config.diff_context_lines,
        todos=[todo for todo in session.todos if isinstance(todo, dict)],
        request_sudo_password=ui.request_sudo_password,
    )
    permissions = _desktop_permission_manager(config)
    registry = build_registry(context, permissions, ui)

    from .agent import Agent

    agent = Agent(config, router, registry, session, ui, store=store)
    agent.checkpoints = CheckpointStore()
    context.checkpoint = lambda path, before, tool: agent.checkpoints.record(
        agent.session.id, path, before, tool
    )
    context.checkpoint_applied = lambda path: agent.checkpoints.mark_applied(
        agent.session.id, path
    )
    ui.bind_runtime(context, agent.checkpoints, lambda: agent.session.id)

    mcp_manager = MCPManager()
    if config.mcp_servers:
        mcp_manager = register_mcp_tools(
            registry,
            config.mcp_servers,
            cwd=cwd,
            ui=ui,
        )
    return config, store, ui, router, agent, permissions, context, mcp_manager


def _public_mcp_servers(servers: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose MCP metadata without returning environment variable values."""
    visible: list[dict[str, Any]] = []
    for name, server in servers.items():
        if not isinstance(server, dict):
            continue
        visible.append({
            "name": str(name),
            "command": str(server.get("command") or ""),
            "args": [str(value) for value in server.get("args", []) if isinstance(value, str)],
            "cwd": str(server.get("cwd") or ""),
            "enabled": bool(server.get("enabled", True)),
            "trusted": bool(server.get("trusted", False)),
            "timeout": int(server.get("timeout", 30)),
            "env_keys": sorted(str(key) for key in server.get("env", {}) if isinstance(key, str)),
        })
    return visible


RUNTIME_LIMITS: dict[str, tuple[type, float, float]] = {
    "max_steps": (int, 1, 500),
    "command_timeout": (int, 1, 3_600),
    "max_tokens": (int, 256, 128_000),
    "temperature": (float, 0, 2),
    "compact_threshold": (float, 0.2, 0.95),
}
RUNTIME_FLAGS = ("auto_compact", "task_routing", "fallback", "free_only", "diff_view")


def _runtime_settings(config: Any) -> dict[str, Any]:
    """Réglages d'exécution modifiables depuis les préférences desktop."""
    data: dict[str, Any] = {key: getattr(config, key) for key in RUNTIME_LIMITS}
    data.update({key: bool(getattr(config, key)) for key in RUNTIME_FLAGS})
    return data


def _apply_runtime_settings(
    config: Any, context: ToolContext | None, values: Any
) -> tuple[bool, str]:
    """Valide puis applique une liste blanche de réglages.

    Les frontières de sécurité (allow_outside_cwd, protect_secrets, permissions) ne
    passent jamais par ce chemin : elles gardent leurs commandes dédiées.
    """
    if not isinstance(values, dict) or not values:
        return False, "Réglages invalides."
    updates: dict[str, Any] = {}
    for key, value in values.items():
        if key in RUNTIME_LIMITS:
            kind, low, high = RUNTIME_LIMITS[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False, f"{key} doit être numérique."
            number = kind(value)
            if not low <= number <= high:
                return False, f"{key} doit être compris entre {low} et {high}."
            updates[key] = number
        elif key in RUNTIME_FLAGS:
            if not isinstance(value, bool):
                return False, f"{key} doit être un booléen."
            updates[key] = value
        else:
            return False, f"Réglage non modifiable : {key}."
    previous = {key: getattr(config, key) for key in updates}
    for key, value in updates.items():
        setattr(config, key, value)
    try:
        validate_config(config)
    except ConfigError as exc:
        for key, value in previous.items():
            setattr(config, key, value)
        return False, str(exc)
    if context is not None:
        if "command_timeout" in updates:
            context.command_timeout = updates["command_timeout"]
        if "diff_view" in updates:
            context.diff_view = updates["diff_view"]
    return True, ""


IMAGE_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,[A-Za-z0-9+/=\s]+$")
MAX_PROMPT_IMAGES = 4
MAX_IMAGE_DATA_URL_CHARS = 8_000_000


def _sanitize_images(raw: Any) -> list[str]:
    """Valide les images encodées en data URL envoyées depuis l'interface Desktop."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Le champ images doit être une liste.")
    if len(raw) > MAX_PROMPT_IMAGES:
        raise ValueError(f"Maximum {MAX_PROMPT_IMAGES} images par message.")
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("Format d'image invalide.")
        value = item.strip()
        if len(value) > MAX_IMAGE_DATA_URL_CHARS:
            raise ValueError("Image trop volumineuse (max ~6 Mo).")
        if not IMAGE_DATA_URL_RE.match(value):
            raise ValueError("Seules les images PNG, JPEG, WebP ou GIF encodées en base64 sont acceptées.")
        cleaned.append(re.sub(r"\s+", "", value))
    return cleaned


def _skills_state(cwd: Path, agent: Any) -> dict[str, Any]:
    """Expose le catalogue de skills disponibles et ceux actuellement actifs."""
    catalog = all_skills(cwd)
    active = list(getattr(agent, "skills", []))
    available = [
        {
            "id": spec.name,
            "label": spec.label,
            "category": spec.category,
            "summary": spec.summary,
            "builtin": bool(spec.builtin),
        }
        for spec in catalog.values()
    ]
    return {"active": active, "available": available}


def _project_memory(cwd: Path) -> dict[str, str]:
    """Lit les consignes persistantes du projet (.zerocode/instructions.md)."""
    rel = ".zerocode/instructions.md"
    target = cwd.resolve() / rel
    content = ""
    if target.is_file():
        with contextlib.suppress(OSError):
            if target.stat().st_size <= 128_000:
                content = redact_secrets(target.read_text(encoding="utf-8", errors="replace"))
    return {"path": rel, "content": content}


def _save_project_memory(cwd: Path, content: str) -> dict[str, str]:
    """Enregistre ou nettoie .zerocode/instructions.md de façon sûre."""
    rel = ".zerocode/instructions.md"
    target = cwd.resolve() / rel
    cleaned = redact_secrets(content).strip()
    if len(cleaned) > MAX_INSTRUCTIONS_CHARS:
        raise ValueError(f"La mémoire projet ne peut pas dépasser {MAX_INSTRUCTIONS_CHARS} caractères.")
    if not cleaned:
        if target.is_file():
            target.unlink()
        return {"path": rel, "content": ""}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cleaned + "\n", encoding="utf-8")
    return {"path": rel, "content": cleaned + "\n"}


def _public_providers(config: Any, router: Router) -> list[dict[str, Any]]:
    """Expose l'état des fournisseurs sans jamais renvoyer de clé API brute."""
    if getattr(router, "is_cloud", False):
        remote = getattr(router, "remote_config", None) or {}
        aliases = [
            item.get("alias")
            for item in remote.get("models", [])
            if isinstance(item, dict) and isinstance(item.get("alias"), str)
        ]
        return [{
            "id": "zerocode-cloud",
            "label": "ZeroCode Cloud",
            "env_var": "",
            "requires_key": False,
            "enabled": True,
            "available": True,
            "source": "keyless",
            "key_masked": "",
            "models_count": len(aliases),
            "signup_url": "",
            "notes": "Inférence distante · modèles et fournisseurs gérés par ZeroCode Cloud.",
        }]
    store = load_key_store()
    items: list[dict[str, Any]] = []
    for spec in router.providers.values():
        env_key: str | None = None
        for env_name in spec.api_key_envs:
            candidate = os.environ.get(env_name)
            if candidate and candidate.strip():
                env_key = candidate.strip()
                break
        store_value: str | None = None
        for name in (spec.name, *spec.api_key_envs):
            candidate = store.get(name)
            if candidate:
                store_value = candidate
                break
        if spec.keyless:
            source = "keyless"
            masked = ""
        elif env_key:
            source = "env"
            masked = mask_key(env_key)
        elif store_value:
            source = "store"
            masked = mask_key(store_value)
        else:
            source = "none"
            masked = ""
        items.append(
            {
                "id": spec.name,
                "label": spec.label,
                "env_var": spec.api_key_envs[0] if spec.api_key_envs else "",
                "requires_key": spec.requires_key,
                "enabled": provider_enabled(spec, config),
                "available": provider_available(spec, config),
                "source": source,
                "key_masked": masked,
                "models_count": len(spec.models),
                "signup_url": spec.signup_url,
                "notes": spec.notes,
            }
        )
    return items


def _refresh_router_providers(config: Any, router: Router) -> None:
    """Reconstruit les clients fournisseurs après ajout/suppression d'une clé API."""
    old_clients = list(router.clients.values())
    router.providers = applied_providers(config)
    router.clients = build_clients(config, router.providers)
    lock = getattr(router, "_cooldown_lock", None)
    if lock is not None:
        with lock:
            router._cooldown.clear()
    else:
        router._cooldown.clear()
    seen: set[int] = set()
    for client in old_clients:
        if id(client) in seen:
            continue
        seen.add(id(client))
        with contextlib.suppress(Exception):
            client.close()


def _public_hooks(hooks: Any) -> dict[str, list[dict[str, Any]]]:
    """Normalise les hooks globaux PreToolUse / PostToolUse pour l'interface."""
    source = hooks if isinstance(hooks, dict) else {}
    out: dict[str, list[dict[str, Any]]] = {"PreToolUse": [], "PostToolUse": []}
    for event in ("PreToolUse", "PostToolUse"):
        entries = source.get(event)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            command = str(entry.get("command") or "").strip()
            if not command:
                continue
            args = [str(item) for item in entry.get("args", []) if isinstance(item, str)]
            raw_timeout = entry.get("timeout", 10)
            timeout = raw_timeout if isinstance(raw_timeout, int) and not isinstance(raw_timeout, bool) else 10
            out[event].append({"command": command, "args": args, "timeout": max(1, min(30, timeout))})
    return out


def _doctor_report(
    cwd: Path,
    config: Any,
    router: Router,
    agent: Any,
    store: SessionStore,
) -> dict[str, Any]:
    """Diagnostic local rapide (sans appel réseau) de l'environnement ZeroCode."""
    providers = _public_providers(config, router)
    ready_providers = [p["id"] for p in providers if p["available"]]
    mcp_total = len(config.mcp_servers)
    mcp_enabled = sum(1 for srv in config.mcp_servers.values() if isinstance(srv, dict) and srv.get("enabled", True))
    hooks_norm = _public_hooks(config.hooks)
    hooks_count = len(hooks_norm["PreToolUse"]) + len(hooks_norm["PostToolUse"])
    memory = _project_memory(cwd)
    git_path = shutil.which("git")
    rg_path = shutil.which("rg")
    checks = [
        {
            "id": "engine",
            "label": "Moteur ZeroCode",
            "status": "ok",
            "detail": f"v{__version__} · Python {platform.python_version()} ({platform.system()})",
        },
        {
            "id": "workspace",
            "label": "Dossier actif",
            "status": "ok" if cwd.is_dir() and os.access(cwd, os.W_OK) else "warn",
            "detail": f"{cwd} ({'accessible en écriture' if os.access(cwd, os.W_OK) else 'lecture seule'})",
        },
        {
            "id": "providers",
            "label": "Fournisseurs disponibles",
            "status": "ok" if ready_providers else "error",
            "detail": f"{len(ready_providers)} prêt(s) : {', '.join(ready_providers[:6])}" if ready_providers else "Aucun fournisseur configuré",
        },
        {
            "id": "git",
            "label": "Git",
            "status": "ok" if git_path else "warn",
            "detail": git_path or "git introuvable dans PATH",
        },
        {
            "id": "ripgrep",
            "label": "Ripgrep (rg)",
            "status": "ok" if rg_path else "info",
            "detail": rg_path or "non installé (repli Python / Rust actif)",
        },
        {
            "id": "mcp",
            "label": "Serveurs MCP",
            "status": "ok" if mcp_enabled else "info",
            "detail": f"{mcp_enabled}/{mcp_total} activé(s)",
        },
        {
            "id": "hooks",
            "label": "Hooks globaux",
            "status": "ok" if hooks_count else "info",
            "detail": f"{hooks_count} hook(s) (PreToolUse: {len(hooks_norm['PreToolUse'])}, PostToolUse: {len(hooks_norm['PostToolUse'])})",
        },
        {
            "id": "skills",
            "label": "Skills & mémoire projet",
            "status": "ok",
            "detail": f"{len(getattr(agent, 'skills', []))} skill(s) actif(s) · mémoire {'présente' if memory['content'].strip() else 'vide'} · {len(_session_summaries(store, cwd))} session(s)",
        },
    ]
    return {"version": __version__, "checks": checks}


def _resolve_model_selection(
    router: Router, raw_model: str, raw_provider: Any = None
) -> tuple[str, str | None]:
    """Normalize UI model IDs while keeping provider routing local/cloud-safe."""
    next_model = raw_model.strip()
    if isinstance(raw_provider, str):
        return next_model, raw_provider.strip() or None
    if "/" in next_model:
        prefix, model_id = next_model.split("/", 1)
        if prefix in getattr(router, "providers", {}) :
            return model_id, prefix
        if prefix == "zerocode-cloud" and getattr(router, "is_cloud", False):
            return model_id, None
    return next_model, None


def _available_models(router: Router) -> list[str]:
    models: list[str] = ["auto"]
    for item in router.preview("auto"):
        if item not in models:
            models.append(item)
    return models[:24]


def _think_value(config: Any) -> str:
    if not getattr(config, "show_reasoning", False):
        return "off"
    effort = str(getattr(config, "reasoning_effort", "low") or "low").lower()
    return effort if effort in {"low", "high", "max"} else "low"


def _emit_session_state(
    ui: DesktopBridgeUI,
    event_name: str,
    cwd: Path,
    config: Any,
    store: SessionStore,
    router: Router,
    agent: Any,
    permissions: PermissionManager,
    context: ToolContext,
) -> None:
    checkpoints = (
        agent.checkpoints.pending(agent.session.id)
        if getattr(agent, "checkpoints", None) is not None
        else 0
    )
    ui.emit(
        event_name,
        cwd=str(cwd),
        session_id=agent.session.id,
        model=config.model,
        provider=config.provider,
        mode=agent.mode,
        permissions=permissions.mode,
        think=_think_value(config),
        available=bool(router.preview()),
        models=_available_models(router),
        messages=_visible_history(agent.messages),
        sessions=_session_summaries(store, cwd),
        todos=list(context.todos),
        checkpoints=checkpoints,
        runtime=_runtime_settings(config),
        subagent_roles=roles_catalog(),
        skills=_skills_state(cwd, agent),
        memory=_project_memory(cwd),
        providers=_public_providers(config, router),
        hooks=_public_hooks(config.hooks),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zerocode desktop-bridge",
        description="Pont local JSONL pour ZeroCode Desktop.",
    )
    parser.add_argument("--cwd", required=True, help="Dossier de travail local.")
    parser.add_argument("--session", help="Identifiant d'une session à reprendre.")
    parser.add_argument("--model", help="Modèle à utiliser.")
    args = parser.parse_args(argv)

    cwd = Path(args.cwd).expanduser().resolve()
    if not cwd.is_dir():
        print(json.dumps({"type": "error", "message": "Dossier de travail introuvable."}), flush=True)
        return 2

    runtime = None
    try:
        runtime = _build_runtime(cwd, args.session, args.model)
        config, store, ui, router, agent, permissions, context, mcp_manager = runtime
        _emit_session_state(
            ui, "ready", cwd, config, store, router, agent, permissions, context
        )
        ui.emit("mcp_servers", servers=_public_mcp_servers(config.mcp_servers))
        turn_lock = threading.Lock()
        active = {"turn": False, "subagents": 0}

        def _begin_job(*, is_turn: bool) -> tuple[bool, bool]:
            with turn_lock:
                if is_turn:
                    if active["turn"]:
                        return False, False
                    was_idle = active["subagents"] == 0
                    active["turn"] = True
                    return True, was_idle
                if active["subagents"] >= 4:
                    return False, False
                was_idle = (not active["turn"]) and active["subagents"] == 0
                active["subagents"] += 1
                return True, was_idle

        def _end_job(*, is_turn: bool) -> bool:
            with turn_lock:
                if is_turn:
                    active["turn"] = False
                else:
                    active["subagents"] = max(0, active["subagents"] - 1)
                return (not active["turn"]) and active["subagents"] == 0

        def run_prompt(text: str, images: list[str] | None, emit_started: bool) -> None:
            try:
                if emit_started:
                    ui.emit("turn_started")
                ui.emit("assistant_start")
                result = agent.run_turn(text, images=images or None)
                ui.emit(
                    "result",
                    content=result,
                    session_id=agent.session.id,
                    usage=agent.usage.as_dict(),
                    model=config.model,
                    provider=config.provider,
                )
            except KeyboardInterrupt:
                ui.emit("warning", message="Exécution interrompue.")
            except ZeroCodeError as exc:
                ui.error(str(exc))
            except Exception as exc:  # Le pont reste vivant après une erreur isolée.
                ui.error(f"{exc.__class__.__name__}: {exc}")
            finally:
                ui.usage(agent.usage, router.last)
                ui.todos(list(context.todos))
                if getattr(agent, "checkpoints", None) is not None:
                    ui.emit(
                        "checkpoints_changed",
                        checkpoints=agent.checkpoints.pending(agent.session.id),
                    )
                ui.emit("sessions_changed", sessions=_session_summaries(store, cwd))
                if _end_job(is_turn=True):
                    ui.emit("turn_complete")

        def run_subagent_job(task: str, role: str, emit_started: bool) -> None:
            try:
                if emit_started:
                    ui.emit("turn_started")
                agent._run_subagent(task, role)
            except KeyboardInterrupt:
                ui.emit("warning", message="Sous-agent interrompu.")
            except ZeroCodeError as exc:
                ui.error(str(exc))
            except Exception as exc:  # Le pont reste vivant après une erreur isolée.
                ui.error(f"{exc.__class__.__name__}: {exc}")
            finally:
                ui.usage(agent.usage, router.last)
                if _end_job(is_turn=False):
                    ui.emit("turn_complete")

        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                ui.error("Message desktop invalide : JSON attendu.")
                continue
            if not isinstance(message, dict):
                ui.error("Message desktop invalide : objet attendu.")
                continue

            kind = message.get("type")
            if kind == "mcp_list":
                ui.emit("mcp_servers", servers=_public_mcp_servers(config.mcp_servers))
                continue
            if kind == "mcp_save":
                name = str(message.get("name") or "").strip()
                server = message.get("server")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name):
                    ui.error("Identifiant MCP invalide.")
                    continue
                if not isinstance(server, dict):
                    ui.error("Configuration MCP invalide.")
                    continue
                previous = config.mcp_servers
                candidate = dict(previous)
                next_server = dict(server)
                if "env" not in next_server and name in previous:
                    next_server["env"] = previous[name].get("env", {})
                candidate[name] = next_server
                config.mcp_servers = candidate
                try:
                    save_mcp_servers(candidate, cwd=cwd)
                except Exception as exc:
                    config.mcp_servers = previous
                    ui.error(f"Configuration MCP refusée : {exc}")
                    continue
                ui.emit("mcp_saved", servers=_public_mcp_servers(config.mcp_servers))
                continue
            if kind == "mcp_remove":
                name = str(message.get("name") or "").strip()
                if name not in config.mcp_servers:
                    ui.error("Serveur MCP introuvable.")
                    continue
                previous = config.mcp_servers
                candidate = dict(previous)
                candidate.pop(name, None)
                config.mcp_servers = candidate
                try:
                    save_mcp_servers(candidate, cwd=cwd)
                except Exception as exc:
                    config.mcp_servers = previous
                    ui.error(f"Suppression MCP refusée : {exc}")
                    continue
                ui.emit("mcp_removed", servers=_public_mcp_servers(config.mcp_servers))
                continue
            if kind in {"permission_response", "sudo_confirmation_response", "sudo_password_response"}:
                ui.receive(message)
                continue
            if kind == "set_runtime":
                ok, problem = _apply_runtime_settings(config, context, message.get("values"))
                if not ok:
                    ui.error(problem)
                    continue
                ui.emit("runtime_changed", runtime=_runtime_settings(config))
                continue
            if kind == "run_subagent":
                role = str(message.get("role") or "explorer").strip().lower()
                task = message.get("task")
                if role not in SPECIALIST_ROLES:
                    ui.error("Rôle de sous-agent inconnu.")
                    continue
                if not isinstance(task, str) or not task.strip():
                    ui.error("La tâche du sous-agent est vide.")
                    continue
                accepted, first = _begin_job(is_turn=False)
                if not accepted:
                    ui.error("Maximum 4 sous-agents simultanés atteint.")
                    continue
                ui.reset_interrupt()
                threading.Thread(
                    target=run_subagent_job, args=(task.strip(), role, first), daemon=True
                ).start()
                continue
            if kind == "skills_list":
                ui.emit("skills_changed", skills=_skills_state(cwd, agent))
                continue
            if kind == "skill_toggle":
                raw_name = str(message.get("name") or "").strip()
                if not raw_name:
                    ui.error("Nom de skill manquant.")
                    continue
                ok, feedback = agent.toggle_skill(raw_name)
                ui.emit("skills_changed", skills=_skills_state(cwd, agent))
                if ok:
                    ui.info(feedback)
                else:
                    ui.error(feedback)
                continue
            if kind == "skills_set":
                names = message.get("names")
                if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                    ui.error("Liste de skills invalide.")
                    continue
                agent.set_skills(names)
                ui.emit("skills_changed", skills=_skills_state(cwd, agent))
                continue
            if kind == "memory_get":
                ui.emit("memory_changed", memory=_project_memory(cwd))
                continue
            if kind == "memory_add":
                note = str(message.get("note") or "").strip()
                if not note:
                    ui.error("La consigne à mémoriser est vide.")
                    continue
                try:
                    remember_project_instruction(cwd, note)
                    agent._refresh_system_mode()
                except (OSError, ValueError) as exc:
                    ui.error(f"Impossible d'enregistrer la consigne : {exc}")
                    continue
                ui.emit("memory_changed", memory=_project_memory(cwd))
                ui.success("Consigne mémorisée dans .zerocode/instructions.md.")
                continue
            if kind == "memory_save":
                raw_content = message.get("content")
                if not isinstance(raw_content, str):
                    ui.error("Contenu de mémoire invalide.")
                    continue
                try:
                    mem = _save_project_memory(cwd, raw_content)
                    agent._refresh_system_mode()
                except (OSError, ValueError) as exc:
                    ui.error(f"Impossible d'enregistrer la mémoire : {exc}")
                    continue
                ui.emit("memory_changed", memory=mem)
                ui.success("Mémoire projet enregistrée.")
                continue
            if kind == "providers_list":
                ui.emit("providers_changed", providers=_public_providers(config, router))
                continue
            if kind == "provider_key_save":
                provider_id = str(message.get("provider") or "").strip()
                raw_key = str(message.get("key") or "").strip()
                spec = router.providers.get(provider_id)
                if spec is None or not spec.requires_key:
                    ui.error("Fournisseur inconnu ou sans clé API requise.")
                    continue
                if not raw_key:
                    ui.error("La clé API est vide.")
                    continue
                try:
                    store_key(spec.name, raw_key)
                    _refresh_router_providers(config, router)
                except (OSError, ConfigError) as exc:
                    ui.error(f"Impossible d'enregistrer la clé : {exc}")
                    continue
                ui.emit("providers_changed", providers=_public_providers(config, router))
                ui.emit("models_changed", models=_available_models(router))
                ui.success(f"Clé API enregistrée pour {spec.label}.")
                continue
            if kind == "provider_key_delete":
                provider_id = str(message.get("provider") or "").strip()
                spec = router.providers.get(provider_id)
                if spec is None or not spec.requires_key:
                    ui.error("Fournisseur inconnu.")
                    continue
                removed = False
                for key_name in (spec.name, *spec.api_key_envs):
                    if delete_key(key_name):
                        removed = True
                _refresh_router_providers(config, router)
                ui.emit("providers_changed", providers=_public_providers(config, router))
                ui.emit("models_changed", models=_available_models(router))
                if removed:
                    ui.info(f"Clé API supprimée du coffre pour {spec.label}.")
                else:
                    ui.info(f"Aucune clé stockée pour {spec.label} (une variable d'environnement peut rester active).")
                continue
            if kind == "interrupt":
                ui.request_interrupt()
                context.terminate_active_process(user=True)
                continue
            if kind == "prompt":
                prompt = message.get("text")
                try:
                    images = _sanitize_images(message.get("images"))
                except ValueError as exc:
                    ui.error(str(exc))
                    continue
                text = prompt.strip() if isinstance(prompt, str) else ""
                if not text and images:
                    text = "Analyse l'image jointe."
                if not text:
                    ui.error("Le message est vide.")
                    continue
                accepted, first = _begin_job(is_turn=True)
                if not accepted:
                    ui.error("Une demande est déjà en cours.")
                    continue
                ui.reset_interrupt()
                threading.Thread(
                    target=run_prompt, args=(text, images, first), daemon=True
                ).start()
                continue
            if kind == "set_mode":
                mode = str(message.get("mode") or "")
                if mode not in {"build", "plan", "full-stack"}:
                    ui.error("Mode inconnu.")
                    continue
                agent.set_mode(mode)
                ui.emit(
                    "mode_changed",
                    mode=agent.mode,
                    permissions=permissions.mode,
                    think=_think_value(config),
                )
                continue
            if kind == "set_model":
                next_model = str(message.get("model") or "").strip()
                if not next_model:
                    ui.error("Modèle invalide.")
                    continue
                next_model, next_provider = _resolve_model_selection(
                    router, next_model, message.get("provider")
                )
                config.model = next_model
                config.provider = next_provider
                agent.session.model = next_model
                agent.session.provider = next_provider
                store.save(agent.session)
                ui.emit(
                    "config_changed",
                    model=config.model,
                    provider=config.provider,
                    permissions=permissions.mode,
                    think=_think_value(config),
                )
                continue
            if kind == "set_permissions":
                perm_mode = str(message.get("permissions") or "").strip()
                if perm_mode not in {"ask", "auto", "allow", "deny"}:
                    ui.error("Mode d'autorisation inconnu.")
                    continue
                permissions.mode = perm_mode
                config.permissions = perm_mode
                ui.emit(
                    "config_changed",
                    model=config.model,
                    provider=config.provider,
                    permissions=permissions.mode,
                    think=_think_value(config),
                )
                continue
            if kind == "set_think":
                think_mode = str(message.get("think") or "").strip().lower()
                if think_mode not in {"off", "low", "high", "max"}:
                    ui.error("Mode de raisonnement inconnu.")
                    continue
                agent.set_think(think_mode)
                ui.emit(
                    "config_changed",
                    model=config.model,
                    provider=config.provider,
                    permissions=permissions.mode,
                    think=_think_value(config),
                )
                continue
            if kind == "new_session":
                session = store.new(cwd, config.model, config.provider)
                agent.load_session(session)
                _emit_session_state(
                    ui, "session_changed", cwd, config, store, router, agent, permissions, context
                )
                continue
            if kind == "resume_session":
                ref = str(message.get("session_id") or "")
                session = store.load(ref) if ref else None
                if session is None or Path(session.cwd).expanduser().resolve() != cwd:
                    ui.error("Session introuvable pour ce dossier.")
                    continue
                agent.load_session(session)
                _emit_session_state(
                    ui, "session_changed", cwd, config, store, router, agent, permissions, context
                )
                continue
            if kind == "delete_session":
                ref = str(message.get("session_id") or "").strip()
                if not ref:
                    ui.error("Identifiant de session manquant.")
                    continue
                target = store.load(ref)
                if target is None or Path(target.cwd).expanduser().resolve() != cwd:
                    ui.error("Session introuvable pour ce dossier.")
                    continue
                was_active = target.id == agent.session.id
                store.delete(target.id)
                if getattr(agent, "checkpoints", None) is not None:
                    agent.checkpoints.clear(target.id)
                if was_active:
                    next_session = store.latest(cwd) or store.new(cwd, config.model, config.provider)
                    agent.load_session(next_session)
                    _emit_session_state(
                        ui, "session_changed", cwd, config, store, router, agent, permissions, context
                    )
                else:
                    ui.emit("sessions_changed", sessions=_session_summaries(store, cwd))
                continue
            if kind == "rename_session":
                ref = str(message.get("session_id") or agent.session.id).strip()
                title = message.get("title")
                if not isinstance(title, str):
                    ui.error("Titre de session invalide.")
                    continue
                target = store.load(ref)
                if target is None or Path(target.cwd).expanduser().resolve() != cwd:
                    ui.error("Session introuvable pour ce dossier.")
                    continue
                renamed = store.rename(target.id, title)
                if renamed is not None and renamed.id == agent.session.id:
                    agent.session.title = renamed.title
                ui.emit("sessions_changed", sessions=_session_summaries(store, cwd))
                ui.success("Conversation renommée.")
                continue
            if kind == "fork_session":
                ref = str(message.get("session_id") or agent.session.id).strip()
                target = store.load(ref)
                if target is None or Path(target.cwd).expanduser().resolve() != cwd:
                    ui.error("Session introuvable pour ce dossier.")
                    continue
                if target.id == agent.session.id:
                    store.save(agent.session)
                forked = store.fork(target.id)
                if forked is None:
                    ui.error("Impossible de dupliquer cette conversation.")
                    continue
                agent.load_session(forked)
                _emit_session_state(
                    ui, "session_changed", cwd, config, store, router, agent, permissions, context
                )
                ui.success("Conversation bifurquée (fork créé).")
                continue
            if kind == "hooks_list":
                ui.emit("hooks_changed", hooks=_public_hooks(config.hooks))
                continue
            if kind == "hooks_save":
                raw_hooks = message.get("hooks")
                if not isinstance(raw_hooks, dict):
                    ui.error("Configuration de hooks invalide.")
                    continue
                cleaned_hooks: dict[str, list[dict[str, Any]]] = {}
                for event in ("PreToolUse", "PostToolUse"):
                    entries = raw_hooks.get(event)
                    if entries:
                        cleaned_hooks[event] = entries
                previous = config.hooks
                config.hooks = cleaned_hooks
                try:
                    save_hooks(cleaned_hooks, cwd=cwd)
                except Exception as exc:
                    config.hooks = previous
                    ui.error(f"Hooks refusés : {exc}")
                    continue
                hook_mgr = getattr(context.run_hook, "__self__", None)
                if isinstance(hook_mgr, HookManager):
                    hook_mgr.config = cleaned_hooks
                ui.emit("hooks_changed", hooks=_public_hooks(config.hooks))
                ui.success("Hooks globaux enregistrés et actifs.")
                continue
            if kind == "doctor_run":
                ui.emit("doctor_report", report=_doctor_report(cwd, config, router, agent, store))
                continue
            if kind == "undo_checkpoint":
                if getattr(agent, "checkpoints", None) is None:
                    ui.error("Historique de checkpoints indisponible.")
                    continue
                ok, undo_msg = agent.checkpoints.undo(agent.session.id, cwd)
                remaining = agent.checkpoints.pending(agent.session.id)
                ui.emit(
                    "checkpoint_restored",
                    ok=ok,
                    message=undo_msg,
                    checkpoints=remaining,
                )
                continue
            if kind == "compact_context":
                agent.compact(force=True)
                _emit_session_state(
                    ui, "session_changed", cwd, config, store, router, agent, permissions, context
                )
                continue
            ui.error("Commande desktop non reconnue.")

        ui.request_interrupt()
        context.terminate_active_process(user=True)
        return 0
    except (ConfigError, ZeroCodeError) as exc:
        print(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False), flush=True)
        return 1
    finally:
        if runtime is not None:
            with contextlib.suppress(Exception):
                runtime[6].terminate_active_process(user=True)
            with contextlib.suppress(Exception):
                runtime[7].close()
            with contextlib.suppress(Exception):
                runtime[3].close()

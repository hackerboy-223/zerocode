from __future__ import annotations

import argparse
import contextlib
import json
import secrets
import sys
import threading
from pathlib import Path
from typing import Any

from .checkpoints import CheckpointStore
from .config import load_config, save_config, validate_config
from .errors import ConfigError, ZeroCodeError
from .hooks import HookManager
from .mcp import MCPManager, register_mcp_tools
from .router import Router
from .security import redact_secrets
from .session import SessionStore
from .tools import PermissionManager, ToolContext, build_registry
from .types import Completion, Usage


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
            content = " ".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
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
    router = Router(config, ui=ui)
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
        active = {"value": False}

        def run_prompt(text: str) -> None:
            try:
                ui.emit("turn_started")
                ui.emit("assistant_start")
                result = agent.run_turn(text)
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
                ui.emit("turn_complete")
                with turn_lock:
                    active["value"] = False

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
                candidate[name] = server
                config.mcp_servers = candidate
                try:
                    validate_config(config)
                    save_config(config)
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
                    validate_config(config)
                    save_config(config)
                except Exception as exc:
                    config.mcp_servers = previous
                    ui.error(f"Suppression MCP refusée : {exc}")
                    continue
                ui.emit("mcp_removed", servers=_public_mcp_servers(config.mcp_servers))
                continue
            kind = message.get("type")
            if kind in {"permission_response", "sudo_confirmation_response", "sudo_password_response"}:
                ui.receive(message)
                continue
            if kind == "interrupt":
                ui.request_interrupt()
                context.terminate_active_process(user=True)
                continue
            if kind == "prompt":
                prompt = message.get("text")
                if not isinstance(prompt, str) or not prompt.strip():
                    ui.error("Le message est vide.")
                    continue
                with turn_lock:
                    if active["value"]:
                        ui.error("Une demande est déjà en cours.")
                        continue
                    active["value"] = True
                ui.reset_interrupt()
                threading.Thread(target=run_prompt, args=(prompt,), daemon=True).start()
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
                next_provider = message.get("provider")
                if isinstance(next_provider, str):
                    next_provider = next_provider.strip() or None
                elif "/" in next_model and next_model.split("/", 1)[0] in router.providers:
                    next_provider, next_model = next_model.split("/", 1)
                else:
                    next_provider = None
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

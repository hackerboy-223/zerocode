from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
from pathlib import Path
from typing import Any

from .checkpoints import CheckpointStore
from .config import load_config
from .errors import ConfigError, ZeroCodeError
from .hooks import HookManager
from .mcp import MCPManager, register_mcp_tools
from .router import Router
from .session import SessionStore
from .tools import PermissionManager, ToolContext, build_registry
from .types import Completion, Usage


class DesktopBridgeUI:
    """Pont JSONL entre l'agent Python et l'interface desktop locale."""

    interactive = True

    def __init__(self, stream: Any | None = None, *, request_timeout: float = 900.0) -> None:
        self.stream = stream or sys.stdout
        self.request_timeout = request_timeout
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._interrupt = threading.Event()

    def emit(self, event: str, **data: Any) -> None:
        payload = {"type": event, **data}
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
            if not ready.wait(self.request_timeout):
                self.emit("warning", message="Demande d'autorisation expirée.")
                return default
            response = pending.get("response") or {}
            return response
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
    permissions = PermissionManager(mode=config.permissions, interactive=True)
    registry = build_registry(context, permissions, ui)

    from .agent import Agent

    agent = Agent(config, router, registry, session, ui, store=store)
    agent.checkpoints = CheckpointStore()
    context.checkpoint = lambda path, before, tool: agent.checkpoints.record(
        agent.session.id, path, before, tool
    )

    mcp_manager = MCPManager()
    if config.mcp_servers:
        mcp_manager = register_mcp_tools(
            registry,
            config.mcp_servers,
            cwd=cwd,
            ui=ui,
        )
    return config, store, ui, router, agent, permissions, context, mcp_manager


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
        ui.emit(
            "ready",
            cwd=str(cwd),
            session_id=agent.session.id,
            model=config.model,
            provider=config.provider,
            permissions=config.permissions,
            available=bool(router.preview()),
        )
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

            kind = message.get("type")
            if kind in {"permission_response", "sudo_confirmation_response", "sudo_password_response"}:
                ui.receive(message)
                continue
            if kind == "interrupt":
                ui.request_interrupt()
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
                ui.emit("mode_changed", mode=agent.mode)
                continue
            if kind == "new_session":
                session = store.new(cwd, config.model, config.provider)
                agent.load_session(session)
                ui.emit("session_changed", session_id=agent.session.id)
                continue
            if kind == "resume_session":
                ref = str(message.get("session_id") or "")
                session = store.load(ref) if ref else None
                if session is None or Path(session.cwd).expanduser().resolve() != cwd:
                    ui.error("Session introuvable pour ce dossier.")
                    continue
                agent.load_session(session)
                ui.emit("session_changed", session_id=agent.session.id)
                continue
            ui.error("Commande desktop non reconnue.")

        ui.request_interrupt()
        return 0
    except (ConfigError, ZeroCodeError) as exc:
        print(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False), flush=True)
        return 1
    finally:
        if runtime is not None:
            try:
                runtime[7].close()
            except Exception:
                pass
            try:
                runtime[3].close()
            except Exception:
                pass

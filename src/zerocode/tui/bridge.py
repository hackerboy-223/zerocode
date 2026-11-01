from __future__ import annotations

import threading
from typing import Any


class TuiBridge:
    """Adapte les callbacks synchrones de l'agent vers l'application Textual."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.thread_id = threading.get_ident()
        self.show_reasoning = app.config.show_reasoning
        self.quiet = False
        self.interactive = True

    def interrupted(self) -> bool:
        return bool(getattr(self.app, "_interrupt_requested", False))

    def stream_text(self, delta: str) -> None:
        if self.interrupted():
            raise KeyboardInterrupt
        if delta:
            self._dispatch("_stream_text", delta)

    def stream_reasoning(self, delta: str) -> None:
        if self.interrupted():
            raise KeyboardInterrupt
        if delta and self.show_reasoning:
            self._dispatch("_stream_reasoning", delta)

    def end_assistant(self) -> None:
        self._dispatch("_end_assistant")

    def tool_start(self, name: str, args: dict[str, Any]) -> None:
        self._dispatch("_tool_start", name, args)

    def tool_result(self, name: str, result: str) -> None:
        self._dispatch("_tool_result", name, result)

    def stream_tool_output(self, name: str, chunk: str) -> None:
        if chunk:
            self._dispatch("_tool_output", name, chunk)

    def show_diff(self, path: str, diff: str) -> None:
        self._dispatch("_tool_diff", path, diff)

    def warn(self, message: str) -> None:
        self._dispatch("_notice", message, "warning")

    def error(self, message: str) -> None:
        self._dispatch("_notice", message, "error")

    def info(self, message: str) -> None:
        self._dispatch("_notice", message, "info")

    def success(self, message: str) -> None:
        self._dispatch("_notice", message, "success")

    def todos(self, todos: list[dict[str, Any]]) -> None:
        self._dispatch("show_todos", todos)

    def confirm_tool(self, name: str, args: dict[str, Any]) -> bool:
        done = threading.Event()
        result = {"allowed": False}

        def receive(allowed: bool | None) -> None:
            result["allowed"] = bool(allowed)
            done.set()

        self._dispatch("ask_tool_permission", name, args, receive)
        if not done.wait(timeout=900):
            return False
        return result["allowed"]

    def request_sudo_password(self, command: str) -> str | None:
        if not self.interactive:
            return None
        done = threading.Event()
        result: dict[str, str | None] = {"password": None}

        def receive(password: str | None) -> None:
            result["password"] = password or None
            done.set()

        self._dispatch("ask_sudo_password", command, receive)
        if not done.wait(timeout=900):
            return None
        return result["password"]

    def _dispatch(self, method: str, *args: Any) -> Any:
        callback = getattr(self.app, method)
        if threading.get_ident() == self.thread_id:
            return callback(*args)
        return self.app.call_from_thread(callback, *args)

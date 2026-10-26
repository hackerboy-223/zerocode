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

    def stream_text(self, delta: str) -> None:
        if delta:
            self._dispatch("_stream_text", delta)

    def stream_reasoning(self, delta: str) -> None:
        if delta and self.show_reasoning:
            self._dispatch("_stream_reasoning", delta)

    def end_assistant(self) -> None:
        self._dispatch("_end_assistant")

    def tool_start(self, name: str, args: dict[str, Any]) -> None:
        self._dispatch("_tool_start", name, args)

    def tool_result(self, name: str, result: str) -> None:
        self._dispatch("_tool_result", name, result)

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

    def _dispatch(self, method: str, *args: Any) -> Any:
        callback = getattr(self.app, method)
        if threading.get_ident() == self.thread_id:
            return callback(*args)
        return self.app.call_from_thread(callback, *args)

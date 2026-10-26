from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text

from .config import Config, data_dir
from .tokens import truncate_text
from .types import Completion, Usage
from .version import __author__, __github__, __portfolio__, __version__

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _safe(text: str) -> str:
    cleaned = ANSI_RE.sub("", text)
    return "".join(
        char for char in cleaned if char in "\n\t" or ord(char) >= 32
    )


class NullUI:
    interactive = False

    def stream_text(self, delta: str) -> None:
        return None

    def stream_reasoning(self, delta: str) -> None:
        return None

    def end_assistant(self) -> None:
        return None

    def tool_start(self, name: str, args: dict[str, Any]) -> None:
        return None

    def tool_result(self, name: str, result: str) -> None:
        return None

    def warn(self, message: str) -> None:
        return None

    def error(self, message: str) -> None:
        return None

    def info(self, message: str) -> None:
        return None

    def success(self, message: str) -> None:
        return None

    def confirm_tool(self, name: str, args: dict[str, Any]) -> bool:
        return False

    def ask(self, prompt: str = "> ") -> str:
        raise EOFError


class ConsoleUI:
    def __init__(
        self,
        config: Config,
        *,
        console: Console | None = None,
        show_reasoning: bool | None = None,
        quiet: bool = False,
        interactive: bool | None = None,
    ) -> None:
        self.config = config
        self.console = console or Console()
        self.show_reasoning = (
            config.show_reasoning if show_reasoning is None else show_reasoning
        )
        self.quiet = quiet
        self.interactive = sys.stdin.isatty() if interactive is None else interactive
        self._in_text = False
        self._in_reasoning = False
        self._prompt_session: Any = None
        self._history_path = data_dir() / "history"

    def stream_text(self, delta: str) -> None:
        if not delta:
            return
        if self._in_reasoning:
            self.console.print()
            self._in_reasoning = False
        text = _safe(delta)
        if not text:
            return
        self.console.print(text, end="", markup=False, highlight=False, soft_wrap=True)
        self._in_text = True

    def stream_reasoning(self, delta: str) -> None:
        if not self.show_reasoning or not delta or self._in_text:
            return
        if not self._in_reasoning:
            self.console.print(Text("réflexion  ", style="dim italic"), end="")
            self._in_reasoning = True
        self.console.print(
            _safe(delta),
            end="",
            style="dim italic",
            markup=False,
            highlight=False,
            soft_wrap=True,
        )

    def end_assistant(self) -> None:
        if self._in_text or self._in_reasoning:
            self.console.print()
        self._in_text = False
        self._in_reasoning = False

    def tool_start(self, name: str, args: dict[str, Any]) -> None:
        self.end_assistant()
        line = Text("→ ", style="cyan")
        line.append(name, style="bold cyan")
        if not self.quiet:
            preview = _format_tool_args(name, args)
            if preview:
                line.append("  " + preview, style="dim")
        self.console.print(line)

    def tool_result(self, name: str, result: str) -> None:
        safety_text = " ".join(result.split())
        is_error = safety_text.startswith(("ERREUR", "Action refusee", "TIMEOUT"))
        if "exit_code:" in safety_text and "exit_code: 0" not in safety_text:
            is_error = True
        if self.quiet and not is_error:
            return
        first = " ".join(result.strip().splitlines()[:1])
        style = "red" if is_error else "dim"
        self.console.print(Text("  " + truncate_text(first, 260), style=style))
        if not self.quiet and "\n" in result.strip():
            lines = result.strip().splitlines()[1:6]
            for line in lines:
                self.console.print(Text("  " + line[:220], style="dim"))
            total = len(result.strip().splitlines())
            if total > 6:
                self.console.print(Text(f"  ... ({total} lignes)", style="dim"))

    def warn(self, message: str) -> None:
        self.end_assistant()
        self.console.print(Text("  " + _safe(message), style="yellow"))

    def error(self, message: str) -> None:
        self.end_assistant()
        self.console.print(Text("ERREUR: " + _safe(message), style="bold red"))

    def info(self, message: str) -> None:
        self.end_assistant()
        self.console.print(Text("  " + _safe(message), style="dim"))

    def success(self, message: str) -> None:
        self.end_assistant()
        self.console.print(Text("  " + _safe(message), style="green"))

    def confirm_tool(self, name: str, args: dict[str, Any]) -> bool:
        self.end_assistant()
        body = Text()
        body.append(_format_tool_args(name, args, full=True), style="")
        body.append("\n\nCette action va modifier le système.", style="bold")
        self.console.print(
            Panel(
                body,
                title="Autorisation requise",
                title_align="left",
                border_style="yellow",
                box=box.ROUNDED,
                padding=(0, 1),
                expand=False,
            )
        )
        if not self.interactive:
            self.warn("Mode non interactif: action refusee. Relance avec --yolo si necessaire.")
            return False
        try:
            return bool(
                Confirm.ask(
                    "Autoriser cette action ?",
                    default=False,
                    console=self.console,
                )
            )
        except (EOFError, KeyboardInterrupt):
            return False

    def ask(self, prompt: str = "> ") -> str:
        if not self.interactive:
            line = sys.stdin.readline()
            if not line:
                raise EOFError
            return line.rstrip("\n")
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import FileHistory

            if self._prompt_session is None:
                self._history_path.parent.mkdir(parents=True, exist_ok=True)
                self._prompt_session = PromptSession(
                    history=FileHistory(str(self._history_path)),
                    enable_history_search=True,
                )
            return self._prompt_session.prompt(prompt)
        except ImportError:
            return input(prompt)
        except EOFError:
            raise
        except KeyboardInterrupt:
            raise

    def welcome(
        self,
        *,
        model: str,
        provider: str | None,
        chain: list[str],
        permissions: str,
        session_id: str,
        cwd: Path,
    ) -> None:
        body = Text()
        body.append("Agent de codage pour le terminal\n\n", style="dim")
        body.append("modèle       ", style="dim")
        body.append(model)
        body.append("\n")
        body.append("fournisseur  ", style="dim")
        body.append(provider or "automatique")
        body.append("\n")
        if chain:
            body.append("route        ", style="dim")
            body.append(" · ".join(chain[:3]) + "\n")
        body.append("permissions  ", style="dim")
        body.append(permissions + "\n")
        body.append("session      ", style="dim")
        body.append(session_id + "\n")
        body.append("dossier      ", style="dim")
        body.append(str(cwd) + "\n")
        body.append("\nCréé par ", style="dim")
        body.append(__author__, style="bold")
        body.append("\nGitHub       ", style="dim")
        body.append(__github__, style=f"cyan underline link {__github__}")
        body.append("\nPortfolio    ", style="dim")
        body.append(__portfolio__, style=f"cyan underline link {__portfolio__}")
        body.append("\n\n")
        body.append("/help commandes · /quit quitter", style="dim")
        self.console.print(
            Panel(
                body,
                title=f"zerocode {__version__}",
                title_align="left",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(0, 1),
                expand=False,
            )
        )

    def usage(self, usage: Usage, completion: Completion | None = None) -> None:
        if usage.requests == 0 and usage.total_tokens == 0:
            return
        total = f"{usage.total_tokens:,}".replace(",", " ")
        text = f"{total} jetons · {usage.requests} requêtes"
        if usage.estimated:
            text += " · estimation"
        if completion is not None:
            text = f"{completion.provider}/{completion.model} · " + text
        self.console.print(Text("  " + text, style="dim"))

    def todos(self, todos: list[dict[str, Any]]) -> None:
        if not todos:
            self.info("Aucune tache planifiee.")
            return
        markers = {
            "pending": "[ ]",
            "in_progress": "[~]",
            "completed": "[x]",
            "cancelled": "[-]",
        }
        for todo in todos:
            marker = markers.get(str(todo.get("status")), "[ ]")
            self.console.print(f"{marker} {todo.get('content', '')}")


def _format_tool_args(
    name: str,
    args: dict[str, Any],
    *,
    full: bool = False,
) -> str:
    limit = 1_200 if full else 520
    if not full:
        if name == "bash":
            return truncate_text("$ " + str(args.get("command", "")), 220)
        if name in {"read", "list", "write", "edit"}:
            return truncate_text(str(args.get("path", "")), 220)
        if name == "grep":
            return truncate_text(
                f"{args.get('pattern', '')} · {args.get('path', '.')}",
                220,
            )
        if name == "todo_write":
            todos = args.get("todos")
            count = len(todos) if isinstance(todos, list) else 0
            return f"{count} tâche(s)"
    if name == "bash":
        command = str(args.get("command", ""))
        description = str(args.get("description", "")).strip()
        text = f"$ {command}"
        if description:
            text += f"\n  ({description})"
        return truncate_text(text, limit)
    if name in {"write", "edit"}:
        path = str(args.get("path", ""))
        if name == "write":
            content = str(args.get("content", ""))
            return truncate_text(f"{path}\n{content}", limit)
        old = str(args.get("old_string", ""))
        new = str(args.get("new_string", ""))
        return truncate_text(f"{path}\n- {old}\n+ {new}", limit)
    try:
        rendered = json.dumps(args, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        rendered = str(args)
    return truncate_text(rendered, limit)

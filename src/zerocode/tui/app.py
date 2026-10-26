from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich import box
from rich.panel import Panel
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    DirectoryTree,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    Static,
)

from ..errors import ZeroCodeError
from ..ui import _format_tool_args
from ..version import __author__, __github__, __portfolio__, __version__
from .bridge import TuiBridge
from .commands import ARG_COMMANDS, COMMANDS, CommandHandler
from .screens import CommandPaletteScreen, ConfirmScreen, FilePickerScreen, HelpScreen
from .widgets import PromptInput, ThinkingIndicator, ToolCard

IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".next",
    ".nuxt",
    "dist",
    "build",
    "target",
    "vendor",
}


class SessionItem(ListItem):
    def __init__(
        self,
        session_id: str,
        title: str,
        meta: str,
        *,
        current: bool = False,
    ) -> None:
        body = Text()
        body.append("● " if current else "  ", style="cyan" if current else "dim")
        body.append(title, style="bold" if current else "")
        body.append("\n   " + meta, style="dim")
        super().__init__(Static(body, classes="session-label"))
        self.session_id = session_id
        if current:
            self.add_class("current")


class ZeroCodeApp(App[None]):
    TITLE = "zerocode"
    SUB_TITLE = f"par {__author__}"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+k", "command_palette", "Commandes", priority=True),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", priority=True),
        Binding("tab", "cycle_mode", "Panneau", priority=True, show=False),
        Binding("shift+tab", "cycle_work_mode", "Build/Plan", priority=True, show=False),
        Binding("f1", "help", "Aide", priority=True),
        Binding("f2", "toggle_last_tool", "Dernier outil", priority=True),
        Binding("f6", "cycle_focus", "Focus suivant", priority=True),
        Binding("ctrl+q", "request_exit", "Quitter", priority=True),
    ]

    CSS = """
    Screen {
        background: $surface;
        color: $text;
    }

    #brandbar {
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text-muted;
    }

    #body {
        height: 1fr;
    }

    #modebar {
        height: 1;
        padding: 0 1;
        background: $panel;
    }

    #sidebar {
        width: 32;
        min-width: 24;
        padding: 0 1;
        border-right: solid $primary;
        background: $panel;
    }

    #sidebar.hidden {
        display: none;
    }

    .section {
        margin-top: 1;
        color: $accent;
        text-style: bold;
    }

    #files {
        height: 1fr;
        min-height: 8;
        background: transparent;
        scrollbar-size-vertical: 1;
    }

    #sessions {
        height: 10;
        background: transparent;
        scrollbar-size-vertical: 1;
    }

    SessionItem.current {
        background: $boost;
    }

    .session-label {
        width: 100%;
        height: auto;
    }

    SessionItem.current .session-label {
        color: $accent;
    }

    #main {
        width: 1fr;
    }

    #chat {
        height: 1fr;
        padding: 0 1;
        scrollbar-size-vertical: 1;
    }

    #inspector {
        height: 12;
        border-top: solid $primary;
        padding: 0 1;
        background: $panel;
    }

    #inspector.hidden {
        display: none;
    }

    #inspector-title {
        color: $accent;
        text-style: bold;
    }

    #inspector-content {
        height: 1fr;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text-muted;
    }

    #prompt {
        margin: 0 1 1 1;
        border: tall $primary;
    }

    .welcome {
        margin: 1 0;
    }

    .user-message {
        margin: 1 0 1 0;
        padding: 0 1;
        border-left: thick $primary;
    }

    .assistant {
        margin: 1 0;
    }

    .reasoning {
        color: $text-muted;
        text-style: italic;
        margin: 0 0 1 0;
    }

    .thinking {
        color: $text-muted;
        margin: 0 0 1 0;
    }

    .tool-line {
        color: $text-muted;
        margin: 0;
    }

    ToolCard {
        height: auto;
        margin: 0 0 1 0;
        padding: 0;
        border: none;
        border-left: heavy $primary;
        background: transparent;
    }

    ToolCard.running {
        border-left: heavy $warning;
    }

    ToolCard.success {
        border-left: heavy $success;
    }

    ToolCard.error {
        border-left: heavy $error;
    }

    ToolCard CollapsibleTitle {
        height: auto;
        padding: 0 1;
        background: transparent;
    }

    ToolCard > Contents {
        padding: 0 1 0 3;
    }

    .tool-output {
        color: $text-muted;
        height: auto;
    }

    .notice {
        margin: 0 0 1 0;
        padding: 0 1;
    }

    .notice.warning {
        color: $warning;
    }

    .notice.error {
        color: $error;
        text-style: bold;
    }

    .notice.success {
        color: $success;
    }

    .notice.info {
        color: $text-muted;
    }

    ConfirmScreen, FilePickerScreen, CommandPaletteScreen, HelpScreen {
        align: center middle;
        background: $background 60%;
    }

    #confirm-dialog {
        width: 72;
        max-width: 90%;
        height: auto;
        padding: 1 2;
        border: thick $warning;
        background: $panel;
    }

    #confirm-title, .palette-title {
        color: $accent;
        text-style: bold;
        height: 1;
    }

    #confirm-scroll {
        height: auto;
        max-height: 16;
        margin: 1 0;
        scrollbar-size-vertical: 1;
    }

    #confirm-body {
        height: auto;
    }

    #confirm-hint {
        height: 1;
        color: $text-muted;
    }

    #confirm-actions {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }

    #confirm-actions Button {
        margin-left: 1;
    }

    #palette-dialog {
        width: 72;
        max-width: 90%;
        height: 70%;
        padding: 1 2;
        border: thick $primary;
        background: $panel;
    }

    #file-filter, #command-filter {
        margin-bottom: 1;
    }

    #file-options, #command-options {
        height: 1fr;
        scrollbar-size-vertical: 1;
    }

    #help-dialog {
        width: 82;
        max-width: 94%;
        height: 82%;
        padding: 1 2;
        border: thick $primary;
        background: $panel;
    }

    #help-scroll {
        height: 1fr;
        scrollbar-size-vertical: 1;
    }

    .palette-hint {
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        config: Any,
        agent: Any,
        router: Any,
        store: Any,
        permissions: Any,
        context: Any,
        chain: list[str],
    ) -> None:
        super().__init__()
        self.config = config
        self.agent = agent
        self.router = router
        self.store = store
        self.permissions = permissions
        self.context = context
        self.chain = chain
        self.bridge = TuiBridge(self)
        self.command_handler = CommandHandler(self)
        self.agent.ui = self.bridge
        self.agent.tools.ui = self.bridge
        self.router.ui = self.bridge
        self._thread_id = threading.get_ident()
        self._assistant: Markdown | None = None
        self._assistant_buffer = ""
        self._reasoning: Static | None = None
        self._reasoning_buffer = ""
        self._last_render = 0.0
        self._files: list[str] = []
        self._tool_cards: list[ToolCard] = []
        self._thinking: ThinkingIndicator | None = None
        self._mode = "chat"
        self.work_mode = getattr(agent, "mode", "build")
        self._busy = False
        self._opening_picker = False
        self._branch = ""
        self._spinner_index = 0
        self._spinner_timer: Any = None

    def compose(self) -> ComposeResult:
        yield Static("", id="brandbar")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Label("PROJET", id="project-title", classes="section")
                yield DirectoryTree(str(self.context.cwd), id="files")
                yield Label("SESSIONS", classes="section")
                yield ListView(id="sessions")
            with Vertical(id="main"):
                yield Static("", id="modebar")
                yield VerticalScroll(id="chat")
                with Vertical(id="inspector", classes="hidden"):
                    yield Label("", id="inspector-title")
                    yield Static("", id="inspector-content")
                yield Static("", id="status")
                yield PromptInput(
                    placeholder="Demandez quelque chose…  @ fichiers  Ctrl+K commandes",
                    id="prompt",
                )

    def on_mount(self) -> None:
        self._thread_id = threading.get_ident()
        self._files = _list_project_files(self.context.cwd)
        self._branch = _git_branch(self.context.cwd)
        self.work_mode = getattr(self.agent, "mode", self.work_mode)
        self._refresh_brandbar()
        self._refresh_project_title()
        self._refresh_modebar()
        self._refresh_prompt_placeholder()
        self._refresh_sessions()
        self._refresh_status()
        self._refresh_inspector()
        if len(self.agent.messages) > 1:
            self.render_session(self.agent.session)
        else:
            self.show_welcome()
        self.query_one("#prompt", Input).focus()

    def on_unmount(self) -> None:
        self._opening_picker = False
        self._stop_spinner()
        if self._thinking is not None:
            self._thinking.stop()
            self._thinking = None

    def on_resize(self) -> None:
        self._refresh_status()
        self._refresh_brandbar()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "prompt":
            return
        if event.value.endswith("@") and (
            len(event.value) == 1 or event.value[-2].isspace()
        ):
            event.input.value = event.value[:-1]
            self._open_file_picker()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "prompt":
            return
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if isinstance(event.input, PromptInput):
            event.input.remember(text)
        if self._busy:
            self.notice("Un tour est déjà en cours.", "warning")
            return
        if text.startswith("/"):
            self.command_handler.handle(text)
        else:
            self.submit_prompt(text)

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        try:
            path = event.path.resolve().relative_to(self.context.cwd)
        except ValueError:
            path = event.path
        self._insert_prompt(f"{path} ")
        self.query_one("#prompt", Input).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not isinstance(event.item, SessionItem):
            return
        if self._busy:
            self.notice("Attends la fin du tour avant de changer de session.", "warning")
            return
        session = self.store.load(event.item.session_id)
        if session is None:
            self.notice(f"Session introuvable : {event.item.session_id}", "warning")
            return
        self.agent.load_session(session)
        self.permissions.mode = self.config.permissions
        self.set_work_mode("build", quiet=True)
        self.config.base_dir = self.context.cwd
        self.reload_project(self.context.cwd)
        self.render_session(session)
        self.notice(f"Session reprise : {session.id}", "success")
        self.refresh_after_command()
        self.query_one("#prompt", Input).focus()

    def submit_prompt(self, text: str) -> None:
        self._mount_user(text)
        self._start_thinking()
        self._busy = True
        self.query_one("#prompt", Input).disabled = True
        self._start_spinner()
        self._refresh_status()
        self._scroll_chat()
        self._run_turn(text)

    @work(thread=True, exclusive=True, group="agent")
    def _run_turn(self, text: str) -> None:
        try:
            self.agent.run_turn(text)
        except KeyboardInterrupt:
            self._call_main("_turn_interrupted")
        except ZeroCodeError as exc:
            self._call_main("_turn_error", str(exc))
        except Exception as exc:  # noqa: BLE001 - l'interface doit rester utilisable
            self._call_main("_turn_error", f"{exc.__class__.__name__}: {exc}")
        finally:
            self._call_main("_finish_turn")

    def _call_main(self, method: str, *args: Any) -> None:
        callback = getattr(self, method)
        if threading.get_ident() == self._thread_id:
            callback(*args)
        else:
            with contextlib.suppress(RuntimeError):
                self.call_from_thread(callback, *args)

    def _finish_turn(self) -> None:
        self._busy = False
        self._stop_spinner()
        self._stop_thinking()
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = False
        prompt.focus()
        self._refresh_status()
        self._refresh_sessions()
        self._refresh_inspector()
        if self._is_following():
            self._scroll_chat()

    def _start_spinner(self) -> None:
        self._stop_spinner()
        self._spinner_index = 0
        self._spinner_timer = self.set_interval(0.12, self._spin)

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    def _spin(self) -> None:
        if not self._busy:
            self._stop_spinner()
            return
        self._spinner_index = (self._spinner_index + 1) % len("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
        self._refresh_status()

    def _turn_interrupted(self) -> None:
        self._stop_thinking()
        self.notice("Tour interrompu.", "warning")

    def _turn_error(self, message: str) -> None:
        self._stop_thinking()
        self.notice(f"ERREUR : {message}", "error")

    def action_command_palette(self) -> None:
        if self._busy or isinstance(self.screen, ModalScreen):
            return

        def receive(command: str | None) -> None:
            if not command:
                return
            base = command.split(" ", 1)[0]
            if base in ARG_COMMANDS:
                self._insert_prompt(base + " ")
            else:
                self.command_handler.handle(command)

        self.push_screen(CommandPaletteScreen(COMMANDS), receive)

    def action_toggle_sidebar(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        self.query_one("#sidebar").toggle_class("hidden")

    def action_cycle_mode(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        modes = ["chat", "todos", "tools"]
        self.set_mode(modes[(modes.index(self._mode) + 1) % len(modes)])

    def action_cycle_work_mode(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        if self._busy:
            self.notice("Attends la fin du tour pour changer de mode.", "warning")
            return
        next_mode = "plan" if self.work_mode == "build" else "build"
        self.set_work_mode(next_mode)

    def set_work_mode(self, mode: str, *, quiet: bool = False) -> None:
        if mode not in {"build", "plan", "full-stack"}:
            return
        if self._busy:
            self.notice("Attends la fin du tour pour changer de mode.", "warning")
            return
        self.work_mode = mode
        setter = getattr(self.agent, "set_mode", None)
        if callable(setter):
            setter(mode)
        self.bridge.show_reasoning = self.config.show_reasoning
        self._refresh_modebar()
        self._refresh_status()
        self._refresh_inspector()
        self._refresh_prompt_placeholder()
        if quiet:
            return
        if mode == "plan":
            self.notice(
                "Mode PLAN : lecture seule. write/edit/bash sont désactivés.",
                "info",
            )
        elif mode == "full-stack":
            self.notice(
                "Mode FULL-STACK : autonomie maximale · raisonnement max · "
                "500 étapes · 128k sortie · permissions allow · timeout 1 h.",
                "success",
            )
        else:
            self.notice("Mode BUILD : modifications autorisées.", "success")

    def action_help(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        self.show_help()

    def action_toggle_last_tool(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        if not self._tool_cards:
            self.notice("Aucune carte d'outil à replier.", "info")
            return
        card = self._tool_cards[-1]
        card.collapsed = not card.collapsed
        card.scroll_visible(animate=False)

    def action_cycle_focus(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        widgets = [
            self.query_one("#prompt", Input),
            self.query_one("#files", DirectoryTree),
            self.query_one("#sessions", ListView),
            self.query_one("#chat", VerticalScroll),
        ]
        current = self.focused
        if current in widgets:
            widgets[(widgets.index(current) + 1) % len(widgets)].focus()
        else:
            widgets[0].focus()

    def action_request_exit(self) -> None:
        self.request_exit()

    def request_exit(self) -> None:
        if self._busy:
            self.notice("Un tour est en cours. Attends sa fin avant de quitter.", "warning")
            return
        self.exit()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        panel = self.query_one("#inspector")
        panel.set_class(mode == "chat", "hidden")
        self._refresh_modebar()
        self._refresh_inspector()

    def show_help(self) -> None:
        body = Text()
        body.append("Raccourcis\n", style="bold cyan")
        for key, description in (
            ("Ctrl+K", "palette de commandes"),
            ("@", "rechercher un fichier"),
            ("Shift+Tab", "mode build / plan"),
            ("Tab", "chat / tâches / outils"),
            ("↑ ↓", "historique des demandes"),
            ("F2", "replier / ouvrir le dernier outil"),
            ("F6", "focus prompt → fichiers → sessions → chat"),
            ("Ctrl+B", "afficher ou masquer la sidebar"),
            ("F1", "aide et commandes"),
            ("Ctrl+Q", "quitter"),
        ):
            body.append(f"  {key:<10}", style="bold")
            body.append(description + "\n")
        body.append("\nCommandes\n", style="bold cyan")
        for command, description in COMMANDS:
            body.append(f"  {command:<34}", style="bold")
            body.append(description + "\n")
        body.append("\nCréé par ", style="dim")
        body.append(__author__, style="bold")
        body.append("\nGitHub     ", style="dim")
        body.append(__github__, style=f"cyan underline link {__github__}")
        body.append("\nPortfolio  ", style="dim")
        body.append(__portfolio__, style=f"cyan underline link {__portfolio__}")
        self.push_screen(HelpScreen(body, self.context.cwd))

    def show_welcome(self) -> None:
        body = Text()
        body.append("Agent de codage pour le terminal\n\n", style="dim")
        body.append("modèle       ", style="dim")
        body.append(self.config.model)
        body.append("\nfournisseur  ", style="dim")
        body.append(self.config.provider or "automatique")
        body.append("\n")
        if self.chain:
            body.append("route        ", style="dim")
            body.append(" · ".join(self.chain[:3]) + "\n")
        body.append("mode         ", style="dim")
        body.append(self.work_mode + "\n")
        body.append("permissions  ", style="dim")
        body.append(self.permissions.mode + "\n")
        if self._branch:
            body.append("branche      ", style="dim")
            body.append(self._branch + "\n")
        body.append("dossier      ", style="dim")
        body.append(str(self.context.cwd) + "\n")
        body.append("\nCréé par ", style="dim")
        body.append(__author__, style="bold")
        body.append("\nGitHub       ", style="dim")
        body.append(__github__, style=f"cyan underline link {__github__}")
        body.append("\nPortfolio    ", style="dim")
        body.append(__portfolio__, style=f"cyan underline link {__portfolio__}")
        body.append("\n\n")
        body.append("Ctrl+K commandes · @ fichiers · Tab panneaux · F1 aide", style="dim")
        panel = Panel(
            body,
            title=f"zerocode {__version__}",
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 1),
            expand=False,
        )
        self._mount(Static(panel, classes="welcome"))
        self._scroll_chat()

    def render_session(self, session: Any) -> None:
        self.clear_chat()
        self.show_welcome()
        for message in session.messages:
            role = message.get("role")
            content = str(message.get("content") or "")
            if role == "user" and content:
                self._mount_user(content)
            elif role == "assistant" and content:
                self._mount(Markdown(content, classes="assistant"))
        self._scroll_chat()

    def clear_chat(self) -> None:
        self._stop_thinking()
        self.query_one("#chat", VerticalScroll).remove_children()
        self._assistant = None
        self._assistant_buffer = ""
        self._reasoning = None
        self._reasoning_buffer = ""
        self._tool_cards = []

    def notice(self, message: str, kind: str = "info") -> None:
        style = {
            "warning": "yellow",
            "error": "bold red",
            "success": "green",
            "info": "dim",
        }.get(kind, "dim")
        label = "ERREUR " if kind == "error" else ""
        self._mount(Static(Text(label + message, style=style), classes=f"notice {kind}"))
        self._scroll_chat()

    def show_list(self, title: str, lines: list[str]) -> None:
        body = Text()
        body.append(title + "\n\n", style="bold cyan")
        body.append("\n".join(lines) if lines else "Aucun résultat.", style="")
        self._mount(Static(body, classes="notice"))
        self._scroll_chat()

    def show_todos(self, todos: list[dict[str, Any]]) -> None:
        self._mode = "todos"
        self.query_one("#inspector").remove_class("hidden")
        self._refresh_modebar()
        self._refresh_inspector()

    def refresh_after_command(self) -> None:
        self._refresh_status()
        self._refresh_brandbar()
        self._refresh_sessions()

    def refresh_sessions(self) -> None:
        self._refresh_sessions()

    def reload_project(self, target: Path) -> None:
        tree = self.query_one("#files", DirectoryTree)
        tree.path = target
        self._files = _list_project_files(target)
        self._branch = _git_branch(target)
        self._refresh_brandbar()
        self._refresh_project_title()

    def _mount_user(self, text: str) -> None:
        body = Text.assemble(("vous\n", "bold cyan"), (text, ""))
        self._mount(Static(body, classes="user-message"))

    def _mount(self, widget: Any) -> None:
        self.query_one("#chat", VerticalScroll).mount(widget)

    def _insert_prompt(self, text: str) -> None:
        prompt = self.query_one("#prompt", Input)
        prompt.insert_text_at_cursor(text)

    def _open_file_picker(self) -> None:
        if self._opening_picker or self._busy:
            return
        self._opening_picker = True
        self.push_screen(FilePickerScreen(self._files), self._file_selected)

    def _file_selected(self, path: str | None) -> None:
        self._opening_picker = False
        if path:
            self._insert_prompt(path + " ")
        self.query_one("#prompt", Input).focus()

    def _stream_text(self, delta: str) -> None:
        self._stop_thinking()
        follow = self._is_following()
        self._assistant_buffer += delta
        if self._assistant is None:
            self._assistant = Markdown("", classes="assistant")
            self._mount(self._assistant)
        now = time.monotonic()
        if now - self._last_render >= 0.05:
            self._assistant.update(self._assistant_buffer)
            self._last_render = now
            if follow:
                self._scroll_chat()

    def _stream_reasoning(self, delta: str) -> None:
        self._stop_thinking()
        follow = self._is_following()
        self._reasoning_buffer += delta
        if self._reasoning is None:
            self._reasoning = Static("", classes="reasoning")
            self._mount(self._reasoning)
        now = time.monotonic()
        if now - self._last_render >= 0.05:
            text = Text("réflexion  " + self._reasoning_buffer, style="dim italic")
            self._reasoning.update(text)
            self._last_render = now
            if follow:
                self._scroll_chat()

    def _start_thinking(self) -> None:
        if self._thinking is not None:
            return
        indicator = ThinkingIndicator()
        self._thinking = indicator
        self._mount(indicator)
        self._scroll_chat()

    def _stop_thinking(self) -> None:
        indicator = self._thinking
        if indicator is None:
            return
        self._thinking = None
        indicator.stop()
        self.call_after_refresh(self._discard_thinking, indicator)

    def _discard_thinking(self, indicator: ThinkingIndicator) -> None:
        with contextlib.suppress(Exception):
            indicator.remove()

    def _end_assistant(self) -> None:
        follow = self._is_following()
        if self._assistant is not None:
            self._assistant.update(self._assistant_buffer)
            self._assistant = None
            self._assistant_buffer = ""
        if self._reasoning is not None:
            text = Text("réflexion  " + self._reasoning_buffer, style="dim italic")
            self._reasoning.update(text)
            self._reasoning = None
            self._reasoning_buffer = ""
        if follow:
            self._scroll_chat()

    def _tool_start(self, name: str, args: dict[str, Any]) -> None:
        self._stop_thinking()
        self._end_assistant()
        follow = self._is_following()
        card = ToolCard(name, _format_tool_args(name, args))
        self._tool_cards.append(card)
        self._mount(card)
        if follow:
            self._scroll_chat()

    def _tool_result(self, name: str, result: str) -> None:
        follow = self._is_following()
        card = next(
            (
                candidate
                for candidate in reversed(self._tool_cards)
                if candidate.tool_name == name and not candidate.done
            ),
            None,
        )
        if card is None:
            card = ToolCard(name, "")
            self._tool_cards.append(card)
            self._mount(card)
        card.set_result(result)
        if name == "todo_write":
            self._refresh_inspector()
        if follow:
            self._scroll_chat()

    def ask_tool_permission(self, name: str, args: dict[str, Any], callback: Any) -> None:
        preview = _format_tool_args(name, args, full=True)
        self.push_screen(ConfirmScreen(name, preview), callback)

    def _is_following(self) -> bool:
        try:
            chat = self.query_one("#chat", VerticalScroll)
        except Exception:  # noqa: BLE001 - montage initial
            return True
        return chat.is_vertical_scroll_end or chat.max_scroll_y - chat.scroll_y <= 3

    def _scroll_chat(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

    def _refresh_status(self) -> None:
        try:
            status = self.query_one("#status", Static)
        except Exception:  # noqa: BLE001 - montage initial
            return
        route = self.router.preview()
        usage = self.agent.usage
        width = self.size.width
        text = Text()
        text.append(f"{self.config.model}", style="bold cyan")
        if width >= 70:
            text.append(f"  {self.config.provider or 'auto'}", style="dim")
        if width >= 92:
            text.append("  ·  ", style="dim")
            text.append(" → ".join(route[:2]) if route else "aucune route", style="dim")
        if width >= 64:
            text.append("  ·  ", style="dim")
            text.append(
                f"perms {self.permissions.mode}",
                style="yellow" if self.permissions.mode != "allow" else "green",
            )
        if width >= 108:
            text.append("  ·  ", style="dim")
            text.append(f"session {self.agent.session.id[-8:]}", style="dim")
        if width >= 96:
            text.append("  ·  ", style="dim")
            text.append(f"{usage.total_tokens:,} jetons".replace(",", " "), style="dim")
        if self._busy:
            frame = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[self._spinner_index]
            text.append(f"  ·  {frame} travail…", style="bold yellow")
        status.update(text)

    def _refresh_brandbar(self) -> None:
        try:
            bar = self.query_one("#brandbar", Static)
        except Exception:  # noqa: BLE001 - montage initial
            return
        text = Text()
        text.append(f"zerocode {__version__}", style="bold cyan")
        text.append("  par ", style="dim")
        text.append(__author__, style="bold")
        text.append("  ·  ", style="dim")
        text.append(__github__, style=f"cyan underline link {__github__}")
        if self.size.width >= 110:
            text.append("  ·  ", style="dim")
            text.append(__portfolio__, style=f"cyan underline link {__portfolio__}")
        bar.update(text)

    def _refresh_project_title(self) -> None:
        try:
            title = self.query_one("#project-title", Label)
        except Exception:  # noqa: BLE001 - montage initial
            return
        text = Text("PROJET", style="bold")
        text.append("  " + self.context.cwd.name, style="dim")
        if self._branch:
            text.append("  " + self._branch, style="cyan")
        title.update(text)

    def _refresh_modebar(self) -> None:
        try:
            bar = self.query_one("#modebar", Static)
        except Exception:  # noqa: BLE001 - montage initial
            return
        text = Text()
        for mode, label in (
            ("build", "BUILD"),
            ("plan", "PLAN"),
            ("full-stack", "FULL-STACK"),
        ):
            active = self.work_mode == mode
            if active:
                style = {
                    "build": "bold black on green",
                    "plan": "bold black on yellow",
                    "full-stack": "bold black on magenta",
                }[mode]
            else:
                style = "dim"
            text.append(f" {label} ", style=style)
            text.append(" ")
        text.append("·  ", style="dim")
        for mode, label in (("chat", "CHAT"), ("todos", "TÂCHES"), ("tools", "OUTILS")):
            active = self._mode == mode
            text.append(
                f" {label} ",
                style="bold black on cyan" if active else "dim",
            )
            text.append(" ")
        if self.size.width >= 116:
            text.append(" Shift+Tab mode · Tab panneaux", style="dim")
        bar.update(text)

    def _refresh_prompt_placeholder(self) -> None:
        try:
            prompt = self.query_one("#prompt", Input)
        except Exception:  # noqa: BLE001 - montage initial
            return
        if self.work_mode == "plan":
            prompt.placeholder = (
                "Mode plan (lecture seule) — décris ce que tu veux planifier…  " "Ctrl+K commandes"
            )
        elif self.work_mode == "full-stack":
            prompt.placeholder = (
                "Mode full-stack autonome — décris le projet complet à construire…  "
                "Ctrl+K commandes"
            )
        else:
            prompt.placeholder = (
                "Demandez quelque chose…  @ fichiers  Ctrl+K commandes"
            )

    def _refresh_sessions(self) -> None:
        try:
            list_view = self.query_one("#sessions", ListView)
        except Exception:  # noqa: BLE001 - montage initial
            return
        list_view.clear()
        current_id = self.agent.session.id
        for item in self.store.list()[:30]:
            current = item["id"] == current_id
            stamp = _relative_time(str(item.get("updated_at", "")))
            title = str(item.get("title") or item["id"][-8:])
            meta = f"{stamp:<4}  {item['model']}"
            list_view.append(SessionItem(item["id"], title, meta, current=current))

    def _refresh_inspector(self) -> None:
        try:
            content = self.query_one("#inspector-content", Static)
            title = self.query_one("#inspector-title", Label)
        except Exception:  # noqa: BLE001 - montage initial
            return
        if self._mode == "todos":
            title.update("PLAN DE TRAVAIL")
            content.update(_todos_text(self.context.todos))
        elif self._mode == "tools":
            suffix = {
                "plan": " · LECTURE SEULE",
                "full-stack": " · AUTONOME",
            }.get(self.work_mode, "")
            title.update("OUTILS" + suffix)
            tools = self.agent.tools.tools()
            if self.work_mode == "plan":
                tools = [tool for tool in tools if tool.approval == "never"]
            lines = [f"{tool.name:<14} {tool.description}" for tool in tools]
            content.update(Text("\n".join(lines), style="dim"))
        else:
            title.update("")


def _git_branch(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _relative_time(value: str) -> str:
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return ""
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - stamp
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "mnt"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}min"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 7:
        return f"{days}j"
    return stamp.strftime("%d/%m")


def _todos_text(todos: list[dict[str, Any]]) -> Text:
    if not todos:
        return Text("Aucune tâche planifiée.", style="dim")
    markers = {
        "pending": "[ ]",
        "in_progress": "[~]",
        "completed": "[x]",
        "cancelled": "[-]",
    }
    text = Text()
    for todo in todos:
        marker = markers.get(str(todo.get("status")), "[ ]")
        text.append(f"{marker} ", style="cyan")
        text.append(str(todo.get("content", "")) + "\n")
    return text


def _list_project_files(root: Path, limit: int = 5_000) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            return sorted(files)[:limit]
    except (OSError, subprocess.SubprocessError):
        pass

    files: list[str] = []
    for current, directories, names in os.walk(root):
        directories[:] = [name for name in directories if name not in IGNORED_DIRECTORIES]
        for name in names:
            path = Path(current) / name
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            files.append(relative)
            if len(files) >= limit:
                return sorted(files)
    return sorted(files)

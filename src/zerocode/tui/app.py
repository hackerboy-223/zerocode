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
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DirectoryTree,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    Static,
)

from ..checkpoints import CheckpointStore
from ..errors import ZeroCodeError
from ..tools.base import is_secret_path
from ..ui import _format_tool_args, _safe
from ..version import __author__, __github__, __portfolio__, __version__
from .bridge import TuiBridge
from .commands import ARG_COMMANDS, COMMANDS, CommandHandler
from .screens import (
    CommandPaletteScreen,
    ConfirmScreen,
    FilePickerScreen,
    HelpScreen,
    PasswordScreen,
)
from .widgets import PromptInput, ThinkingIndicator, ToolCard, WolfMascot

THINK_MODES = ("off", "low", "high", "max")

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
        body.append(
            "● " if current else "○ ",
            style="bold #7dd3fc" if current else "#4d5867",
        )
        body.append(title, style="bold #e6edf3" if current else "#c9d1d9")
        body.append("\n   " + meta, style="#6f7c8e")
        super().__init__(Static(body, classes="session-label"))
        self.session_id = session_id
        if current:
            self.add_class("current")


class ZeroCodeApp(App[None]):
    TITLE = "zerocode"
    SUB_TITLE = f"Agent de codage · par {__author__}"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+k", "command_palette", "Commandes", priority=True),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", priority=True),
        Binding("tab", "cycle_mode", "Panneau", priority=True, show=False),
        Binding("shift+tab", "cycle_work_mode", "Build/Plan", priority=True, show=False),
        Binding("f1", "help", "Aide", priority=True),
        Binding("f2", "toggle_last_tool", "Dernier outil", priority=True),
        Binding("f3", "cycle_think", "Mode think", priority=True),
        Binding("f6", "cycle_focus", "Focus suivant", priority=True),
        Binding("escape", "interrupt_turn", "Interrompre", show=False),
        Binding("ctrl+q", "request_exit", "Quitter", priority=True),
    ]

    CSS = """
    /* ------------------------------------------------------------------
       Refonte moderne et sobre
       ------------------------------------------------------------------ */
    Screen {
        background: #0b0f14;
        color: #c9d1d9;
    }

    #brandbar {
        height: 2;
        padding: 0 2;
        background: #0b0f14;
        color: #7d8998;
        border-bottom: solid #151d27;
    }

    #body {
        height: 1fr;
    }

    #modebar-row {
        height: 1;
        background: #0b0f14;
        border-bottom: none;
    }

    #modebar {
        width: 1fr;
        height: 1;
        padding: 0 2;
        background: #0b0f14;
    }

    #web-toolbar {
        height: auto;
        padding: 0 1;
        background: #0b0f14;
        border-bottom: solid #151d27;
    }

    .web-chip {
        min-width: 0;
        height: 1;
        margin: 0;
        padding: 0 1;
        border: none;
        background: transparent;
        color: #7d8998;
    }

    .web-chip:hover {
        background: #121a24;
        color: #7dd3fc;
    }

    .web-chip.primary-chip {
        background: #7dd3fc;
        color: #071016;
    }

    .web-chip.primary-chip:hover {
        background: #a5e4ff;
    }

    .web-chip.accent-chip {
        background: transparent;
        color: #a78bfa;
        text-style: bold;
    }

    .web-chip.accent-chip:hover {
        background: #171326;
        color: #c4b5fd;
    }

    .think-chip {
        min-width: 0;
        height: 1;
        margin-right: 1;
    }

    .think-chip.thinking-on {
        background: #171326;
        color: #c4b5fd;
        text-style: bold;
    }

    #sidebar {
        width: 28;
        min-width: 22;
        padding: 0 1;
        border-right: solid #151d27;
        background: #0d1117;
    }

    #sidebar.hidden {
        display: none;
    }

    .section {
        margin-top: 1;
        margin-bottom: 0;
        color: #7d8998;
        text-style: bold;
    }

    #files {
        height: 1fr;
        min-height: 8;
        background: transparent;
        scrollbar-size-vertical: 1;
    }

    #sessions {
        height: 9;
        background: transparent;
        scrollbar-size-vertical: 1;
    }

    SessionItem {
        padding: 0 1;
        background: transparent;
    }

    SessionItem.current {
        background: #111a24;
        border-left: thick #7dd3fc;
    }

    .session-label {
        width: 100%;
        height: auto;
    }

    SessionItem.current .session-label {
        color: #7dd3fc;
    }

    #main {
        width: 1fr;
        background: #0b0f14;
    }

    #chat {
        height: 1fr;
        padding: 1 3;
        scrollbar-size-vertical: 1;
    }

    #inspector {
        height: 12;
        border-top: solid #151d27;
        padding: 1 3;
        background: #0d1117;
    }

    #inspector.hidden {
        display: none;
    }

    #inspector-title {
        color: #7d8998;
        text-style: bold;
        margin-top: 0;
    }

    #inspector-content {
        height: 1fr;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
    }

    #status {
        height: 2;
        padding: 0 2;
        background: #0b0f14;
        color: #6f7c8e;
        border-top: solid #151d27;
    }

    #prompt {
        margin: 0 2;
        border: round #263244;
        background: #0f1620;
        color: #e6edf3;
    }

    #prompt:focus {
        border: round #7dd3fc;
        background: #111a24;
    }

    .welcome {
        margin: 1 0;
    }

    .wolf-mascot {
        width: auto;
        height: auto;
        margin: 1 0 0 0;
        padding: 1 2;
        background: #0f1620;
        border: round #151d27;
        border-left: thick #7dd3fc;
        text-align: center;
    }

    .user-message {
        margin: 1 0;
        padding: 1 2;
        background: #0f1620;
        border: solid #151d27;
        border-left: thick #7dd3fc;
    }

    .agent-header {
        margin: 1 0 0 0;
        color: #7d8998;
    }

    .assistant {
        margin: 0 0 1 0;
        padding: 0 1;
        border-left: thick #151d27;
        background: transparent;
    }

    .reasoning {
        color: #8b97a8;
        text-style: italic;
        margin: 0 0 1 0;
        padding: 0 1;
        border-left: thick #a78bfa;
        background: transparent;
    }

    .thinking {
        color: #8b97a8;
        margin: 0 0 1 0;
        padding: 0 1;
        background: transparent;
        border-left: thick #fbbf24;
    }

    .tool-line {
        color: #7d8998;
        margin: 0;
    }

    ToolCard {
        height: auto;
        margin: 0 0 1 0;
        padding: 0;
        border: none;
        border-left: thick #263244;
        background: #0f1620;
    }

    ToolCard.running {
        border-left: thick #fbbf24;
        background: #121722;
    }

    ToolCard.success {
        border-left: thick #34d399;
        background: #0f1714;
    }

    ToolCard.error {
        border-left: thick #f87171;
        background: #1a1012;
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
        color: #8b97a8;
        height: auto;
    }

    .notice {
        margin: 0 0 1 0;
        padding: 0 1;
        background: transparent;
        border-left: thick #263244;
    }

    .notice.warning {
        color: #fbbf24;
        border-left: thick #fbbf24;
    }

    .notice.error {
        color: #f87171;
        text-style: bold;
        border-left: thick #f87171;
    }

    .notice.success {
        color: #34d399;
        border-left: thick #34d399;
    }

    .notice.info {
        color: #7d8998;
        border-left: thick #7dd3fc;
    }

    ConfirmScreen, PasswordScreen, FilePickerScreen, CommandPaletteScreen, HelpScreen {
        align: center middle;
        background: #05080c 82%;
    }

    #confirm-dialog,
    #password-dialog,
    #palette-dialog,
    #help-dialog {
        padding: 1 2;
        border: round #263244;
        background: #0f1620;
    }

    #confirm-dialog {
        width: 70;
        max-width: 92%;
        height: auto;
    }

    #password-dialog {
        width: 70;
        max-width: 92%;
        height: auto;
    }

    #palette-dialog {
        width: 70;
        max-width: 92%;
        height: 72%;
    }

    #help-dialog {
        width: 78;
        max-width: 94%;
        height: 82%;
    }

    #confirm-title,
    #password-title,
    .palette-title {
        color: #7dd3fc;
        text-style: bold;
        height: 1;
    }

    #confirm-scroll,
    #password-scroll {
        height: auto;
        max-height: 15;
        margin: 1 0;
        scrollbar-size-vertical: 1;
    }

    #confirm-body,
    #password-body {
        height: auto;
    }

    #confirm-hint,
    #password-hint {
        height: 1;
        color: #6f7c8e;
    }

    #confirm-actions,
    #password-actions {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }

    #confirm-actions Button,
    #password-actions Button {
        margin-left: 1;
        min-width: 12;
    }

    #file-filter,
    #command-filter {
        margin-bottom: 1;
    }

    #file-options,
    #command-options {
        height: 1fr;
        scrollbar-size-vertical: 1;
    }

    #help-scroll {
        height: 1fr;
        scrollbar-size-vertical: 1;
    }

    .palette-hint {
        height: 1;
        color: #6f7c8e;
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
        self.checkpoints = CheckpointStore()
        self.pending_images: list[str] = []
        self.agent.checkpoints = self.checkpoints
        self.context.checkpoint = lambda path, before, tool: self.checkpoints.record(
            self.agent.session.id, path, before, tool
        )
        self.bridge = TuiBridge(self)
        self.command_handler = CommandHandler(self)
        self.agent.ui = self.bridge
        self.agent.tools.ui = self.bridge
        self.router.ui = self.bridge
        if hasattr(self.context, "request_sudo_password"):
            self.context.request_sudo_password = self.bridge.request_sudo_password
        if hasattr(self.context, "show_diff"):
            self.context.show_diff = self.bridge.show_diff
        if hasattr(self.context, "stream_output"):
            self.context.stream_output = self.bridge.stream_tool_output
        self._thread_id = threading.get_ident()
        self._assistant: Markdown | None = None
        self._assistant_buffer = ""
        self._assistant_rendered = 0
        self._reasoning: Static | None = None
        self._reasoning_buffer = ""
        self._last_render = 0.0
        self._last_reasoning_render = 0.0
        self._route: list[str] = list(chain)
        self._route_stamp = time.monotonic()
        self._files: list[str] = []
        self._tool_cards: list[ToolCard] = []
        self._pending_notices: list[tuple[str, str]] = []
        self._thinking: ThinkingIndicator | None = None
        self._mode = "chat"
        self.work_mode = getattr(agent, "mode", "build")
        self._busy = False
        self._interrupt_requested = False
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
                with Horizontal(id="modebar-row"):
                    yield Static("", id="modebar")
                    btn_think = Button(
                        self._think_label(),
                        id="chip-think",
                        classes="web-chip think-chip",
                    )
                    btn_think.can_focus = False
                    yield btn_think
                with Horizontal(id="web-toolbar"):
                    btn_build = Button("Build", id="chip-build", classes="web-chip")
                    btn_build.can_focus = False
                    yield btn_build

                    btn_plan = Button("Plan", id="chip-plan", classes="web-chip")
                    btn_plan.can_focus = False
                    yield btn_plan

                    btn_fs = Button(
                        "Full-stack",
                        id="chip-fullstack",
                        classes="web-chip accent-chip",
                    )
                    btn_fs.can_focus = False
                    yield btn_fs

                    btn_files = Button(
                        "Fichier", id="chip-files", classes="web-chip"
                    )
                    btn_files.can_focus = False
                    yield btn_files

                    btn_todos = Button(
                        "Tâches", id="chip-todos", classes="web-chip"
                    )
                    btn_todos.can_focus = False
                    yield btn_todos

                    btn_palette = Button(
                        "Commandes",
                        id="chip-palette",
                        classes="web-chip primary-chip",
                    )
                    btn_palette.can_focus = False
                    yield btn_palette

                yield VerticalScroll(id="chat")
                with Vertical(id="inspector", classes="hidden"):
                    yield Label("", id="inspector-title")
                    yield Static("", id="inspector-content")
                yield Static("", id="status")
                yield PromptInput(
                    placeholder="Demandez quelque chose…  @ fichiers  ·  Ctrl+K commandes",
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
        self.refresh_think_chip()
        self._refresh_prompt_placeholder()
        self._refresh_sessions()
        self._refresh_status()
        self._refresh_inspector()
        if len(self.agent.messages) > 1:
            self.render_session(self.agent.session)
        else:
            self.show_welcome()
        if self._pending_notices:
            pending = list(self._pending_notices)
            self._pending_notices.clear()
            for message, kind in pending:
                self.notice(message, kind)
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "chip-build":
            self.set_work_mode("build")
        elif btn_id == "chip-plan":
            self.set_work_mode("plan")
        elif btn_id == "chip-fullstack":
            self.set_work_mode("full-stack")
        elif btn_id == "chip-think":
            self.cycle_think_mode()
        elif btn_id == "chip-files":
            self._open_file_picker()
        elif btn_id == "chip-todos":
            self.set_mode("todos" if self._mode != "todos" else "chat")
        elif btn_id == "chip-palette":
            self.action_command_palette()
        else:
            return
        self.query_one("#prompt", Input).focus()

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

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
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
        self._interrupt_requested = False
        images = list(self.pending_images)
        self.pending_images.clear()
        self._mount_user(text, images)
        self._start_thinking()
        self._busy = True
        self.query_one("#prompt", Input).disabled = True
        self._start_spinner()
        self._refresh_status()
        self._scroll_chat()
        self._run_turn(text, images)

    @work(thread=True, exclusive=True, group="agent")
    def _run_turn(self, text: str, images: list[str] | None = None) -> None:
        try:
            if images:
                self.agent.run_turn(text, images=images)
            else:
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
        self._refresh_modebar()
        if self._is_following():
            self._scroll_chat()

    def _start_spinner(self) -> None:
        self._stop_spinner()
        self._spinner_index = 0
        self._spinner_timer = self.set_interval(0.18, self._spin)

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

    def current_think_mode(self) -> str:
        if not self.config.show_reasoning:
            return "off"
        effort = getattr(self.config, "reasoning_effort", "high")
        return effort if effort in THINK_MODES else "high"

    def _think_label(self) -> str:
        mode = self.current_think_mode()
        return "Think off" if mode == "off" else f"Think {mode}"

    def set_think_mode(self, mode: str, *, quiet: bool = False) -> None:
        if mode not in THINK_MODES:
            return
        if mode == "off":
            self.config.show_reasoning = False
        else:
            self.config.show_reasoning = True
            self.config.reasoning_effort = mode
        self.bridge.show_reasoning = self.config.show_reasoning
        self.refresh_think_chip()
        self._refresh_modebar()
        self._refresh_status()
        if quiet:
            return
        if mode == "off":
            self.notice("Think : désactivé (raisonnement masqué).", "info")
        else:
            self.notice(f"Think : {mode} · raisonnement affiché.", "success")

    def cycle_think_mode(self) -> None:
        current = THINK_MODES.index(self.current_think_mode())
        self.set_think_mode(THINK_MODES[(current + 1) % len(THINK_MODES)])

    def action_cycle_think(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        self.cycle_think_mode()

    def refresh_think_chip(self) -> None:
        try:
            button = self.query_one("#chip-think", Button)
        except Exception:  # noqa: BLE001 - montage initial
            return
        button.label = self._think_label()
        button.set_class(self.current_think_mode() != "off", "thinking-on")

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

    def action_interrupt_turn(self) -> None:
        if isinstance(self.screen, ModalScreen) or not self._busy:
            return
        if self._interrupt_requested:
            return
        self._interrupt_requested = True
        terminate = getattr(self.context, "terminate_active_process", None)
        if callable(terminate):
            terminate()
        self.notice("⏹ Interruption demandée…", "warning")
        self._refresh_status()

    def action_request_exit(self) -> None:
        self.request_exit()

    def request_exit(self) -> None:
        if self._busy:
            self.notice(
                "Un tour est en cours. Attends sa fin avant de quitter.", "warning"
            )
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
        body.append("Raccourcis\n", style="bold #7dd3fc")
        for key, description in (
            ("Ctrl+K", "palette de commandes"),
            ("@", "rechercher un fichier"),
            ("Shift+Tab", "mode build / plan"),
            ("Tab", "chat / tâches / outils"),
            ("↑ ↓", "historique des demandes"),
            ("F2", "replier / ouvrir le dernier outil"),
            ("F3", "mode think : off / low / high / max"),
            ("F6", "focus prompt → fichiers → sessions → chat"),
            ("Échap", "interrompre le tour en cours"),
            ("Ctrl+B", "afficher ou masquer la sidebar"),
            ("F1", "aide et commandes"),
            ("Ctrl+Q", "quitter"),
        ):
            body.append(f"  {key:<10}", style="bold #e6edf3")
            body.append(description + "\n", style="#c9d1d9")
        body.append("\nCommandes\n", style="bold #7dd3fc")
        for command, description in COMMANDS:
            body.append(f"  {command:<34}", style="bold #e6edf3")
            body.append(description + "\n", style="#c9d1d9")
        body.append("\nCréé par ", style="#6f7c8e")
        body.append(__author__, style="bold #e6edf3")
        body.append("\nGitHub     ", style="#6f7c8e")
        body.append(__github__, style=f"#7dd3fc underline link {__github__}")
        body.append("\nPortfolio  ", style="#6f7c8e")
        body.append(__portfolio__, style=f"#7dd3fc underline link {__portfolio__}")
        self.push_screen(HelpScreen(body, self.context.cwd))

    def show_welcome(self) -> None:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="#6f7c8e", width=13)
        grid.add_column()

        model = Text(self.config.model, style="bold #e6edf3")
        if self.config.provider:
            model.append(f"  ·  {self.config.provider}", style="#7d8998")
        grid.add_row("Modèle", model)

        route = Text(
            " → ".join(self.chain[:3]) if self.chain else "routeur automatique",
            style="#7dd3fc",
        )
        grid.add_row("Route", route)

        mode_style = {
            "build": "bold #071016 on #34d399",
            "plan": "bold #071016 on #fbbf24",
            "full-stack": "bold #071016 on #a78bfa",
        }.get(self.work_mode, "bold #7dd3fc")
        mode_row = Text()
        mode_row.append(f" {self.work_mode.upper()} ", style=mode_style)
        mode_row.append(f"  ·  permissions {self.permissions.mode}", style="#7d8998")
        grid.add_row("Mode", mode_row)

        workspace = Text(str(self.context.cwd), style="bold #e6edf3")
        if self._branch:
            workspace.append(f"  ⎇ {self._branch}", style="#7dd3fc")
        grid.add_row("Workspace", workspace)

        header = Text()
        header.append("zerocode", style="bold #e6edf3")
        header.append(f"  v{__version__}\n", style="#6f7c8e")
        header.append("Agent de codage autonome dans le terminal", style="#7d8998")

        footer = Text()
        footer.append(
            "\nEntrée envoyer  ·  @ joindre un fichier  ·  Ctrl+K commandes  ·  F1 aide\n",
            style="#6f7c8e",
        )
        footer.append("Créé par ", style="#6f7c8e")
        footer.append(__author__, style="bold #e6edf3")
        footer.append("  ·  ", style="#6f7c8e")
        footer.append(__github__, style=f"#7dd3fc underline link {__github__}")
        footer.append("  ·  ", style="#6f7c8e")
        footer.append(__portfolio__, style=f"#7dd3fc underline link {__portfolio__}")

        wrapper = Table.grid()
        wrapper.add_row(header)
        wrapper.add_row(Text(""))
        wrapper.add_row(grid)
        wrapper.add_row(footer)

        panel = Panel(
            wrapper,
            title=f"v{__version__}",
            title_align="right",
            border_style="#263244",
            box=box.ROUNDED,
            padding=(1, 2),
            expand=True,
        )
        self._mount(WolfMascot())
        self._mount(Static(panel, classes="welcome"))
        self._scroll_chat()

    def render_session(self, session: Any) -> None:
        self.clear_chat()
        self.show_welcome()
        for message in session.messages:
            role = message.get("role")
            content = _safe(str(message.get("content") or ""))
            if role == "user" and content:
                self._mount_user(content)
            elif role == "assistant" and content:
                self._mount_agent_header()
                self._mount(Markdown(content, classes="assistant"))
        self._scroll_chat()

    def clear_chat(self) -> None:
        self._stop_thinking()
        self.query_one("#chat", VerticalScroll).remove_children()
        self._assistant = None
        self._assistant_buffer = ""
        self._assistant_rendered = 0
        self._reasoning = None
        self._reasoning_buffer = ""
        self._tool_cards = []

    def _notice(self, message: str, kind: str = "info") -> None:
        self.notice(message, kind)

    def notice(self, message: str, kind: str = "info") -> None:
        if threading.get_ident() != self._thread_id:
            self._call_main("_notice", message, kind)
            return
        try:
            chat = self.query_one("#chat", VerticalScroll)
        except Exception:  # noqa: BLE001 - avant montage du DOM
            self._pending_notices.append((message, kind))
            return
        if self._assistant is not None or self._reasoning is not None:
            self._end_assistant()
        if kind == "error":
            self._stop_thinking()
        follow = self._is_following()
        style = {
            "warning": "#fbbf24",
            "error": "bold #f87171",
            "success": "#34d399",
            "info": "#7d8998",
        }.get(kind, "#7d8998")
        badge = {
            "warning": "! ",
            "error": "× ",
            "success": "✓ ",
            "info": "· ",
        }.get(kind, "")
        chat.mount(
            Static(Text(badge + _safe(message), style=style), classes=f"notice {kind}")
        )
        if follow:
            self._scroll_chat()

    def show_list(self, title: str, lines: list[str]) -> None:
        body = Text()
        body.append(_safe(title) + "\n\n", style="bold #7dd3fc")
        cleaned = "\n".join(_safe(line) for line in lines)
        body.append(cleaned if lines else "Aucun résultat.", style="#c9d1d9")
        self._mount(Static(body, classes="notice"))
        self._scroll_chat()

    def show_todos(self, todos: list[dict[str, Any]]) -> None:
        self._mode = "todos"
        self.query_one("#inspector").remove_class("hidden")
        self._refresh_modebar()
        self._refresh_inspector()

    def refresh_after_command(self) -> None:
        self._route_stamp = 0.0
        self._refresh_status()
        self._refresh_brandbar()
        self._refresh_sessions()
        self._refresh_modebar()

    def refresh_sessions(self) -> None:
        self._refresh_sessions()

    def reload_project(self, target: Path) -> None:
        tree = self.query_one("#files", DirectoryTree)
        tree.path = target
        self._files = _list_project_files(target)
        self._branch = _git_branch(target)
        self._refresh_brandbar()
        self._refresh_project_title()

    def _mount_user(self, text: str, images: list[str] | None = None) -> None:
        stamp = datetime.now().strftime("%H:%M")
        label = _safe(text)
        if images:
            label += f"\n[{len(images)} image(s) jointe(s)]"
        body = Text.assemble(
            ("Vous", "bold #7dd3fc"),
            (f"  {stamp}\n", "#6f7c8e"),
            (label, "#e6edf3"),
        )
        self._mount(Static(body, classes="user-message"))

    def _mount_agent_header(self) -> None:
        stamp = datetime.now().strftime("%H:%M")
        hdr = Text.assemble(
            ("Zerocode", "bold #34d399"),
            (f"  {self.config.model}  ·  {stamp}", "#6f7c8e"),
        )
        self._mount(Static(hdr, classes="agent-header"))

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
        self._assistant_buffer += _safe(delta)
        if self._assistant is None:
            self._mount_agent_header()
            self._assistant = Markdown("", classes="assistant")
            self._assistant_rendered = 0
            self._mount(self._assistant)
        now = time.monotonic()
        if (
            self._assistant.is_mounted
            and now - self._last_render >= 0.05
            and self._assistant_rendered < len(self._assistant_buffer)
        ):
            self._assistant.append(self._assistant_buffer[self._assistant_rendered :])
            self._assistant_rendered = len(self._assistant_buffer)
            self._last_render = now
            if follow:
                self._scroll_chat()

    def _stream_reasoning(self, delta: str) -> None:
        self._stop_thinking()
        follow = self._is_following()
        self._reasoning_buffer += _safe(delta)
        if self._reasoning is None:
            self._reasoning = Static("", classes="reasoning")
            self._mount(self._reasoning)
        now = time.monotonic()
        if now - self._last_reasoning_render >= 0.08:
            text = Text("Réflexion · " + self._reasoning_buffer, style="#8b97a8 italic")
            self._reasoning.update(text)
            self._last_reasoning_render = now
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
            fully_rendered = (
                self._assistant.is_mounted
                and self._assistant_rendered >= len(self._assistant_buffer)
            )
            if not fully_rendered:
                self._assistant.update(self._assistant_buffer)
            self._assistant = None
            self._assistant_buffer = ""
            self._assistant_rendered = 0
        if self._reasoning is not None:
            text = Text("Réflexion · " + self._reasoning_buffer, style="#8b97a8 italic")
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

    def _tool_output(self, name: str, chunk: str) -> None:
        card = next(
            (
                candidate
                for candidate in reversed(self._tool_cards)
                if candidate.tool_name == name and not candidate.done
            ),
            None,
        )
        if card is None:
            return
        card.append_stream(chunk)
        if self._is_following():
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
            self._refresh_modebar()
        if follow:
            self._scroll_chat()

    def _tool_diff(self, path: str, diff: str) -> None:
        card = next(
            (candidate for candidate in reversed(self._tool_cards) if not candidate.done),
            None,
        )
        if card is None:
            card = ToolCard("diff", "")
            self._tool_cards.append(card)
            self._mount(card)
        card.set_diff(path, diff)
        if self._is_following():
            self._scroll_chat()

    def ask_tool_permission(self, name: str, args: dict[str, Any], callback: Any) -> None:
        preview = _safe(_format_tool_args(name, args, full=True))
        self.push_screen(ConfirmScreen(name, preview), callback)

    def ask_sudo_password(self, command: str, callback: Any) -> None:
        self.push_screen(PasswordScreen(_safe(command)), callback)

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
        now = time.monotonic()
        if now - self._route_stamp >= 3.0:
            self._route = self.router.preview()
            self._route_stamp = now
        route = self._route
        usage = self.agent.usage
        width = self.size.width
        text = Text()
        text.append("● ", style="bold #34d399" if route else "bold #f87171")
        text.append(f"{self.config.model}", style="bold #e6edf3")
        if width >= 70:
            text.append(f"  {self.config.provider or 'auto'}", style="#6f7c8e")
        if width >= 92:
            text.append("  ·  ", style="#263244")
            text.append(
                " → ".join(route[:2]) if route else "aucune route", style="#7dd3fc"
            )
        if width >= 64:
            text.append("  ·  ", style="#263244")
            text.append(
                f"perms {self.permissions.mode}",
                style="#fbbf24" if self.permissions.mode != "allow" else "#34d399",
            )
        if width >= 108:
            text.append("  ·  ", style="#263244")
            text.append(f"session {self.agent.session.id[-8:]}", style="#6f7c8e")
        if width >= 96:
            text.append("  ·  ", style="#263244")
            text.append(
                f"{usage.total_tokens:,} jetons".replace(",", " "), style="#6f7c8e"
            )
        if self._busy:
            if self._interrupt_requested:
                text.append("  ·  interruption…", style="bold #f87171")
            else:
                frame = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[self._spinner_index]
                text.append(f"  ·  {frame} travail…", style="bold #fbbf24")
        status.update(text)

    def _refresh_brandbar(self) -> None:
        try:
            bar = self.query_one("#brandbar", Static)
        except Exception:  # noqa: BLE001 - montage initial
            return
        text = Text()
        text.append("zerocode", style="bold #e6edf3")
        text.append(f"  {__version__}", style="#6f7c8e")
        text.append(f"   /{self.context.cwd.name}", style="bold #c9d1d9")
        if self._branch:
            text.append(f"   ⎇ {self._branch}", style="#7dd3fc")
        text.append("   ·   ", style="#263244")
        text.append(__author__, style="#7d8998")
        text.append("   ", style="#6f7c8e")
        text.append(__github__, style=f"#7dd3fc underline link {__github__}")
        if self.size.width >= 110:
            text.append("   ·   ", style="#263244")
            text.append(__portfolio__, style=f"#7dd3fc underline link {__portfolio__}")
        bar.update(text)

    def _refresh_project_title(self) -> None:
        try:
            title = self.query_one("#project-title", Label)
        except Exception:  # noqa: BLE001 - montage initial
            return
        text = Text("PROJET", style="bold #7d8998")
        text.append("   " + self.context.cwd.name, style="#c9d1d9")
        if self._branch:
            text.append(f"  ⎇ {self._branch}", style="#7dd3fc")
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
                    "build": "bold #071016 on #34d399",
                    "plan": "bold #071016 on #fbbf24",
                    "full-stack": "bold #071016 on #a78bfa",
                }[mode]
            else:
                style = "#6f7c8e"
            text.append(f" {label} ", style=style)
            text.append(" ")
        text.append("  ·  ", style="#263244")
        todo_count = len(self.context.todos)
        todo_label = f"TÂCHES ({todo_count})" if todo_count else "TÂCHES"
        for mode, label in (
            ("chat", "CHAT"),
            ("todos", todo_label),
            ("tools", "OUTILS"),
        ):
            active = self._mode == mode
            text.append(
                f" {label} ",
                style="bold #071016 on #7dd3fc" if active else "#6f7c8e",
            )
            text.append(" ")
        if self.size.width >= 116:
            text.append("  Shift+Tab mode  ·  Tab panneaux", style="#4d5867")
        bar.update(text)

    def _refresh_prompt_placeholder(self) -> None:
        try:
            prompt = self.query_one("#prompt", Input)
        except Exception:  # noqa: BLE001 - montage initial
            return
        if self.work_mode == "plan":
            prompt.placeholder = (
                "Mode plan (lecture seule) — décris ce que tu veux planifier…  "
                "Ctrl+K commandes"
            )
        elif self.work_mode == "full-stack":
            prompt.placeholder = (
                "Mode full-stack autonome — décris le projet complet à construire…  "
                "Ctrl+K commandes"
            )
        else:
            prompt.placeholder = (
                "Demandez quelque chose…  @ fichiers  ·  Ctrl+K commandes"
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
                "plan": "  ·  LECTURE SEULE",
                "full-stack": "  ·  AUTONOME",
            }.get(self.work_mode, "")
            title.update("OUTILS DISPONIBLES" + suffix)
            tools = self.agent.tools.tools()
            if self.work_mode == "plan":
                tools = [tool for tool in tools if tool.approval == "never"]
            text = Text()
            for tool in tools:
                text.append(f"{tool.name:<12}", style="bold #e6edf3")
                perm_badge = "AUTO" if tool.approval in {"never", "auto"} else "CONFIRM"
                text.append(
                    f" [{perm_badge:<7}] ",
                    style="#34d399" if tool.approval == "never" else "#fbbf24",
                )
                text.append(tool.description + "\n", style="#7d8998")
            content.update(text)
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
        return Text("Aucune tâche planifiée pour le moment.", style="dim")
    done_count = sum(1 for t in todos if str(t.get("status")) == "completed")
    total = len(todos)
    pct = int((done_count / total) * 100) if total else 0
    bar_width = 16
    filled = int((done_count / total) * bar_width) if total else 0
    bar = "━" * filled + "─" * (bar_width - filled)

    text = Text()
    text.append(
        f"Progression  {bar}  {pct}%  ({done_count}/{total})\n\n",
        style="bold #7dd3fc",
    )

    markers = {
        "pending": ("○ ATTENTE", "#6f7c8e"),
        "in_progress": ("⟳ EN COURS", "bold #fbbf24"),
        "completed": ("✓ TERMINÉ", "bold #34d399"),
        "cancelled": ("✕ ANNULÉ", "#f87171"),
    }
    for todo in todos:
        status = str(todo.get("status", "pending"))
        badge, style = markers.get(status, ("○ ATTENTE", "#6f7c8e"))
        text.append(f"  {badge:<11} ", style=style)
        text.append(str(todo.get("content", "")) + "\n", style="#c9d1d9")
    return text


def _list_project_files(root: Path, limit: int = 5_000) -> list[str]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            files = [
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip() and not is_secret_path(Path(line.strip()))
            ]
            return sorted(files)[:limit]
    except (OSError, subprocess.SubprocessError):
        pass

    files: list[str] = []
    for current, directories, names in os.walk(root):
        directories[:] = [
            name for name in directories if name not in IGNORED_DIRECTORIES
        ]
        for name in names:
            path = Path(current) / name
            if is_secret_path(path):
                continue
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            files.append(relative)
            if len(files) >= limit:
                return sorted(files)
    return sorted(files)

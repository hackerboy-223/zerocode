from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
        Binding("ctrl+y", "copy_last", "Copier réponse", priority=True, show=False),
        Binding("escape", "interrupt_turn", "Interrompre", show=False),
        Binding("ctrl+q", "request_exit", "Quitter", priority=True),
    ]

    CSS = """
    /* ------------------------------------------------------------------
       Style minimaliste & épuré inspiré de ChatGPT
       ------------------------------------------------------------------ */
    Screen {
        background: #171717;
        color: #ececec;
    }

    #brandbar {
        height: 1;
        padding: 0 2;
        background: #171717;
        color: #8e8e8e;
        border-bottom: none;
    }

    #body {
        height: 1fr;
    }

    #modebar-row {
        height: 1;
        background: #171717;
        border-bottom: none;
    }

    #modebar {
        width: 1fr;
        height: 1;
        padding: 0 2;
        background: #171717;
    }

    #web-toolbar {
        height: auto;
        padding: 0 1;
        background: #171717;
        border-bottom: solid #262626;
    }

    .web-chip {
        min-width: 0;
        height: 1;
        margin: 0;
        padding: 0 1;
        border: none;
        background: transparent;
        color: #8e8e8e;
    }

    .web-chip:hover {
        background: #262626;
        color: #ececec;
    }

    .web-chip.primary-chip {
        background: #2f2f2f;
        color: #ececec;
    }

    .web-chip.primary-chip:hover {
        background: #383838;
    }

    .web-chip.accent-chip {
        background: transparent;
        color: #10a37f;
        text-style: bold;
    }

    .web-chip.accent-chip:hover {
        background: #1f2e29;
        color: #34d399;
    }

    .web-chip.chip-active-build {
        background: #1f2e29;
        color: #34d399;
        text-style: bold;
    }

    .web-chip.chip-active-plan {
        background: #2e2618;
        color: #fbbf24;
        text-style: bold;
    }

    .web-chip.chip-active-fs {
        background: #10a37f;
        color: #ffffff;
        text-style: bold;
    }

    .web-chip.chip-active-panel {
        background: #2f2f2f;
        color: #ececec;
        text-style: bold;
    }

    .think-chip {
        min-width: 0;
        height: 1;
        margin-right: 1;
    }

    .think-chip.thinking-on {
        background: #2f2f2f;
        color: #ececec;
        text-style: bold;
    }

    #sidebar {
        width: 24;
        min-width: 20;
        padding: 0 1;
        border-right: solid #262626;
        background: #111111;
    }

    #sidebar.hidden {
        display: none;
    }

    .section {
        margin-top: 1;
        margin-bottom: 0;
        color: #737373;
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
        background: #212121;
        border-left: thick #10a37f;
    }

    .session-label {
        width: 100%;
        height: auto;
    }

    SessionItem.current .session-label {
        color: #ececec;
    }

    #main {
        width: 1fr;
        background: #171717;
    }

    #chat {
        height: 1fr;
        padding: 1 4;
        scrollbar-size-vertical: 1;
    }

    #inspector {
        height: 12;
        border-top: solid #262626;
        padding: 1 4;
        background: #111111;
    }

    #inspector.hidden {
        display: none;
    }

    #inspector-title {
        color: #8e8e8e;
        text-style: bold;
        margin-top: 0;
    }

    #inspector-content {
        height: 1fr;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
    }

    #status {
        height: 1;
        padding: 0 4;
        background: #171717;
        color: #737373;
        border-top: none;
    }

    #prompt {
        margin: 0 3 1 3;
        border: round #383838;
        background: #212121;
        color: #ececec;
    }

    #prompt:focus {
        border: round #10a37f;
        background: #262626;
    }

    .welcome {
        width: 100%;
        margin: 1 0 2 0;
        padding: 0 2;
        text-align: center;
        background: transparent;
        border: none;
    }

    .wolf-mascot {
        width: 100%;
        height: auto;
        margin: 2 0 0 0;
        padding: 0 2;
        background: transparent;
        border: none;
        text-align: center;
    }

    .user-message {
        margin: 1 0;
        padding: 0 2;
        background: #2f2f2f;
        border: round #383838;
        color: #ececec;
    }

    .agent-header {
        margin: 1 0 0 0;
        color: #8e8e8e;
    }

    .assistant {
        margin: 0 0 1 0;
        padding: 0 1;
        border: none;
        background: transparent;
    }

    .reasoning {
        color: #8e8e8e;
        text-style: italic;
        margin: 0 0 1 0;
        padding: 0 1;
        border-left: solid #383838;
        background: transparent;
    }

    .thinking {
        color: #8e8e8e;
        margin: 0 0 1 0;
        padding: 0 1;
        background: transparent;
        border: none;
    }

    .tool-line {
        color: #8e8e8e;
        margin: 0;
    }

    ToolCard {
        height: auto;
        margin: 0 0 1 0;
        padding: 0;
        border: none;
        border-left: solid #383838;
        background: #212121;
    }

    ToolCard.running {
        border-left: solid #fbbf24;
        background: #212121;
    }

    ToolCard.success {
        border-left: solid #10a37f;
        background: #1e1e1e;
    }

    ToolCard.error {
        border-left: solid #f87171;
        background: #241818;
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
        color: #9b9b9b;
        height: auto;
    }

    .notice {
        margin: 0 0 1 0;
        padding: 0 1;
        background: transparent;
        border-left: solid #383838;
    }

    .notice.warning {
        color: #fbbf24;
        border-left: solid #fbbf24;
    }

    .notice.error {
        color: #f87171;
        text-style: bold;
        border-left: solid #f87171;
    }

    .notice.success {
        color: #34d399;
        border-left: solid #10a37f;
    }

    .notice.info {
        color: #9b9b9b;
        border-left: solid #383838;
    }

    ConfirmScreen, PasswordScreen, FilePickerScreen, CommandPaletteScreen, HelpScreen {
        align: center middle;
        background: #0a0a0a 80%;
    }

    #confirm-dialog,
    #password-dialog,
    #palette-dialog,
    #help-dialog {
        padding: 1 2;
        border: round #383838;
        background: #212121;
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

                    btn_tools = Button(
                        "Outils", id="chip-tools", classes="web-chip"
                    )
                    btn_tools.can_focus = False
                    yield btn_tools

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
        elif btn_id == "chip-tools":
            self.set_mode("tools" if self._mode != "tools" else "chat")
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
        think_setter = getattr(self.agent, "set_think", None)
        if callable(think_setter):
            think_setter(mode)
        else:
            refresh = getattr(self.agent, "_refresh_system_mode", None)
            if callable(refresh):
                refresh()
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
        self.permissions.mode = self.config.permissions
        self.bridge.show_reasoning = self.config.show_reasoning
        self.refresh_think_chip()
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

    def action_copy_last(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        self.copy_last_response()

    def copy_last_response(self) -> None:
        getter = getattr(self.agent, "last_assistant_text", None)
        text = getter() if callable(getter) else ""
        if not text:
            for msg in reversed(getattr(self.agent, "messages", [])):
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    candidate = str(msg.get("content") or "").strip()
                    if candidate:
                        text = candidate
                        break
        if not text:
            self.notice("Aucune réponse de l'assistant à copier.", "warning")
            return
        with contextlib.suppress(Exception):
            self.copy_to_clipboard(text)
        _copy_system_clipboard(text)
        self.notice(f"Réponse copiée ({len(text)} caractères).", "success")

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
        welcome = Text(justify="center")
        welcome.append("\nComment puis-je t'aider aujourd'hui ?\n\n", style="bold #ececec")
        branch_part = f"  ·  ⎇ {self._branch}" if self._branch else ""
        welcome.append(
            f"zerocode v{__version__}  ·  {self.config.model}  ·  {self.context.cwd.name}{branch_part}\n",
            style="#8e8e8e",
        )
        welcome.append(
            "@ fichier   ·   /skills   ·   /audit   ·   Ctrl+K commandes   ·   Ctrl+B sidebar\n",
            style="#676767",
        )
        self._mount(WolfMascot())
        self._mount(Static(welcome, classes="welcome"))
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
        label = _safe(text)
        if images:
            label += f"\n[{len(images)} image(s) jointe(s)]"
        self._mount(Static(Text(label, style="#ececec"), classes="user-message"))

    def _mount_agent_header(self) -> None:
        hdr = Text.assemble(
            ("● ", "bold #10a37f"),
            ("zerocode", "bold #ececec"),
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
            self._insert_prompt(f"@{path} ")
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
        text.append("● ", style="bold #10a37f" if route else "bold #f87171")
        text.append(f"{self.config.model}", style="#ececec")
        if width >= 80:
            text.append("  ·  ", style="#383838")
            text.append(
                route[0] if route else "aucune route", style="#8e8e8e"
            )
        if width >= 64:
            text.append("  ·  ", style="#383838")
            text.append(f"{self.permissions.mode}", style="#8e8e8e")
        if width >= 96 and usage.total_tokens > 0:
            text.append("  ·  ", style="#383838")
            text.append(
                f"{usage.total_tokens:,} jetons".replace(",", " "), style="#737373"
            )
        if self.context.todos and width >= 84:
            done_todos = sum(
                1 for t in self.context.todos if str(t.get("status")) == "completed"
            )
            text.append("  ·  ", style="#383838")
            text.append(
                f"tâches {done_todos}/{len(self.context.todos)}",
                style="#10a37f" if done_todos == len(self.context.todos) else "#8e8e8e",
            )
        if self._busy:
            if self._interrupt_requested:
                text.append("  ·  interruption…", style="bold #f87171")
            else:
                frame = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[self._spinner_index]
                text.append(f"  ·  {frame} génération…", style="bold #10a37f")
        status.update(text)

    def _refresh_brandbar(self) -> None:
        try:
            bar = self.query_one("#brandbar", Static)
        except Exception:  # noqa: BLE001 - montage initial
            return
        text = Text()
        text.append("zerocode", style="bold #ececec")
        text.append(f" {__version__}", style="#8e8e8e")
        text.append(f"  ·  {self.context.cwd.name}", style="#9b9b9b")
        if self._branch:
            text.append(f" ({self._branch})", style="#737373")
        text.append("  ·  ", style="#383838")
        text.append(__author__, style="#9b9b9b")
        text.append("  ", style="#737373")
        text.append(__github__, style=f"#8e8e8e underline link {__github__}")
        bar.update(text)

    def _refresh_project_title(self) -> None:
        try:
            title = self.query_one("#project-title", Label)
        except Exception:  # noqa: BLE001 - montage initial
            return
        text = Text("PROJET", style="bold #737373")
        text.append("  " + self.context.cwd.name, style="#ececec")
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
                    "build": "bold #10a37f",
                    "plan": "bold #fbbf24",
                    "full-stack": "bold #34d399",
                }[mode]
            else:
                style = "#676767"
            text.append(f"{label}", style=style)
            text.append("   ")
        text.append("·   ", style="#383838")
        todo_count = len(self.context.todos)
        todo_label = f"TÂCHES ({todo_count})" if todo_count else "TÂCHES"
        for mode, label in (
            ("chat", "CHAT"),
            ("todos", todo_label),
            ("tools", "OUTILS"),
        ):
            active = self._mode == mode
            text.append(
                f"{label}",
                style="bold #ececec" if active else "#676767",
            )
            text.append("   ")
        bar.update(text)
        self._refresh_toolbar_chips()

    def _refresh_toolbar_chips(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#chip-build", Button).set_class(
                self.work_mode == "build", "chip-active-build"
            )
            self.query_one("#chip-plan", Button).set_class(
                self.work_mode == "plan", "chip-active-plan"
            )
            self.query_one("#chip-fullstack", Button).set_class(
                self.work_mode == "full-stack", "chip-active-fs"
            )
            btn_todos = self.query_one("#chip-todos", Button)
            count = len(self.context.todos)
            btn_todos.label = f"Tâches ({count})" if count else "Tâches"
            btn_todos.set_class(self._mode == "todos", "chip-active-panel")
            self.query_one("#chip-tools", Button).set_class(
                self._mode == "tools", "chip-active-panel"
            )

    def _refresh_prompt_placeholder(self) -> None:
        try:
            prompt = self.query_one("#prompt", Input)
        except Exception:  # noqa: BLE001 - montage initial
            return
        if self.work_mode == "plan":
            prompt.placeholder = "Mode plan (lecture seule) — envoyer un message…"
        elif self.work_mode == "full-stack":
            prompt.placeholder = "Mode full-stack autonome — envoyer un message…"
        else:
            prompt.placeholder = "Envoyer un message à ZeroCode…"

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


def _copy_system_clipboard(text: str) -> bool:
    import shutil

    for cmd in (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
        ["pbcopy"],
        ["clip"],
    ):
        if shutil.which(cmd[0]) is None:
            continue
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            res = subprocess.run(
                cmd,
                input=text,
                text=True,
                capture_output=True,
                timeout=2,
                check=False,
            )
            if res.returncode == 0:
                return True
    return False


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

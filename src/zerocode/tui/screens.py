from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option


def _fuzzy_score(text: str, needle: str) -> int | None:
    """Score de sous-séquence: plus petit = meilleur."""
    if not needle:
        return 0
    position = -1
    first = -1
    for char in needle:
        position = text.find(char, position + 1)
        if position < 0:
            return None
        if first < 0:
            first = position
    span = position - first + 1
    return span * 10 + first + len(text) // 10


def _matches(path: str, query: str) -> bool:
    lowered = path.lower()
    for token in query.lower().split():
        if token not in lowered and _fuzzy_score(lowered, token) is None:
            return False
    return True


def _rank(path: str, query: str) -> tuple[int, int, int, str]:
    lowered = path.lower()
    basename = lowered.rsplit("/", 1)[-1]
    tokens = query.lower().split()
    needle = " ".join(tokens)
    if not needle:
        return (0, 0, len(path), lowered)
    if lowered.startswith(needle):
        return (0, 0, len(path), lowered)
    if basename.startswith(needle):
        return (1, 0, len(path), lowered)
    if needle in basename:
        return (2, 0, len(path), lowered)
    if needle in lowered:
        return (3, 0, len(path), lowered)
    scores = [_fuzzy_score(lowered, token) for token in tokens]
    score = sum(item for item in scores if item is not None)
    return (4, score, len(path), lowered)


def _options(options: Iterable[tuple[str, str]]) -> list[Option]:
    return [
        Option(
            Text.assemble((value, "bold #7dd3fc"), ("  " + label, "#7d8998")),
            id=value,
        )
        for value, label in options
    ]


def _file_options(paths: Iterable[str]) -> list[Option]:
    options: list[Option] = []
    for path in paths:
        parent, _, name = path.rpartition("/")
        label = Text()
        label.append(name or path, style="bold #e6edf3")
        if parent:
            label.append("  " + parent, style="#6f7c8e")
        options.append(Option(label, id=path))
    return options


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "deny", "Refuser"),
        Binding("n", "deny", "Refuser"),
        Binding("y", "allow", "Autoriser"),
    ]

    def __init__(self, name: str, preview: str) -> None:
        super().__init__()
        self.tool_name = name
        self.preview = preview

    def compose(self) -> ComposeResult:
        body = Text()
        body.append(self.preview, style="bold")
        body.append(
            "\n\nCette action peut modifier les fichiers ou exécuter une commande.",
            style="#7d8998",
        )
        with Vertical(id="confirm-dialog"):
            yield Label(f"Autorisation · {self.tool_name}", id="confirm-title")
            with VerticalScroll(id="confirm-scroll"):
                yield Static(body, id="confirm-body")
            yield Static(
                "Entrée autoriser · Échap refuser · y/n",
                id="confirm-hint",
                classes="palette-hint",
            )
            with Horizontal(id="confirm-actions"):
                yield Button("Refuser", id="deny", variant="default")
                yield Button("Autoriser", id="allow", variant="success")

    def on_mount(self) -> None:
        self.query_one("#allow", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "allow")

    def action_allow(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)


class PasswordScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Annuler")]

    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command

    def compose(self) -> ComposeResult:
        body = Text()
        body.append("Commande privilégiée détectée\n\n", style="bold #fbbf24")
        body.append(self.command, style="bold")
        body.append(
            "\n\nTon mot de passe reste en local et n'est jamais envoyé au modèle.",
            style="#7d8998",
        )
        with Vertical(id="password-dialog"):
            yield Label("Mot de passe sudo", id="password-title")
            with VerticalScroll(id="password-scroll"):
                yield Static(body, id="password-body")
            yield Input(
                placeholder="Mot de passe…",
                password=True,
                id="password-input",
            )
            yield Static(
                "Entrée valider · Échap annuler",
                id="password-hint",
                classes="palette-hint",
            )
            with Horizontal(id="password-actions"):
                yield Button("Annuler", id="password-cancel", variant="default")
                yield Button("Valider", id="password-allow", variant="success")

    def on_mount(self) -> None:
        self.query_one("#password-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "password-input":
            self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "password-allow":
            self.dismiss(self.query_one("#password-input", Input).value)
        elif event.button.id == "password-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class FilePickerScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Fermer")]

    def __init__(self, files: list[str]) -> None:
        super().__init__()
        self.files = files
        self._filtered: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-dialog"):
            yield Label("Fichiers du projet", classes="palette-title")
            yield Input(placeholder="Filtrer…", id="file-filter")
            yield OptionList(id="file-options")
            yield Static("Entrée choisir · Échap fermer", id="file-hint", classes="palette-hint")

    def on_mount(self) -> None:
        self._refresh("")
        self.query_one("#file-filter", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "file-filter":
            self._refresh(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "file-filter" and self._filtered:
            self.dismiss(self._filtered[0])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _refresh(self, query: str) -> None:
        candidates = sorted(
            (path for path in self.files if _matches(path, query)),
            key=lambda path: _rank(path, query),
        )
        matches = candidates[:300]
        self._filtered = matches
        option_list = self.query_one("#file-options", OptionList)
        if matches:
            option_list.set_options(_file_options(matches))
            option_list.highlighted = 0
        else:
            option_list.set_options(
                [Option(Text("Aucun fichier", style="dim"), disabled=True)]
            )
        count = f"{len(candidates)} fichier" + ("s" if len(candidates) > 1 else "")
        if len(candidates) > 300:
            count += " (300 affichés)"
        self.query_one("#file-hint", Static).update(
            f"{count} · Entrée choisir · Échap fermer"
        )


class CommandPaletteScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Fermer")]

    def __init__(self, commands: list[tuple[str, str]]) -> None:
        super().__init__()
        self.commands = commands
        self._filtered: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-dialog"):
            yield Label("Commandes", classes="palette-title")
            yield Input(placeholder="Rechercher une commande…", id="command-filter")
            yield OptionList(id="command-options")
            yield Static("Entrée choisir · Échap fermer", id="command-hint", classes="palette-hint")

    def on_mount(self) -> None:
        self._refresh("")
        self.query_one("#command-filter", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "command-filter":
            self._refresh(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "command-filter" and self._filtered:
            self.dismiss(self._filtered[0][0])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _refresh(self, query: str) -> None:
        needle = query.lower().strip()
        matches = [
            (command, description)
            for command, description in self.commands
            if not needle
            or needle in command.lower()
            or needle in description.lower()
            or _fuzzy_score((command + " " + description).lower(), needle) is not None
        ]
        self._filtered = matches
        option_list = self.query_one("#command-options", OptionList)
        if matches:
            option_list.set_options(_options(matches))
            option_list.highlighted = 0
        else:
            option_list.set_options(
                [Option(Text("Aucune commande", style="dim"), disabled=True)]
            )
        count = f"{len(matches)} commande" + ("s" if len(matches) > 1 else "")
        self.query_one("#command-hint", Static).update(
            f"{count} · Entrée choisir · Échap fermer"
        )


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Fermer")]

    def __init__(self, body: Text, cwd: Path) -> None:
        super().__init__()
        self.body = body
        self.cwd = cwd

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("Aide", classes="palette-title")
            with VerticalScroll(id="help-scroll"):
                yield Static(self.body, id="help-body")
            yield Static(f"{self.cwd} · Échap fermer", id="help-cwd", classes="palette-hint")

    def action_close(self) -> None:
        self.dismiss(None)


class SettingsScreen(ModalScreen[None]):
    """Panneau interactif de paramétrage complet de ZeroCode."""

    BINDINGS = [Binding("escape", "close", "Fermer")]

    def __init__(
        self,
        get_rows: Callable[[], list[tuple[str, str, str, str]]],
        on_toggle: Callable[[str], str | None],
    ) -> None:
        super().__init__()
        self._get_rows = get_rows
        self._on_toggle = on_toggle
        self._filtered: list[tuple[str, str, str, str]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-dialog"):
            yield Label("Paramètres ZeroCode", classes="palette-title")
            yield Input(placeholder="Filtrer un paramètre…", id="command-filter")
            yield OptionList(id="command-options")
            yield Static(
                "Entrée basculer/modifier · Échap fermer",
                id="command-hint",
                classes="palette-hint",
            )

    def on_mount(self) -> None:
        self._refresh("")
        self.query_one("#command-filter", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "command-filter":
            self._refresh(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "command-filter" and self._filtered:
            self._activate(self._filtered[0][0])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self._activate(event.option.id)

    def _activate(self, key: str) -> None:
        status = self._on_toggle(key)
        query = self.query_one("#command-filter", Input).value
        self._refresh(query, status=status)

    def action_close(self) -> None:
        self.dismiss(None)

    def _refresh(self, query: str, *, status: str | None = None) -> None:
        needle = query.lower().strip()
        rows = self._get_rows()
        matches = [
            row
            for row in rows
            if not needle
            or needle in row[0].lower()
            or needle in row[1].lower()
            or needle in row[2].lower()
            or needle in row[3].lower()
        ]
        self._filtered = matches
        option_list = self.query_one("#command-options", OptionList)
        highlighted = option_list.highlighted or 0
        if matches:
            opts: list[Option] = []
            for key, label, value, desc in matches:
                val_style = (
                    "bold #34d399"
                    if value in {"on", "allow", "full-stack", "max", "high"}
                    else "bold #7dd3fc"
                    if value not in {"off", "deny"}
                    else "#8e8e8e"
                )
                line = Text.assemble(
                    (f"{label:<26}", "bold #ececec"),
                    (f" [{value:<18}] ", val_style),
                    (desc, "#7d8998"),
                )
                opts.append(Option(line, id=key))
            option_list.set_options(opts)
            option_list.highlighted = min(highlighted, len(opts) - 1)
        else:
            option_list.set_options(
                [Option(Text("Aucun paramètre", style="dim"), disabled=True)]
            )
        hint = status or f"{len(matches)} paramètres · Entrée basculer · Échap fermer"
        self.query_one("#command-hint", Static).update(hint)

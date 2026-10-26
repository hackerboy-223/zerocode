from __future__ import annotations

import time

from rich.text import Text
from textual.binding import Binding
from textual.timer import Timer
from textual.widgets import Collapsible, Input, Static

from ..tokens import truncate_text


class PromptInput(Input):
    """Champ de saisie avec historique navigable aux flèches."""

    BINDINGS = [
        Binding("up", "history_previous", "Historique précédent", show=False),
        Binding("down", "history_next", "Historique suivant", show=False),
    ]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.history: list[str] = []
        self._history_index = 0
        self._draft = ""

    def remember(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if not self.history or self.history[-1] != text:
            self.history.append(text)
        self._history_index = len(self.history)
        self._draft = ""

    def action_history_previous(self) -> None:
        if not self.history:
            return
        if self._history_index >= len(self.history):
            self._draft = self.value
        self._history_index = max(0, self._history_index - 1)
        self._set_history_value(self.history[self._history_index])

    def action_history_next(self) -> None:
        if self._history_index >= len(self.history):
            return
        self._history_index += 1
        if self._history_index >= len(self.history):
            self._set_history_value(self._draft)
        else:
            self._set_history_value(self.history[self._history_index])

    def _set_history_value(self, value: str) -> None:
        self.value = value
        self.cursor_position = len(value)


class ThinkingIndicator(Static):
    """Animation visible pendant l'attente du premier jeton du modèle."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self) -> None:
        super().__init__("", classes="thinking")
        self._started = 0.0
        self._index = 0
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        self._started = time.monotonic()
        self._timer = self.set_interval(0.1, self._tick)
        self._tick()

    def on_unmount(self) -> None:
        self.stop()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        frame = self.FRAMES[self._index % len(self.FRAMES)]
        dots = "." * (self._index % 4)
        elapsed = time.monotonic() - self._started
        text = Text()
        text.append(frame + " ", style="bold yellow")
        text.append("réflexion" + dots, style="italic")
        text.append(f"  {elapsed:4.1f}s", style="dim")
        self.update(text)
        self._index += 1


class ToolCard(Collapsible):
    """Carte repliable pour une exécution d'outil et son résultat."""

    def __init__(self, name: str, preview: str) -> None:
        self.tool_name = name
        self.preview = " ".join(preview.split())
        self.done = False
        self._body = Static(Text("Exécution en cours…", style="dim italic"), classes="tool-output")
        super().__init__(
            self._body,
            title=self._header("◌", "yellow"),
            collapsed=False,
            classes="tool-card running",
        )

    def set_result(self, result: str) -> None:
        self.done = True
        lines = result.strip().splitlines() or ["(vide)"]
        is_error = _is_tool_error(result)
        self.remove_class("running")
        self.add_class("error" if is_error else "success")
        suffix = f"{len(lines)} ligne{'s' if len(lines) > 1 else ''}"
        self.title = self._header("✗" if is_error else "✓", "red" if is_error else "green", suffix)
        body = Text()
        for index, line in enumerate(truncate_text(result.strip() or "(vide)", 6_000).splitlines()):
            style = "red" if is_error and index == 0 else "dim"
            body.append(line + "\n", style=style)
        self._body.update(body)
        self.collapsed = len(lines) > 8

    def _header(self, icon: str, icon_style: str, suffix: str = "") -> Text:
        title = Text()
        title.append(icon + " ", style=icon_style)
        title.append(self.tool_name, style="bold cyan")
        if self.preview:
            title.append("  " + truncate_text(self.preview, 100), style="dim")
        if suffix:
            title.append("  · " + suffix, style="dim")
        return title


def _is_tool_error(result: str) -> bool:
    flat = " ".join(result.split())
    if flat.startswith(("ERREUR", "Action refusee", "TIMEOUT")):
        return True
    return "exit_code:" in flat and "exit_code: 0" not in flat

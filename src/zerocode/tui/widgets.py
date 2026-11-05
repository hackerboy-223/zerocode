from __future__ import annotations

import time

from rich.text import Text
from textual.binding import Binding
from textual.timer import Timer
from textual.widgets import Collapsible, Input, Static

from ..tokens import truncate_text
from ..ui import _safe


class WolfMascot(Static):
    """Mascotte loup cybernétique animée (LUPUS) avec coloration multi-tons."""

    STATES: tuple[tuple[str, str, str, str], ...] = (
        # (ear_glyph, eye_glyph, mouth_glyph [6 cols], wisdom)
        ("◤", "◉", "╲_ᴥᴥ_╱", "Observer avant d'agir."),
        ("▲", "◈", "╲_══_╱", "La précision vaut mieux que la précipitation."),
        ("◤", "─", "╲_──_╱", "Chaque erreur révèle une piste."),
        ("◤", "●", "╲_▾▾_╱", "Vérifier les faits, protéger le système."),
    )
    FRAMES = tuple(state[1] for state in STATES)
    WISDOM = tuple(state[3] for state in STATES)

    def __init__(self) -> None:
        super().__init__("", classes="wolf-mascot")
        self._index = 0
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.75, self._tick)
        self._tick()

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        ear, eye, mouth, wisdom = self.STATES[self._index % len(self.STATES)]
        right_ear = "◥" if ear == "◤" else "▲"
        eye_style = "bold #38bdf8" if eye == "◈" else "bold #10a37f" if eye == "─" else "bold #34d399"
        fur = "bold #e4e4e7"
        shadow = "#71717a"
        accent = "bold #10a37f"

        text = Text(justify="center")
        # Ligne 1 : pointes des oreilles
        text.append("     ◢", style=fur)
        text.append(ear, style=accent)
        text.append("╲      ╱", style=fur)
        text.append(right_ear, style=accent)
        text.append("◣     \n", style=fur)
        # Ligne 2 : base des oreilles et front
        text.append("    ◢◤  ", style=fur)
        text.append("╲____╱", style=shadow)
        text.append("  ◥◣    \n", style=fur)
        # Ligne 3 : arcade sourcilière et regard lumineux
        text.append("   ◢◤ ", style=fur)
        text.append("╲  ", style=shadow)
        text.append(f"{eye}  {eye}", style=eye_style)
        text.append("  ╱", style=shadow)
        text.append(" ◥◣   \n", style=fur)
        # Ligne 4 : joues et chanfrein
        text.append("  ▐▌   ", style=shadow)
        text.append("╲  ", style=fur)
        text.append("▾▾", style=accent)
        text.append("  ╱", style=fur)
        text.append("   ▐▌  \n", style=shadow)
        # Ligne 5 : museau (symétrie exacte 22 colonnes : 8 + 6 + 8)
        text.append("   ◥◣   ", style=fur)
        text.append(mouth, style="bold #ececec")
        text.append("   ◢◤   \n", style=fur)
        # Ligne 6 : menton / collerette
        text.append("     ◥◣________◢◤     \n\n", style=shadow)

        # Titre & devise
        text.append("LUPUS", style="bold #ececec")
        text.append("  ·  ", style="#52525b")
        text.append("LE VEILLEUR\n", style="bold #10a37f")
        text.append(f"« {wisdom} »", style="#8e8e8e italic")
        self.update(text)
        self._index += 1


class PromptInput(Input):
    """Champ de saisie style Web Composer avec historique navigable aux flèches."""

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
    """Carte d'animation style Web Agent pendant l'attente du flux du modèle."""

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
        text.append(f"  {frame}  ", style="bold #fbbf24")
        text.append("réflexion en cours" + f"{dots:<3}", style="#c9d1d9")
        text.append(f"   {elapsed:4.1f}s", style="#6f7c8e")
        self.update(text)
        self._index += 1


class ToolCard(Collapsible):
    """Carte repliable style Web Agent pour une exécution d'outil et son résultat."""

    def __init__(self, name: str, preview: str) -> None:
        self.tool_name = name
        self.preview = " ".join(_safe(preview).split())
        self.done = False
        self._started = time.monotonic()
        self.diff_path = ""
        self.diff = ""
        self.diff_added = 0
        self.diff_removed = 0
        self._stream = ""
        self._body = Static(
            Text("Exécution en cours…", style="#6f7c8e italic"),
            classes="tool-output",
        )
        super().__init__(
            self._body,
            title=self._header("·", "bold #fbbf24", badge="en cours"),
            collapsed=False,
            classes="tool-card running",
        )

    def append_stream(self, chunk: str) -> None:
        self._stream += _safe(chunk)
        rendered = truncate_text(self._stream, 6_000)
        self._body.update(Text(rendered, style="dim"))

    def set_diff(self, path: str, diff: str) -> None:
        self.diff_path = _safe(path)
        self.diff = _safe(diff).strip("\n")
        self.diff_added = 0
        self.diff_removed = 0
        for line in self.diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                self.diff_added += 1
            elif line.startswith("-") and not line.startswith("---"):
                self.diff_removed += 1

    def set_result(self, result: str) -> None:
        self.done = True
        result = _safe(result)
        lines = result.strip().splitlines() or ["(vide)"]
        is_error = _is_tool_error(result)
        self.remove_class("running")
        self.add_class("error" if is_error else "success")
        elapsed = max(0.0, time.monotonic() - self._started)
        suffix = f"{len(lines)} ligne{'s' if len(lines) > 1 else ''}"
        if self.diff:
            suffix += f" · +{self.diff_added} −{self.diff_removed}"
        suffix += f" · {elapsed:.2f}s" if elapsed < 10 else f" · {elapsed:.1f}s"
        badge = "erreur" if is_error else "ok"
        self.title = self._header(
            "✕" if is_error else "✓",
            "bold #f87171" if is_error else "bold #34d399",
            suffix=suffix,
            badge=badge,
        )
        rendered = truncate_text(result.strip() or "(vide)", 6_000).splitlines()
        body = Text()
        for index, line in enumerate(rendered):
            if is_error and index == 0:
                style = "bold #f87171"
            elif line.startswith("DIAGNOSTIC "):
                style = "bold #fbbf24"
            elif line.startswith("+") and not line.startswith("+++"):
                style = "#34d399"
            elif line.startswith("-") and not line.startswith("---"):
                style = "#f87171"
            elif line.startswith("exit_code:"):
                style = "#7dd3fc"
            else:
                style = "#7d8998"
            body.append(line + "\n", style=style)
        diff_lines = self.diff.splitlines()
        if diff_lines:
            body.append("\n")
            body.append("fichier " + self.diff_path, style="bold #7dd3fc")
            body.append(f"  +{self.diff_added}", style="bold #34d399")
            body.append(f"  −{self.diff_removed}\n", style="bold #f87171")
            for line in diff_lines:
                body.append(line + "\n", style=_diff_style(line))
        self._body.update(body)
        self.collapsed = len(diff_lines) > 80 if diff_lines else len(lines) > 8

    def _header(
        self,
        icon: str,
        icon_style: str,
        suffix: str = "",
        badge: str = "",
    ) -> Text:
        title = Text()
        title.append(f"{icon} ", style=icon_style)
        title.append(self.tool_name, style="bold #ececec")
        if self.preview:
            title.append("  " + truncate_text(self.preview, 88), style="#9b9b9b")
        if suffix:
            title.append("  ·  " + suffix, style="#676767")
        elif badge == "en cours":
            title.append("  ·  en cours…", style="#fbbf24")
        return title


def _diff_style(line: str) -> str:
    if line.startswith(("+++", "---")):
        return "bold"
    if line.startswith("+"):
        return "#34d399"
    if line.startswith("-"):
        return "#f87171"
    if line.startswith("@@"):
        return "#7dd3fc"
    return "#7d8998"


def _is_tool_error(result: str) -> bool:
    flat = " ".join(result.split())
    if flat.startswith(("ERREUR", "Action refusee", "TIMEOUT")):
        return True
    return "exit_code:" in flat and "exit_code: 0" not in flat

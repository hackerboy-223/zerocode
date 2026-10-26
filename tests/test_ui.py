from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from zerocode.config import Config
from zerocode.ui import ConsoleUI


def test_welcome_shows_creator_and_links():
    output = io.StringIO()
    console = Console(file=output, width=100, color_system=None)
    ui = ConsoleUI(Config(), console=console, interactive=False)

    ui.welcome(
        model="auto",
        provider=None,
        chain=["kilo/kilo-auto/free"],
        permissions="ask",
        session_id="session-test",
        cwd=Path("/tmp/project"),
    )

    rendered = output.getvalue()
    assert "H@CKERBOY" in rendered
    assert "https://github.com/hackerboy-223" in rendered
    assert "https://hackerboy-223.vercel.app" in rendered
    assert "Agent de codage pour le terminal" in rendered

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


def test_json_ui_emits_json_lines():
    import io
    import json

    from zerocode.types import Completion, Usage
    from zerocode.ui import JsonUI

    stream = io.StringIO()
    ui = JsonUI(stream)
    ui.tool_start("read", {"path": "a.py"})
    ui.stream_text("bonjour")
    ui.result(
        "bonjour",
        session_id="s1",
        usage=Usage(total_tokens=3, requests=1),
        completion=Completion(content="bonjour", provider="kilo", model="auto"),
    )
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert events[0]["type"] == "tool_start"
    assert events[1] == {"type": "text_delta", "delta": "bonjour"}
    assert events[2]["type"] == "result"
    assert events[2]["session_id"] == "s1"
    assert events[2]["usage"]["total_tokens"] == 3

from __future__ import annotations

import io

from rich.console import Console

from zerocode import cli


def test_json_without_prompt_is_rejected(monkeypatch):
    def fail(name):
        raise AssertionError("TUI ne doit pas etre lancee")

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(cli, "find_spec", fail)
    stream = io.StringIO()
    code = cli.run_agent(["--json"], Console(file=stream, width=100))
    assert code == 1
    assert "necessite un prompt" in stream.getvalue()

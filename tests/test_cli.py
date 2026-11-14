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


def test_update_check_reports_available_release(monkeypatch):
    monkeypatch.setattr(cli, "latest_release_tag", lambda: "v99.0.0")
    stream = io.StringIO()
    code = cli.update_command(["--check"], Console(file=stream, width=100))
    assert code == 0
    assert "99.0.0" in stream.getvalue()
    assert "zerocode update" in stream.getvalue()



def test_repair_command_reinstalls_without_prompt_when_yes(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "repair_from_release", lambda: (calls.append(True) or True, "Réparation terminée."))
    stream = io.StringIO()
    code = cli.repair_command(["--yes"], Console(file=stream, width=100))
    assert code == 0
    assert calls == [True]
    assert "Réparation terminée" in stream.getvalue()



def test_rollback_command_uses_requested_version(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "rollback_to_release",
        lambda version: (calls.append(version) or True, f"Version {version} installée."),
    )
    stream = io.StringIO()
    code = cli.rollback_command(["v1.0.0", "--yes"], Console(file=stream, width=100))
    assert code == 0
    assert calls == ["v1.0.0"]
    assert "v1.0.0" in stream.getvalue()



def test_uninstall_command_passes_explicit_data_removal(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "uninstall_from_pipx",
        lambda **kwargs: (calls.append(kwargs) or True, "Désinstallation terminée."),
    )
    stream = io.StringIO()
    code = cli.uninstall_command(["--remove-data", "--yes"], Console(file=stream, width=100))
    assert code == 0
    assert calls == [{"remove_data": True}]
    assert "Désinstallation terminée" in stream.getvalue()


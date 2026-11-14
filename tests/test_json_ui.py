from __future__ import annotations

import io
import json

from zerocode.ui import JsonUI


def test_json_ui_requests_tool_approval(monkeypatch) -> None:
    output = io.StringIO()
    monkeypatch.setattr("zerocode.ui.sys.stdin", io.StringIO('{"approved": true}\n'))
    ui = JsonUI(stream=output, approval_protocol=True)

    assert ui.confirm_tool("write", {"path": "src/main.py"}) is True
    event = json.loads(output.getvalue().splitlines()[0])
    assert event["type"] == "approval_required"
    assert event["name"] == "write"
    assert event["arguments"]["path"] == "src/main.py"


def test_json_ui_refuses_when_approval_protocol_is_disabled() -> None:
    output = io.StringIO()
    ui = JsonUI(stream=output)

    assert ui.confirm_tool("write", {"path": "src/main.py"}) is False
    assert output.getvalue() == ""


def test_json_ui_returns_sudo_password_from_protocol(monkeypatch) -> None:
    output = io.StringIO()
    monkeypatch.setattr("zerocode.ui.sys.stdin", io.StringIO('{"approved": true, "password": "test-password"}\n'))
    ui = JsonUI(stream=output, approval_protocol=True)

    assert ui.confirm_sudo_command("apt install package") is True
    assert ui.request_sudo_password("apt install package") == "test-password"
    events = [json.loads(line)["type"] for line in output.getvalue().splitlines()]
    assert events == ["sudo_confirmation_required", "sudo_password_required"]

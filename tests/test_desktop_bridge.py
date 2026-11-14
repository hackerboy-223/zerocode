from __future__ import annotations

import io
import json
import threading
from pathlib import Path

from zerocode.checkpoints import CheckpointStore
from zerocode.desktop_bridge import (
    DesktopBridgeUI,
    _desktop_permission_manager,
    _session_summaries,
    _think_value,
    _visible_history,
)
from zerocode.session import SessionStore
from zerocode.tools import ToolContext


def test_desktop_bridge_emits_json_lines() -> None:
    stream = io.StringIO()
    ui = DesktopBridgeUI(stream=stream)

    ui.info("Le dossier est prêt.")

    event = json.loads(stream.getvalue().strip())
    assert event == {"type": "info", "message": "Le dossier est prêt."}


def test_desktop_bridge_waits_for_explicit_permission_response() -> None:
    class WaitingStream(io.StringIO):
        def __init__(self) -> None:
            super().__init__()
            self.written = threading.Event()

        def write(self, value: str) -> int:
            result = super().write(value)
            self.written.set()
            return result

    stream = WaitingStream()
    ui = DesktopBridgeUI(stream=stream, request_timeout=1)
    result: list[bool] = []

    worker = threading.Thread(
        target=lambda: result.append(ui.confirm_tool("write", {"path": "notes.txt"}))
    )
    worker.start()
    assert stream.written.wait(timeout=1)

    request = json.loads(stream.getvalue().strip())
    assert request["type"] == "permission_request"
    assert request["tool"] == "write"
    assert ui.receive(
        {
            "type": "permission_response",
            "request_id": request["request_id"],
            "allowed": True,
        }
    )

    worker.join(timeout=1)
    assert not worker.is_alive()
    assert result == [True]


def test_desktop_bridge_denies_permission_when_response_is_missing() -> None:
    stream = io.StringIO()
    ui = DesktopBridgeUI(stream=stream, request_timeout=0.01)

    assert ui.confirm_tool("bash", {"command": "rm -rf ./tmp"}) is False



def test_visible_history_hides_system_and_tool_messages() -> None:
    messages = [
        {"role": "system", "content": "Instruction interne"},
        {"role": "user", "content": "Construis une page"},
        {"role": "tool", "content": "sortie technique"},
        {"role": "assistant", "content": [{"type": "text", "text": "Page créée."}]},
    ]

    assert _visible_history(messages) == [
        {"role": "user", "content": "Construis une page"},
        {"role": "assistant", "content": "Page créée."},
    ]


def test_session_summaries_are_limited_to_the_active_workspace(tmp_path: Path) -> None:
    store = SessionStore(root=tmp_path / "sessions")
    project = tmp_path / "project"
    other_project = tmp_path / "other"
    project.mkdir()
    other_project.mkdir()

    current = store.new(project, "auto")
    current.messages.append({"role": "user", "content": "Créer une API"})
    store.save(current)
    other = store.new(other_project, "auto")
    store.save(other)

    summaries = _session_summaries(store, project)

    assert len(summaries) == 1
    assert summaries[0]["id"] == current.id
    assert summaries[0]["title"] == "Créer une API"


def test_desktop_bridge_emits_todos_and_checkpoints_on_tool_result(tmp_path: Path) -> None:
    stream = io.StringIO()
    ui = DesktopBridgeUI(stream=stream)
    ctx = ToolContext(
        cwd=tmp_path,
        todos=[{"content": "Configurer les icônes", "status": "in_progress"}],
    )
    checkpoints = CheckpointStore(root=tmp_path / "checkpoints")
    sample_file = tmp_path / "demo.txt"
    checkpoints.record("sess-1", sample_file, None, "write")
    ui.bind_runtime(ctx, checkpoints, lambda: "sess-1")

    ui.tool_result("todo_write", "Plan mis à jour")
    ui.tool_result("write", "Fichier écrit")

    events = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    assert events == [
        {"type": "tool_result", "name": "todo_write", "result": "Plan mis à jour"},
        {
            "type": "todos",
            "todos": [{"content": "Configurer les icônes", "status": "in_progress"}],
        },
        {"type": "tool_result", "name": "write", "result": "Fichier écrit"},
        {"type": "checkpoints_changed", "checkpoints": 1},
    ]


def test_think_value_normalizes_reasoning_config() -> None:
    class DummyConfig:
        show_reasoning = False
        reasoning_effort = "high"

    cfg = DummyConfig()
    assert _think_value(cfg) == "off"
    cfg.show_reasoning = True
    assert _think_value(cfg) == "high"
    cfg.reasoning_effort = "unknown"
    assert _think_value(cfg) == "low"


def test_desktop_bridge_redacts_secrets_from_nested_events() -> None:
    stream = io.StringIO()
    ui = DesktopBridgeUI(stream=stream)
    token = "sk-proj-123456789012345678901234567890"

    ui.tool_start("bash", {"command": f"echo {token}", "metadata": {"note": token}})

    event = json.loads(stream.getvalue().strip())
    assert event["arguments"]["command"] == "echo [SECRET MASQUE: JETON API]"
    assert event["arguments"]["metadata"]["note"] == "[SECRET MASQUE: JETON API]"
    assert token not in stream.getvalue()


def test_visible_history_redacts_secrets_before_desktop_display() -> None:
    token = "ghp_123456789012345678901234567890123456"
    messages = [{"role": "assistant", "content": f"Voici le jeton : {token}"}]

    visible = _visible_history(messages)

    assert token not in visible[0]["content"]
    assert "[SECRET MASQUE: JETON API]" in visible[0]["content"]


def test_desktop_bridge_downgrades_inherited_autonomous_permissions() -> None:
    class Config:
        permissions = "allow"

    config = Config()
    permissions = _desktop_permission_manager(config)

    assert permissions.mode == "ask"
    assert config.permissions == "ask"


def test_desktop_bridge_preserves_explicit_deny_permissions() -> None:
    class Config:
        permissions = "deny"

    permissions = _desktop_permission_manager(Config())

    assert permissions.mode == "deny"

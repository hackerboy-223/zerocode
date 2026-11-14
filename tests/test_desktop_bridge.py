from __future__ import annotations

import io
import json
import threading
from pathlib import Path

from zerocode.desktop_bridge import DesktopBridgeUI, _session_summaries, _visible_history
from zerocode.session import SessionStore


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

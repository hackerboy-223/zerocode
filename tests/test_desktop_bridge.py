from __future__ import annotations

import io
import json
import threading

from zerocode.desktop_bridge import DesktopBridgeUI


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

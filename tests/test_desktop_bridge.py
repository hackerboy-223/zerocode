from __future__ import annotations

import io
import json
import threading
from pathlib import Path

from zerocode.checkpoints import CheckpointStore
from zerocode.desktop_bridge import (
    DesktopBridgeUI,
    _desktop_permission_manager,
    _public_mcp_servers,
    _public_providers,
    _resolve_model_selection,
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
        allow_outside_cwd = True
        protect_secrets = False
        allow_secrets = True

    config = Config()
    permissions = _desktop_permission_manager(config)

    assert permissions.mode == "ask"
    assert config.permissions == "ask"
    assert config.allow_outside_cwd is False
    assert config.protect_secrets is True
    assert config.allow_secrets is False


def test_desktop_bridge_preserves_explicit_deny_permissions() -> None:
    class Config:
        permissions = "deny"

    permissions = _desktop_permission_manager(Config())

    assert permissions.mode == "deny"



def test_public_mcp_server_metadata_never_exposes_environment_values() -> None:
    servers = {
        "local-search": {
            "command": "npx",
            "args": ["-y", "example-server"],
            "enabled": True,
            "trusted": False,
            "timeout": 45,
            "env": {"API_TOKEN": "super-secret-value", "MODE": "safe"},
        }
    }

    public = _public_mcp_servers(servers)

    assert public == [
        {
            "name": "local-search",
            "command": "npx",
            "args": ["-y", "example-server"],
            "cwd": "",
            "enabled": True,
            "trusted": False,
            "timeout": 45,
            "env_keys": ["API_TOKEN", "MODE"],
        }
    ]
    assert "super-secret-value" not in json.dumps(public)


def test_runtime_settings_are_validated_and_applied(tmp_path: Path) -> None:
    from zerocode.config import Config
    from zerocode.desktop_bridge import _apply_runtime_settings, _runtime_settings

    config = Config()
    context = ToolContext(cwd=tmp_path)

    ok, problem = _apply_runtime_settings(
        config, context, {"max_steps": 12, "command_timeout": 30, "auto_compact": False}
    )

    assert ok, problem
    assert config.max_steps == 12
    assert context.command_timeout == 30
    assert _runtime_settings(config)["auto_compact"] is False


def test_runtime_settings_reject_unsafe_or_invalid_values(tmp_path: Path) -> None:
    from zerocode.config import Config
    from zerocode.desktop_bridge import _apply_runtime_settings

    config = Config()
    context = ToolContext(cwd=tmp_path)

    for values in (
        {"allow_outside_cwd": True},
        {"protect_secrets": False},
        {"max_steps": 0},
        {"max_steps": True},
        {"temperature": 9},
        {"auto_compact": "yes"},
        {},
    ):
        ok, problem = _apply_runtime_settings(config, context, values)
        assert not ok and problem
    assert config.allow_outside_cwd is False
    assert config.protect_secrets is True
    assert config.max_steps == Config().max_steps


def test_subagent_events_are_forwarded_to_the_desktop() -> None:
    stream = io.StringIO()
    ui = DesktopBridgeUI(stream=stream)

    ui.subagent_event({"phase": "start", "id": "abc", "role": "reviewer", "task": "Lire"})

    event = json.loads(stream.getvalue().strip())
    assert event["type"] == "subagent"
    assert event["role"] == "reviewer"
    assert event["phase"] == "start"


def test_sanitize_images_validates_format_and_limits() -> None:
    import pytest

    from zerocode.desktop_bridge import _sanitize_images

    valid = "data:image/png;base64,iVBORw0KGgo="
    assert _sanitize_images([valid]) == [valid]
    assert _sanitize_images(None) == []

    with pytest.raises(ValueError):
        _sanitize_images(["https://example.com/a.png"])
    with pytest.raises(ValueError):
        _sanitize_images(["data:image/svg+xml;base64,PHN2Zz4="])
    with pytest.raises(ValueError):
        _sanitize_images([valid] * 5)


def test_visible_history_keeps_multimodal_indicator() -> None:
    history = _visible_history(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Regarde ce bug"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
                ],
            }
        ]
    )
    assert history == [{"role": "user", "content": "Regarde ce bug\n[1 image(s) jointe(s)]"}]


def test_project_memory_roundtrip_and_secret_redaction(tmp_path: Path) -> None:
    from zerocode.desktop_bridge import _project_memory, _save_project_memory

    assert _project_memory(tmp_path)["content"] == ""
    saved = _save_project_memory(tmp_path, "- Utilise pytest\n- Clé: sk-1234567890abcdefghijklmnop")
    assert "Utilise pytest" in saved["content"]
    assert "sk-1234567890abcdefghijklmnop" not in saved["content"]
    assert (tmp_path / ".zerocode" / "instructions.md").is_file()

    cleared = _save_project_memory(tmp_path, "   ")
    assert cleared["content"] == ""
    assert not (tmp_path / ".zerocode" / "instructions.md").exists()


def test_public_providers_never_expose_raw_api_keys(monkeypatch, tmp_path: Path) -> None:
    from zerocode.config import Config
    from zerocode.desktop_bridge import _public_providers
    from zerocode.router import Router

    secret = "gsk_super_secret_key_999999999999"
    monkeypatch.setenv("GROQ_API_KEY", secret)
    monkeypatch.setattr("zerocode.desktop_bridge.load_key_store", lambda: {})
    monkeypatch.setattr("zerocode.providers.load_key_store", lambda: {})

    config = Config()
    router = Router(config)
    try:
        items = _public_providers(config, router)
    finally:
        router.close()

    groq = next(item for item in items if item["id"] == "groq")
    assert groq["available"] is True
    assert groq["source"] == "env"
    assert secret not in json.dumps(items)
    assert groq["key_masked"] and groq["key_masked"] != secret


def test_public_hooks_and_doctor_report(tmp_path: Path) -> None:
    from zerocode.agent import Agent
    from zerocode.config import Config
    from zerocode.desktop_bridge import _doctor_report, _public_hooks
    from zerocode.router import Router
    from zerocode.tools import PermissionManager, build_registry
    from zerocode.ui import NullUI

    hooks = _public_hooks(
        {"PreToolUse": [{"command": "python3", "args": ["-V"], "timeout": 99}], "PostToolUse": []}
    )
    assert hooks["PreToolUse"] == [{"command": "python3", "args": ["-V"], "timeout": 30}]
    assert hooks["PostToolUse"] == []

    config = Config(hooks=hooks)
    store = SessionStore(tmp_path / "sessions")
    session = store.new(tmp_path, "auto")
    ctx = ToolContext(cwd=tmp_path)
    registry = build_registry(ctx, PermissionManager(mode="ask", interactive=False), NullUI())
    router = Router(config)
    try:
        agent = Agent(config, router, registry, session, NullUI(), store=store)
        report = _doctor_report(tmp_path, config, router, agent, store)
    finally:
        router.close()

    ids = {check["id"] for check in report["checks"]}
    assert {"engine", "workspace", "providers", "git", "mcp", "hooks", "skills"} <= ids



def test_desktop_bridge_exposes_cloud_gateway_without_local_api_keys() -> None:
    class CloudRouter:
        is_cloud = True
        remote_config = {
            "models": [
                {"alias": "MIMI"},
                {"alias": "MIMI-CODE"},
            ]
        }

    providers = _public_providers(object(), CloudRouter())

    assert providers == [
        {
            "id": "zerocode-cloud",
            "label": "ZeroCode Cloud",
            "env_var": "",
            "requires_key": False,
            "enabled": True,
            "available": True,
            "source": "keyless",
            "key_masked": "",
            "models_count": 2,
            "signup_url": "",
            "notes": "Inférence distante · modèles et fournisseurs gérés par ZeroCode Cloud.",
        }
    ]



def test_desktop_bridge_normalizes_cloud_model_aliases() -> None:
    class CloudRouter:
        is_cloud = True
        providers = {}

    assert _resolve_model_selection(
        CloudRouter(), "zerocode-cloud/MIMI"
    ) == ("MIMI", None)

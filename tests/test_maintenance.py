from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from zerocode import maintenance


def test_latest_release_tag_accepts_semver(monkeypatch):
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"tag_name": "v1.2.3"}

    monkeypatch.setattr(maintenance.httpx, "get", lambda *args, **kwargs: Response())
    assert maintenance.latest_release_tag() == "v1.2.3"


def test_latest_release_tag_rejects_untrusted_tag(monkeypatch):
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"tag_name": "../../run-this"}

    monkeypatch.setattr(maintenance.httpx, "get", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="tag de version invalide"):
        maintenance.latest_release_tag()


def test_latest_release_tag_reports_missing_release(monkeypatch):
    class Response:
        status_code = 404

        def raise_for_status(self):
            return None

        def json(self):
            return {}

    monkeypatch.setattr(maintenance.httpx, "get", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="Aucune version stable"):
        maintenance.latest_release_tag()


def test_pipx_command_prefers_binary(monkeypatch):
    monkeypatch.setattr(maintenance.shutil, "which", lambda name: "/usr/bin/pipx" if name == "pipx" else None)
    assert maintenance.pipx_command() == ["/usr/bin/pipx"]


def test_pipx_manages_zerocode_from_json(monkeypatch):
    monkeypatch.setattr(
        maintenance.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"venvs": {"zerocode": {"metadata": {}}}}),
        ),
    )
    assert maintenance.pipx_manages_zerocode(["pipx"])


def test_pipx_does_not_claim_unrelated_package(monkeypatch):
    monkeypatch.setattr(
        maintenance.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"venvs": {"ruff": {"metadata": {}}}}),
        ),
    )
    assert not maintenance.pipx_manages_zerocode(["pipx"])


def test_update_reinstalls_latest_tag(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(maintenance, "latest_release_tag", lambda: "v1.0.1")
    monkeypatch.setattr(maintenance, "pipx_command", lambda: ["pipx"])
    monkeypatch.setattr(maintenance, "pipx_manages_zerocode", lambda command: True)

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(maintenance.subprocess, "run", fake_run)
    ok, message = maintenance.update_from_release()

    assert ok
    assert "1.0.1" in message
    assert calls == [
        ["pipx", "install", "--force", "git+https://github.com/hackerboy-223/zerocode.git@v1.0.1"]
    ]


def test_uninstall_keeps_user_data_by_default(tmp_path, monkeypatch):
    config = tmp_path / "config" / "zerocode"
    data = tmp_path / "data" / "zerocode"
    config.mkdir(parents=True)
    data.mkdir(parents=True)

    monkeypatch.setattr(maintenance, "pipx_command", lambda: ["pipx"])
    monkeypatch.setattr(maintenance, "pipx_manages_zerocode", lambda command: True)
    monkeypatch.setattr(
        maintenance.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(maintenance, "config_dir", lambda: config)
    monkeypatch.setattr(maintenance, "data_dir", lambda: data)

    ok, message = maintenance.uninstall_from_pipx()

    assert ok
    assert "conservées" in message
    assert config.is_dir()
    assert data.is_dir()


def test_uninstall_removes_only_application_data_when_requested(tmp_path, monkeypatch):
    config_parent = tmp_path / "config"
    data_parent = tmp_path / "data"
    config = config_parent / "zerocode"
    data = data_parent / "zerocode"
    config.mkdir(parents=True)
    data.mkdir(parents=True)
    (config / "keys.json").write_text("{}")
    (data / "sessions").mkdir()

    monkeypatch.setattr(maintenance, "pipx_command", lambda: ["pipx"])
    monkeypatch.setattr(maintenance, "pipx_manages_zerocode", lambda command: True)
    monkeypatch.setattr(
        maintenance.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(maintenance, "config_dir", lambda: config)
    monkeypatch.setattr(maintenance, "data_dir", lambda: data)

    ok, message = maintenance.uninstall_from_pipx(remove_data=True)

    assert ok
    assert "Données utilisateur supprimées" in message
    assert not config.exists()
    assert not data.exists()
    assert config_parent.is_dir()
    assert data_parent.is_dir()


def test_uninstall_does_not_delete_data_when_pipx_fails(tmp_path, monkeypatch):
    config = tmp_path / "config" / "zerocode"
    data = tmp_path / "data" / "zerocode"
    config.mkdir(parents=True)
    data.mkdir(parents=True)

    monkeypatch.setattr(maintenance, "pipx_command", lambda: ["pipx"])
    monkeypatch.setattr(maintenance, "pipx_manages_zerocode", lambda command: True)
    monkeypatch.setattr(
        maintenance.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )
    monkeypatch.setattr(maintenance, "config_dir", lambda: config)
    monkeypatch.setattr(maintenance, "data_dir", lambda: data)

    ok, message = maintenance.uninstall_from_pipx(remove_data=True)

    assert not ok
    assert "ont été conservées" in message
    assert config.is_dir()
    assert data.is_dir()

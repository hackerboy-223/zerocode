from __future__ import annotations

import json
from pathlib import Path
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



def test_release_asset_checksum_accepts_matching_digest(monkeypatch, tmp_path):
    import hashlib

    payload = b"verified-wheel"

    class Response:
        status_code = 200
        content = payload
        text = f"{hashlib.sha256(payload).hexdigest()}  package.whl\n"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(maintenance.httpx, "get", lambda *args, **kwargs: Response())
    destination = tmp_path / "package.whl"
    assert maintenance._release_asset_checksum(
        filename="package.whl",
        asset_url="https://github.com/hackerboy-223/zerocode/releases/download/v1.0.1/package.whl",
        checksum_url="https://github.com/hackerboy-223/zerocode/releases/download/v1.0.1/SHA256SUMS",
        destination=destination,
    )
    assert destination.read_bytes() == payload



def test_update_reinstalls_verified_release_wheel(monkeypatch):
    calls: list[list[str]] = []
    wheel_name = "zerocode-1.0.1-py3-none-any.whl"
    wheel_url = f"https://github.com/hackerboy-223/zerocode/releases/download/v1.0.1/{wheel_name}"
    assets = {
        wheel_name: wheel_url,
        "SHA256SUMS": "https://github.com/hackerboy-223/zerocode/releases/download/v1.0.1/SHA256SUMS",
    }
    monkeypatch.setattr(maintenance, "latest_release_details", lambda tag=None: ("v1.0.1", assets))
    def verify_and_save(**kwargs):
        kwargs["destination"].write_bytes(b"verified wheel")
        return True

    monkeypatch.setattr(maintenance, "_release_asset_checksum", verify_and_save)
    monkeypatch.setattr(maintenance, "pipx_command", lambda: ["pipx"])
    monkeypatch.setattr(maintenance, "pipx_manages_zerocode", lambda command: True)

    def fake_run(command, **kwargs):
        calls.append(command)
        assert Path(command[3]).read_bytes() == b"verified wheel"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(maintenance.subprocess, "run", fake_run)
    ok, message = maintenance.update_from_release()

    assert ok
    assert "1.0.1" in message
    assert len(calls) == 1
    assert calls[0][:3] == ["pipx", "install", "--force"]
    assert calls[0][3].endswith(wheel_name)
    assert Path(calls[0][3]).parent.name.startswith("zerocode-update-")



def test_repair_reinstalls_the_current_release(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    wheel_name = "zerocode-1.0.0-py3-none-any.whl"
    assets = {
        wheel_name: f"https://github.com/hackerboy-223/zerocode/releases/download/v1.0.0/{wheel_name}",
        "SHA256SUMS": "https://github.com/hackerboy-223/zerocode/releases/download/v1.0.0/SHA256SUMS",
    }
    monkeypatch.setattr(maintenance, "latest_release_details", lambda tag=None: ("v1.0.0", assets))
    monkeypatch.setattr(
        maintenance,
        "_release_asset_checksum",
        lambda **kwargs: kwargs["destination"].write_bytes(b"verified repair wheel"),
    )
    monkeypatch.setattr(maintenance, "pipx_command", lambda: ["pipx"])
    monkeypatch.setattr(maintenance, "pipx_manages_zerocode", lambda command: True)
    monkeypatch.setattr(
        maintenance.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0),
    )

    ok, message = maintenance.repair_from_release()

    assert ok
    assert "réparation terminée" in message
    assert len(calls) == 1
    assert calls[0][:3] == ["pipx", "install", "--force"]
    assert calls[0][3].endswith(wheel_name)



def test_rollback_uses_the_requested_validated_tag(monkeypatch):
    calls: list[list[str]] = []
    wheel_name = "zerocode-0.9.0-py3-none-any.whl"
    assets = {
        wheel_name: f"https://github.com/hackerboy-223/zerocode/releases/download/v0.9.0/{wheel_name}",
        "SHA256SUMS": "https://github.com/hackerboy-223/zerocode/releases/download/v0.9.0/SHA256SUMS",
    }
    requested: list[str | None] = []

    def release_details(tag=None):
        requested.append(tag)
        return "v0.9.0", assets

    monkeypatch.setattr(maintenance, "latest_release_details", release_details)
    monkeypatch.setattr(
        maintenance,
        "_release_asset_checksum",
        lambda **kwargs: kwargs["destination"].write_bytes(b"verified rollback wheel"),
    )
    monkeypatch.setattr(maintenance, "pipx_command", lambda: ["pipx"])
    monkeypatch.setattr(maintenance, "pipx_manages_zerocode", lambda command: True)
    monkeypatch.setattr(
        maintenance.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0),
    )

    ok, message = maintenance.rollback_to_release("v0.9.0")

    assert ok
    assert "retour à la version v0.9.0 terminé" in message
    assert requested == ["v0.9.0"]
    assert len(calls) == 1
    assert calls[0][3].endswith(wheel_name)



def test_rollback_rejects_an_untrusted_tag(monkeypatch):
    monkeypatch.setattr(
        maintenance,
        "latest_release_details",
        lambda tag=None: (_ for _ in ()).throw(RuntimeError("Le tag de version demandé est invalide.")),
    )
    ok, message = maintenance.rollback_to_release("../../unsafe")
    assert not ok
    assert "tag de version demandé est invalide" in message



def test_windows_update_uses_standalone_installer(monkeypatch):
    monkeypatch.setattr(maintenance.os, "name", "nt")
    ok, message = maintenance.update_from_release()
    assert not ok
    assert "PowerShell" in message



def test_windows_uninstall_requires_closed_application(monkeypatch):
    monkeypatch.setattr(maintenance.os, "name", "nt")
    ok, message = maintenance.uninstall_from_pipx()
    assert not ok
    assert "pipx uninstall zerocode" in message
    assert "sessions" in message



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



def test_release_asset_checksum_rejects_changed_download(monkeypatch, tmp_path):
    import hashlib

    expected_payload = b"official-wheel"
    changed_payload = b"modified-wheel"

    class Response:
        status_code = 200
        content = changed_payload
        text = f"{hashlib.sha256(expected_payload).hexdigest()}  package.whl\n"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(maintenance.httpx, "get", lambda *args, **kwargs: Response())
    destination = tmp_path / "package.whl"
    with pytest.raises(RuntimeError, match="ne correspond pas"):
        maintenance._release_asset_checksum(
            filename="package.whl",
            asset_url="https://github.com/hackerboy-223/zerocode/releases/download/v1.0.1/package.whl",
            checksum_url="https://github.com/hackerboy-223/zerocode/releases/download/v1.0.1/SHA256SUMS",
            destination=destination,
        )
    assert not destination.exists()


from __future__ import annotations

import os
import stat
import subprocess

from zerocode.checkpoints import CheckpointStore


def test_checkpoint_restores_existing_file(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("apres", encoding="utf-8")
    store = CheckpointStore(tmp_path / "checkpoints")
    assert store.record("s1", target, "avant", "edit")
    ok, message = store.undo("s1")
    assert ok
    assert "Restaure" in message
    assert target.read_text(encoding="utf-8") == "avant"
    assert store.pending("s1") == 0


def test_checkpoint_deletes_created_file(tmp_path):
    target = tmp_path / "new.txt"
    target.write_text("contenu", encoding="utf-8")
    store = CheckpointStore(tmp_path / "checkpoints")
    assert store.record("s1", target, None, "write")
    ok, _ = store.undo("s1")
    assert ok
    assert not target.exists()


def test_checkpoint_rejects_oversized_content(tmp_path):
    target = tmp_path / "big.txt"
    store = CheckpointStore(tmp_path / "checkpoints")
    assert not store.record("s1", target, "x" * 1_000_001, "write")


def test_checkpoint_file_is_private(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("contenu", encoding="utf-8")
    store = CheckpointStore(tmp_path / "checkpoints")
    assert store.record("s1", target, "avant", "edit")

    path = tmp_path / "checkpoints" / "s1.json"
    assert path.is_file()
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    else:
        acl = subprocess.run(
            ["icacls", str(path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.lower()
        assert (os.environ.get("USERNAME") or "").lower() in acl


def test_checkpoint_undo_refuses_secret_or_git_paths(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=keep\n", encoding="utf-8")
    assert store.record("s1", env_file, "SECRET=overwritten\n", "edit")
    ok, message = store.undo("s1")
    assert not ok
    assert "sensible" in message
    assert env_file.read_text(encoding="utf-8") == "SECRET=keep\n"



def test_checkpoint_undo_refuses_to_overwrite_changes_made_after_agent(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("agent version", encoding="utf-8")
    store = CheckpointStore(tmp_path / "checkpoints")
    assert store.record("s1", target, "before agent", "edit")
    assert store.mark_applied("s1", target)

    target.write_text("user's newer work", encoding="utf-8")
    ok, message = store.undo("s1", tmp_path)

    assert not ok
    assert "change depuis le checkpoint" in message
    assert target.read_text(encoding="utf-8") == "user's newer work"


def test_checkpoint_undo_refuses_paths_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("agent version", encoding="utf-8")
    store = CheckpointStore(tmp_path / "checkpoints")
    assert store.record("s1", outside, "before", "edit")
    assert store.mark_applied("s1", outside)

    ok, message = store.undo("s1", workspace)

    assert not ok
    assert "hors du dossier de travail" in message
    assert outside.read_text(encoding="utf-8") == "agent version"


def test_checkpoint_undo_restores_when_file_is_unchanged(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("agent version", encoding="utf-8")
    store = CheckpointStore(tmp_path / "checkpoints")
    assert store.record("s1", target, "before agent", "edit")
    assert store.mark_applied("s1", target)

    ok, _ = store.undo("s1", tmp_path)

    assert ok
    assert target.read_text(encoding="utf-8") == "before agent"

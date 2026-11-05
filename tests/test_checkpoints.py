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


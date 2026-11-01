from __future__ import annotations

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

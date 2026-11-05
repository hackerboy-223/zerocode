from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import _set_private_permissions, data_dir
from .tools.base import is_secret_path

MAX_CHECKPOINT_CHARS = 1_000_000
MAX_ENTRIES = 50


@dataclass
class Checkpoint:
    path: str
    existed: bool
    content: str
    tool: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "existed": self.existed,
            "content": self.content,
            "tool": self.tool,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint | None:
        path = data.get("path")
        if not isinstance(path, str) or not path:
            return None
        return cls(
            path=path,
            existed=bool(data.get("existed")),
            content=str(data.get("content") or ""),
            tool=str(data.get("tool") or ""),
            created_at=str(data.get("created_at") or ""),
        )


class CheckpointStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or (data_dir() / "checkpoints")).expanduser()

    def record(
        self,
        session_id: str,
        path: Path,
        before: str | None,
        tool: str,
    ) -> bool:
        if before is not None and len(before) > MAX_CHECKPOINT_CHARS:
            return False
        entries = self._load(session_id)
        entries.append(
            Checkpoint(
                path=str(path.resolve()),
                existed=before is not None,
                content=before or "",
                tool=tool,
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
        )
        self._save(session_id, entries[-MAX_ENTRIES:])
        return True

    def undo(self, session_id: str) -> tuple[bool, str]:
        entries = self._load(session_id)
        if not entries:
            return False, "Aucune modification a annuler."
        checkpoint = entries.pop()
        path = Path(checkpoint.path)
        if ".git" in path.parts or is_secret_path(path):
            return False, f"Restauration refusee pour le chemin sensible: {path}"
        try:
            if checkpoint.existed:
                _atomic_text_write(path, checkpoint.content)
                message = f"Restaure {path} (avant {checkpoint.tool or 'modification'})."
            else:
                path.unlink(missing_ok=True)
                message = f"Supprime {path} (cree par {checkpoint.tool or 'un outil'})."
        except OSError as exc:
            return False, f"Impossible d'annuler {path}: {exc}"
        self._save(session_id, entries)
        return True, message

    def pending(self, session_id: str) -> int:
        return len(self._load(session_id))

    def clear(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)

    def _path(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id) or "session"
        return self.root / f"{safe}.json"

    def _load(self, session_id: str) -> list[Checkpoint]:
        path = self._path(session_id)
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, dict):
            return []
        raw = data.get("entries")
        if not isinstance(raw, list):
            return []
        entries: list[Checkpoint] = []
        for item in raw:
            if isinstance(item, dict):
                checkpoint = Checkpoint.from_dict(item)
                if checkpoint is not None:
                    entries.append(checkpoint)
        return entries

    def _save(self, session_id: str, entries: list[Checkpoint]) -> None:
        path = self._path(session_id)
        if not entries:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"version": 1, "entries": [entry.to_dict() for entry in entries]},
            ensure_ascii=False,
            indent=2,
        )
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            _set_private_permissions(temp, 0o600)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def _atomic_text_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o644
    if path.exists():
        with contextlib.suppress(OSError):
            mode = path.stat().st_mode & 0o777
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

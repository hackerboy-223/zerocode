from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import data_dir
from .errors import ConfigError
from .types import Usage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Session:
    id: str
    cwd: str
    model: str
    provider: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    messages: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    todos: list[dict[str, Any]] = field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "id": self.id,
            "cwd": self.cwd,
            "model": self.model,
            "provider": self.provider,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
            "usage": self.usage.as_dict(),
            "todos": self.todos,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        try:
            session_id = str(data["id"])
            cwd = str(data["cwd"])
            model = str(data["model"])
        except KeyError as exc:
            raise ConfigError(f"Session invalide: champ manquant {exc}.") from exc
        messages = data.get("messages") or []
        if not isinstance(messages, list):
            raise ConfigError("Session invalide: messages doit etre une liste.")
        todos = data.get("todos") or []
        if not isinstance(todos, list):
            todos = []
        return cls(
            id=session_id,
            cwd=cwd,
            model=model,
            provider=data.get("provider"),
            created_at=str(data.get("created_at") or _now()),
            updated_at=str(data.get("updated_at") or _now()),
            messages=[message for message in messages if isinstance(message, dict)],
            usage=Usage.from_dict(data.get("usage")),
            todos=[todo for todo in todos if isinstance(todo, dict)],
        )


class SessionStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or (data_dir() / "sessions")).expanduser()

    def new(self, cwd: Path, model: str, provider: str | None = None) -> Session:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        session_id = f"{stamp}-{secrets.token_hex(3)}"
        return Session(id=session_id, cwd=str(cwd.resolve()), model=model, provider=provider)

    def path_for(self, session: Session) -> Path:
        return self.root / f"{session.id}.json"

    def save(self, session: Session) -> Path:
        session.touch()
        path = self.path_for(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(session.to_dict(), ensure_ascii=False, indent=2) + "\n"
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return path

    def load(self, ref: str | None = None) -> Session | None:
        if ref:
            candidate = Path(ref).expanduser()
            if candidate.is_file():
                return self._load_file(candidate)
            matches = [
                path
                for path in self.root.glob("*.json")
                if path.stem == ref or path.stem.startswith(ref) or ref in path.stem
            ]
            if not matches:
                return None
            matches.sort(key=lambda item: item.stat().st_mtime, reverse=True)
            return self._load_file(matches[0])
        return self.latest()

    def latest(self, cwd: Path | None = None) -> Session | None:
        items = self.list()
        if cwd is not None:
            resolved = str(cwd.resolve())
            items = [item for item in items if item["cwd"] == resolved]
        if not items:
            return None
        return self._load_file(Path(items[0]["path"]))

    def list(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if not self.root.is_dir():
            return result
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            result.append(
                {
                    "id": str(data.get("id", path.stem)),
                    "path": str(path),
                    "cwd": str(data.get("cwd", "")),
                    "model": str(data.get("model", "")),
                    "provider": data.get("provider"),
                    "created_at": str(data.get("created_at", "")),
                    "updated_at": str(data.get("updated_at", "")),
                    "messages": len(data.get("messages") or []),
                    "total_tokens": int((data.get("usage") or {}).get("total_tokens", 0) or 0),
                }
            )
        result.sort(key=lambda item: item["updated_at"], reverse=True)
        return result

    def delete(self, ref: str) -> bool:
        session = self.load(ref)
        if session is None:
            return False
        self.path_for(session).unlink(missing_ok=True)
        return True

    def clear(self) -> int:
        removed = 0
        if not self.root.is_dir():
            return 0
        for path in self.root.glob("*.json"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def _load_file(self, path: Path) -> Session:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(f"Impossible de lire la session {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Session invalide {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"Session invalide {path}: objet JSON attendu.")
        return Session.from_dict(data)

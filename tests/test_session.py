from __future__ import annotations

import json

import pytest

from zerocode.errors import ConfigError
from zerocode.session import Session, SessionStore
from zerocode.types import Usage


def test_session_save_load_list_and_latest(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    first = store.new(tmp_path, "auto")
    first.messages.append({"role": "user", "content": "bonjour"})
    first.usage = Usage(prompt_tokens=3, completion_tokens=4, total_tokens=7, requests=1)
    first.todos = [{"content": "test", "status": "pending"}]
    path = store.save(first)

    assert path.is_file()
    loaded = store.load(first.id)
    assert loaded is not None
    assert loaded.id == first.id
    assert loaded.messages == first.messages
    assert loaded.usage.as_dict() == first.usage.as_dict()
    assert loaded.todos == first.todos

    assert store.load(first.id[:12]) is not None
    assert store.load(str(path)) is not None
    items = store.list()
    assert items[0]["id"] == first.id
    assert items[0]["messages"] == 1
    assert items[0]["total_tokens"] == 7

    second = store.new(tmp_path, "glm-5.3-flash")
    store.save(second)
    assert store.latest(tmp_path) is not None
    assert store.latest(tmp_path / "other") is None

    assert store.delete(first.id) is True
    assert store.load(first.id) is None


def test_clear_removes_all_sessions(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    store.save(store.new(tmp_path, "auto"))
    store.save(store.new(tmp_path, "auto"))
    assert store.clear() == 2
    assert store.list() == []


def test_invalid_session_file(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(ConfigError):
        store.load(str(broken))


def test_session_roundtrip_ignores_invalid_messages(tmp_path):
    session = Session(
        id="abc",
        cwd=str(tmp_path),
        model="auto",
        messages=[{"role": "user", "content": "ok"}, "invalid"],
    )
    data = session.to_dict()
    data["messages"] = [{"role": "user", "content": "ok"}, "invalid"]
    loaded = Session.from_dict(data)
    assert loaded.messages == [{"role": "user", "content": "ok"}]


def test_session_requires_core_fields(tmp_path):
    with pytest.raises(ConfigError):
        Session.from_dict({"id": "abc", "cwd": str(tmp_path)})


def test_session_list_handles_bad_json(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    (root / "bad.json").write_text("{", encoding="utf-8")
    (root / "good.json").write_text(
        json.dumps({"id": "good", "cwd": str(tmp_path), "model": "auto"}),
        encoding="utf-8",
    )
    store = SessionStore(root)
    assert [item["id"] for item in store.list()] == ["good"]

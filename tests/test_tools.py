from __future__ import annotations

from pathlib import Path

from zerocode.tools import PermissionManager, ToolContext, build_registry
from zerocode.types import ToolCall


def make_registry(tmp_path, *, mode="allow", allow_outside=False):
    context = ToolContext(cwd=tmp_path, allow_outside=allow_outside)
    permissions = PermissionManager(mode=mode, interactive=False)
    return build_registry(context, permissions), context


def call(registry, name, **arguments):
    return registry.execute(ToolCall(id="call-1", name=name, arguments=arguments))


def test_write_read_edit_and_list(tmp_path):
    registry, _ = make_registry(tmp_path)
    assert "Ecrit" in call(registry, "write", path="src/app.py", content="un\ndeux\n")
    read = call(registry, "read", path="src/app.py")
    assert "1: un" in read
    assert "2: deux" in read
    assert "Modifie" in call(
        registry,
        "edit",
        path="src/app.py",
        old_string="deux",
        new_string="trois",
    )
    assert "trois" in call(registry, "read", path="src/app.py")
    listing = call(registry, "list", path=".", glob="**/*.py")
    assert "src/app.py" in listing


def test_path_outside_workspace_is_refused(tmp_path):
    registry, _ = make_registry(tmp_path)
    result = call(registry, "read", path="../outside.txt")
    assert result.startswith("ERREUR:")
    assert "hors du repertoire" in result


def test_write_into_git_is_refused(tmp_path):
    registry, _ = make_registry(tmp_path)
    result = call(registry, "write", path=".git/config", content="bad")
    assert result.startswith("ERREUR:")
    assert ".git" in result


def test_binary_read_is_refused(tmp_path):
    (tmp_path / "image.bin").write_bytes(b"\x00\x01")
    registry, _ = make_registry(tmp_path)
    result = call(registry, "read", path="image.bin")
    assert result.startswith("ERREUR:")
    assert "binaire" in result


def test_edit_requires_unique_match(tmp_path):
    (tmp_path / "file.txt").write_text("same same", encoding="utf-8")
    registry, _ = make_registry(tmp_path)
    result = call(
        registry,
        "edit",
        path="file.txt",
        old_string="same",
        new_string="other",
    )
    assert result.startswith("ERREUR:")
    assert "2 fois" in result


def test_grep_python_fallback(tmp_path):
    (tmp_path / "a.py").write_text("print('bonjour')\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("bonjour\n", encoding="utf-8")
    registry, _ = make_registry(tmp_path)
    result = call(registry, "grep", pattern="bonjour", include="*.py")
    assert "a.py" in result
    assert "b.txt" not in result


def test_todo_write_replaces_plan(tmp_path):
    registry, context = make_registry(tmp_path)
    result = call(
        registry,
        "todo_write",
        todos=[
            {"content": "inspecter", "status": "completed"},
            {"content": "modifier", "status": "in_progress"},
        ],
    )
    assert "inspecter" in result
    assert context.todos[1]["status"] == "in_progress"


def test_bash_runs_in_workspace(tmp_path):
    registry, _ = make_registry(tmp_path)
    result = call(registry, "bash", command="printf hello")
    assert "exit_code: 0" in result
    assert "hello" in result


def test_permissions_deny_mutation_but_allow_read(tmp_path):
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    registry, _ = make_registry(tmp_path, mode="deny")
    assert "hello" in call(registry, "read", path="file.txt")
    denied = call(registry, "write", path="new.txt", content="no")
    assert "refusee" in denied


def test_unknown_tool_and_missing_argument(tmp_path):
    registry, _ = make_registry(tmp_path)
    assert "outil inconnu" in call(registry, "nope")
    assert "Argument obligatoire manquant" in call(registry, "read")
    assert "Argument inconnu" in call(registry, "read", path="x", extra=1)


def test_allow_outside_cwd(tmp_path):
    outside = tmp_path.parent / "outside-zerocode.txt"
    outside.write_text("ok", encoding="utf-8")
    try:
        registry, _ = make_registry(tmp_path, allow_outside=True)
        assert "ok" in call(registry, "read", path=str(Path(outside)))
    finally:
        outside.unlink(missing_ok=True)

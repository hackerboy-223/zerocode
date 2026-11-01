from __future__ import annotations

import threading
import time
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


def test_write_and_edit_emit_diffs(tmp_path):
    diffs: list[tuple[str, str]] = []
    context = ToolContext(cwd=tmp_path, show_diff=lambda path, diff: diffs.append((path, diff)))
    permissions = PermissionManager(mode="allow", interactive=False)
    registry = build_registry(context, permissions)

    call(registry, "write", path="src/app.py", content="un\ndeux\n")
    assert diffs[-1][0] == "src/app.py"
    assert "--- /dev/null" in diffs[-1][1]
    assert "+un" in diffs[-1][1]
    assert "+deux" in diffs[-1][1]

    call(registry, "edit", path="src/app.py", old_string="deux", new_string="trois")
    assert diffs[-1][0] == "src/app.py"
    assert "-deux" in diffs[-1][1]
    assert "+trois" in diffs[-1][1]


def test_sudo_command_detection():
    from zerocode.tools.shell import has_sudo_command

    assert has_sudo_command("sudo apt update")
    assert has_sudo_command("cd /tmp && sudo rm -rf build")
    assert has_sudo_command("echo x | sudo tee /etc/motd")
    assert has_sudo_command("/usr/bin/sudo id")
    assert not has_sudo_command("man sudo")
    assert not has_sudo_command("which sudo")
    assert not has_sudo_command("visudo")


def test_bash_command_can_be_interrupted(tmp_path):
    registry, context = make_registry(tmp_path)
    result: dict[str, str] = {}

    def worker() -> None:
        result["output"] = call(registry, "bash", command="sleep 30", timeout=60)

    thread = threading.Thread(target=worker)
    thread.start()
    for _ in range(200):
        if context._active_process is not None:
            break
        time.sleep(0.01)
    assert context._active_process is not None
    context.terminate_active_process()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert "interrompue par l'utilisateur" in result["output"]
    assert "exit_code: 130" in result["output"]


def test_secret_files_are_protected(tmp_path):
    (tmp_path / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    registry, context = make_registry(tmp_path)
    blocked = call(registry, "read", path=".env")
    assert blocked.startswith("ERREUR:")
    assert "protege" in blocked
    assert call(registry, "write", path=".env", content="TOKEN=x\n").startswith("ERREUR:")
    grep = call(registry, "grep", pattern="TOKEN")
    assert ".env" not in grep
    context.allow_secrets = True
    assert "TOKEN=secret" in call(registry, "read", path=".env")


def test_gitignore_is_respected(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("cache\n", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("visible\n", encoding="utf-8")
    registry, _ = make_registry(tmp_path)
    listing = call(registry, "list", path=".")
    assert "visible.txt" in listing
    assert "ignored.txt" not in listing
    assert "ignored.txt" not in call(registry, "grep", pattern="cache")


def test_bash_timeout_terminates_command(tmp_path):
    registry, _ = make_registry(tmp_path)
    started = time.monotonic()
    result = call(registry, "bash", command="sleep 5", timeout=1)
    assert "exit_code: 124" in result
    assert time.monotonic() - started < 4


def test_bash_streams_output(tmp_path):
    chunks: list[tuple[str, str]] = []
    context = ToolContext(cwd=tmp_path, stream_output=lambda name, chunk: chunks.append((name, chunk)))
    permissions = PermissionManager(mode="allow", interactive=False)
    registry = build_registry(context, permissions)
    result = call(registry, "bash", command="printf 'un\\ndeux\\n'")
    assert "exit_code: 0" in result
    assert any("un" in chunk for _, chunk in chunks)
    assert any("deux" in chunk for _, chunk in chunks)


def test_web_tools_are_registered_and_block_localhost(tmp_path):
    registry, _ = make_registry(tmp_path)
    assert "fetch" in registry.names()
    assert "web_search" in registry.names()
    result = call(registry, "fetch", url="http://127.0.0.1:8080")
    assert result.startswith("ERREUR:")
    assert "locales et privees" in result


def test_bash_output_is_bounded_without_streaming(tmp_path):
    import sys

    context = ToolContext(cwd=tmp_path, max_output_chars=4_000)
    permissions = PermissionManager(mode="allow", interactive=False)
    registry = build_registry(context, permissions)
    command = f'"{sys.executable}" -c "print(\'x\' * 100000)"'

    result = call(registry, "bash", command=command)

    assert "exit_code: 0" in result
    assert "stdout tronque" in result
    assert len(result) < 3_000


def test_bash_output_is_bounded_with_streaming(tmp_path):
    import sys

    chunks: list[tuple[str, str]] = []
    context = ToolContext(
        cwd=tmp_path,
        max_output_chars=4_000,
        stream_output=lambda name, chunk: chunks.append((name, chunk)),
    )
    permissions = PermissionManager(mode="allow", interactive=False)
    registry = build_registry(context, permissions)
    command = f'"{sys.executable}" -c "print(\'x\' * 100000)"'

    result = call(registry, "bash", command=command)

    assert "exit_code: 0" in result
    assert "stdout tronque" in result
    assert chunks
    assert len(result) < 3_000

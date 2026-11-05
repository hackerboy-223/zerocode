from __future__ import annotations

import sys
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


def python_command(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


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
    result = call(registry, "bash", command=python_command("print('hello')"))
    assert "exit_code: 0" in result
    assert "hello" in result


def test_bash_does_not_read_parent_stdin(tmp_path):
    registry, _ = make_registry(tmp_path)
    command = python_command("import sys; print(len(sys.stdin.read()))")
    result = call(registry, "bash", command=command, timeout=5)
    assert "exit_code: 0" in result
    assert "\n0" in result or "stdout:\n0" in result


def test_ripgrep_line_path_supports_windows_drive_and_colons():
    from zerocode.tools.search import _ripgrep_line_path

    assert _ripgrep_line_path(r"C:\repo\src\app.py:12:match") == r"C:\repo\src\app.py"
    assert _ripgrep_line_path("src/app.py:3:foo:bar") == "src/app.py"
    assert _ripgrep_line_path("src/app.py:4:2: value") == "src/app.py"
    assert _ripgrep_line_path("no-match") == "no-match"


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
        result["output"] = call(
            registry,
            "bash",
            command=python_command("import time; time.sleep(30)"),
            timeout=60,
        )

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
    result = call(
        registry,
        "bash",
        command=python_command("import time; time.sleep(5)"),
        timeout=1,
    )
    assert "exit_code: 124" in result
    assert time.monotonic() - started < 4


def test_bash_streams_output(tmp_path):
    chunks: list[tuple[str, str]] = []
    context = ToolContext(cwd=tmp_path, stream_output=lambda name, chunk: chunks.append((name, chunk)))
    permissions = PermissionManager(mode="allow", interactive=False)
    registry = build_registry(context, permissions)
    result = call(registry, "bash", command=python_command("print('un'); print('deux')"))
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
    context = ToolContext(cwd=tmp_path, max_output_chars=4_000)
    permissions = PermissionManager(mode="allow", interactive=False)
    registry = build_registry(context, permissions)
    command = python_command("print('x' * 100000)")

    result = call(registry, "bash", command=command)

    assert "exit_code: 0" in result
    assert "stdout tronque" in result
    assert len(result) < 3_000


def test_bash_output_is_bounded_with_streaming(tmp_path):
    chunks: list[tuple[str, str]] = []
    context = ToolContext(
        cwd=tmp_path,
        max_output_chars=4_000,
        stream_output=lambda name, chunk: chunks.append((name, chunk)),
    )
    permissions = PermissionManager(mode="allow", interactive=False)
    registry = build_registry(context, permissions)
    command = python_command("print('x' * 100000)")

    result = call(registry, "bash", command=command)

    assert "exit_code: 0" in result
    assert "stdout tronque" in result
    assert chunks
    assert len(result) < 3_000

def test_auto_permissions_allow_new_files_and_in_workspace_edits(tmp_path):
    context = ToolContext(cwd=tmp_path)
    permissions = PermissionManager(mode="ask", interactive=False)
    registry = build_registry(context, permissions)

    created = call(registry, "write", path="src/app.py", content="value = 1\n")
    assert "Ecrit" in created
    edited = call(
        registry,
        "edit",
        path="src/app.py",
        old_string="value = 1",
        new_string="value = 2",
    )
    assert "Modifie" in edited
    assert "value = 2" in (tmp_path / "src/app.py").read_text(encoding="utf-8")


def test_auto_permissions_do_not_overwrite_existing_files(tmp_path):
    target = tmp_path / "existing.py"
    target.write_text("keep = True\n", encoding="utf-8")
    context = ToolContext(cwd=tmp_path)
    permissions = PermissionManager(mode="ask", interactive=False)
    registry = build_registry(context, permissions)

    result = call(registry, "write", path="existing.py", content="replace = True\n")

    assert "refusee" in result
    assert target.read_text(encoding="utf-8") == "keep = True\n"


def test_auto_shell_allows_safe_commands_and_blocks_arbitrary_commands(tmp_path):
    context = ToolContext(cwd=tmp_path)
    permissions = PermissionManager(mode="ask", interactive=False)
    registry = build_registry(context, permissions)

    safe = call(registry, "bash", command="python -m pytest --version")
    assert "exit_code: 0" in safe
    assert "Action refusee" not in safe

    unsafe = call(registry, "bash", command="rm -rf build")
    assert "Action refusee" in unsafe

    compound = call(registry, "bash", command="pwd; touch unexpected.txt")
    assert "Action refusee" in compound
    assert not (tmp_path / "unexpected.txt").exists()

    (tmp_path / ".env").write_text("TOKEN=secret\\n", encoding="utf-8")
    secret = call(registry, "bash", command="cat .env")
    assert "Action refusee" in secret

    outside = call(registry, "bash", command="ls ../")
    assert "Action refusee" in outside


def test_web_ssrf_blocks_unspecified_and_ipv4_mapped_ipv6(tmp_path):
    registry, _ = make_registry(tmp_path)
    for blocked_url in (
        "http://0.0.0.0:8000",
        "http://[::ffff:127.0.0.1]:8000",
        "http://[::ffff:169.254.169.254]/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
    ):
        result = call(registry, "fetch", url=blocked_url)
        assert result.startswith("ERREUR:")
        assert "locales et privees" in result


def test_list_files_hides_secrets_and_outside_symlinks(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (workspace / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (workspace / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (workspace / "id_rsa.pem").write_text("PRIVATE\n", encoding="utf-8")
    (workspace / "escape.txt").symlink_to(outside)

    registry, _ = make_registry(workspace)
    listed = call(registry, "list", glob="*")
    assert "ok.py" in listed
    assert ".env" not in listed
    assert "id_rsa.pem" not in listed
    assert "escape.txt" not in listed


def test_bash_scrubs_provider_api_keys_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-super-secret")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-super-secret")
    registry, _ = make_registry(tmp_path)
    result = call(
        registry,
        "bash",
        command=python_command(
            "import os; print(os.environ.get('OPENROUTER_API_KEY', 'ABSENT'), os.environ.get('NVIDIA_API_KEY', 'ABSENT'))"
        ),
    )
    assert "ABSENT ABSENT" in result
    assert "super-secret" not in result


def test_syntax_diagnostics_on_write_and_edit(tmp_path):
    registry, _ = make_registry(tmp_path)
    broken = call(registry, "write", path="broken.py", content="def oops(:\n    pass\n")
    assert "DIAGNOSTIC SYNTAXE PYTHON" in broken

    broken_json = call(registry, "write", path="broken.json", content="{bad: 1}\n")
    assert "DIAGNOSTIC JSON" in broken_json

    broken_toml = call(registry, "write", path="broken.toml", content="[section\nx = 1\n")
    assert "DIAGNOSTIC TOML" in broken_toml

    broken_sh = call(registry, "write", path="broken.sh", content="if [ 1 -eq 1 ]; then\n  echo hi\n")
    assert "DIAGNOSTIC SHELL" in broken_sh


def test_dlp_secret_redaction_and_catastrophic_shell_block(tmp_path):
    (tmp_path / "notes.txt").write_text(
        "Cle leak: sk-or-v1-1234567890abcdef1234567890abcdef et AKIA1234567890ABCDEF\n",
        encoding="utf-8",
    )
    registry, _ = make_registry(tmp_path, mode="allow")
    read_out = call(registry, "read", path="notes.txt")
    assert "[SECRET MASQUE: JETON API]" in read_out
    assert "1234567890abcdef1234567890abcdef" not in read_out
    assert "AKIA1234567890ABCDEF" not in read_out

    for catastrophic in (
        "rm -rf /",
        "sudo rm -rf /*",
        ":(){ :|:& };:",
        "dd if=/dev/zero of=/dev/sda bs=1M",
    ):
        blocked = call(registry, "bash", command=catastrophic)
        assert "Action refusee (securite)" in blocked


def test_multi_edit_atomic_and_rollback_on_failure(tmp_path):
    target = tmp_path / "service.py"
    target.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    registry, _ = make_registry(tmp_path)

    # Atomic failure when one edit does not match
    failed = call(
        registry,
        "multi_edit",
        path="service.py",
        edits=[
            {"old_string": "a = 1", "new_string": "a = 10"},
            {"old_string": "missing = 99", "new_string": "missing = 100"},
        ],
    )
    assert failed.startswith("ERREUR:")
    assert target.read_text(encoding="utf-8") == "a = 1\nb = 2\nc = 3\n"

    # Successful multi-block edit
    ok = call(
        registry,
        "multi_edit",
        path="service.py",
        edits=[
            {"old_string": "a = 1", "new_string": "a = 10"},
            {"old_string": "c = 3", "new_string": "c = 30"},
        ],
    )
    assert "2 bloc(s), 2 remplacement(s)" in ok
    assert target.read_text(encoding="utf-8") == "a = 10\nb = 2\nc = 30\n"


def test_symbols_tool_extracts_python_and_generic_symbols(tmp_path):
    (tmp_path / "engine.py").write_text(
        "class SecurityScanner:\n"
        "    def scan_repo(self):\n"
        "        return True\n\n"
        "async def run_pipeline():\n"
        "    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "client.ts").write_text(
        "export class ApiClient {}\nexport async function fetchUser() {}\n",
        encoding="utf-8",
    )
    registry, _ = make_registry(tmp_path)

    all_syms = call(registry, "symbols", path=".")
    assert "engine.py:1: [class] SecurityScanner" in all_syms
    assert "engine.py:2: [method] SecurityScanner.scan_repo" in all_syms
    assert "engine.py:5: [async def] run_pipeline" in all_syms
    assert "client.ts:1: [class] ApiClient" in all_syms
    assert "client.ts:2: [function] fetchUser" in all_syms

    filtered = call(registry, "symbols", path=".", query="scan_repo")
    assert "SecurityScanner.scan_repo" in filtered
    assert "ApiClient" not in filtered


def test_security_audit_and_sys_diag_tools(tmp_path):
    (tmp_path / "vuln_app.py").write_text(
        "import subprocess, pickle, hashlib\n"
        "def run_cmd(user_input):\n"
        "    subprocess.run(user_input, shell=True)\n"
        "    pickle.loads(b'data')\n"
        "    h = hashlib.md5(b'pw')\n"
        "    eval(user_input)\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    registry, _ = make_registry(tmp_path)

    report = call(registry, "security_audit", path=".")
    assert "SEC-001" in report
    assert "SEC-002" in report
    assert "SEC-003" in report
    assert "SEC-007" in report
    assert "SEC-ENV" in report

    diag = call(registry, "sys_diag", section="all")
    assert "DIAGNOSTIC SYSTÈME & TECHNICIEN ZEROCODE" in diag
    assert "[Système & Ressources]" in diag
    assert "[Toolchain Dev, Sécurité & Système]" in diag



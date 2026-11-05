from __future__ import annotations

import contextlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from ..catalog import PROVIDERS
from .base import Tool, ToolContext, ToolRegistry

PROVIDER_KEY_ENVS = frozenset(
    env_name for spec in PROVIDERS.values() for env_name in spec.api_key_envs
)

MAX_COMMAND_TIMEOUT = 3_600
TERMINATE_GRACE = 2.0
SUDO_COMMAND_RE = re.compile(
    r"(?P<prefix>(?:^|[;&|(\n]|&&|\|\|)\s*"
    r"(?:(?:env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*)?)"
    r"(?P<sudo>(?:[\w./-]*/)?sudo)(?P<suffix>(?=\s|$|[;&|)]))"
)


def _safe_workspace_arguments(
    arguments: list[str], ctx: ToolContext, *, check_bare_paths: bool = False
) -> bool:
    for argument in arguments:
        candidate = argument
        if argument.startswith("-"):
            if "=" not in argument:
                continue
            candidate = argument.split("=", 1)[1]
        if not candidate:
            continue
        if (
            candidate.startswith(("/", "~"))
            or candidate == ".."
            or candidate.startswith("../")
            or "/../" in candidate
            or "\\..\\" in candidate
            or re.match(r"^[A-Za-z]:", candidate)
        ):
            return False
        if check_bare_paths or "/" in candidate or "\\" in candidate:
            try:
                path = ctx.resolve_path(candidate)
                ctx.check_secret(path)
            except Exception:
                return False
    return True


def is_safe_auto_command(command: str, ctx: ToolContext) -> bool:
    """Return true only for simple, non-mutating inspection and dev-check commands."""
    raw = command.strip()
    if not raw or any(char in raw for char in (";", "&", "|", "<", ">", "`", "$", "\n", "\r")):
        return False
    try:
        parts = shlex.split(raw)
    except ValueError:
        return False
    if not parts:
        return False

    executable = os.path.basename(parts[0]).lower()
    arguments = parts[1:]

    if executable == "pwd":
        return not arguments
    if executable == "ls":
        return _safe_workspace_arguments(arguments, ctx, check_bare_paths=True)
    if not _safe_workspace_arguments(arguments, ctx):
        return False
    if executable == "git" and arguments:
        subcommand = arguments[0]
        options = arguments[1:]
        if subcommand == "status":
            return all(option in {"--short", "--porcelain", "--branch", "--ignored"} for option in options)
        if subcommand == "diff":
            return bool(options) and all(
                option in {"--check", "--stat", "--name-only", "--no-ext-diff", "--"}
                for option in options
            )
        if subcommand == "log":
            return bool(options) and all(
                option == "--oneline" or option.startswith(("-n", "--max-count="))
                for option in options
            )
        if subcommand == "branch":
            return options == ["--show-current"]
        if subcommand == "rev-parse":
            return options == ["--show-toplevel"]
        return False

    test_commands = {
        ("pytest",),
        ("ruff", "check"),
        ("ruff", "format", "--check"),
        ("mypy",),
        ("flake8",),
        ("python", "-m", "pytest"),
        ("python3", "-m", "pytest"),
        ("python", "-m", "unittest"),
        ("python3", "-m", "unittest"),
        ("python", "-m", "py_compile"),
        ("python3", "-m", "py_compile"),
        ("python", "-m", "ruff", "check"),
        ("python3", "-m", "ruff", "check"),
        ("python", "-m", "mypy"),
        ("python3", "-m", "mypy"),
        ("uv", "run", "pytest"),
        ("uv", "run", "ruff", "check"),
        ("npm", "test"),
        ("pnpm", "test"),
        ("yarn", "test"),
        ("bun", "test"),
        ("cargo", "test"),
        ("cargo", "check"),
        ("cargo", "clippy"),
        ("go", "test"),
        ("go", "vet"),
        ("composer", "test"),
        ("composer", "validate"),
        ("php", "artisan", "test"),
        ("php", "-l"),
    }
    if any(tuple(parts[: len(prefix)]) == prefix for prefix in test_commands):
        return _safe_workspace_arguments(arguments, ctx, check_bare_paths=True)

    script_runners = {"npm", "pnpm", "yarn", "bun"}
    safe_scripts = {"test", "lint", "build", "typecheck", "check"}
    if executable in script_runners and arguments:
        if arguments[0] in safe_scripts:
            return True
        if len(arguments) >= 2 and arguments[0] == "run" and arguments[1] in safe_scripts:
            return True
    return False


def _clean_environment() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in PROVIDER_KEY_ENVS
    }
    python_bin = str(Path(sys.executable).absolute().parent)
    current_path = env.get("PATH", "")
    path_parts = [part for part in current_path.split(os.pathsep) if part]
    if python_bin and python_bin not in path_parts:
        env["PATH"] = (
            os.pathsep.join([python_bin, *path_parts]) if path_parts else python_bin
        )
    env.setdefault("PAGER", "cat")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("TERM", "dumb")
    return env


def _build_bwrap_args(command: str, cwd: Path) -> list[str] | None:
    if os.environ.get("ZEROCODE_SANDBOX") != "1" or os.name != "posix":
        return None
    if SUDO_COMMAND_RE.search(command):
        return None
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return None
    resolved_cwd = str(cwd.resolve())
    return [
        bwrap,
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--bind",
        resolved_cwd,
        resolved_cwd,
        "--chdir",
        resolved_cwd,
        "--unshare-pid",
        "--die-with-parent",
        "sh",
        "-c",
        command,
    ]


def run_bash(args: dict[str, Any], ctx: ToolContext) -> str:
    command = str(args["command"]).strip()
    if not command:
        return "ERREUR: commande vide."
    timeout = min(max(1, int(args.get("timeout", ctx.command_timeout))), MAX_COMMAND_TIMEOUT)
    env = _clean_environment()

    sudo_binary = shutil.which("sudo")
    if (
        sudo_binary
        and SUDO_COMMAND_RE.search(command)
        and not _sudo_credentials_cached(sudo_binary, env, ctx.cwd)
    ):
        provider = ctx.request_sudo_password
        if provider is None:
            return "Action refusee: mot de passe sudo requis."
        password = provider(command)
        if not password:
            return "Action refusee: mot de passe sudo non fourni."
        if not _prime_sudo(sudo_binary, password, env, ctx.cwd):
            return "Action refusee: mot de passe sudo refuse."

    bwrap_args = _build_bwrap_args(command, ctx.cwd)
    try:
        process = subprocess.Popen(
            bwrap_args if bwrap_args is not None else command,
            shell=bwrap_args is None,
            cwd=ctx.cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            **_process_group_kwargs(),
        )
    except OSError as exc:
        return f"ERREUR: impossible de lancer la commande: {exc}"

    ctx.attach_process(process)
    try:
        stdout, stderr, exit_code = _communicate_streaming(
            process, timeout, ctx, ctx.stream_output
        )
        if ctx.process_interrupted():
            stdout += "\n[commande interrompue par l'utilisateur]"
            exit_code = 130
    finally:
        ctx.detach_process(process)

    parts = [f"exit_code: {exit_code}"]
    if stdout.strip():
        parts.append("stdout:\n" + stdout.rstrip())
    if stderr.strip():
        parts.append("stderr:\n" + stderr.rstrip())
    if len(parts) == 1:
        parts.append("(aucune sortie)")
    return "\n\n".join(parts)


def _communicate_streaming(
    process: subprocess.Popen[str],
    timeout: int,
    ctx: ToolContext,
    stream: Any | None,
) -> tuple[str, str, int]:
    # Bound each pipe independently so noisy commands cannot exhaust process memory.
    budget = max(1_000, ctx.max_output_chars // 2)
    buffers: dict[str, list[str]] = {"stdout": [], "stderr": []}
    totals = {"stdout": 0, "stderr": 0}
    stored = {"stdout": 0, "stderr": 0}

    def reader(pipe: Any, name: str) -> None:
        try:
            while True:
                chunk = pipe.read(4_096)
                if not chunk:
                    break
                totals[name] += len(chunk)
                remaining = max(0, budget - stored[name])
                if remaining:
                    kept = chunk[:remaining]
                    buffers[name].append(kept)
                    stored[name] += len(kept)
                if stream is not None:
                    with contextlib.suppress(Exception):
                        stream("bash", chunk)
        finally:
            with contextlib.suppress(Exception):
                pipe.close()

    threads = [
        threading.Thread(target=reader, args=(process.stdout, "stdout"), daemon=True),
        threading.Thread(target=reader, args=(process.stderr, "stderr"), daemon=True),
    ]
    for thread in threads:
        thread.start()

    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        ctx.terminate_active_process(user=False, grace=TERMINATE_GRACE)
        try:
            process.wait(timeout=TERMINATE_GRACE + 3)
        except subprocess.TimeoutExpired:
            ctx.kill_active_process()
            process.wait()

    for thread in threads:
        thread.join(timeout=TERMINATE_GRACE + 3)

    def render(name: str) -> str:
        value = "".join(buffers[name])
        if totals[name] > stored[name]:
            value += (
                f"\n[... {name} tronque: {totals[name]} caracteres recus, "
                f"{stored[name]} conserves ...]"
            )
        return value

    stdout = render("stdout")
    stderr = render("stderr")
    if timed_out:
        stdout += f"\n[commande interrompue apres {timeout} secondes]"
        return stdout, stderr, 124
    return stdout, stderr, process.returncode


def has_sudo_command(command: str) -> bool:
    return SUDO_COMMAND_RE.search(command) is not None


def _process_group_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _sudo_credentials_cached(
    sudo_binary: str,
    env: dict[str, str],
    cwd: Any,
) -> bool:
    try:
        result = subprocess.run(
            [sudo_binary, "-n", "true"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _prime_sudo(
    sudo_binary: str,
    password: str,
    env: dict[str, str],
    cwd: Any,
) -> bool:
    try:
        result = subprocess.run(
            [sudo_binary, "-S", "-p", "", "-v"],
            input=password + "\n",
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
            cwd=cwd,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def register_shell_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="bash",
            description=(
                "Run a shell command in the workspace. Use it for tests, builds, git status "
                "and inspection. Destructive commands require confirmation. "
                "sudo is supported: the user will be asked for their password in a secure "
                "dialog before the command runs. "
                "The working directory does not persist between calls."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds. Default from config, max 3600.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Short reason for running the command.",
                    },
                },
                "required": ["command"],
            },
            handler=run_bash,
            approval="auto",
        )
    )

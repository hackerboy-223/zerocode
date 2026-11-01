from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import threading
from typing import Any

from .base import Tool, ToolContext, ToolRegistry

MAX_COMMAND_TIMEOUT = 3_600
TERMINATE_GRACE = 2.0
SUDO_COMMAND_RE = re.compile(
    r"(?P<prefix>(?:^|[;&|(\n]|&&|\|\|)\s*"
    r"(?:(?:env\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*)?)"
    r"(?P<sudo>(?:[\w./-]*/)?sudo)(?P<suffix>(?=\s|$|[;&|)]))"
)


def run_bash(args: dict[str, Any], ctx: ToolContext) -> str:
    command = str(args["command"]).strip()
    if not command:
        return "ERREUR: commande vide."
    timeout = min(max(1, int(args.get("timeout", ctx.command_timeout))), MAX_COMMAND_TIMEOUT)
    env = os.environ.copy()
    env.setdefault("PAGER", "cat")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("TERM", "dumb")

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

    try:
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=ctx.cwd,
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
        if ctx.stream_output is None:
            try:
                stdout_raw, stderr_raw = process.communicate(timeout=timeout)
                stdout = _as_text(stdout_raw)
                stderr = _as_text(stderr_raw)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                ctx.terminate_active_process(user=False, grace=TERMINATE_GRACE)
                try:
                    stdout_raw, stderr_raw = process.communicate(timeout=TERMINATE_GRACE + 3)
                except subprocess.TimeoutExpired:
                    ctx.kill_active_process()
                    stdout_raw, stderr_raw = process.communicate()
                stdout = _as_text(stdout_raw)
                stderr = _as_text(stderr_raw)
                stdout += f"\n[commande interrompue apres {timeout} secondes]"
                exit_code = 124
        else:
            stdout, stderr, exit_code = _communicate_streaming(
                process, timeout, ctx, ctx.stream_output
            )
        if ctx.process_interrupted():
            stdout += "\n[commande interrompue par l'utilisateur]"
            exit_code = 130
    finally:
        ctx.detach_process(process)

    budget = max(2_000, ctx.max_output_chars // 2)
    if len(stdout) > budget:
        stdout = stdout[:budget] + f"\n[... stdout tronque: {len(stdout)} caracteres ...]"
    if len(stderr) > budget:
        stderr = stderr[:budget] + f"\n[... stderr tronque: {len(stderr)} caracteres ...]"

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
    stream: Any,
) -> tuple[str, str, int]:
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    def reader(pipe: Any, parts: list[str]) -> None:
        try:
            for line in iter(pipe.readline, ""):
                parts.append(line)
                with contextlib.suppress(Exception):
                    stream("bash", line)
        finally:
            with contextlib.suppress(Exception):
                pipe.close()

    threads = [
        threading.Thread(target=reader, args=(process.stdout, stdout_parts), daemon=True),
        threading.Thread(target=reader, args=(process.stderr, stderr_parts), daemon=True),
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
        thread.join(timeout=2)

    stdout = "".join(stdout_parts)
    stderr = "".join(stderr_parts)
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
            approval="ask",
        )
    )

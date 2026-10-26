from __future__ import annotations

import os
import subprocess
from typing import Any

from .base import Tool, ToolContext, ToolRegistry


def run_bash(args: dict[str, Any], ctx: ToolContext) -> str:
    command = str(args["command"]).strip()
    if not command:
        return "ERREUR: commande vide."
    timeout = min(max(1, int(args.get("timeout", ctx.command_timeout))), 600)
    env = os.environ.copy()
    env.setdefault("PAGER", "cat")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("TERM", "dumb")
    try:
        process = subprocess.run(
            command,
            shell=True,
            cwd=ctx.cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        stdout = process.stdout or ""
        stderr = process.stderr or ""
        exit_code = process.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = _as_text(exc.stdout)
        stderr = _as_text(exc.stderr)
        stdout += f"\n[commande interrompue apres {timeout} secondes]"
        exit_code = 124
    except OSError as exc:
        return f"ERREUR: impossible de lancer la commande: {exc}"

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
                "The working directory does not persist between calls."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds. Default from config, max 600.",
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

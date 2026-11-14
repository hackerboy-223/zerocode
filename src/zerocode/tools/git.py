from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..errors import ToolError
from ..tokens import truncate_text
from .base import Tool, ToolContext, ToolRegistry, is_secret_path


def _git(
    args: list[str],
    ctx: ToolContext,
    *,
    timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(ctx.cwd), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolError("Git n'est pas installé ou n'est pas accessible dans le PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError("Git n'a pas répondu dans le délai imparti.") from exc
    except OSError as exc:
        raise ToolError(f"Impossible d'exécuter Git : {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if "not a git repository" in detail.lower():
            raise ToolError("Le dossier courant n'appartient pas à un dépôt Git.")
        raise ToolError(truncate_text(detail or "La commande Git a échoué.", 2_000))
    return result


def git_status(args: dict[str, Any], ctx: ToolContext) -> str:
    """Show branch state and working/staging changes without reading file contents."""
    status = _git(["status", "--short", "--branch"], ctx)
    branch = _git(["branch", "--show-current"], ctx).stdout.strip() or "(HEAD détachée)"
    unstaged = _git(["diff", "--stat", "--no-ext-diff"], ctx).stdout.strip()
    staged = _git(["diff", "--cached", "--stat", "--no-ext-diff"], ctx).stdout.strip()
    lines = [
        "ÉTAT GIT",
        f"Branche : {branch}",
        "",
        status.stdout.strip() or "Aucune modification détectée.",
    ]
    if staged:
        lines.extend(["", "DIFF INDEXÉ", staged])
    if unstaged:
        lines.extend(["", "DIFF NON INDEXÉ", unstaged])
    return truncate_text("\n".join(lines), ctx.max_output_chars)


def git_diff(args: dict[str, Any], ctx: ToolContext) -> str:
    """Read selected tracked diffs while excluding protected secret paths."""
    scope = str(args.get("scope", "working")).strip().lower()
    if scope not in {"working", "staged"}:
        raise ToolError("scope doit valoir 'working' ou 'staged'.")
    raw_path = str(args.get("path", "")).strip()
    paths: list[str] = []
    if raw_path:
        resolved = ctx.resolve_path(raw_path)
        ctx.check_secret(resolved)
        paths = [resolved.relative_to(ctx.cwd.resolve()).as_posix()]
    else:
        name_args = ["diff", "--name-only", "--no-ext-diff"]
        if scope == "staged":
            name_args.insert(1, "--cached")
        changed = _git([*name_args, "-z"], ctx).stdout
        paths = [name for name in changed.split("\x00") if name]

    safe_paths = [
        name for name in paths
        if not is_secret_path(Path(name))
        and not Path(name).is_absolute()
        and ".." not in Path(name).parts
    ]
    if not safe_paths:
        return "Aucun diff lisible dans ce périmètre (fichiers sensibles exclus ou aucun changement suivi)."

    max_chars = min(
        ctx.max_output_chars,
        max(1_000, min(30_000, int(args.get("max_chars", 16_000)))),
    )
    chunks = [f"DIFF GIT · {scope.upper()}"]
    remaining = max_chars
    for name in safe_paths:
        if remaining <= 0:
            break
        command = ["diff"]
        if scope == "staged":
            command.append("--cached")
        command.extend(["--no-ext-diff", "--no-color", "--unified=3", "--", name])
        result = _git(command, ctx)
        if not result.stdout:
            continue
        part = result.stdout[:remaining]
        chunks.append(part)
        remaining -= len(part)
    if len(chunks) == 1:
        return "Aucun changement textuel détecté."
    rendered = "\n".join(chunks)
    if remaining <= 0:
        rendered += "\n[… diff tronqué par la limite de sortie.]"
    return truncate_text(rendered, max_chars)


def register_git_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="git_status",
            description=(
                "Inspect the current Git branch, staged/unstaged file list and diff statistics. "
                "Does not modify the repository or read file contents."
            ),
            parameters={"type": "object", "properties": {}},
            handler=git_status,
            approval="never",
        )
    )
    registry.register(
        Tool(
            name="git_diff",
            description=(
                "Read working-tree or staged Git diffs for review. Secret paths are excluded. "
                "Use before final delivery to inspect the actual changes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["working", "staged"],
                        "description": "Diff scope, defaults to working.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional path relative to the workspace.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum output size, up to 30000 characters.",
                    },
                },
            },
            handler=git_diff,
            approval="never",
        )
    )

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..errors import ToolError
from ..tokens import truncate_text
from .base import Tool, ToolContext, ToolRegistry
from .files import DEFAULT_IGNORES, _is_binary

MAX_FILE_BYTES = 1_000_000
MAX_FILES = 5000


def grep_files(args: dict[str, Any], ctx: ToolContext) -> str:
    pattern = str(args["pattern"])
    if not pattern:
        raise ToolError("Le motif est vide.")
    root = ctx.resolve_path(str(args.get("path", ".")))
    include = args.get("include")
    include = str(include) if include else None
    max_results = min(max(1, int(args.get("max_results", 100))), 500)
    ignore_case = bool(args.get("ignore_case", False))

    try:
        regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        raise ToolError(f"Expression reguliere invalide: {exc}") from exc

    lines = _grep_with_ripgrep(
        ctx, root, pattern, include, max_results, ignore_case
    )
    if lines is None:
        lines = _grep_with_python(ctx, root, regex, include, max_results)

    if not lines:
        return "(aucune correspondance)"
    output = "\n".join(lines)
    if len(lines) >= max_results:
        output += f"\n... (limite de {max_results} resultats atteinte)"
    return truncate_text(output, ctx.max_output_chars)


def _grep_with_ripgrep(
    ctx: ToolContext,
    root: Path,
    pattern: str,
    include: str | None,
    max_results: int,
    ignore_case: bool,
) -> list[str] | None:
    executable = shutil.which("rg")
    if executable is None:
        return None
    command = [
        executable,
        "-n",
        "--no-heading",
        "--color",
        "never",
        "--max-count",
        str(max_results),
    ]
    if ignore_case:
        command.append("-i")
    if include:
        command.extend(["-g", include])
    command.extend(["--", pattern, str(root)])
    try:
        process = subprocess.run(
            command,
            cwd=ctx.cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode not in (0, 1):
        return None
    result = [line for line in process.stdout.splitlines() if line.strip()]
    return result[:max_results]


def _grep_with_python(
    ctx: ToolContext,
    root: Path,
    regex: re.Pattern[str],
    include: str | None,
    max_results: int,
) -> list[str]:
    files: list[Path] = []
    if root.is_file():
        files = [root]
    elif root.is_dir():
        scanned = 0
        for current, dirs, names in os.walk(root):
            dirs[:] = [name for name in dirs if name not in DEFAULT_IGNORES]
            for name in names:
                if scanned >= MAX_FILES:
                    break
                path = Path(current) / name
                relative = str(path.relative_to(root))
                if include and not (
                    fnmatch.fnmatch(name, include) or fnmatch.fnmatch(relative, include)
                ):
                    continue
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    if path.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                files.append(path)
                scanned += 1
            if scanned >= MAX_FILES:
                break
    else:
        raise ToolError(f"Chemin introuvable: {ctx.display_path(root)}")

    results: list[str] = []
    for path in files:
        try:
            if _is_binary(path):
                continue
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, start=1):
                    if regex.search(line):
                        label = (
                            str(path.relative_to(ctx.cwd))
                            if path.is_relative_to(ctx.cwd)
                            else str(path)
                        )
                        results.append(f"{label}:{number}:{line.rstrip()[:300]}")
                        if len(results) >= max_results:
                            return results
        except OSError:
            continue
    return results


def register_search_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="grep",
            description=(
                "Search text files with a regular expression. Returns path:line:text. "
                "Use include to restrict file names, for example '*.py'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Python regular expression."},
                    "path": {"type": "string", "description": "File or directory. Default '.'."},
                    "include": {
                        "type": "string",
                        "description": "Glob filter such as '*.ts' or 'src/**/*.py'.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum matches. Default 100, max 500.",
                    },
                    "ignore_case": {
                        "type": "boolean",
                        "description": "Case-insensitive search. Default false.",
                    },
                },
                "required": ["pattern"],
            },
            handler=grep_files,
            approval="never",
        )
    )

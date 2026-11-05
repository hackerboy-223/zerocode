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
from .base import Tool, ToolContext, ToolRegistry, is_secret_path
from .files import DEFAULT_IGNORES, _git_visible_files, _is_binary

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
    if not ctx.allow_outside:
        command.append("--no-follow")
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
    result = []
    protect = ctx.protect_secrets and not ctx.allow_secrets
    for line in process.stdout.splitlines():
        if not line.strip():
            continue
        raw_path = Path(_ripgrep_line_path(line))
        candidate = raw_path if raw_path.is_absolute() else (ctx.cwd / raw_path)
        if not ctx.allow_outside:
            try:
                if not candidate.resolve().is_relative_to(ctx.cwd):
                    continue
            except OSError:
                continue
        if protect and (is_secret_path(raw_path) or is_secret_path(candidate)):
            continue
        result.append(line)
        if len(result) >= max_results:
            break
    return result


_RIPGREP_LINE_RE = re.compile(r"^(?P<path>.*?):(?P<line>\d+):")


def _ripgrep_line_path(line: str) -> str:
    """Extract the file path from `rg -n` output, including Windows drive paths."""
    match = _RIPGREP_LINE_RE.match(line)
    if match is not None:
        return match.group("path")
    return line.split(":", 1)[0]


def _walk_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in DEFAULT_IGNORES]
        files.extend(Path(current) / name for name in names)
    return files


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
        visible = _git_visible_files(root)
        candidates = (
            sorted(visible)
            if visible is not None
            else _walk_files(root)
        )
        for path in candidates:
            if len(files) >= MAX_FILES:
                break
            try:
                relative = str(path.relative_to(root))
            except ValueError:
                continue
            if include and not (
                fnmatch.fnmatch(path.name, include) or fnmatch.fnmatch(relative, include)
            ):
                continue
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                if (
                    ctx.protect_secrets
                    and not ctx.allow_secrets
                    and is_secret_path(path)
                ):
                    continue
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            files.append(path)
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

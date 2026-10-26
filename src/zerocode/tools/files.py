from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Any

from ..errors import ToolError
from ..tokens import truncate_text
from .base import Tool, ToolContext, ToolRegistry

DEFAULT_IGNORES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".next",
    ".nuxt",
    "dist",
    "build",
    "target",
    "vendor",
}
MAX_READ_BYTES = 2_000_000
MAX_WRITE_CHARS = 1_000_000


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            sample = handle.read(8192)
    except OSError as exc:
        raise ToolError(f"Impossible de lire {path}: {exc}") from exc
    return b"\x00" in sample


def _read_slice(path: Path, offset: int, limit: int) -> tuple[list[str], bool]:
    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for _ in range(max(0, offset - 1)):
            if not handle.readline():
                return [], False
        for _ in range(limit):
            line = handle.readline()
            if not line:
                return lines, False
            lines.append(line.rstrip("\n"))
    return lines, True


def _atomic_text_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = 0o644
    if path.exists():
        with contextlib.suppress(OSError):
            existing_mode = path.stat().st_mode & 0o777
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, existing_mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_file(args: dict[str, Any], ctx: ToolContext) -> str:
    path = ctx.resolve_path(str(args["path"]))
    if not path.exists():
        raise ToolError(f"Fichier introuvable: {ctx.display_path(path)}")
    if path.is_dir():
        raise ToolError(f"{ctx.display_path(path)} est un dossier; utilise `list`.")
    if _is_binary(path):
        raise ToolError(f"Fichier binaire: {ctx.display_path(path)}")
    offset = max(1, int(args.get("offset", 1)))
    limit = min(max(1, int(args.get("limit", 2000))), 4000)
    lines, truncated = _read_slice(path, offset, limit)
    if not lines:
        return f"(aucune ligne pour {ctx.display_path(path)} a partir de la ligne {offset})"
    width = len(str(offset + len(lines) - 1))
    numbered = "\n".join(
        f"{number:>{width}}: {line}" for number, line in enumerate(lines, start=offset)
    )
    if truncated:
        numbered += f"\n... (limite de {limit} lignes atteinte; utilise offset/limit)"
    return truncate_text(numbered, ctx.max_output_chars)


def write_file(args: dict[str, Any], ctx: ToolContext) -> str:
    path = ctx.resolve_path(str(args["path"]), for_write=True)
    content = str(args["content"])
    if len(content) > MAX_WRITE_CHARS:
        raise ToolError(f"Contenu trop volumineux (max {MAX_WRITE_CHARS} caracteres).")
    _atomic_text_write(path, content)
    return f"Ecrit {len(content)} caracteres dans {ctx.display_path(path)}"


def edit_file(args: dict[str, Any], ctx: ToolContext) -> str:
    path = ctx.resolve_path(str(args["path"]), for_write=True)
    if not path.is_file():
        raise ToolError(f"Fichier introuvable: {ctx.display_path(path)}")
    if path.stat().st_size > MAX_READ_BYTES:
        raise ToolError("Fichier trop volumineux pour une edition directe (max 2 Mo).")
    if _is_binary(path):
        raise ToolError(f"Fichier binaire: {ctx.display_path(path)}")
    old = str(args["old_string"])
    new = str(args["new_string"])
    if not old:
        raise ToolError("old_string ne peut pas etre vide.")
    text = path.read_text(encoding="utf-8", errors="replace")
    count = text.count(old)
    if count == 0:
        raise ToolError("old_string est introuvable dans le fichier.")
    replace_all = bool(args.get("replace_all", False))
    if count > 1 and not replace_all:
        raise ToolError(
            f"old_string apparait {count} fois. Ajoute du contexte ou utilise replace_all=true."
        )
    updated = text.replace(old, new, -1 if replace_all else 1)
    _atomic_text_write(path, updated)
    replacements = count if replace_all else 1
    return f"Modifie {ctx.display_path(path)} ({replacements} remplacement(s))"


def list_files(args: dict[str, Any], ctx: ToolContext) -> str:
    root = ctx.resolve_path(str(args.get("path", ".")))
    pattern = str(args.get("glob", "*")).strip() or "*"
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise ToolError("Le motif glob doit rester relatif et sans '..'.")
    limit = min(max(1, int(args.get("limit", 200))), 2000)
    if root.is_file():
        return ctx.display_path(root)
    if not root.is_dir():
        raise ToolError(f"Dossier introuvable: {ctx.display_path(root)}")

    entries: list[str] = []
    for path in sorted(root.glob(pattern), key=lambda item: str(item).lower()):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in DEFAULT_IGNORES for part in relative.parts):
            continue
        label = str(path.relative_to(ctx.cwd)) if path.is_relative_to(ctx.cwd) else str(path)
        if path.is_dir():
            label += "/"
        entries.append(label)
        if len(entries) >= limit:
            break
    if not entries:
        return f"(aucun fichier pour le motif {pattern!r} dans {ctx.display_path(root)})"
    output = "\n".join(entries)
    if len(entries) >= limit:
        output += f"\n... (limite de {limit} entrees atteinte)"
    return truncate_text(output, ctx.max_output_chars)


def register_file_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="read",
            description=(
                "Read a UTF-8 text file from the workspace. Returns line numbers. "
                "Use offset and limit for large files."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file."},
                    "offset": {
                        "type": "integer",
                        "description": "First line to read (1-based). Default 1.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines. Default 2000, max 4000.",
                    },
                },
                "required": ["path"],
            },
            handler=read_file,
            approval="never",
        )
    )
    registry.register(
        Tool(
            name="write",
            description=(
                "Create or replace a text file. Parent directories are created automatically. "
                "Prefer edit for small changes to existing files."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to write."},
                    "content": {"type": "string", "description": "Full file content."},
                },
                "required": ["path", "content"],
            },
            handler=write_file,
            approval="ask",
        )
    )
    registry.register(
        Tool(
            name="edit",
            description=(
                "Replace an exact string in an existing text file. "
                "Read the file first. If old_string appears multiple times, add context "
                "or set replace_all to true."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to edit."},
                    "old_string": {"type": "string", "description": "Exact text to replace."},
                    "new_string": {"type": "string", "description": "Replacement text."},
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace every occurrence. Default false.",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
            handler=edit_file,
            approval="ask",
        )
    )
    registry.register(
        Tool(
            name="list",
            description=(
                "List files in the workspace using a glob pattern. "
                "Heavy directories such as .git and node_modules are skipped."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory. Default '.'."},
                    "glob": {
                        "type": "string",
                        "description": "Glob pattern, for example '**/*.py'. Default '*'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum entries. Default 200, max 2000.",
                    },
                },
            },
            handler=list_files,
            approval="never",
        )
    )

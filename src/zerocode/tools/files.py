from __future__ import annotations

import ast
import contextlib
import difflib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import tomllib

from ..errors import ToolError
from ..tokens import truncate_text
from .base import Tool, ToolContext, ToolRegistry, is_secret_path

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
MAX_DIFF_LINES = 300
MAX_DIFF_LINE_CHARS = 500
MAX_DIFF_CHARS = 24_000
_GIT_VISIBLE_CACHE: dict[str, tuple[float, set[Path] | None]] = {}
_GIT_CACHE_TTL = 2.0


def _git_visible_files(root: Path) -> set[Path] | None:
    if not root.is_dir():
        return None
    key = str(root.resolve())
    now = time.monotonic()
    cached = _GIT_VISIBLE_CACHE.get(key)
    if cached is not None and now - cached[0] < _GIT_CACHE_TTL:
        return cached[1]
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        _GIT_VISIBLE_CACHE[key] = (now, None)
        return None
    if result.returncode != 0:
        _GIT_VISIBLE_CACHE[key] = (now, None)
        return None
    visible = {
        (root / name).resolve()
        for name in result.stdout.decode("utf-8", errors="replace").split("\0")
        if name
    }
    _GIT_VISIBLE_CACHE[key] = (now, visible)
    return visible


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


def _diff_source(text: str) -> list[str]:
    return [line[:MAX_DIFF_LINE_CHARS] for line in text.splitlines()]


def _emit_diff(
    ctx: ToolContext,
    path: Path,
    before: str,
    after: str,
    *,
    existed: bool,
) -> None:
    emitter = ctx.show_diff
    if emitter is None or before == after:
        return
    label = ctx.display_path(path)
    diff = difflib.unified_diff(
        _diff_source(before),
        _diff_source(after),
        fromfile=f"a/{label}" if existed else "/dev/null",
        tofile=f"b/{label}",
        lineterm="",
        n=3,
    )
    lines: list[str] = []
    truncated = False
    for line in diff:
        if len(lines) >= MAX_DIFF_LINES:
            truncated = True
            break
        lines.append(line)
    if not lines:
        return
    text = "\n".join(lines)
    if truncated:
        text += f"\n... diff tronque ({MAX_DIFF_LINES} lignes max) ..."
    if len(text) > MAX_DIFF_CHARS:
        text = text[:MAX_DIFF_CHARS] + "\n... diff tronque ..."
    emitter(label, text)


def _record_checkpoint(
    ctx: ToolContext,
    path: Path,
    before: str | None,
    tool: str,
) -> None:
    recorder = ctx.checkpoint
    if recorder is None:
        return
    try:
        recorder(path, before, tool)
    except (OSError, ValueError):
        return


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
    ctx.check_secret(path)
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


def _syntax_diagnostic(path: Path, content: str) -> str:
    suffix = path.suffix.lower()
    if suffix == ".py":
        try:
            ast.parse(content, filename=str(path))
        except SyntaxError as exc:
            line = exc.lineno or "?"
            return f"\nDIAGNOSTIC SYNTAXE PYTHON (ligne {line}): {exc.msg}"
    elif suffix == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            return f"\nDIAGNOSTIC JSON (ligne {exc.lineno}): {exc.msg}"
    elif suffix == ".toml":
        try:
            tomllib.loads(content)
        except tomllib.TOMLDecodeError as exc:
            return f"\nDIAGNOSTIC TOML: {exc}"
    elif suffix in {".sh", ".bash"} and path.is_file():
        shell_bin = shutil.which("bash") or shutil.which("sh")
        if shell_bin:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                check = subprocess.run(
                    [shell_bin, "-n", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if check.returncode != 0 and check.stderr.strip():
                    first = check.stderr.strip().splitlines()[0]
                    return f"\nDIAGNOSTIC SHELL: {first}"
    elif suffix in {".js", ".mjs", ".cjs"} and path.is_file():
        node_bin = shutil.which("node")
        if node_bin:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                check = subprocess.run(
                    [node_bin, "--check", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if check.returncode != 0 and check.stderr.strip():
                    first = check.stderr.strip().splitlines()[0]
                    return f"\nDIAGNOSTIC JS: {first}"
    return ""


def write_file(args: dict[str, Any], ctx: ToolContext) -> str:
    path = ctx.resolve_path(str(args["path"]), for_write=True)
    ctx.check_secret(path)
    content = str(args["content"])
    if len(content) > MAX_WRITE_CHARS:
        raise ToolError(f"Contenu trop volumineux (max {MAX_WRITE_CHARS} caracteres).")
    existed = path.is_file()
    before = ""
    can_diff = True
    if existed:
        try:
            if path.stat().st_size > MAX_READ_BYTES:
                can_diff = False
            else:
                before = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            can_diff = False
    if can_diff:
        _record_checkpoint(ctx, path, before if existed else None, "write")
    _atomic_text_write(path, content)
    if not existed:
        _GIT_VISIBLE_CACHE.clear()
    if can_diff:
        _emit_diff(ctx, path, before, content, existed=existed)
    diag = _syntax_diagnostic(path, content)
    return f"Ecrit {len(content)} caracteres dans {ctx.display_path(path)}{diag}"


def edit_file(args: dict[str, Any], ctx: ToolContext) -> str:
    path = ctx.resolve_path(str(args["path"]), for_write=True)
    ctx.check_secret(path)
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
    _record_checkpoint(ctx, path, text, "edit")
    _atomic_text_write(path, updated)
    _emit_diff(ctx, path, text, updated, existed=True)
    replacements = count if replace_all else 1
    diag = _syntax_diagnostic(path, updated)
    return f"Modifie {ctx.display_path(path)} ({replacements} remplacement(s)){diag}"


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

    visible = _git_visible_files(root)
    entries: list[str] = []
    protect = ctx.protect_secrets and not ctx.allow_secrets
    for path in sorted(root.glob(pattern), key=lambda item: str(item).lower()):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in DEFAULT_IGNORES for part in relative.parts):
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if not ctx.allow_outside and not resolved.is_relative_to(ctx.cwd):
            continue
        if protect and (is_secret_path(path) or is_secret_path(resolved)):
            continue
        if visible is not None:
            if path.is_file() and resolved not in visible:
                continue
            if path.is_dir() and not any(
                item.is_relative_to(path) for item in visible
            ):
                continue
        label = (
            path.relative_to(ctx.cwd).as_posix()
            if path.is_relative_to(ctx.cwd)
            else path.as_posix()
        )
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
            approval="auto",
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
            approval="auto",
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

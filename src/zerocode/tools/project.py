from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..tokens import truncate_text
from .base import Tool, ToolContext, ToolRegistry, is_secret_path
from .shell import run_bash

SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    "node_modules", "vendor", "dist", "build", "coverage", ".next",
    ".nuxt", ".output", ".turbo", ".cache", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".idea", ".vscode", "target", "Pods",
}
ENTRYPOINTS = (
    "main.py", "app.py", "manage.py", "artisan", "package.json",
    "pyproject.toml", "composer.json", "go.mod", "Cargo.toml",
    "pom.xml", "build.gradle", "Makefile", "Dockerfile",
    "index.html", "src/main.ts", "src/main.tsx", "src/main.js",
    "src/index.ts", "src/index.tsx", "src/app/page.tsx",
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _git_summary(root: Path) -> list[str]:
    if not (root / ".git").exists():
        return ["Git : dépôt non détecté."]
    lines: list[str] = []
    for args, label in (
        (["git", "branch", "--show-current"], "Branche"),
        (["git", "status", "--short"], "Modifications"),
    ):
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            value = result.stdout.strip() or ("aucune" if label == "Modifications" else "inconnue")
            lines.append(f"{label} : {value[:500]}")
    return lines


def project_map(args: dict[str, Any], ctx: ToolContext) -> str:
    """Build a bounded, secret-aware overview of the current workspace."""
    root = ctx.cwd.resolve()
    max_files = min(400, max(40, int(args.get("max_files", 180))))
    discovered: list[str] = []
    omitted = 0

    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        dirs[:] = sorted(
            name for name in dirs
            if name not in SKIP_DIRS and not (base / name).is_symlink()
        )
        for name in sorted(files):
            path = base / name
            if path.is_symlink() or is_secret_path(path):
                continue
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            if len(discovered) >= max_files:
                omitted += 1
                continue
            discovered.append(relative)

    root_files = sorted(
        name for name in discovered
        if "/" not in name and not name.startswith(".env")
    )
    entrypoints = [name for name in ENTRYPOINTS if name in discovered]
    manifests: list[str] = []
    stacks: list[str] = []
    details: list[str] = []

    package_path = root / "package.json"
    if package_path.is_file():
        package = _read_json(package_path)
        scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
        dependencies = package.get("dependencies") if isinstance(package.get("dependencies"), dict) else {}
        dev_dependencies = package.get("devDependencies") if isinstance(package.get("devDependencies"), dict) else {}
        stacks.append("JavaScript / TypeScript")
        manifests.append("package.json")
        if dependencies or dev_dependencies:
            names = sorted(set(dependencies) | set(dev_dependencies))
            details.append("Dépendances Node : " + ", ".join(names[:35]))
        if scripts:
            details.append("Scripts Node disponibles : " + ", ".join(sorted(str(k) for k in scripts)[:25]))

    pyproject_path = root / "pyproject.toml"
    if pyproject_path.is_file():
        stacks.append("Python")
        manifests.append("pyproject.toml")
        try:
            try:
                import tomllib
            except ImportError:  # Python 3.10
                import tomli as tomllib
            parsed = tomllib.loads(pyproject_path.read_text(encoding="utf-8")[:100_000])
            project = parsed.get("project", {})
            if isinstance(project, dict):
                if project.get("name"):
                    details.append(f"Paquet Python : {project['name']}")
                deps = project.get("dependencies", [])
                if isinstance(deps, list) and deps:
                    details.append("Dépendances Python : " + ", ".join(str(x).split(";")[0] for x in deps[:25]))
            tool_config = parsed.get("tool", {})
            if isinstance(tool_config, dict):
                configured = [name for name in ("pytest", "ruff", "mypy", "black") if name in tool_config]
                if configured:
                    details.append("Outils Python configurés : " + ", ".join(configured))
        except (OSError, UnicodeError, ValueError):
            details.append("pyproject.toml : analyse partielle impossible.")

    if (root / "requirements.txt").is_file() or (root / "setup.py").is_file():
        if "Python" not in stacks:
            stacks.append("Python")
        if (root / "requirements.txt").is_file():
            manifests.append("requirements.txt")

    composer_path = root / "composer.json"
    if composer_path.is_file():
        composer = _read_json(composer_path)
        scripts = composer.get("scripts") if isinstance(composer.get("scripts"), dict) else {}
        stacks.append("PHP / Composer")
        manifests.append("composer.json")
        if scripts:
            details.append("Scripts Composer disponibles : " + ", ".join(sorted(str(k) for k in scripts)[:25]))

    if (root / "go.mod").is_file():
        stacks.append("Go")
        manifests.append("go.mod")
    if (root / "Cargo.toml").is_file():
        stacks.append("Rust")
        manifests.append("Cargo.toml")
    if (root / "pom.xml").is_file() or (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        stacks.append("Java / JVM")
        manifests.extend(name for name in ("pom.xml", "build.gradle", "build.gradle.kts") if (root / name).is_file())

    if not stacks:
        stacks.append("Stack non identifiée automatiquement")

    lines = [
        "CARTOGRAPHIE DU PROJET",
        f"Racine : {root}",
        f"Fichiers visibles : {len(discovered)}" + (f" (+ au moins {omitted} non affichés)" if omitted else ""),
        "Stacks détectées : " + ", ".join(dict.fromkeys(stacks)),
        "Manifestes : " + (", ".join(dict.fromkeys(manifests)) or "aucun manifeste standard"),
        "Points d'entrée : " + (", ".join(entrypoints) or "à déterminer"),
        "Fichiers racine : " + (", ".join(root_files[:45]) or "aucun"),
        "",
        "ARBORESCENCE (fichiers)",
        *(f"  {name}" for name in discovered),
    ]
    if omitted:
        lines.append(f"  … {omitted} fichier(s) supplémentaire(s) masqué(s) par la limite.")
    if details:
        lines.extend(["", "INDICES DE CONFIGURATION", *[f"  {item}" for item in details]])
    lines.extend(["", "GIT", *[f"  {item}" for item in _git_summary(root)]])
    return truncate_text("\n".join(lines), ctx.max_output_chars)


def _verification_commands(root: Path, checks: list[str]) -> list[tuple[str, str]]:
    commands: list[tuple[str, str]] = []
    package_path = root / "package.json"
    package = _read_json(package_path) if package_path.is_file() else {}
    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    if package:
        if (root / "pnpm-lock.yaml").exists():
            manager = "pnpm"
        elif (root / "yarn.lock").exists():
            manager = "yarn"
        elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
            manager = "bun"
        else:
            manager = "npm"
        for check, script in (("tests", "test"), ("lint", "lint"), ("typecheck", "typecheck"), ("build", "build")):
            if check in checks and script in scripts:
                commands.append((check, f"{manager} run {script}"))

    composer_path = root / "composer.json"
    composer = _read_json(composer_path) if composer_path.is_file() else {}
    composer_scripts = composer.get("scripts") if isinstance(composer.get("scripts"), dict) else {}
    if composer:
        if "tests" in checks:
            if (root / "artisan").is_file():
                commands.append(("tests", "php artisan test"))
            elif "test" in composer_scripts:
                commands.append(("tests", "composer test"))
        if "lint" in checks and "lint" in composer_scripts:
            commands.append(("lint", "composer lint"))
        if "build" in checks and "build" in composer_scripts:
            commands.append(("build", "composer build"))

    if (root / "pyproject.toml").is_file() or (root / "requirements.txt").is_file() or (root / "tests").is_dir():
        python = shlex.quote(sys.executable)
        if "tests" in checks and ((root / "tests").is_dir() or shutil.which("pytest")):
            commands.append(("tests", f"{python} -m pytest -q"))
        if "lint" in checks and (shutil.which("ruff") or importlib.util.find_spec("ruff")):
            commands.append(("lint", "ruff check ." if shutil.which("ruff") else f"{python} -m ruff check ."))
        if "typecheck" in checks and (shutil.which("mypy") or importlib.util.find_spec("mypy")):
            commands.append(("typecheck", "mypy ." if shutil.which("mypy") else f"{python} -m mypy ."))
        if "build" in checks and (root / "pyproject.toml").is_file():
            try:
                try:
                    import tomllib
                except ImportError:  # Python 3.10
                    import tomli as tomllib
                parsed = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")[:100_000])
            except (OSError, UnicodeError, ValueError):
                parsed = {}
            if parsed.get("build-system"):
                commands.append(("build", f"{python} -m build"))

    if (root / "go.mod").is_file():
        if "tests" in checks:
            commands.append(("tests", "go test ./..."))
        if "lint" in checks:
            commands.append(("lint", "go vet ./..."))
        if "build" in checks:
            commands.append(("build", "go build ./..."))

    if (root / "Cargo.toml").is_file():
        if "tests" in checks:
            commands.append(("tests", "cargo test"))
        if "lint" in checks:
            commands.append(("lint", "cargo clippy --all-targets --all-features -- -D warnings"))
        if "build" in checks:
            commands.append(("build", "cargo build"))

    if (root / "pom.xml").is_file():
        if "tests" in checks:
            commands.append(("tests", "mvn test"))
        if "build" in checks:
            commands.append(("build", "mvn -q package -DskipTests"))

    if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        gradle = "./gradlew" if (root / "gradlew").is_file() else "gradle"
        if "tests" in checks:
            commands.append(("tests", f"{gradle} test"))
        if "build" in checks:
            commands.append(("build", f"{gradle} build"))

    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for check, command in commands:
        if command not in seen:
            unique.append((check, command))
            seen.add(command)
    return unique


def project_verify(args: dict[str, Any], ctx: ToolContext) -> str:
    """Run the checks declared or conventionally detected for this workspace."""
    raw_checks = args.get("checks") or ["tests", "lint", "typecheck", "build"]
    if not isinstance(raw_checks, list):
        return "ERREUR: checks doit être une liste."
    allowed = {"tests", "lint", "typecheck", "build"}
    checks = list(dict.fromkeys(str(value).strip().lower() for value in raw_checks))
    unknown = sorted(set(checks) - allowed)
    if unknown:
        return "ERREUR: vérifications inconnues : " + ", ".join(unknown)
    commands = _verification_commands(ctx.cwd, checks)
    if not commands:
        return "Aucune commande de vérification détectée pour ces contrôles. Consulte les scripts du projet et indique les commandes adaptées."

    timeout = min(900, max(5, int(args.get("timeout", 300))))
    results = ["VÉRIFICATION DU PROJET", f"Contrôles demandés : {', '.join(checks)}"]
    completed = 0
    failed = 0
    for check, command in commands:
        results.extend(["", f"[{check.upper()}] {command}"])
        output = run_bash({"command": command, "timeout": timeout}, ctx)
        results.append(output)
        completed += 1
        if "exit_code: 0" not in output:
            failed += 1
    results.extend(["", f"Résultat : {completed - failed}/{completed} commande(s) réussie(s)."])
    if failed:
        results.append("Des contrôles ont échoué. Analyse les sorties, corrige les problèmes puis relance project_verify.")
    return truncate_text("\n".join(results), ctx.max_output_chars)


def register_project_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="project_map",
            description=(
                "Create a concise, secret-aware map of the workspace: detected stacks, manifests, "
                "entry points, root files, bounded source tree and Git status. Use before architecture work."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "max_files": {"type": "integer", "description": "Maximum number of visible files to list (40-400, default 180)."}
                },
            },
            handler=project_map,
            approval="never",
        )
    )
    registry.register(
        Tool(
            name="project_verify",
            description=(
                "Detect and run the project's available test, lint, type-check and build scripts. "
                "Uses package.json, Composer, Python, Go, Rust or JVM conventions. Run after meaningful changes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "checks": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["tests", "lint", "typecheck", "build"]},
                        "description": "Checks to run. Defaults to tests, lint, typecheck and build."
                    },
                    "timeout": {"type": "integer", "description": "Timeout in seconds per command (5-900, default 300)."}
                },
            },
            handler=project_verify,
            approval="ask",
        )
    )

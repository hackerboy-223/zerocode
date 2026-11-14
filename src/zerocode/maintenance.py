from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import httpx

from .config import config_dir, data_dir
from .version import __version__

REPOSITORY = "hackerboy-223/zerocode"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}.git"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
_PACKAGE_NAME = "zerocode"
_TAG_PATTERN = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def latest_release_tag(*, timeout: float = 12.0) -> str:
    """Return the latest stable, validated GitHub release tag."""
    response = httpx.get(
        LATEST_RELEASE_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ZeroCode"},
        timeout=timeout,
        follow_redirects=False,
    )
    if response.status_code == 404:
        raise RuntimeError("Aucune version stable n'a encore été publiée sur GitHub.")
    response.raise_for_status()
    payload = response.json()
    tag = payload.get("tag_name") if isinstance(payload, dict) else None
    if not isinstance(tag, str) or not _TAG_PATTERN.fullmatch(tag):
        raise RuntimeError("La dernière release GitHub contient un tag de version invalide.")
    return tag


def pipx_command() -> list[str] | None:
    """Find pipx without assuming that the current Python belongs to the host."""
    executable = shutil.which("pipx")
    if executable:
        return [executable]

    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "pipx",
        home / ".local" / "bin" / "pipx.exe",
        home / "bin" / "pipx",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate)]

    for name in ("python3", "python", "py"):
        interpreter = shutil.which(name)
        if not interpreter:
            continue
        prefix = ["-3"] if Path(interpreter).name.lower() in {"py", "py.exe"} else []
        command = [interpreter, *prefix, "-m", "pipx"]
        try:
            probe = subprocess.run(
                [*command, "--version"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            return command
    return None


def pipx_manages_zerocode(command: list[str]) -> bool:
    """Confirm that pipx owns this installation before replacing or removing it."""
    try:
        result = subprocess.run(
            [*command, "list", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    environments = payload.get("venvs") if isinstance(payload, dict) else None
    return isinstance(environments, dict) and _PACKAGE_NAME in environments


def update_from_release() -> tuple[bool, str]:
    """Install the newest stable GitHub tag into an existing pipx environment."""
    try:
        tag = latest_release_tag()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        return False, f"Impossible de vérifier les releases : {exc}"

    target_version = tag.removeprefix("v")
    if target_version == __version__:
        return True, f"ZeroCode {__version__} est déjà à jour."

    command = pipx_command()
    if command is None:
        return False, "pipx est introuvable. Réinstalle ZeroCode avec l'installateur officiel."
    if not pipx_manages_zerocode(command):
        return (
            False,
            "Cette installation n'est pas gérée par pipx. "
            "Utilise l'installateur officiel pour la mettre à jour sans créer une seconde installation.",
        )

    spec = f"git+{REPOSITORY_URL}@{tag}"
    try:
        result = subprocess.run(
            [*command, "install", "--force", spec],
            check=False,
        )
    except OSError as exc:
        return False, f"Impossible de lancer pipx : {exc}"
    if result.returncode != 0:
        return False, "La mise à jour a échoué. L'installation précédente n'a pas été supprimée volontairement."
    return True, f"ZeroCode a été mis à jour vers {target_version}. Rouvre ton terminal."


def uninstall_from_pipx(*, remove_data: bool = False) -> tuple[bool, str]:
    """Remove the pipx app; user configuration and sessions are preserved by default."""
    command = pipx_command()
    if command is None:
        return False, "pipx est introuvable. Aucune modification n'a été effectuée."
    if not pipx_manages_zerocode(command):
        return False, "pipx ne gère pas cette installation. Aucune modification n'a été effectuée."

    try:
        result = subprocess.run(
            [*command, "uninstall", _PACKAGE_NAME],
            check=False,
        )
    except OSError as exc:
        return False, f"Impossible de lancer pipx : {exc}"
    if result.returncode != 0:
        return False, "La désinstallation du moteur a échoué. Les données utilisateur ont été conservées."

    message = "Le moteur ZeroCode a été désinstallé."
    if not remove_data:
        return True, message + " La configuration, les clés et les sessions sont conservées."

    removed: list[str] = []
    errors: list[str] = []
    seen: set[Path] = set()
    for directory in (config_dir(), data_dir()):
        target = directory.expanduser()
        try:
            resolved = target.resolve(strict=False)
            if resolved in seen:
                continue
            seen.add(resolved)
            if target.is_symlink():
                target.unlink()
            elif target.exists():
                if resolved.name != "zerocode" or resolved == Path.home() or resolved == Path("/"):
                    errors.append(f"Chemin ignoré par sécurité : {target}")
                    continue
                shutil.rmtree(target)
            removed.append(str(target))
        except OSError as exc:
            errors.append(f"{target}: {exc}")

    if errors:
        return False, message + " Certaines données n'ont pas pu être supprimées : " + "; ".join(errors)
    if removed:
        message += " Données utilisateur supprimées : " + ", ".join(removed)
    else:
        message += " Aucune donnée utilisateur restante n'a été trouvée."
    return True, message

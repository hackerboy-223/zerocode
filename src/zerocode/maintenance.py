from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .config import config_dir, data_dir
from .version import __version__

REPOSITORY = "hackerboy-223/zerocode"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}.git"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
_PACKAGE_NAME = "zerocode"
_TAG_PATTERN = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def latest_release_details(*, timeout: float = 12.0) -> tuple[str, dict[str, str]]:
    """Return the latest stable release tag and its trusted GitHub asset URLs."""
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

    raw_assets = payload.get("assets", []) if isinstance(payload, dict) else []
    if not isinstance(raw_assets, list):
        raise RuntimeError("La liste des fichiers de la release est invalide.")

    assets: dict[str, str] = {}
    expected_prefix = f"/{REPOSITORY}/releases/download/{tag}/"
    for asset in raw_assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "github.com":
            continue
        if not parsed.path.startswith(expected_prefix) or ".." in parsed.path.split("/"):
            continue
        assets[name] = url
    return tag, assets


def latest_release_tag(*, timeout: float = 12.0) -> str:
    return latest_release_details(timeout=timeout)[0]


def _release_asset_checksum(
    *,
    filename: str,
    asset_url: str,
    checksum_url: str,
    timeout: float = 60.0,
) -> bool:
    """Verify a downloaded release asset against the published SHA-256 manifest."""
    file_response = httpx.get(asset_url, timeout=timeout, follow_redirects=True)
    file_response.raise_for_status()
    checksum_response = httpx.get(checksum_url, timeout=timeout, follow_redirects=True)
    checksum_response.raise_for_status()

    expected = None
    for line in checksum_response.text.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2:
            continue
        digest, listed_name = fields
        if listed_name.lstrip("*") == filename and _SHA256_PATTERN.fullmatch(digest):
            expected = digest.lower()
            break
    if expected is None:
        raise RuntimeError(f"Aucune empreinte SHA-256 publiée pour {filename}.")
    actual = hashlib.sha256(file_response.content).hexdigest()
    if not hashlib.compare_digest(actual, expected):
        raise RuntimeError(f"L'empreinte SHA-256 de {filename} ne correspond pas à la release.")
    return True


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
    """Install the newest stable, checksum-verified GitHub release into pipx."""
    try:
        tag, assets = latest_release_details()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        return False, f"Impossible de vérifier les releases : {exc}"

    target_version = tag.removeprefix("v")
    if target_version == __version__:
        return True, f"ZeroCode {__version__} est déjà à jour."

    wheel_name = next(
        (
            name
            for name in assets
            if name.startswith(f"zerocode-{target_version}-") and name.endswith(".whl")
        ),
        None,
    )
    checksum_url = assets.get("SHA256SUMS")
    if wheel_name is None or checksum_url is None:
        return False, f"La release {tag} ne contient pas le wheel Python et son manifeste SHA-256."

    command = pipx_command()
    if command is None:
        return False, "pipx est introuvable. Réinstalle ZeroCode avec l'installateur officiel."
    if not pipx_manages_zerocode(command):
        return (
            False,
            "Cette installation n'est pas gérée par pipx. "
            "Utilise l'installateur officiel pour la mettre à jour sans créer une seconde installation.",
        )

    wheel_url = assets[wheel_name]
    try:
        _release_asset_checksum(
            filename=wheel_name,
            asset_url=wheel_url,
            checksum_url=checksum_url,
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        return False, f"Vérification de la release impossible : {exc}"

    try:
        result = subprocess.run(
            [*command, "install", "--force", wheel_url],
            check=False,
        )
    except OSError as exc:
        return False, f"Impossible de lancer pipx : {exc}"
    if result.returncode != 0:
        return False, "La mise à jour a échoué. L'installation précédente n'a pas été supprimée volontairement."
    return True, f"Le moteur ZeroCode a été mis à jour vers {target_version}. Rouvre ton terminal."


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

from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .errors import ConfigError

APP_NAME = "zerocode"
PROJECT_CONFIG_NAMES = (".zerocode.json", "zerocode.json")
VALID_REASONING = {"low", "high", "max"}
VALID_PERMISSIONS = {"ask", "allow", "deny"}

DEFAULT_CONFIG: dict[str, Any] = {
    "model": "glm-5.3",
    "provider": None,
    "free_only": True,
    "fallback": True,
    "reasoning_effort": "high",
    "temperature": 0.2,
    "max_tokens": 8192,
    "max_steps": 40,
    "permissions": "ask",
    "allow_outside_cwd": False,
    "command_timeout": 120,
    "compact_threshold": 0.75,
    "show_reasoning": False,
    "providers": {},
}


def _home() -> Path:
    return Path.home()


def config_dir() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    base = Path(raw).expanduser() if raw else _home() / ".config"
    return base / APP_NAME


def data_dir() -> Path:
    raw = os.environ.get("XDG_DATA_HOME")
    base = Path(raw).expanduser() if raw else _home() / ".local" / "share"
    return base / APP_NAME


def default_config_path() -> Path:
    override = os.environ.get("ZEROCODE_CONFIG")
    return Path(override).expanduser() if override else config_dir() / "config.json"


def keys_path() -> Path:
    override = os.environ.get("ZEROCODE_KEYS_FILE")
    return Path(override).expanduser() if override else config_dir() / "keys.json"


def project_config_path(cwd: Path) -> Path | None:
    current = cwd.resolve()
    while True:
        for name in PROJECT_CONFIG_NAMES:
            candidate = current / name
            if candidate.is_file():
                return candidate
        if current.parent == current:
            return None
        current = current.parent


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Impossible de lire {label} ({path}): {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON invalide dans {label} ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{label} doit contenir un objet JSON ({path}).")
    return data


def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> None:
    for key, value in update.items():
        if key == "providers" and isinstance(value, dict):
            providers = base.setdefault("providers", {})
            if not isinstance(providers, dict):
                providers = {}
                base["providers"] = providers
            for name, override in value.items():
                if isinstance(override, dict) and isinstance(providers.get(name), dict):
                    providers[name] = {**providers[name], **override}
                else:
                    providers[name] = override
        else:
            base[key] = value


def _as_bool(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "oui"}:
            return True
        if lowered in {"0", "false", "no", "off", "non"}:
            return False
    raise ConfigError(f"Valeur booleenne invalide pour {key}: {value!r}")


def _as_int(value: Any, key: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Valeur entiere invalide pour {key}: {value!r}") from exc


def _as_float(value: Any, key: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Valeur numerique invalide pour {key}: {value!r}") from exc


def _env_overrides() -> dict[str, Any]:
    mapping: dict[str, tuple[str, str]] = {
        "ZEROCODE_MODEL": ("model", "str"),
        "ZEROCODE_PROVIDER": ("provider", "str"),
        "ZEROCODE_FREE_ONLY": ("free_only", "bool"),
        "ZEROCODE_FALLBACK": ("fallback", "bool"),
        "ZEROCODE_REASONING_EFFORT": ("reasoning_effort", "str"),
        "ZEROCODE_TEMPERATURE": ("temperature", "float"),
        "ZEROCODE_MAX_TOKENS": ("max_tokens", "int"),
        "ZEROCODE_MAX_STEPS": ("max_steps", "int"),
        "ZEROCODE_PERMISSIONS": ("permissions", "str"),
        "ZEROCODE_ALLOW_OUTSIDE_CWD": ("allow_outside_cwd", "bool"),
        "ZEROCODE_COMMAND_TIMEOUT": ("command_timeout", "int"),
        "ZEROCODE_COMPACT_THRESHOLD": ("compact_threshold", "float"),
        "ZEROCODE_SHOW_REASONING": ("show_reasoning", "bool"),
    }
    result: dict[str, Any] = {}
    for env_name, (key, kind) in mapping.items():
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            continue
        if kind == "bool":
            result[key] = _as_bool(raw, env_name)
        elif kind == "int":
            result[key] = _as_int(raw, env_name)
        elif kind == "float":
            result[key] = _as_float(raw, env_name)
        else:
            result[key] = raw.strip()
    return result


@dataclass
class Config:
    model: str = "glm-5.3"
    provider: str | None = None
    free_only: bool = True
    fallback: bool = True
    reasoning_effort: str = "high"
    temperature: float = 0.2
    max_tokens: int = 8192
    max_steps: int = 40
    permissions: str = "ask"
    allow_outside_cwd: bool = False
    command_timeout: int = 120
    compact_threshold: float = 0.75
    show_reasoning: bool = False
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    base_dir: Path = field(default_factory=Path.cwd)
    sources: list[str] = field(default_factory=list)

    def provider_config(self, name: str) -> dict[str, Any]:
        return dict(self.providers.get(name, {}))

    def public_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for item in fields(self):
            if item.name in {"base_dir", "sources"}:
                continue
            data[item.name] = getattr(self, item.name)
        return data


def validate_config(config: Config) -> None:
    if not config.model or not isinstance(config.model, str):
        raise ConfigError("model doit etre une chaine non vide.")
    if config.reasoning_effort not in VALID_REASONING:
        raise ConfigError(
            f"reasoning_effort doit valoir {', '.join(sorted(VALID_REASONING))}."
        )
    if config.permissions not in VALID_PERMISSIONS:
        raise ConfigError(f"permissions doit valoir {', '.join(sorted(VALID_PERMISSIONS))}.")
    if not 0 <= config.temperature <= 2:
        raise ConfigError("temperature doit etre comprise entre 0 et 2.")
    if not 256 <= config.max_tokens <= 128_000:
        raise ConfigError("max_tokens doit etre compris entre 256 et 128000.")
    if not 1 <= config.max_steps <= 500:
        raise ConfigError("max_steps doit etre compris entre 1 et 500.")
    if not 1 <= config.command_timeout <= 3_600:
        raise ConfigError("command_timeout doit etre compris entre 1 et 3600 secondes.")
    if not 0.2 <= config.compact_threshold <= 0.95:
        raise ConfigError("compact_threshold doit etre compris entre 0.2 et 0.95.")
    if not isinstance(config.providers, dict):
        raise ConfigError("providers doit etre un objet JSON.")
    for name, override in config.providers.items():
        if not isinstance(override, dict):
            raise ConfigError(f"providers.{name} doit etre un objet JSON.")
        unknown = set(override) - {"base_url", "enabled"}
        if unknown:
            raise ConfigError(
                f"providers.{name}: cles inconnues {', '.join(sorted(unknown))} "
                "(valeurs acceptees: base_url, enabled)."
            )
        if "base_url" in override:
            value = override["base_url"]
            if not isinstance(value, str) or not value.startswith(("http://", "https://")):
                raise ConfigError(f"providers.{name}.base_url doit etre une URL HTTP(S).")
        if "enabled" in override and not isinstance(override["enabled"], bool):
            raise ConfigError(f"providers.{name}.enabled doit etre un booleen.")


def load_config(
    cwd: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> Config:
    cwd = (cwd or Path.cwd()).resolve()
    merged: dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))
    sources: list[str] = []

    global_path = default_config_path()
    if global_path.is_file():
        _deep_merge(merged, _read_json(global_path, label="la configuration globale"))
        sources.append(str(global_path))

    project_path = project_config_path(cwd)
    if project_path is not None:
        _deep_merge(merged, _read_json(project_path, label="la configuration du projet"))
        sources.append(str(project_path))

    _deep_merge(merged, _env_overrides())
    if overrides:
        _deep_merge(merged, {key: value for key, value in overrides.items() if value is not None})

    known = {item.name for item in fields(Config)} - {"base_dir", "sources"}
    data = {key: value for key, value in merged.items() if key in known}

    for key in ("free_only", "fallback", "allow_outside_cwd", "show_reasoning"):
        data[key] = _as_bool(data.get(key, DEFAULT_CONFIG[key]), key)
    data["temperature"] = _as_float(data.get("temperature", 0.2), "temperature")
    for key in ("max_tokens", "max_steps", "command_timeout"):
        data[key] = _as_int(data.get(key, DEFAULT_CONFIG[key]), key)
    data["compact_threshold"] = _as_float(
        data.get("compact_threshold", 0.75), "compact_threshold"
    )
    provider = data.get("provider")
    if provider in ("", "none", "null", "auto"):
        data["provider"] = None

    config = Config(**data, base_dir=cwd, sources=sources)
    validate_config(config)
    return config


def save_config(config: Config, path: Path | None = None) -> Path:
    target = path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = config.public_dict()
    payload.pop("sources", None)
    _atomic_write(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", mode=0o600)
    return target


def load_key_store() -> dict[str, str]:
    path = keys_path()
    if not path.is_file():
        return {}
    data = _read_json(path, label="le fichier de cles")
    result: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, str) and value.strip():
            result[str(key)] = value.strip()
    return result


def save_key_store(keys: dict[str, str]) -> Path:
    path = keys_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {str(key): str(value).strip() for key, value in keys.items() if str(value).strip()}
    _atomic_write(path, json.dumps(clean, ensure_ascii=False, indent=2) + "\n", mode=0o600)
    return path


def store_key(name: str, value: str) -> Path:
    keys = load_key_store()
    keys[name] = value.strip()
    return save_key_store(keys)


def delete_key(name: str) -> bool:
    keys = load_key_store()
    if name not in keys:
        return False
    keys.pop(name)
    save_key_store(keys)
    return True


def mask_key(value: str | None) -> str:
    if not value:
        return "(absente)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _atomic_write(path: Path, content: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)

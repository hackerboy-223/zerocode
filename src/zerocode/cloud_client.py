from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from rich.console import Console
from rich.text import Text

from .config import Config, config_dir
from .errors import ConfigError, ProviderError
from .router import Router
from .types import Completion, ModelSpec, ProviderSpec, ToolCall, Usage


def _auth_path() -> Path:
    return config_dir() / "cloud.json"


def load_cloud_auth() -> dict[str, Any]:
    try:
        value = json.loads(_auth_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        raise ConfigError("Impossible de lire la session ZeroCode Cloud.") from None
    if not isinstance(value, dict):
        raise ConfigError("Fichier de session ZeroCode Cloud invalide.")
    return value


def save_cloud_auth(value: dict[str, Any]) -> None:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(directory, 0o700)
    fd, name = tempfile.mkstemp(prefix=".cloud-", dir=directory)
    path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
        os.replace(path, _auth_path())
        with contextlib.suppress(OSError):
            os.chmod(_auth_path(), 0o600)
    finally:
        path.unlink(missing_ok=True)


def _validate_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
        raise ConfigError("L'URL Cloud doit utiliser HTTPS (HTTP est autorisé uniquement en local).")
    if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigError("URL ZeroCode Cloud invalide.")
    return value.strip().rstrip("/")


def _save_tokens(auth: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    auth.update({
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "access_expires_at": data.get("access_expires_at"),
        "user": data.get("user", auth.get("user", {})),
        "mode": "cloud",
    })
    save_cloud_auth(auth)
    return auth


def _refresh(auth: dict[str, Any]) -> dict[str, Any]:
    token = auth.get("refresh_token")
    if not token:
        raise ConfigError("Session Cloud expirée. Lance zerocode cloud login.")
    try:
        response = httpx.post(
            auth["base_url"] + "/v1/auth/refresh",
            json={"refresh_token": token},
            timeout=25,
            follow_redirects=False,
        )
    except httpx.HTTPError:
        raise ConfigError("ZeroCode Cloud est inaccessible.") from None
    if response.status_code != 200:
        raise ConfigError("Session Cloud expirée ou révoquée. Reconnecte-toi.")
    return _save_tokens(auth, response.json())


def _error_message(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return " ".join(raw.split())[:500] or "Erreur ZeroCode Cloud."
    if isinstance(data, dict):
        detail = data.get("detail") or data.get("error") or data.get("message")
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("detail") or detail)[:500]
        if detail:
            return str(detail)[:500]
    return "Erreur ZeroCode Cloud."


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _delta_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(str(item.get("text", "")) for item in value if isinstance(item, dict))
    return ""


def _reasoning_text(delta: dict[str, Any]) -> str:
    for key in ("reasoning_content", "reasoning", "thinking"):
        value = delta.get(key)
        if isinstance(value, str):
            return value
    return ""


def cloud_mode_enabled() -> bool:
    return load_cloud_auth().get("mode") == "cloud"


class CloudRouter:
    """Adaptateur du routeur existant : l'inférence est distante, les outils restent locaux."""

    def __init__(self, config: Config, ui: Any = None) -> None:
        self.config = config
        self.ui = ui
        # Keep the Router interface expected by TUI/Desktop bridge consumers.
        # Cloud mode owns provider selection remotely, so local provider/key
        # management must see an empty catalog rather than crash or expose BYOK.
        self.providers: dict[str, ProviderSpec] = {}
        self.is_cloud = True
        self.auth = load_cloud_auth()
        if self.auth.get("mode") != "cloud" or not self.auth.get("access_token"):
            raise ConfigError("Connecte-toi avec zerocode cloud login.")
        self.auth["base_url"] = _validate_url(str(self.auth.get("base_url", "")))
        self.http = httpx.Client(
            timeout=httpx.Timeout(900, connect=20),
            follow_redirects=False,
        )
        self.last: Completion | None = None
        self.last_task = "auto"
        self.last_provider = ProviderSpec(
            name="zerocode-cloud",
            label="ZeroCode Cloud",
            base_url=self.auth["base_url"],
            models=(),
        )
        self.last_model: ModelSpec | None = None
        self.remote_config: dict[str, Any] | None = None
        self.remote_config_checked_at = 0.0

    def close(self) -> None:
        self.http.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.auth['access_token']}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-Client": "zerocode-python",
        }

    def _stream_request(self, payload: dict[str, Any]) -> httpx.Response:
        url = self.auth["base_url"] + "/v1/chat/completions"
        try:
            response = self.http.send(
                self.http.build_request("POST", url, headers=self._headers(), json=payload),
                stream=True,
            )
            if response.status_code == 401:
                response.close()
                self.auth = _refresh(self.auth)
                response = self.http.send(
                    self.http.build_request("POST", url, headers=self._headers(), json=payload),
                    stream=True,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Connexion Cloud impossible ({exc.__class__.__name__})",
                provider="zerocode-cloud",
                model=str(payload.get("model", "auto")),
                retryable=True,
            ) from None
        if response.status_code >= 300:
            status = response.status_code
            try:
                message = _error_message(response.read().decode("utf-8", errors="replace"))
            finally:
                response.close()
            raise ProviderError(
                message,
                provider="zerocode-cloud",
                model=str(payload.get("model", "auto")),
                status=status,
                retryable=status in {408, 425, 429, 500, 502, 503, 504},
            )
        return response

    def _get_remote_config(self) -> dict[str, Any]:
        now = time.monotonic()
        if self.remote_config is not None and now - self.remote_config_checked_at < 30:
            return self.remote_config
        url = self.auth["base_url"] + "/v1/client/config"
        try:
            response = self.http.get(url, headers=self._headers())
            if response.status_code == 401:
                self.auth = _refresh(self.auth)
                response = self.http.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Connexion Cloud impossible ({exc.__class__.__name__})",
                provider="zerocode-cloud",
                retryable=True,
            ) from None
        if response.status_code >= 300:
            raise ProviderError(
                _error_message(response.text),
                provider="zerocode-cloud",
                status=response.status_code,
            )
        self.remote_config = response.json()
        self.remote_config_checked_at = time.monotonic()
        return self.remote_config

    def preview(self, model: str | None = None, provider: str | None = None) -> list[str]:
        # Provider selection is controlled by the Cloud admin routing policy.
        # Ignore a stale local/BYOK provider setting while Cloud mode is active.
        try:
            aliases = [
                item.get("alias")
                for item in self._get_remote_config().get("models", [])
                if isinstance(item, dict) and item.get("alias")
            ]
        except (ProviderError, ConfigError):
            return ["zerocode-cloud/auto"]
        if model and model != "auto":
            return [f"zerocode-cloud/{model}"] if model in aliases else ["zerocode-cloud/auto"]
        return [f"zerocode-cloud/{item}" for item in aliases] or ["zerocode-cloud/auto"]

    def context_window(self, model: str | None = None) -> int:
        return 128_000

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        model: str | None = None,
        provider: str | None = None,
        callbacks: Any = None,
        needs_vision: bool = False,
    ) -> Completion:
        # The Cloud control plane owns provider choice. Ignore any provider left
        # in the local config; BYOK/Ollama is selected by switching to local mode.
        remote = self._get_remote_config()
        if remote.get("maintenance_mode"):
            raise ProviderError(
                "ZeroCode Cloud est en maintenance. Réessaie dans quelques instants.",
                provider="zerocode-cloud",
                model=model or "auto",
                status=503,
                retryable=True,
            )
        flags = remote.get("feature_flags", {})
        if isinstance(flags, dict) and flags.get("cloud_ai") is False:
            raise ProviderError(
                "L'inférence Cloud est désactivée par l'administrateur.",
                provider="zerocode-cloud",
                model=model or "auto",
                status=503,
                retryable=False,
            )
        requested_model = (model or self.config.model or "auto").strip()
        available_aliases = {
            item.get("alias")
            for item in remote.get("models", [])
            if isinstance(item, dict) and isinstance(item.get("alias"), str)
        }
        if requested_model != "auto" and requested_model not in available_aliases:
            requested_model = "auto"
        payload: dict[str, Any] = {
            "model": requested_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        response = self._stream_request(payload)
        self.last_task = response.headers.get("X-ZeroCode-Task", "auto")
        content: list[str] = []
        reasoning: list[str] = []
        tool_parts: dict[int, dict[str, str]] = {}
        usage = Usage(requests=1)
        finish_reason = "stop"
        response_model = requested_model
        try:
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    break
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "error" in event:
                    error = event["error"]
                    message = error.get("message", "Upstream error") if isinstance(error, dict) else str(error)
                    raise ProviderError(message, provider="zerocode-cloud", model=requested_model, retryable=True)
                if isinstance(event.get("usage"), dict):
                    info = event["usage"]
                    usage = Usage(
                        prompt_tokens=_as_int(info.get("prompt_tokens")),
                        completion_tokens=_as_int(info.get("completion_tokens")),
                        total_tokens=_as_int(info.get("total_tokens")),
                        requests=1,
                    )
                if isinstance(event.get("model"), str):
                    response_model = event["model"]
                choices = event.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    continue
                choice = choices[0]
                delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
                text = _delta_text(delta.get("content"))
                if text:
                    content.append(text)
                    if callbacks and callable(getattr(callbacks, "on_text", None)):
                        callbacks.on_text(text)
                thought = _reasoning_text(delta)
                if thought:
                    reasoning.append(thought)
                    if callbacks and callable(getattr(callbacks, "on_reasoning", None)):
                        callbacks.on_reasoning(thought)
                tool_deltas = delta.get("tool_calls")
                if isinstance(tool_deltas, list):
                    for tool_delta in tool_deltas:
                        if not isinstance(tool_delta, dict):
                            continue
                        index = _as_int(tool_delta.get("index"))
                        item = tool_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        if tool_delta.get("id"):
                            item["id"] = str(tool_delta["id"])
                        function = tool_delta.get("function")
                        if isinstance(function, dict):
                            if function.get("name"):
                                item["name"] = str(function["name"])
                            if function.get("arguments") is not None:
                                item["arguments"] += str(function["arguments"])
                if choice.get("finish_reason"):
                    finish_reason = str(choice["finish_reason"])
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Flux Cloud interrompu ({exc.__class__.__name__})",
                provider="zerocode-cloud",
                model=requested_model,
                retryable=True,
            ) from None
        finally:
            response.close()

        calls: list[ToolCall] = []
        for index, item in sorted(tool_parts.items()):
            try:
                arguments = json.loads(item["arguments"] or "{}")
                if not isinstance(arguments, dict):
                    arguments = {}
            except json.JSONDecodeError:
                arguments = {}
            calls.append(ToolCall(
                id=item["id"] or f"call_{index}",
                name=item["name"],
                arguments=arguments,
            ))
        completion = Completion(
            content="".join(content),
            reasoning="".join(reasoning),
            tool_calls=calls,
            finish_reason=finish_reason,
            provider="zerocode-cloud",
            model=response_model,
            usage=usage,
        )
        self.last = completion
        self.last_model = ModelSpec(id=response_model, label=response_model)
        return completion


def create_router(config: Config, ui: Any = None) -> Router | CloudRouter:
    if cloud_mode_enabled():
        return CloudRouter(config, ui=ui)
    return Router(config, ui=ui)


def cloud_command(args_list: list[str], console: Console) -> int:
    parser = argparse.ArgumentParser(prog="zerocode cloud")
    commands = parser.add_subparsers(dest="action", required=True)
    login = commands.add_parser("login", help="Connecter ce client à ZeroCode Cloud")
    login.add_argument("--url", default=os.environ.get("ZEROCODE_CLOUD_URL", ""))
    register = commands.add_parser("register", help="Créer un compte ZeroCode Cloud")
    register.add_argument("--url", default=os.environ.get("ZEROCODE_CLOUD_URL", ""))
    commands.add_parser("logout", help="Déconnecter ce client")
    commands.add_parser("status", help="Afficher le compte et le mode actif")
    use = commands.add_parser("use", help="Choisir le moteur IA")
    use.add_argument("mode", choices=("cloud", "local"))
    args = parser.parse_args(args_list)

    if args.action in {"login", "register"}:
        try:
            base_url = _validate_url(args.url or console.input("URL ZeroCode Cloud : ").strip())
        except ConfigError as exc:
            console.print(Text(str(exc), style="bold red"))
            return 1
        email = console.input("Adresse e-mail : ").strip()
        password = getpass.getpass("Mot de passe : ")
        if args.action == "register":
            endpoint = base_url + "/v1/auth/register"
            body = {"email": email, "password": password}
        else:
            endpoint = base_url + "/v1/auth/login"
            body = {"email": email, "password": password, "device_name": os.environ.get("HOSTNAME", "ZeroCode device")}
        try:
            response = httpx.post(endpoint, json=body, timeout=25, follow_redirects=False)
        except httpx.HTTPError:
            console.print(Text("ZeroCode Cloud est inaccessible.", style="bold red"))
            return 1
        if response.status_code >= 300:
            console.print(Text(_error_message(response.text), style="bold red"))
            return 1
        if args.action == "register":
            console.print(Text("Compte créé. Connecte-toi avec zerocode cloud login.", style="green"))
            return 0
        auth = _save_auth({"base_url": base_url}, response.json())
        console.print(Text(f"Connecté : {auth.get('user', {}).get('email', email)}", style="green"))
        console.print(Text("Le moteur Cloud est maintenant actif sur ce client.", style="dim"))
        return 0

    auth = load_cloud_auth()
    if args.action == "status":
        console.print(f"Moteur IA : [bold]{auth.get('mode', 'local')}[/bold]")
        if auth.get("base_url"):
            console.print(f"Serveur : {auth['base_url']}")
        if auth.get("user", {}).get("email"):
            console.print(f"Compte : {auth['user']['email']}")
        return 0
    if args.action == "use":
        if args.mode == "cloud" and not auth.get("access_token"):
            console.print(Text("Connecte-toi d'abord avec zerocode cloud login.", style="yellow"))
            return 1
        auth["mode"] = args.mode
        save_cloud_auth(auth)
        console.print(Text(f"Moteur IA actif : {args.mode}", style="green"))
        return 0
    if args.action == "logout":
        if auth.get("base_url") and auth.get("access_token"):
            try:
                base_url = _validate_url(str(auth["base_url"]))
                httpx.post(
                    base_url + "/v1/auth/logout",
                    headers={"Authorization": f"Bearer {auth['access_token']}"},
                    timeout=10,
                    follow_redirects=False,
                )
            except httpx.HTTPError:
                pass
        try:
            _auth_path().unlink(missing_ok=True)
        except OSError:
            console.print(Text("Impossible de supprimer la session locale.", style="red"))
            return 1
        console.print(Text("Déconnecté. Le mode local est actif.", style="green"))
        return 0
    return 0


def _save_auth(auth: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    auth.update({
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "access_expires_at": data.get("access_expires_at"),
        "user": data.get("user", {}),
        "mode": "cloud",
    })
    save_cloud_auth(auth)
    return auth

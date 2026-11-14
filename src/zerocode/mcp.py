from __future__ import annotations

import contextlib
import json
import math
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

from .catalog import PROVIDERS
from .errors import ToolError
from .tokens import truncate_text
from .tools.base import Tool, ToolRegistry
from .version import __version__

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 30.0
PROVIDER_KEY_ENVS = frozenset(
    env_name for spec in PROVIDERS.values() for env_name in spec.api_key_envs
)


def _sanitized_base_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in PROVIDER_KEY_ENVS
    }


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.name = name
        self.command = command
        self.args = args or []
        self.cwd = cwd
        self.timeout = timeout
        self._env = {**_sanitized_base_env(), **(env or {})}
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._responses: dict[int, dict[str, Any]] = {}
        self._condition = threading.Condition()
        self._reader: threading.Thread | None = None
        self._stderr: threading.Thread | None = None
        self._stderr_lines: list[str] = []

    def start(self) -> None:
        if self._process is not None:
            return
        try:
            self._process = subprocess.Popen(
                [self.command, *self.args],
                cwd=self.cwd,
                env=self._env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                **_process_group_kwargs(),
            )
        except OSError as exc:
            raise MCPError(f"{self.name}: impossible de lancer {self.command}: {exc}") from exc
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._stderr.start()
        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "zerocode", "version": __version__},
                },
                timeout=max(self.timeout, 10.0),
            )
            self._notify("notifications/initialized", {})
        except Exception:
            self.close()
            raise

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        return [item for item in tools or [] if isinstance(item, dict)]

    def list_resources(self) -> list[dict[str, Any]]:
        try:
            result = self._request("resources/list", {})
        except MCPError:
            return []
        resources = result.get("resources") if isinstance(result, dict) else None
        return [item for item in resources or [] if isinstance(item, dict)]

    def list_prompts(self) -> list[dict[str, Any]]:
        try:
            result = self._request("prompts/list", {})
        except MCPError:
            return []
        prompts = result.get("prompts") if isinstance(result, dict) else None
        return [item for item in prompts or [] if isinstance(item, dict)]

    def read_resource(self, uri: str) -> str:
        result = self._request("resources/read", {"uri": uri})
        return _render_resource_result(result)

    def get_prompt(self, name: str, arguments: dict[str, str]) -> str:
        result = self._request("prompts/get", {"name": name, "arguments": arguments})
        return _render_prompt_result(result)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=max(self.timeout, 60.0),
        )
        if result.get("isError"):
            return "ERREUR: " + _render_content(result)
        return _render_content(result)

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin is not None:
            with contextlib.suppress(OSError):
                process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            message_id = message.get("id")
            if isinstance(message_id, int):
                with self._condition:
                    self._responses[message_id] = message
                    self._condition.notify_all()

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._stderr_lines.append(line.rstrip())
            del self._stderr_lines[:-20]

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdin is None:
            raise MCPError(f"{self.name}: serveur non demarre.")
        request_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except OSError as exc:
            raise MCPError(f"{self.name}: ecriture impossible: {exc}") from exc

        with self._condition:
            found = self._condition.wait_for(
                lambda: request_id in self._responses,
                timeout=timeout or self.timeout,
            )
            if not found:
                detail = " | ".join(self._stderr_lines[-3:])
                suffix = f" ({detail})" if detail else ""
                raise MCPError(f"{self.name}: delai depasse pour {method}{suffix}")
            message = self._responses.pop(request_id)
        if "error" in message:
            error = message["error"]
            if isinstance(error, dict):
                text = error.get("message") or error.get("data") or str(error)
            else:
                text = str(error)
            raise MCPError(f"{self.name}: {text}")
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()


class MCPManager:
    def __init__(self) -> None:
        self.clients: list[MCPClient] = []

    def close(self) -> None:
        for client in self.clients:
            client.close()
        self.clients.clear()


def register_mcp_tools(
    registry: ToolRegistry,
    servers: dict[str, Any],
    *,
    cwd: Path,
    ui: Any | None = None,
) -> MCPManager:
    manager = MCPManager()
    for server_name, config in servers.items():
        if not isinstance(config, dict) or config.get("enabled") is False:
            continue
        command = str(config.get("command") or "").strip()
        if not command:
            _warn(ui, f"MCP {server_name}: commande absente.")
            continue
        raw_args = config.get("args") or []
        if not isinstance(raw_args, list):
            _warn(ui, f"MCP {server_name}: args doit etre une liste.")
            continue
        args = [str(item) for item in raw_args]
        env = config.get("env") if isinstance(config.get("env"), dict) else {}
        raw_timeout = config.get("timeout")
        if raw_timeout in (None, ""):
            timeout = DEFAULT_TIMEOUT
        else:
            if isinstance(raw_timeout, bool):
                _warn(ui, f"MCP {server_name}: timeout invalide ({raw_timeout!r}).")
                continue
            try:
                timeout = float(raw_timeout)
            except (OverflowError, TypeError, ValueError):
                _warn(ui, f"MCP {server_name}: timeout invalide ({raw_timeout!r}).")
                continue
            if not math.isfinite(timeout) or not 1 <= timeout <= 3_600:
                _warn(ui, f"MCP {server_name}: timeout doit etre entre 1 et 3600 secondes.")
                continue
        server_cwd = config.get("cwd")
        client = MCPClient(
            str(server_name),
            command,
            args,
            env={str(key): str(value) for key, value in env.items()},
            cwd=Path(str(server_cwd)).expanduser() if server_cwd else cwd,
            timeout=timeout,
        )
        try:
            client.start()
            tools = client.list_tools()
        except Exception as exc:  # noqa: BLE001 - un serveur MCP ne doit pas bloquer l'agent
            _warn(ui, f"MCP {server_name}: {exc}")
            client.close()
            continue
        manager.clients.append(client)
        trusted = config.get("trusted") is True
        for item in tools:
            _register_tool(registry, client, str(server_name), item, trusted=trusted)
        for item in client.list_resources()[:100]:
            _register_resource_tool(registry, client, str(server_name), item)
        for item in client.list_prompts()[:100]:
            _register_prompt_tool(registry, client, str(server_name), item)
    return manager


def _process_group_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _register_tool(
    registry: ToolRegistry,
    client: MCPClient,
    server_name: str,
    item: dict[str, Any],
    *,
    trusted: bool = False,
) -> None:
    remote_name = str(item.get("name") or "").strip()
    if not remote_name:
        return
    name = _tool_name(server_name, remote_name)
    schema = item.get("inputSchema")
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    description = str(item.get("description") or f"Outil MCP {server_name}/{remote_name}.")
    annotations = item.get("annotations")
    read_only_hint = (
        isinstance(annotations, dict)
        and annotations.get("readOnlyHint") is True
        and annotations.get("destructiveHint") is not True
    )

    def handler(args: dict[str, Any], ctx: Any) -> str:
        try:
            return truncate_text(client.call_tool(remote_name, args), ctx.max_output_chars)
        except MCPError as exc:
            raise ToolError(str(exc)) from exc

    try:
        registry.register(
            Tool(
                name=name,
                description=description[:1_000],
                parameters=schema,
                handler=handler,
                # A configured trusted server can participate in autonomous workflows.
                # Otherwise, only explicitly read-only annotated tools are non-destructive.
                approval="ask" if trusted or read_only_hint else "confirm",
            )
        )
    except ValueError:
        return


def _register_resource_tool(
    registry: ToolRegistry,
    client: MCPClient,
    server_name: str,
    item: dict[str, Any],
) -> None:
    uri = str(item.get("uri") or "").strip()
    if not uri:
        return
    label = str(item.get("name") or uri.rsplit("/", 1)[-1] or "resource")
    name = _tool_name(server_name, "resource_" + label)

    def handler(args: dict[str, Any], ctx: Any) -> str:
        try:
            return truncate_text(client.read_resource(uri), ctx.max_output_chars)
        except MCPError as exc:
            raise ToolError(str(exc)) from exc

    try:
        registry.register(
            Tool(
                name=name,
                description=(
                    "Read an MCP resource from " + server_name + ": "
                    + str(item.get("description") or label)
                )[:1_000],
                parameters={"type": "object", "properties": {}},
                handler=handler,
                approval="ask",
            )
        )
    except ValueError:
        return


def _register_prompt_tool(
    registry: ToolRegistry,
    client: MCPClient,
    server_name: str,
    item: dict[str, Any],
) -> None:
    prompt_name = str(item.get("name") or "").strip()
    if not prompt_name:
        return
    name = _tool_name(server_name, "prompt_" + prompt_name)
    properties: dict[str, Any] = {}
    required: list[str] = []
    raw_arguments = item.get("arguments")
    if isinstance(raw_arguments, list):
        for argument in raw_arguments[:40]:
            if not isinstance(argument, dict) or not argument.get("name"):
                continue
            key = str(argument["name"])
            properties[key] = {
                "type": "string",
                "description": str(argument.get("description") or "")[:300],
            }
            if argument.get("required") is True:
                required.append(key)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required

    def handler(args: dict[str, Any], ctx: Any) -> str:
        try:
            safe_args = {str(key): str(value) for key, value in args.items()}
            return truncate_text(
                client.get_prompt(prompt_name, safe_args),
                ctx.max_output_chars,
            )
        except MCPError as exc:
            raise ToolError(str(exc)) from exc

    try:
        registry.register(
            Tool(
                name=name,
                description=(
                    "Get an MCP prompt from " + server_name + ": "
                    + str(item.get("description") or prompt_name)
                )[:1_000],
                parameters=schema,
                handler=handler,
                approval="ask",
            )
        )
    except ValueError:
        return


def _render_resource_result(result: dict[str, Any]) -> str:
    contents = result.get("contents")
    parts: list[str] = []
    if isinstance(contents, list):
        for item in contents[:30]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("uri") or "resource")
            mime = str(item.get("mimeType") or "unknown")
            if isinstance(item.get("text"), str):
                parts.append(f"[{label} · {mime}]\n{item['text']}")
            elif item.get("blob"):
                parts.append(f"[{label} · {mime}] contenu binaire omis.")
    return "\n\n".join(parts) or "(ressource MCP vide ou non textuelle)"


def _render_prompt_result(result: dict[str, Any]) -> str:
    messages = result.get("messages")
    parts: list[str] = []
    if isinstance(messages, list):
        for message in messages[:40]:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "assistant")
            content = message.get("content")
            if isinstance(content, str):
                rendered = content
            elif isinstance(content, dict):
                rendered = str(content.get("text") or content.get("uri") or "")
            elif isinstance(content, list):
                rendered = "\n".join(
                    str(part.get("text") or part.get("uri") or "")
                    for part in content
                    if isinstance(part, dict)
                )
            else:
                rendered = ""
            if rendered:
                parts.append(f"[{role}]\n{rendered}")
    return "\n\n".join(parts) or "(prompt MCP vide)"


def _tool_name(server: str, tool: str) -> str:
    raw = f"mcp_{server}_{tool}"
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    return cleaned[:64]


def _render_content(result: dict[str, Any]) -> str:
    content = result.get("content")
    parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif item.get("type") == "resource":
                resource = item.get("resource")
                if isinstance(resource, dict):
                    parts.append(str(resource.get("text") or resource.get("uri") or ""))
    if not parts and isinstance(result.get("structuredContent"), dict):
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False, indent=2))
    return "\n".join(part for part in parts if part) or "(resultat MCP vide)"


def _warn(ui: Any | None, message: str) -> None:
    warn = getattr(ui, "warn", None)
    if callable(warn):
        warn(message)

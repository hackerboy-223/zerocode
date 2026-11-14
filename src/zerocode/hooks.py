from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .catalog import PROVIDERS
from .security import redact_secrets

PROVIDER_KEY_ENVS = frozenset(
    env_name for spec in PROVIDERS.values() for env_name in spec.api_key_envs
)
HOOK_EVENTS = frozenset({"PreToolUse", "PostToolUse"})
MAX_HOOK_TIMEOUT = 30
MAX_HOOK_OUTPUT = 4_000


class HookManager:
    """Runs explicitly configured user-level lifecycle hooks without a shell."""

    def __init__(self, config: dict[str, Any] | None, cwd: Path) -> None:
        self.cwd = cwd.resolve()
        self.config = config or {}

    def run(
        self,
        event: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: str | None = None,
    ) -> str | None:
        hooks = self.config.get(event, [])
        if event not in HOOK_EVENTS or not isinstance(hooks, list):
            return None

        payload = redact_secrets(
            json.dumps(
                {
                    "event": event,
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": result,
                    "cwd": str(self.cwd),
                },
                ensure_ascii=False,
                default=str,
            )
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in PROVIDER_KEY_ENVS
        }

        for hook in hooks[:8]:
            if not isinstance(hook, dict):
                continue
            command = str(hook.get("command") or "").strip()
            raw_args = hook.get("args") or []
            if not command or not isinstance(raw_args, list):
                continue
            timeout = min(
                MAX_HOOK_TIMEOUT,
                max(1, int(hook.get("timeout", 10))),
            )
            try:
                process = subprocess.run(
                    [command, *[str(arg) for arg in raw_args]],
                    cwd=self.cwd,
                    env=env,
                    input=payload,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                message = f"Hook {event} expiré après {timeout}s."
                if event == "PreToolUse":
                    return message
                continue
            except OSError as exc:
                message = f"Impossible de lancer le hook {command}: {exc}"
                if event == "PreToolUse":
                    return message
                continue

            output = (process.stdout or process.stderr or "").strip()[:MAX_HOOK_OUTPUT]
            if event == "PreToolUse":
                if process.returncode != 0:
                    return output or f"Hook {command} a refusé l'action."
                if output:
                    try:
                        decision = json.loads(output)
                    except json.JSONDecodeError:
                        decision = None
                    if isinstance(decision, dict) and str(decision.get("decision", "")).lower() == "deny":
                        return str(decision.get("reason") or "Action refusée par le hook.")
            elif process.returncode != 0:
                return output or f"Hook {command} a échoué (code {process.returncode})."
        return None

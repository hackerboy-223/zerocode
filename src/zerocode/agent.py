from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Config
from .errors import ConfigError
from .prompts import build_system_prompt
from .session import Session, SessionStore
from .tokens import compact_messages, estimate_messages
from .types import StreamCallbacks, Usage

PLAN_MODE_INSTRUCTION = """
MODE PLAN ACTIF (lecture seule):
- Tu ne dois modifier aucun fichier et tu ne dois pas executer de commande shell.
- Les outils write, edit et bash ne sont pas disponibles.
- Inspecte le depot, verifie les faits et propose un plan d'action precis.
- Si l'utilisateur demande une modification, decris les changements a faire sans les appliquer.
"""

FULL_STACK_MODE_INSTRUCTION = """
MODE FULL-STACK AUTONOME ACTIF:
- Mission: construire ou terminer un projet complet de bout en bout, pas seulement proposer un plan.
- L'utilisateur a explicitement active ce mode: cette autorisation remplace la regle generale et t'autorise a installer les dependances locales et a lancer les commandes de build, de test et de lint sans demander confirmation.
- Inspecte le depot, puis cree un plan avec todo_write et maintiens-le a jour jusqu'a la livraison.
- Si le projet existe deja, respecte sa stack et ses conventions. S'il est vide, choisis une stack moderne et coherente, puis cree la structure complete.
- Implemente les couches necessaires: interface, backend/API, donnees, validation, authentification si utile, tests, scripts et documentation.
- Prends des decisions raisonnables sans multiplier les questions. Ne t'arrete que si une information critique ou un secret manque.
- Execute les tests et le build, lis les erreurs, corrige et recommence jusqu'a obtenir un resultat fonctionnel.
- Cree des tests si le projet n'en a pas et verifie au moins une fois le parcours principal.
- Reste dans le repertoire de travail, ne detruis pas de donnees irremplacables, ne lis jamais les secrets et ne commit/push pas sans demande explicite.
- Continue tant qu'il reste une etape faisable. A la fin, fournis un resume court des livrables et des commandes de lancement.
"""

VALID_AGENT_MODES = {"build", "plan", "full-stack"}

FULL_STACK_PRESET = {
    "reasoning_effort": "max",
    "temperature": 0.2,
    "max_tokens": 128_000,
    "max_steps": 500,
    "permissions": "allow",
    "command_timeout": 3_600,
    "compact_threshold": 0.95,
    "show_reasoning": True,
}


class Agent:
    def __init__(
        self,
        config: Config,
        router: Any,
        tools: Any,
        session: Session,
        ui: Any,
        store: SessionStore | None = None,
    ) -> None:
        self.config = config
        self.router = router
        self.tools = tools
        self.session = session
        self.ui = ui
        self.store = store
        self.usage = session.usage
        self.mode = "build"
        self._full_stack_backup: dict[str, Any] | None = None
        self.messages: list[dict[str, Any]] = session.messages
        self.tools.context.todos[:] = [todo for todo in session.todos if isinstance(todo, dict)]
        self.tools.read_only = self.mode == "plan"
        if not self.messages:
            self.messages = [self._system_message()]
        elif self.messages[0].get("role") != "system":
            self.messages.insert(0, self._system_message())
        self._refresh_system_mode()
        self._sync_session()

    def run_turn(self, user_text: str) -> str:
        text = user_text.strip()
        if not text:
            return ""
        self.messages.append({"role": "user", "content": text})
        self._sync_session()
        self._save_quiet()
        final_text = ""
        try:
            for _ in range(self.config.max_steps):
                self._maybe_compact()
                callbacks = StreamCallbacks(
                    on_text=self._callable("stream_text"),
                    on_reasoning=(
                        self._callable("stream_reasoning") if self.config.show_reasoning else None
                    ),
                )
                completion = self.router.complete(
                    self.messages,
                    self.tools.schemas(),
                    model=self.config.model,
                    provider=self.config.provider,
                    callbacks=callbacks,
                )
                self.usage.add(completion.usage)
                assistant: dict[str, Any] = {
                    "role": "assistant",
                    "content": completion.content or "",
                }
                if completion.tool_calls:
                    assistant["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": _json_arguments(call.arguments),
                            },
                        }
                        for call in completion.tool_calls
                    ]
                self.messages.append(assistant)
                self._call_ui("end_assistant")
                if completion.content:
                    final_text = completion.content
                if not completion.tool_calls:
                    if completion.finish_reason == "length" and not completion.content:
                        self._call_ui("warn", "Reponse vide ou tronquee: augmente max_tokens.")
                    break
                if completion.finish_reason == "length" and not completion.content:
                    self._call_ui("warn", "Reponse tronquee avant l'appel d'outil.")
                    break
                for call in completion.tool_calls:
                    self._call_ui("tool_start", call.name, call.arguments)
                    result = self.tools.execute(call)
                    self._call_ui("tool_result", call.name, result)
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": result,
                        }
                    )
                self._sync_session()
                self._save_quiet()
            else:
                self._call_ui(
                    "warn",
                    f"Limite de {self.config.max_steps} etapes atteinte. "
                    "Augmente max_steps ou precise la demande.",
                )
            return final_text
        finally:
            self._sync_session()
            self._save_quiet()

    def compact(self, force: bool = False) -> None:
        context = self.router.context_window(self.config.model)
        threshold = int(context * self.config.compact_threshold)
        before = estimate_messages(self.messages)
        if not force and before <= threshold:
            return
        target = max(4_000, int(context * 0.55))
        self.messages = compact_messages(self.messages, target, keep_last=8, force=True)
        after = estimate_messages(self.messages)
        self._sync_session()
        self._save_quiet()
        self._call_ui(
            "info",
            f"Contexte compacte: {before} -> {after} jetons estimes (limite {context}).",
        )

    def _maybe_compact(self) -> None:
        context = self.router.context_window(self.config.model)
        overhead = 2_000
        if estimate_messages(self.messages) + overhead > int(
            context * self.config.compact_threshold
        ):
            self.compact(force=True)

    def reset(self) -> None:
        self.messages = [self._system_message()]
        self.usage = Usage()
        self.tools.context.todos.clear()
        self._sync_session()
        self._save_quiet()

    def load_session(self, session: Session) -> None:
        self.session = session
        self.messages = session.messages
        self.usage = session.usage
        self.config.model = session.model
        self.config.provider = session.provider
        self.tools.context.cwd = Path(session.cwd).expanduser().resolve()
        self.tools.context.todos[:] = [todo for todo in session.todos if isinstance(todo, dict)]
        self.tools.read_only = self.mode == "plan"
        if not self.messages:
            self.messages = [self._system_message()]
        elif self.messages[0].get("role") != "system":
            self.messages.insert(0, self._system_message())
        self._refresh_system_mode()
        self._sync_session()
        self._save_quiet()

    def set_mode(self, mode: str) -> None:
        if mode not in VALID_AGENT_MODES:
            raise ValueError(f"Mode inconnu: {mode}")
        if mode == "full-stack":
            self._activate_full_stack()
            return
        if self.mode == "full-stack":
            self._restore_full_stack()
        self.mode = mode
        self.tools.read_only = mode == "plan"
        self._refresh_system_mode()
        self._save_quiet()

    def _activate_full_stack(self) -> None:
        if self._full_stack_backup is None:
            self._full_stack_backup = {
                "config": {
                    key: getattr(self.config, key)
                    for key in FULL_STACK_PRESET
                },
                "permissions": self.tools.permissions.mode,
                "ui_reasoning": getattr(self.ui, "show_reasoning", None),
            }
        for key, value in FULL_STACK_PRESET.items():
            setattr(self.config, key, value)
        self.tools.permissions.mode = "allow"
        self.tools.context.command_timeout = self.config.command_timeout
        self.tools.read_only = False
        self.mode = "full-stack"
        self._sync_reasoning_visibility()
        self._refresh_system_mode()
        self._save_quiet()

    def _restore_full_stack(self) -> None:
        backup = self._full_stack_backup
        self._full_stack_backup = None
        if backup is None:
            return
        for key, value in backup["config"].items():
            setattr(self.config, key, value)
        self.tools.permissions.mode = str(backup["permissions"])
        self.tools.context.command_timeout = self.config.command_timeout
        self._sync_reasoning_visibility()
        previous = backup.get("ui_reasoning")
        if previous is not None and hasattr(self.ui, "show_reasoning"):
            self.ui.show_reasoning = bool(previous)

    def _sync_reasoning_visibility(self) -> None:
        if hasattr(self.ui, "show_reasoning"):
            self.ui.show_reasoning = self.config.show_reasoning

    def _refresh_system_mode(self) -> None:
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = self._system_message()["content"]

    def set_model(self, model: str, provider: str | None = None) -> None:
        self.config.model = model
        if provider is not None:
            self.config.provider = provider
        self.session.model = model
        self.session.provider = self.config.provider
        self._save_quiet()

    def set_provider(self, provider: str | None) -> None:
        self.config.provider = provider
        self.session.provider = provider
        self._save_quiet()

    def session_path(self) -> str:
        if self.store is None:
            return "(non sauvegardee)"
        return str(self.store.path_for(self.session))

    def _system_message(self) -> dict[str, Any]:
        cwd = self.tools.context.cwd
        content = build_system_prompt(cwd)
        if self.mode == "plan":
            content += "\n\n" + PLAN_MODE_INSTRUCTION
        elif self.mode == "full-stack":
            content += "\n\n" + FULL_STACK_MODE_INSTRUCTION
        return {"role": "system", "content": content}

    def _sync_session(self) -> None:
        self.session.messages = self.messages
        self.session.usage = self.usage
        self.session.todos = list(self.tools.context.todos)
        self.session.model = self.config.model
        self.session.provider = self.config.provider
        self.session.cwd = str(self.tools.context.cwd)

    def _save_quiet(self) -> None:
        if self.store is None:
            return
        try:
            self.store.save(self.session)
        except (OSError, ValueError, ConfigError) as exc:
            self._call_ui("warn", f"Impossible de sauvegarder la session: {exc}")

    def _call_ui(self, name: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self.ui, name, None)
        if callable(method):
            return method(*args, **kwargs)
        return None

    def _callable(self, name: str) -> Any:
        method = getattr(self.ui, name, None)
        return method if callable(method) else None


def _json_arguments(arguments: dict[str, Any]) -> str:
    import json

    return json.dumps(arguments, ensure_ascii=False)

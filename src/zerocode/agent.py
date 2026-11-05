from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .config import Config
from .errors import ConfigError, ToolError
from .prompts import build_system_prompt
from .security import redact_secrets
from .session import Session, SessionStore
from .skills import DEFAULT_ACTIVE_SKILLS, all_skills, normalize_skill_names
from .tokens import compact_messages, estimate_messages, truncate_text
from .tools import PermissionManager, ToolContext, build_registry
from .tools.files import _is_binary
from .types import StreamCallbacks, Usage

FILE_MENTION_RE = re.compile(r"(?:^|(?<=\s))@([A-Za-z0-9_./-]+)")

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

THINK_MODE_INSTRUCTIONS: dict[str, str] = {
    "low": """
MODE THINK (LOW) ACTIF:
- Avant ta réponse finale, commence par un court bloc `<think>...</think>` (1 à 2 phrases concises) résumant l'objectif et l'action choisie.
- Ferme obligatoirement la balise `</think>` avant d'écrire la réponse destinée à l'utilisateur.
""".strip(),
    "high": """
MODE THINK (HIGH) ACTIF:
- Avant ta réponse finale ou tes appels d'outils, commence par un bloc `<think>...</think>` structuré (3 à 6 lignes) analysant le contexte, les hypothèses, les fichiers/outils pertinents et les cas limites.
- Ferme obligatoirement la balise `</think>` avant d'écrire la réponse finale destinée à l'utilisateur.
""".strip(),
    "max": """
MODE THINK (MAX) ACTIF:
- Avant ta réponse finale ou tes appels d'outils, commence par un bloc `<think>...</think>` approfondi et méthodique : décompose l'architecture, la sécurité (OWASP/CWE), les dépendances, les risques de régression et la stratégie de vérification étape par étape.
- Ferme obligatoirement la balise `</think>` avant d'écrire la réponse finale destinée à l'utilisateur.
""".strip(),
}

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
        self.skills: list[str] = list(DEFAULT_ACTIVE_SKILLS)
        self._full_stack_backup: dict[str, Any] | None = None
        self.messages: list[dict[str, Any]] = session.messages
        self.tools.context.todos[:] = [todo for todo in session.todos if isinstance(todo, dict)]
        self.tools.context.run_subagent = self._run_subagent
        self.tools.read_only = self.mode == "plan"
        if not self.messages:
            self.messages = [self._system_message()]
        elif self.messages[0].get("role") != "system":
            self.messages.insert(0, self._system_message())
        self._refresh_system_mode()
        self._sync_session()

    def run_turn(self, user_text: str, images: list[str] | None = None) -> str:
        text = user_text.strip()
        if not text:
            return ""
        expanded_text = self._expand_file_mentions(text)
        content: str | list[dict[str, Any]] = expanded_text
        if images:
            content = [{"type": "text", "text": expanded_text}]
            content.extend(
                {"type": "image_url", "image_url": {"url": image}} for image in images
            )
        self.messages.append({"role": "user", "content": content})
        self._sync_session()
        self._save_quiet()
        final_text = ""
        try:
            repeated_failures: dict[str, int] = {}
            auto_continues = 0
            for _ in range(self.config.max_steps):
                if self._interrupted():
                    raise KeyboardInterrupt
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
                    needs_vision=_messages_have_images(self.messages),
                )
                if self._interrupted():
                    raise KeyboardInterrupt
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
                    elif (
                        self.mode == "full-stack"
                        and auto_continues < 2
                        and self._has_incomplete_todos()
                    ):
                        auto_continues += 1
                        self.messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Continue l'execution autonome des taches restantes "
                                    "du plan jusqu'a completion et verification."
                                ),
                            }
                        )
                        continue
                    break
                if completion.finish_reason == "length":
                    self._call_ui(
                        "warn",
                        "Reponse tronquee pendant l'appel d'outil: augmente max_tokens.",
                    )
                    self._repair_pending_tool_calls()
                    break
                stop_after_repeated_failure = False
                calls = completion.tool_calls
                if self._can_parallelize_calls(calls):
                    for call in calls:
                        if self._interrupted():
                            raise KeyboardInterrupt
                        self._call_ui("tool_start", call.name, call.arguments)
                    with ThreadPoolExecutor(max_workers=min(4, len(calls))) as pool:
                        results = list(pool.map(self._safe_execute_tool, calls))
                    for call, result in zip(calls, results, strict=False):
                        fingerprint = _tool_call_fingerprint(call)
                        if result.startswith("ERREUR:"):
                            repeated_failures[fingerprint] = (
                                repeated_failures.get(fingerprint, 0) + 1
                            )
                            if repeated_failures[fingerprint] >= 2:
                                stop_after_repeated_failure = True
                        self._call_ui("tool_result", call.name, result)
                        self.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": result,
                            }
                        )
                else:
                    for call in calls:
                        if self._interrupted():
                            raise KeyboardInterrupt
                        self._call_ui("tool_start", call.name, call.arguments)
                        fingerprint = _tool_call_fingerprint(call)
                        result = self.tools.execute(call)
                        if result.startswith("ERREUR:"):
                            repeated_failures[fingerprint] = (
                                repeated_failures.get(fingerprint, 0) + 1
                            )
                            if repeated_failures[fingerprint] >= 2:
                                stop_after_repeated_failure = True
                        self._call_ui("tool_result", call.name, result)
                        self.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": result,
                            }
                        )
                        if self._interrupted():
                            raise KeyboardInterrupt
                self._sync_session()
                self._save_quiet()
                if stop_after_repeated_failure:
                    final_text = (
                        "J'ai arrêté la boucle : le même appel d'outil a échoué deux fois "
                        "avec les mêmes arguments. Vérifie l'erreur ci-dessus avant de réessayer."
                    )
                    self._call_ui("warn", final_text)
                    break
            else:
                self._call_ui(
                    "warn",
                    f"Limite de {self.config.max_steps} etapes atteinte. "
                    "Augmente max_steps ou precise la demande.",
                )
            return final_text
        finally:
            self._repair_pending_tool_calls()
            self._sync_session()
            self._save_quiet()

    def _repair_pending_tool_calls(self) -> None:
        for index in range(len(self.messages) - 1, -1, -1):
            message = self.messages[index]
            if message.get("role") != "assistant":
                continue
            calls = message.get("tool_calls") or []
            if not calls:
                return
            completed = {
                str(item.get("tool_call_id"))
                for item in self.messages[index + 1 :]
                if item.get("role") == "tool"
            }
            for call in calls:
                call_id = str(call.get("id") or "")
                if not call_id or call_id in completed:
                    continue
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": (
                            "ERREUR: appel d'outil interrompu avant execution. "
                            "Relance l'action si necessaire."
                        ),
                    }
                )
            return

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
        self.tools.context.run_subagent = self._run_subagent
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

    def set_think(self, mode: str) -> None:
        token = mode.strip().lower()
        if token == "off":
            self.config.show_reasoning = False
        elif token in {"low", "high", "max"}:
            self.config.show_reasoning = True
            self.config.reasoning_effort = token
        else:
            raise ValueError(f"Mode think inconnu: {mode}")
        self._sync_reasoning_visibility()
        self._refresh_system_mode()
        self._save_quiet()

    def _refresh_system_mode(self) -> None:
        if not self.messages or self.messages[0].get("role") != "system":
            return
        current = str(self.messages[0].get("content") or "")
        title = "## Contexte anterieur (resume automatique)"
        summary = ""
        if title in current:
            _, summary = current.split(title, 1)
            summary = summary.strip()
        content = self._system_message()["content"]
        if summary:
            content = f"{content.rstrip()}\n\n{title}\n{summary}"
        self.messages[0]["content"] = content

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

    def set_skills(self, names: list[str] | tuple[str, ...] | None) -> list[str]:
        self.skills = normalize_skill_names(names, self.tools.context.cwd)
        self._refresh_system_mode()
        self._save_quiet()
        return list(self.skills)

    def toggle_skill(self, raw_name: str) -> tuple[bool, str]:
        token = raw_name.strip().lower()
        cwd = self.tools.context.cwd
        catalog = all_skills(cwd)
        if token in {"all", "tous", "*"}:
            self.skills = list(catalog)
            self._refresh_system_mode()
            self._save_quiet()
            return True, f"Tous les skills sont actifs ({', '.join(self.skills)})."
        if token in {"off", "none", "aucun", "0"}:
            self.skills = []
            self._refresh_system_mode()
            self._save_quiet()
            return True, "Tous les skills additionnels sont désactivés."
        if token in {"default", "defaut", "reset"}:
            self.skills = list(DEFAULT_ACTIVE_SKILLS)
            self._refresh_system_mode()
            self._save_quiet()
            return True, f"Skills par défaut restaurés ({', '.join(self.skills)})."
        if token not in catalog:
            return False, (
                f"Skill inconnu : {raw_name!r}. "
                f"Disponibles : {', '.join(catalog)} (ou all / off / default)."
            )
        if token in self.skills:
            self.skills.remove(token)
            state = "désactivé"
        else:
            self.skills.append(token)
            state = "activé"
        self._refresh_system_mode()
        self._save_quiet()
        return True, f"Skill {token} {state} (actifs : {', '.join(self.skills) or 'aucun'})."

    def session_path(self) -> str:
        if self.store is None:
            return "(non sauvegardee)"
        return str(self.store.path_for(self.session))

    def _system_message(self) -> dict[str, Any]:
        cwd = self.tools.context.cwd
        content = build_system_prompt(cwd, skills=self.skills)
        if self.mode == "plan":
            content += "\n\n" + PLAN_MODE_INSTRUCTION
        elif self.mode == "full-stack":
            content += "\n\n" + FULL_STACK_MODE_INSTRUCTION
        if self.config.show_reasoning:
            effort = str(getattr(self.config, "reasoning_effort", "high") or "high").lower()
            think_instruction = THINK_MODE_INSTRUCTIONS.get(
                effort, THINK_MODE_INSTRUCTIONS["high"]
            )
            content += "\n\n" + think_instruction
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

    def _interrupted(self) -> bool:
        checker = getattr(self.ui, "interrupted", None)
        return bool(checker()) if callable(checker) else False

    def _has_incomplete_todos(self) -> bool:
        return any(
            isinstance(todo, dict) and todo.get("status") in {"pending", "in_progress"}
            for todo in self.tools.context.todos
        )

    def last_assistant_text(self) -> str:
        for message in reversed(self.messages):
            if message.get("role") != "assistant":
                continue
            content = str(message.get("content") or "").strip()
            if content:
                return content
        return ""

    def _expand_file_mentions(self, text: str) -> str:
        matches = FILE_MENTION_RE.findall(text)
        if not matches:
            return text
        seen: set[Path] = set()
        snippets: list[str] = []
        ctx = self.tools.context
        for raw_ref in matches:
            if len(snippets) >= 5:
                break
            cleaned_ref = raw_ref.rstrip(".,;:!?")
            if not cleaned_ref:
                continue
            try:
                path = ctx.resolve_path(cleaned_ref)
                ctx.check_secret(path)
                if path in seen or not path.is_file() or path.stat().st_size > 200_000:
                    continue
                if _is_binary(path):
                    continue
                file_text = path.read_text(encoding="utf-8", errors="replace")
            except (ToolError, OSError):
                continue
            seen.add(path)
            if ctx.protect_secrets and not ctx.allow_secrets:
                file_text = redact_secrets(file_text)
            label = ctx.display_path(path)
            snippets.append(
                f"### {label}\n```\n{truncate_text(file_text, 10_000)}\n```"
            )
        if not snippets:
            return text
        joined = "\n\n".join(snippets)
        return f"{text}\n\n<referenced-files>\n{joined}\n</referenced-files>"

    def _can_parallelize_calls(self, calls: list[Any]) -> bool:
        if len(calls) < 2:
            return False
        tool_map = {tool.name: tool for tool in self.tools.tools()}
        for call in calls:
            if call.name in {"todo_write", "subagent"}:
                return False
            spec = tool_map.get(call.name)
            if spec is None or spec.approval != "never":
                return False
        return True

    def _safe_execute_tool(self, call: Any) -> str:
        try:
            return self.tools.execute(call)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - isolation des threads d'outils
            return f"ERREUR: {exc.__class__.__name__}: {exc}"

    def _run_subagent(self, task: str) -> str:
        sub_ctx = ToolContext(
            cwd=self.tools.context.cwd,
            allow_outside=self.tools.context.allow_outside,
            command_timeout=self.tools.context.command_timeout,
            protect_secrets=self.tools.context.protect_secrets,
            allow_secrets=self.tools.context.allow_secrets,
        )
        sub_perms = PermissionManager(mode="deny", interactive=False)
        sub_registry = build_registry(
            sub_ctx,
            sub_perms,
            ui=None,
            include_subagent=False,
        )
        sub_registry.read_only = True
        sub_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "Tu es un sous-agent d'exploration en lecture seule pour zerocode. "
                    "Explore rapidement le depot avec symbols, grep, list, read, "
                    "security_audit, sys_diag, fetch ou web_search et renvoie une synthese "
                    "concise, factuelle et directement exploitable avec les chemins et lignes exacts."
                ),
            },
            {"role": "user", "content": task},
        ]
        max_sub_steps = min(8, max(2, self.config.max_steps))
        last_text = ""
        for _ in range(max_sub_steps):
            if self._interrupted():
                raise KeyboardInterrupt
            completion = self.router.complete(
                sub_messages,
                sub_registry.schemas(),
                model=self.config.model,
                provider=self.config.provider,
            )
            self.usage.add(completion.usage)
            if completion.content:
                last_text = completion.content
            if not completion.tool_calls:
                break
            sub_messages.append(
                {
                    "role": "assistant",
                    "content": completion.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": _json_arguments(call.arguments),
                            },
                        }
                        for call in completion.tool_calls
                    ],
                }
            )
            for call in completion.tool_calls:
                if self._interrupted():
                    raise KeyboardInterrupt
                result = sub_registry.execute(call)
                sub_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": truncate_text(result, 8_000),
                    }
                )
        return last_text.strip() or "(aucune synthese produite par le sous-agent)"

    def _callable(self, name: str) -> Any:
        method = getattr(self.ui, name, None)
        return method if callable(method) else None


def _messages_have_images(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        if any(
            isinstance(part, dict) and part.get("type") in {"image_url", "input_image"}
            for part in content
        ):
            return True
    return False


def _json_arguments(arguments: dict[str, Any]) -> str:
    import json

    return json.dumps(arguments, ensure_ascii=False)


def _tool_call_fingerprint(call: Any) -> str:
    import json

    return f"{call.name}:{json.dumps(call.arguments, ensure_ascii=False, sort_keys=True)}"

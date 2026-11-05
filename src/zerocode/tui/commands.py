from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..catalog import PROVIDERS, all_choices
from ..config import mask_key
from ..prompts import remember_project_instruction
from ..providers import (
    applied_providers,
    provider_available,
    provider_enabled,
    resolve_api_key,
)

if TYPE_CHECKING:
    from .app import ZeroCodeApp

COMMANDS: list[tuple[str, str]] = [
    ("/help", "Aide et raccourcis"),
    ("/model [nom]", "Voir ou changer le modèle"),
    ("/provider [nom]", "Voir ou changer le fournisseur"),
    ("/build", "Mode build : modifications autorisées"),
    ("/plan", "Mode plan : lecture seule"),
    ("/full-stack", "Projet complet autonome, réglages max"),
    ("/permissions [ask|allow|deny]", "Politique d'autorisation"),
    ("/yolo", "Tout autoriser"),
    ("/safe", "Revenir au mode ask"),
    ("/reasoning [low|high|max]", "Effort de raisonnement"),
    ("/think [off|low|high|max]", "Mode think et affichage du raisonnement"),
    ("/temp [0-2]", "Température"),
    ("/max-steps [n]", "Étapes d'outils maximum"),
    ("/compact", "Compacter le contexte"),
    ("/cost", "Jetons et requêtes"),
    ("/session", "Détails de la session"),
    ("/new", "Nouvelle session"),
    ("/resume [id]", "Reprendre une session"),
    ("/sessions", "Lister les sessions"),
    ("/todos", "Plan de travail"),
    ("/tools", "Outils disponibles"),
    ("/models [all]", "Catalogue des modèles"),
    ("/free", "Modèles gratuits"),
    ("/providers", "État des fournisseurs"),
    ("/cd [chemin]", "Changer de répertoire"),
    ("/init", "Créer ZEROCODE.md"),
    ("/remember [règle]", "Mémoriser une consigne durable du projet"),
    ("/copy", "Copier la dernière réponse de l'assistant"),
    ("/undo", "Annuler la dernière modification de fichier"),
    ("/image [fichier|clear]", "Joindre une image au prochain message"),
    ("/clear", "Effacer la conversation"),
    ("/quit", "Quitter"),
]

ARG_COMMANDS = {
    "/model",
    "/provider",
    "/permissions",
    "/reasoning",
    "/temp",
    "/max-steps",
    "/resume",
    "/cd",
    "/image",
    "/remember",
}


def _load_image(raw_path: str, cwd: Path, *, allow_outside: bool = False) -> str:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = cwd / path
    path = path.resolve()
    if not allow_outside and not path.is_relative_to(cwd.resolve()):
        raise ValueError(f"Accès refusé hors du dossier de travail : {path}")
    if not path.is_file():
        raise ValueError(f"Image introuvable : {path}")
    data = path.read_bytes()
    if len(data) > 10 * 1024 * 1024:
        raise ValueError(f"Image trop volumineuse (max 10 Mo) : {path}")
    mime, _ = mimetypes.guess_type(path.name)
    allowed = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    if mime not in allowed:
        raise ValueError(
            f"Format non supporté : {path.name} (attendu : PNG, JPEG, WEBP ou GIF)."
        )
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


class CommandHandler:
    def __init__(self, app: ZeroCodeApp) -> None:
        self.app = app

    def handle(self, line: str) -> None:
        command, _, rest = line[1:].partition(" ")
        command = command.strip().lower()
        rest = rest.strip()
        app = self.app

        if command in {"quit", "exit", "q"}:
            app.request_exit()
            return
        if command in {"help", "h", "?"}:
            app.show_help()
        elif command == "clear":
            app.pending_images.clear()
            app.agent.reset()
            app.clear_chat()
            app.show_welcome()
            app.notice("Conversation effacée. Les fichiers sont inchangés.", "success")
        elif command == "new":
            app.pending_images.clear()
            session = app.store.new(app.context.cwd, app.config.model, app.config.provider)
            app.agent.load_session(session)
            app.permissions.mode = app.config.permissions
            app.set_work_mode("build", quiet=True)
            app.clear_chat()
            app.show_welcome()
            app.notice(f"Nouvelle session : {session.id}", "success")
        elif command == "resume":
            reference = rest or None
            session = app.store.load(reference)
            if session is None:
                app.notice(f"Session introuvable : {reference or 'aucune'}", "warning")
            else:
                app.agent.load_session(session)
                app.permissions.mode = app.config.permissions
                app.config.base_dir = app.context.cwd
                app.set_work_mode("build", quiet=True)
                app.reload_project(app.context.cwd)
                app.render_session(session)
                app.notice(f"Session reprise : {session.id}", "success")
        elif command == "session":
            for label, value in (
                ("id", app.agent.session.id),
                ("fichier", app.agent.session_path()),
                ("dossier", app.context.cwd),
                ("messages", str(len(app.agent.messages))),
                ("modèle", f"{app.config.provider or 'auto'}/{app.config.model}"),
            ):
                app.notice(f"{label:<9} {value}", "info")
        elif command == "compact":
            app.agent.compact(force=True)
        elif command == "cost":
            usage = app.agent.usage
            completion = app.router.last
            text = f"{usage.total_tokens} jetons · {usage.requests} requêtes"
            if usage.estimated:
                text += " · estimation"
            if completion is not None:
                text = f"{completion.provider}/{completion.model} · " + text
            app.notice(text, "info")
        elif command == "todos":
            app.set_mode("todos")
        elif command == "build":
            app.set_work_mode("build")
        elif command == "plan":
            app.set_work_mode("plan")
        elif command in {"full-stack", "fullstack"}:
            app.set_work_mode("full-stack")
        elif command == "model":
            self._model(rest)
        elif command == "provider":
            self._provider(rest)
        elif command == "permissions":
            self._permissions(rest)
        elif command in {"yolo", "unsafe"}:
            app.permissions.mode = "allow"
            app.config.permissions = "allow"
            app.notice("Permissions : allow", "success")
        elif command == "safe":
            if getattr(app.agent, "mode", "build") == "full-stack":
                app.set_work_mode("build", quiet=True)
            app.permissions.mode = "ask"
            app.config.permissions = "ask"
            app.notice("Permissions : ask", "success")
        elif command in {"think", "thinking"}:
            if rest in {"off", "non", "0", "false"}:
                app.set_think_mode("off")
            elif rest in {"low", "high", "max"}:
                app.set_think_mode(rest)
            elif rest in {"on", "oui", "1", "true"}:
                mode = app.current_think_mode()
                app.set_think_mode("high" if mode == "off" else mode)
            elif not rest:
                app.cycle_think_mode()
            else:
                app.notice("Valeurs : off, low, high, max", "warning")
        elif command == "reasoning":
            if rest not in {"low", "high", "max"}:
                app.notice("Valeurs : low, high, max", "warning")
            else:
                app.config.reasoning_effort = rest
                app.refresh_think_chip()
                app._refresh_modebar()
                app.notice(f"Raisonnement : {rest}", "success")
        elif command in {"temp", "temperature"}:
            try:
                value = float(rest)
            except ValueError:
                app.notice("Valeur numérique attendue.", "warning")
            else:
                if not 0 <= value <= 2:
                    app.notice("La température doit être entre 0 et 2.", "warning")
                else:
                    app.config.temperature = value
                    app.notice(f"Température : {value}", "success")
        elif command == "max-steps":
            try:
                value = int(rest)
            except ValueError:
                app.notice("Entier attendu.", "warning")
            else:
                if not 1 <= value <= 500:
                    app.notice("La limite doit être entre 1 et 500.", "warning")
                else:
                    app.config.max_steps = value
                    app.notice(f"Étapes maximum : {value}", "success")
        elif command == "cd":
            self._cd(rest)
        elif command == "tools":
            app.set_mode("tools")
        elif command == "models":
            self._models(free_only=rest not in {"all", "tous"})
        elif command == "free":
            self._models(free_only=True)
        elif command == "providers":
            self._providers()
        elif command == "sessions":
            app.refresh_sessions()
            app.notice(f"{len(app.store.list())} session(s) dans {app.store.root}", "info")
        elif command == "init":
            self._init_project_file()
        elif command == "remember":
            self._remember(rest)
        elif command == "copy":
            app.copy_last_response()
        elif command == "image":
            self._image(rest)
        elif command == "undo":
            ok, message = app.checkpoints.undo(app.agent.session.id)
            app.notice(message, "success" if ok else "warning")
            if ok:
                app.reload_project(app.context.cwd)
        elif command == "setup":
            app.notice("Quitte puis lance `zerocode setup` dans le terminal.", "info")
        else:
            app.notice(f"Commande inconnue : /{command}. Tape /help.", "warning")

        app.refresh_after_command()

    def _image(self, rest: str) -> None:
        app = self.app
        if not rest:
            count = len(app.pending_images)
            app.notice(f"{count} image(s) joignable(s). Usage : /image chemin.png", "info")
            return
        if rest in {"clear", "none", "aucune"}:
            app.pending_images.clear()
            app.notice("Images joignables effacées.", "success")
            return
        try:
            data_url = _load_image(
                rest,
                app.context.cwd,
                allow_outside=bool(getattr(app.context, "allow_outside", False)),
            )
        except (OSError, ValueError) as exc:
            app.notice(str(exc), "warning")
            return
        app.pending_images.append(data_url)
        app.notice(
            f"Image joignable au prochain message ({len(app.pending_images)}).",
            "success",
        )

    def _model(self, rest: str) -> None:
        app = self.app
        if not rest:
            app.notice(f"Modèle actuel : {app.config.model}", "info")
            chain = app.router.preview(app.config.model, app.config.provider)
            if chain:
                app.notice("Route : " + " → ".join(chain[:8]), "info")
            return
        preview = app.router.preview(rest, app.config.provider)
        if not preview:
            app.notice(
                f"Aucun candidat disponible pour {rest!r}. Vérifie les clés et les modèles gratuits.",
                "warning",
            )
            return
        app.agent.set_model(rest)
        app.notice(f"Modèle : {rest}", "success")
        app.notice("Route : " + " → ".join(preview[:8]), "info")

    def _provider(self, rest: str) -> None:
        app = self.app
        if not rest:
            app.notice(f"Fournisseur actuel : {app.config.provider or 'auto'}", "info")
            return
        if rest in {"auto", "none", "aucun"}:
            app.agent.set_provider(None)
            app.notice("Fournisseur : auto", "success")
            return
        if rest not in PROVIDERS:
            app.notice(f"Fournisseur inconnu : {rest}", "warning")
            return
        preview = app.router.preview(app.config.model, rest)
        if not preview:
            app.notice(
                f"Aucun modèle disponible chez {rest} (clé manquante ou modèle payant).",
                "warning",
            )
            return
        app.agent.set_model(app.config.model, rest)
        app.notice(f"Fournisseur : {rest}", "success")

    def _permissions(self, rest: str) -> None:
        app = self.app
        if not rest:
            app.notice(f"Permissions : {app.permissions.mode}", "info")
            return
        if rest not in {"ask", "allow", "deny"}:
            app.notice("Valeurs : ask, allow, deny", "warning")
            return
        app.permissions.mode = rest
        app.config.permissions = rest
        app.notice(f"Permissions : {rest}", "success")

    def _cd(self, rest: str) -> None:
        app = self.app
        if not rest:
            app.notice(str(app.context.cwd), "info")
            return
        target = Path(rest).expanduser()
        if not target.is_absolute():
            target = app.context.cwd / target
        target = target.resolve()
        if not target.is_dir():
            app.notice(f"Dossier introuvable : {target}", "warning")
            return
        app.context.cwd = target
        app.config.base_dir = target
        app.agent.session.cwd = str(target)
        app.agent.set_model(app.config.model)
        app.reload_project(target)
        app.notice(f"Dossier : {target}", "success")
        app.notice("Utilise /clear pour recharger le prompt système.", "info")

    def _models(self, *, free_only: bool) -> None:
        lines: list[str] = []
        for provider, model in all_choices():
            if free_only and not model.is_free:
                continue
            lines.append(f"{model.id}  ·  {provider.name}  ·  {model.tier}")
        title = "Modèles gratuits" if free_only else "Catalogue"
        self.app.show_list(title, lines[:80])

    def _providers(self) -> None:
        lines: list[str] = []
        for name, spec in applied_providers(self.app.config).items():
            key = resolve_api_key(spec, self.app.config)
            if not provider_enabled(spec, self.app.config):
                status = "désactivé"
            elif provider_available(spec, self.app.config):
                status = "disponible"
            else:
                status = "sans clé"
            key_label = "anonyme" if spec.keyless and not key else mask_key(key)
            lines.append(f"{name:<14} {status:<12} {key_label}")
        self.app.show_list("Fournisseurs", lines)

    def _init_project_file(self) -> None:
        path = self.app.context.cwd / "ZEROCODE.md"
        if path.exists():
            self.app.notice(f"{path} existe déjà.", "warning")
            return
        path.write_text(_PROJECT_TEMPLATE, encoding="utf-8")
        self.app.notice(f"Créé : {path}", "success")

    def _remember(self, rest: str) -> None:
        if not rest:
            self.app.notice("Usage : /remember <consigne durable du projet>", "info")
            return
        try:
            target = remember_project_instruction(self.app.context.cwd, rest)
        except (OSError, ValueError) as exc:
            self.app.notice(str(exc), "warning")
            return
        refresh = getattr(self.app.agent, "_refresh_system_mode", None)
        if callable(refresh):
            refresh()
        self.app.notice(f"Consigne mémorisée dans {target}", "success")


def usage_summary(usage: Any, completion: Any = None) -> str:
    total = f"{usage.total_tokens:,}".replace(",", " ")
    text = f"{total} jetons · {usage.requests} requêtes"
    if usage.estimated:
        text += " · estimation"
    if completion is not None:
        text = f"{completion.provider}/{completion.model} · " + text
    return text


_PROJECT_TEMPLATE = """# ZEROCODE.md

## Contexte
Décris ici le projet en quelques lignes.

## Commandes
- Tests :
- Lint :
- Build :

## Conventions
- Style de code :
- Architecture :
- Points à ne pas modifier :

## Sécurité
- Ne jamais lire ni afficher de secrets.
"""

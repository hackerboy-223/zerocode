from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import sys
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import httpx
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from .agent import Agent
from .catalog import PROVIDERS, all_choices, get_provider
from .config import (
    Config,
    default_config_path,
    keys_path,
    load_config,
    mask_key,
    project_config_path,
    save_config,
    store_key,
)
from .errors import ZeroCodeError
from .providers import (
    applied_providers,
    discover_free_models,
    fetch_models,
    provider_available,
    provider_enabled,
    resolve_api_key,
)
from .router import Router
from .session import Session, SessionStore
from .tools import PermissionManager, ToolContext, build_registry
from .types import StreamCallbacks
from .ui import ConsoleUI
from .version import __author__, __github__, __portfolio__, __version__

COMMANDS = {
    "setup",
    "doctor",
    "models",
    "providers",
    "sessions",
    "config",
    "help",
    "version",
    "run",
    "chat",
    "tui",
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    console = Console()
    try:
        return _dispatch(args, console)
    except KeyboardInterrupt:
        console.print(Text("Interrompu.", style="yellow"))
        return 130
    except ZeroCodeError as exc:
        console.print(Text("ERREUR: " + str(exc), style="bold red"))
        return 1


def _dispatch(argv: list[str], console: Console) -> int:
    if not argv:
        return run_agent([], console)
    first = argv[0]
    if first in {"help", "--help", "-h"}:
        print_global_help(console)
        return 0
    if first in {"version", "--version", "-V"}:
        console.print(f"zerocode {__version__}")
        return 0
    if first == "setup":
        return setup_command(argv[1:], console)
    if first == "doctor":
        return doctor_command(argv[1:], console)
    if first == "models":
        return models_command(argv[1:], console)
    if first == "providers":
        return providers_command(argv[1:], console)
    if first == "sessions":
        return sessions_command(argv[1:], console)
    if first == "config":
        return config_command(argv[1:], console)
    if first == "tui":
        return run_agent(argv[1:], console, force_tui=True)
    if first in {"run", "chat"}:
        return run_agent(argv[1:], console)
    return run_agent(argv, console)


def _run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zerocode",
        description="Agent de codage pour le terminal, gratuit par defaut.",
    )
    parser.add_argument("prompt", nargs="*", help="Demande a executer. Sans prompt: mode interactif.")
    parser.add_argument("-m", "--model", help="Modele ou alias: glm-5.3, glm-5.3-flash, auto, ...")
    parser.add_argument("--provider", help="Forcer un fournisseur: kilo, nvidia, zai, groq, ...")
    parser.add_argument(
        "--free-only",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="N'utiliser que les modeles gratuits (defaut: oui).",
    )
    parser.add_argument(
        "--fallback",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Basculer automatiquement vers un autre modele (defaut: oui).",
    )
    parser.add_argument("--reasoning", choices=("low", "high", "max"), help="Effort GLM 5.3.")
    parser.add_argument("--temperature", type=float, help="Temperature (0 a 2).")
    parser.add_argument("--max-tokens", type=int, help="Jetons de sortie maximum.")
    parser.add_argument("--max-steps", type=int, help="Nombre maximum d'etapes d'outils.")
    parser.add_argument(
        "--permissions",
        choices=("ask", "allow", "deny"),
        help="Politique pour les ecritures et commandes.",
    )
    parser.add_argument("--yolo", action="store_true", help="Autoriser toutes les actions sans demander.")
    parser.add_argument(
        "--allow-outside-cwd",
        action="store_true",
        default=None,
        help="Autoriser les chemins hors du repertoire de travail.",
    )
    parser.add_argument("--session", help="Reprendre une session par identifiant.")
    parser.add_argument(
        "-c",
        "--continue",
        dest="continue_session",
        action="store_true",
        help="Reprendre la derniere session du repertoire courant.",
    )
    parser.add_argument("--cwd", help="Repertoire de travail.")
    parser.add_argument("--show-thinking", action="store_true", help="Afficher le raisonnement.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Reduire la sortie des outils.")
    parser.add_argument(
        "--classic",
        action="store_true",
        help="Utiliser l'ancienne interface REPL au lieu du TUI.",
    )
    parser.add_argument("--version", action="version", version=f"zerocode {__version__}")
    return parser


def run_agent(
    args_list: list[str],
    console: Console,
    *,
    force_tui: bool = False,
) -> int:
    parser = _run_parser()
    args = parser.parse_args(args_list)
    if force_tui:
        args.classic = False

    cwd = Path(args.cwd).expanduser().resolve() if args.cwd else Path.cwd().resolve()
    if not cwd.is_dir():
        console.print(Text(f"ERREUR: repertoire introuvable: {cwd}", style="bold red"))
        return 1

    overrides: dict[str, Any] = {
        "model": args.model,
        "provider": args.provider,
        "free_only": args.free_only,
        "fallback": args.fallback,
        "reasoning_effort": args.reasoning,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "max_steps": args.max_steps,
        "permissions": args.permissions,
        "allow_outside_cwd": args.allow_outside_cwd,
        "show_reasoning": True if args.show_thinking else None,
    }
    if args.yolo:
        overrides["permissions"] = "allow"

    config = load_config(cwd, overrides)
    store = SessionStore()

    session: Session | None = None
    if args.session:
        session = store.load(args.session)
        if session is None:
            console.print(Text(f"ERREUR: session introuvable: {args.session}", style="bold red"))
            return 1
    elif args.continue_session:
        session = store.latest(cwd)

    if session is not None:
        if args.cwd is None:
            session_cwd = Path(session.cwd).expanduser().resolve()
            if session_cwd.is_dir():
                cwd = session_cwd
        if args.model is None:
            config.model = session.model
        if args.provider is None and session.provider:
            config.provider = session.provider
        config.base_dir = cwd
    else:
        session = store.new(cwd, config.model, config.provider)

    session.cwd = str(cwd)
    session.model = config.model
    session.provider = config.provider

    interactive = sys.stdin.isatty()
    ui = ConsoleUI(
        config,
        console=console,
        show_reasoning=config.show_reasoning,
        quiet=args.quiet,
        interactive=interactive,
    )
    router = Router(config, ui=ui)
    context = ToolContext(
        cwd=cwd,
        allow_outside=config.allow_outside_cwd,
        command_timeout=config.command_timeout,
        todos=[todo for todo in session.todos if isinstance(todo, dict)],
    )
    permissions = PermissionManager(mode=config.permissions, interactive=interactive)
    registry = build_registry(context, permissions, ui)
    agent = Agent(config, router, registry, session, ui, store=store)

    chain = router.preview()
    prompt = " ".join(args.prompt).strip()

    try:
        if force_tui and not interactive:
            console.print(Text("ERREUR: le TUI necessite un terminal interactif.", style="bold red"))
            return 1
        if not prompt and not interactive:
            prompt = sys.stdin.read().strip()

        if prompt:
            if not chain:
                ui.error(
                    "Aucun fournisseur disponible. Lance `zerocode setup` ou `zerocode doctor`."
                )
                return 1
            try:
                agent.run_turn(prompt)
            except ZeroCodeError as exc:
                ui.error(str(exc))
                return 1
            finally:
                ui.usage(agent.usage, router.last)
            return 0

        if not interactive:
            print_global_help(console)
            return 0

        if not args.classic:
            if find_spec("textual") is None:
                ui.warn(
                    "Textual n'est pas installe; utilisation de l'interface classique. "
                    "Installe-le avec `pip install textual`."
                )
            else:
                from .tui import run_tui

                return run_tui(
                    config,
                    agent,
                    router,
                    store,
                    permissions,
                    context,
                    chain,
                )

        if not chain:
            ui.warn(
                "Aucun fournisseur disponible pour le moment. "
                "Kilo Gateway devrait fonctionner sans cle; verifie le reseau, puis `zerocode doctor`."
            )
        ui.welcome(
            model=config.model,
            provider=config.provider,
            chain=chain,
            permissions=config.permissions,
            session_id=agent.session.id,
            cwd=context.cwd,
        )
        return _interactive_loop(agent, router, ui, store, permissions, context, config)

    finally:
        router.close()


def _interactive_loop(
    agent: Agent,
    router: Router,
    ui: ConsoleUI,
    store: SessionStore,
    permissions: PermissionManager,
    context: ToolContext,
    config: Config,
) -> int:
    while True:
        try:
            line = ui.ask("› ")
        except EOFError:
            return 0
        except KeyboardInterrupt:
            ui.info("Utilise /quit pour quitter.")
            continue
        line = line.strip()
        if not line:
            continue
        if line.startswith("/"):
            should_exit = _slash_command(
                line, agent, router, ui, store, permissions, context, config
            )
            if should_exit:
                return 0
            continue
        try:
            agent.run_turn(line)
        except ZeroCodeError as exc:
            ui.error(str(exc))
        except KeyboardInterrupt:
            ui.warn("Tour interrompu.")
        except Exception as exc:  # noqa: BLE001 - l'interface doit rester utilisable
            ui.error(f"{exc.__class__.__name__}: {exc}")
        finally:
            ui.usage(agent.usage, router.last)


def _slash_command(
    line: str,
    agent: Agent,
    router: Router,
    ui: ConsoleUI,
    store: SessionStore,
    permissions: PermissionManager,
    context: ToolContext,
    config: Config,
) -> bool:
    command, _, rest = line[1:].partition(" ")
    command = command.strip().lower()
    rest = rest.strip()

    if command in {"quit", "exit", "q"}:
        return True
    if command in {"help", "h", "?"}:
        print_chat_help(ui.console)
        return False
    if command == "clear":
        agent.reset()
        ui.success("Conversation effacee (fichiers inchanges).")
        return False
    if command == "new":
        new_session = store.new(context.cwd, config.model, config.provider)
        agent.load_session(new_session)
        ui.success(f"Nouvelle session: {new_session.id}")
        return False
    if command == "resume":
        if not rest:
            ui.info("Usage: /resume <id>")
            return False
        session = store.load(rest)
        if session is None:
            ui.warn(f"Session introuvable: {rest}")
            return False
        agent.load_session(session)
        config = agent.config
        permissions.mode = config.permissions
        ui.success(f"Session reprise: {session.id}")
        return False
    if command == "session":
        ui.info(f"id: {agent.session.id}")
        ui.info(f"fichier: {agent.session_path()}")
        ui.info(f"cwd: {context.cwd}")
        ui.info(f"messages: {len(agent.messages)}")
        return False
    if command == "compact":
        agent.compact(force=True)
        return False
    if command == "cost":
        ui.usage(agent.usage, router.last)
        return False
    if command == "todos":
        ui.todos(context.todos)
        return False
    if command == "build":
        agent.set_mode("build")
        ui.success("Mode build: modifications autorisees.")
        return False
    if command == "plan":
        agent.set_mode("plan")
        ui.info("Mode plan: lecture seule. write, edit et bash sont desactives.")
        return False
    if command == "model":
        if not rest:
            ui.info(f"modele actuel: {config.model}")
            chain = router.preview(config.model, config.provider)
            if chain:
                ui.info("chaine: " + " -> ".join(chain[:8]))
            return False
        preview = router.preview(rest, config.provider)
        if not preview:
            ui.warn(f"Aucun candidat disponible pour {rest!r}. Verifie les cles et `zerocode models --free`.")
            return False
        agent.set_model(rest)
        ui.success(f"Modele: {rest}")
        ui.info("chaine: " + " -> ".join(preview[:8]))
        return False
    if command == "provider":
        if not rest:
            ui.info(f"fournisseur actuel: {config.provider or 'auto'}")
            return False
        if rest in {"auto", "none", "aucun"}:
            agent.set_provider(None)
            ui.success("Fournisseur: auto")
            return False
        if rest not in PROVIDERS:
            ui.warn(f"Fournisseur inconnu: {rest}")
            return False
        preview = router.preview(config.model, rest)
        if not preview:
            ui.warn(f"Aucun modele disponible chez {rest} (cle manquante ou modele payant).")
            return False
        agent.set_model(config.model, rest)
        ui.success(f"Fournisseur: {rest}")
        return False
    if command == "permissions":
        if not rest:
            ui.info(f"permissions: {permissions.mode}")
            return False
        if rest not in {"ask", "allow", "deny"}:
            ui.warn("Valeurs: ask, allow, deny")
            return False
        permissions.mode = rest
        config.permissions = rest
        ui.success(f"Permissions: {rest}")
        return False
    if command in {"yolo", "unsafe"}:
        permissions.mode = "allow"
        config.permissions = "allow"
        ui.success("Permissions: allow (toutes les actions sont autorisees).")
        return False
    if command == "safe":
        permissions.mode = "ask"
        config.permissions = "ask"
        ui.success("Permissions: ask")
        return False
    if command in {"think", "thinking"}:
        if rest in {"on", "oui", "1", "true"}:
            config.show_reasoning = True
        elif rest in {"off", "non", "0", "false"}:
            config.show_reasoning = False
        else:
            config.show_reasoning = not config.show_reasoning
        ui.show_reasoning = config.show_reasoning
        ui.info(f"raisonnement affiche: {'oui' if config.show_reasoning else 'non'}")
        return False
    if command == "reasoning":
        if rest not in {"low", "high", "max"}:
            ui.warn("Valeurs: low, high, max")
            return False
        config.reasoning_effort = rest
        ui.success(f"reasoning_effort: {rest}")
        return False
    if command in {"temp", "temperature"}:
        try:
            value = float(rest)
        except ValueError:
            ui.warn("Valeur numerique attendue.")
            return False
        if not 0 <= value <= 2:
            ui.warn("La temperature doit etre entre 0 et 2.")
            return False
        config.temperature = value
        ui.success(f"temperature: {value}")
        return False
    if command == "max-steps":
        try:
            value = int(rest)
        except ValueError:
            ui.warn("Entier attendu.")
            return False
        if not 1 <= value <= 500:
            ui.warn("max-steps doit etre entre 1 et 500.")
            return False
        config.max_steps = value
        ui.success(f"max_steps: {value}")
        return False
    if command == "cd":
        if not rest:
            ui.info(str(context.cwd))
            return False
        target = Path(rest).expanduser()
        if not target.is_absolute():
            target = context.cwd / target
        target = target.resolve()
        if not target.is_dir():
            ui.warn(f"Dossier introuvable: {target}")
            return False
        context.cwd = target
        config.base_dir = target
        agent.session.cwd = str(target)
        agent.set_model(config.model)
        ui.success(f"cwd: {target}")
        ui.info("Utilise /clear pour recharger le prompt systeme avec le nouveau repertoire.")
        return False
    if command == "tools":
        for tool in agent.tools.tools():
            ui.console.print(
                Text(f"{tool.name:<12}", style="bold"),
                Text(tool.description, style="dim"),
            )
        return False
    if command == "models":
        free_only = rest not in {"all", "tous"}
        print_models_table(ui.console, free_only=free_only)
        return False
    if command == "providers":
        print_providers_table(ui.console, config)
        return False
    if command == "free":
        print_models_table(ui.console, free_only=True)
        return False
    if command == "sessions":
        print_sessions_table(ui.console, store)
        return False
    if command == "init":
        _init_project_file(context, ui.console)
        return False
    if command == "setup":
        ui.info("Quitte et lance `zerocode setup`.")
        return False
    ui.warn(f"Commande inconnue: /{command}. Tape /help.")
    return False


def print_global_help(console: Console | None = None) -> None:
    console = console or Console()
    text = Text()
    text.append("Agent de codage pour le terminal\n\n", style="dim")
    text.append("Usage\n", style="bold cyan")
    text.append("  zerocode [options] [prompt...]\n")
    text.append("  zerocode setup | doctor | models | providers | sessions | config\n")
    text.append("  zerocode tui [-m modele]\n\n")
    text.append("Démarrage\n", style="bold cyan")
    text.append("  zerocode                 interface TUI interactive\n")
    text.append('  zerocode "explique la structure du projet"\n')
    text.append("  zerocode -m auto\n")
    text.append("  zerocode -c\n")
    text.append("  zerocode --classic       ancienne interface REPL\n\n")
    text.append("Modèles\n", style="bold cyan")
    text.append("  glm-5.3        GLM 5.3 complet (essai ou payant selon le fournisseur)\n")
    text.append("  glm-5.3-flash  GLM 5.3 Flash (gratuit chez NVIDIA/OpenCode Zen)\n")
    text.append("  auto           chaîne gratuite, sans clé via Kilo Gateway\n\n")
    text.append("Dans le chat\n", style="bold cyan")
    text.append("  /help  /build  /plan  /model  /provider  /permissions  /compact  /cost  /quit\n")
    text.append("\nCréé par ", style="dim")
    text.append(__author__, style="bold")
    text.append("\nGitHub       ", style="dim")
    text.append(__github__, style=f"cyan underline link {__github__}")
    text.append("\nPortfolio    ", style="dim")
    text.append(__portfolio__, style=f"cyan underline link {__portfolio__}")
    console.print(
        Panel(
            text,
            title=f"zerocode {__version__}",
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 1),
            expand=False,
        )
    )


def print_chat_help(console: Console) -> None:
    text = Text()
    text.append("Commandes du chat\n\n", style="bold")
    rows = [
        ("/help", "afficher cette aide"),
        ("/model [nom]", "voir ou changer le modele"),
        ("/provider [nom]", "voir ou changer le fournisseur"),
        ("/build", "mode build: modifications autorisees"),
        ("/plan", "mode plan: lecture seule"),
        ("/permissions [ask|allow|deny]", "politique d'autorisation"),
        ("/yolo", "tout autoriser pour la session"),
        ("/reasoning low|high|max", "effort de raisonnement GLM"),
        ("/think [on|off]", "afficher le raisonnement"),
        ("/temp <0-2>", "temperature"),
        ("/max-steps <n>", "etapes d'outils maximum"),
        ("/compact", "compacter le contexte"),
        ("/cost", "jetons et requetes"),
        ("/session", "identifiant et fichier de session"),
        ("/new", "nouvelle session"),
        ("/resume <id>", "reprendre une session"),
        ("/sessions", "lister les sessions"),
        ("/todos", "afficher le plan de travail"),
        ("/tools", "lister les outils"),
        ("/models", "catalogue des modeles"),
        ("/free", "modeles gratuits"),
        ("/providers", "etat des fournisseurs"),
        ("/cd <chemin>", "changer de repertoire"),
        ("/init", "creer ZEROCODE.md"),
        ("/clear", "effacer la conversation"),
        ("/quit", "quitter"),
    ]
    for command, description in rows:
        text.append(f"  {command:<34}", style="bold")
        text.append(description + "\n")
    console.print(
        Panel(
            text,
            title="commandes du chat",
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 1),
            expand=False,
        )
    )


def setup_command(args_list: list[str], console: Console) -> int:
    parser = argparse.ArgumentParser(prog="zerocode setup")
    parser.add_argument("--provider", choices=sorted(PROVIDERS))
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--test", action="store_true", help="Tester le routeur avec une requete.")
    args = parser.parse_args(args_list)

    config = load_config(Path.cwd())
    console.print(
        Panel(
            Text.from_markup(
                "[bold]Démarrage sans clé[/bold]\n\n"
                "Kilo Gateway fournit des modèles gratuits en accès anonyme "
                "(200 requêtes/heure/IP).\n\n"
                "[bold]GLM 5.3[/bold] n'a pas d'API gratuite permanente. "
                "GLM 5.3 Flash est gratuit via NVIDIA Build et OpenCode Zen. "
                "GLM 4.7/4.5 Flash sont gratuits via Z.AI.\n\n"
                "Les clés sont stockées dans ~/.config/zerocode/keys.json avec les droits 600."
            ),
            title="configuration",
            title_align="left",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 1),
            expand=False,
        )
    )

    if args.show:
        _print_keys_table(console, config)
        return 0
    if not sys.stdin.isatty():
        _print_keys_table(console, config)
        console.print(
            Text("Mode non interactif: ajoute les cles via les variables d'environnement.", style="dim")
        )
        return 0

    try:
        wanted = Confirm.ask("Configurer des cles maintenant ?", default=False, console=console)
    except (EOFError, KeyboardInterrupt):
        return 0
    if not wanted:
        console.print(Text("Aucune modification. `zerocode` fonctionne deja avec Kilo.", style="dim"))
        return 0

    specs = [get_provider(args.provider)] if args.provider else [
        get_provider(name)
        for name in (
            "nvidia",
            "opencode-zen",
            "zai",
            "openrouter",
            "groq",
            "gemini",
            "together",
            "mistral",
            "sambanova",
            "kilo",
        )
    ]
    for spec in specs:
        if spec is None or not spec.api_key_envs:
            continue
        env_name = spec.api_key_envs[0]
        existing = resolve_api_key(spec, config)
        console.print()
        console.print(Text(f"{spec.label} ({spec.name})", style="bold"))
        console.print(Text(f"  inscription: {spec.signup_url}", style="dim"))
        console.print(Text(f"  variable: {env_name}", style="dim"))
        if existing:
            console.print(Text(f"  cle actuelle: {mask_key(existing)}", style="dim"))
        try:
            value = getpass.getpass("  cle (vide pour ignorer): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not value:
            continue
        store_key(spec.name, value)
        console.print(Text("  cle enregistree.", style="green"))

    console.print()
    console.print(Text(f"Cles: {keys_path()}", style="dim"))
    console.print(Text("Verification: zerocode doctor", style="dim"))
    if args.test:
        return doctor_command(["--live"], console)
    return 0


def doctor_command(args_list: list[str], console: Console) -> int:
    parser = argparse.ArgumentParser(prog="zerocode doctor")
    parser.add_argument("--live", action="store_true", help="Tester une vraie requete gratuite.")
    args = parser.parse_args(args_list)

    cwd = Path.cwd().resolve()
    config = load_config(cwd)
    providers = applied_providers(config)
    console.print(Text(f"zerocode {__version__} - diagnostic", style="bold"))
    console.print()

    python_ok = sys.version_info >= (3, 10)
    _check_line(console, python_ok, "Python", sys.version.split()[0])
    _check_line(console, default_config_path().is_file(), "Config globale", str(default_config_path()))
    project = project_config_path(cwd)
    _check_line(console, project is not None, "Config projet", str(project) if project else "absente")
    key_file = keys_path()
    if key_file.is_file():
        mode = stat.S_IMODE(key_file.stat().st_mode)
        secure = (mode & 0o077) == 0
        _check_line(console, secure, "Cles", f"{key_file} (droits {oct(mode)[-3:]})")
    else:
        _check_line(console, True, "Cles", "absentes (acces anonyme Kilo possible)")

    table = Table(
        title="Fournisseurs",
        box=box.SIMPLE,
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("Nom")
    table.add_column("Statut")
    table.add_column("Cle")
    table.add_column("Gratuits", justify="right")
    table.add_column("URL", overflow="fold")
    for name, spec in providers.items():
        key = resolve_api_key(spec, config)
        if not provider_enabled(spec, config):
            status = "desactive"
        elif provider_available(spec, config) or spec.keyless:
            status = "disponible"
        else:
            status = "sans cle"
        key_label = "anonyme" if spec.keyless and not key else mask_key(key)
        free_count = len([model for model in spec.models if model.is_free])
        table.add_row(name, status, key_label, str(free_count), spec.base_url)
    console.print(table)

    console.print(Text("Connectivite", style="bold"))
    kilo = providers.get("kilo")
    if kilo is not None:
        try:
            rows = fetch_models(kilo, config, timeout=12)
            _check_line(console, True, "Kilo Gateway", f"{len(rows)} modeles listes")
        except Exception as exc:  # noqa: BLE001 - diagnostic
            _check_line(console, False, "Kilo Gateway", f"{exc.__class__.__name__}: {exc}")
    ollama = providers.get("ollama")
    if ollama is not None and provider_enabled(ollama, config):
        try:
            with httpx.Client(timeout=5) as client:
                response = client.get(ollama.base_url.rstrip("/") + "/models")
            _check_line(console, response.status_code < 400, "Ollama", f"HTTP {response.status_code}")
        except Exception as exc:  # noqa: BLE001
            _check_line(console, False, "Ollama", str(exc))

    router = Router(config)
    try:
        chain = router.preview()
        console.print()
        console.print(Text("Chaine gratuite prevue", style="bold"))
        if chain:
            for index, item in enumerate(chain, start=1):
                console.print(Text(f"  {index}. {item}", style="dim"))
        else:
            _check_line(console, False, "Chaine", "aucun candidat disponible")
        if args.live:
            console.print()
            console.print(Text("Test live (consomme un peu de quota gratuit)", style="dim"))
            config.max_tokens = 256
            router.config = config
            chunks: list[str] = []
            callbacks = StreamCallbacks(on_text=chunks.append)
            try:
                completion = router.complete(
                    [{"role": "user", "content": "Reponds uniquement: OK"}],
                    None,
                    callbacks=callbacks,
                )
                preview = "".join(chunks).strip() or completion.reasoning.strip()
                console.print(
                    Text(
                        f"  {completion.provider}/{completion.model}: "
                        f"{preview[:120] or '(vide)'} [{completion.finish_reason}]",
                        style="green",
                    )
                )
                console.print(
                    Text(
                        f"  jetons: {completion.usage.total_tokens} "
                        f"(estimation: {'oui' if completion.usage.estimated else 'non'})",
                        style="dim",
                    )
                )
            except ZeroCodeError as exc:
                console.print(Text(f"  ERREUR: {exc}", style="red"))
    finally:
        router.close()
    return 0


def models_command(args_list: list[str], console: Console) -> int:
    parser = argparse.ArgumentParser(prog="zerocode models")
    parser.add_argument("--free", action="store_true", help="Seulement les modeles gratuits/essai/local.")
    parser.add_argument("--provider", help="Filtrer par fournisseur.")
    parser.add_argument("--search", help="Rechercher dans l'identifiant ou le libelle.")
    parser.add_argument("--live", action="store_true", help="Decouvrir les offres gratuites en direct.")
    parser.add_argument("--json", action="store_true", help="Sortie JSON.")
    args = parser.parse_args(args_list)

    config = load_config(Path.cwd())
    if args.live:
        providers = applied_providers(config)
        names = [args.provider] if args.provider else ["kilo", "openrouter", "opencode-zen"]
        unknown = [name for name in names if name not in providers]
        if unknown:
            console.print(Text(f"Fournisseur inconnu: {unknown[0]}", style="red"))
            return 1
        with console.status("Interrogation des catalogues..."):
            rows = discover_free_models(config, names)
        if args.json:
            console.print_json(json.dumps(rows, ensure_ascii=False))
            return 0
        if not rows:
            console.print(
                Text(
                    "Aucun modele gratuit detecte. Verifie le reseau et les cles, puis reessaie.",
                    style="yellow",
                )
            )
            return 0
        table = Table(
            title="Offres gratuites détectées en direct",
            box=box.SIMPLE,
            header_style="bold cyan",
        )
        table.add_column("Fournisseur")
        table.add_column("Modele", overflow="fold")
        table.add_column("Contexte", justify="right")
        for row in rows:
            table.add_row(
                str(row["provider"]),
                str(row["id"]),
                _format_context(int(row.get("context") or 0)),
            )
        console.print(table)
        console.print(Text("Les offres changent souvent; verifie les conditions du fournisseur.", style="dim"))
        return 0

    choices = all_choices()
    if args.free:
        choices = [(provider, model) for provider, model in choices if model.is_free]
    if args.provider:
        choices = [(provider, model) for provider, model in choices if provider.name == args.provider]
    if args.search:
        needle = args.search.lower()
        choices = [
            (provider, model)
            for provider, model in choices
            if needle in model.id.lower()
            or needle in model.label.lower()
            or needle in provider.name.lower()
        ]

    if args.json:
        payload = [
            {
                "provider": provider.name,
                "model": model.id,
                "label": model.label,
                "context": model.context,
                "max_output": model.max_output,
                "tier": model.tier,
                "tools": model.tools,
                "reasoning": model.reasoning,
                "notes": model.notes,
            }
            for provider, model in choices
        ]
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return 0

    if not choices:
        console.print(Text("Aucun modele ne correspond au filtre.", style="yellow"))
        return 0

    table = Table(title="Catalogue zerocode", box=box.SIMPLE, header_style="bold cyan")
    table.add_column("Modele", overflow="fold")
    table.add_column("Fournisseur")
    table.add_column("Contexte", justify="right")
    table.add_column("Type")
    table.add_column("Outils")
    table.add_column("Notes", overflow="fold")
    for provider, model in choices:
        table.add_row(
            model.id,
            provider.name,
            _format_context(model.context),
            model.tier,
            "oui" if model.tools else "non",
            model.notes[:90],
        )
    console.print(table)
    console.print(
        Text(
            "GLM 5.3 complet n'a pas d'API gratuite permanente. "
            "GLM 5.3 Flash est gratuit chez NVIDIA et OpenCode Zen. "
            "Offres verifiees le 26/10/2026.",
            style="dim",
        )
    )
    return 0


def providers_command(args_list: list[str], console: Console) -> int:
    parser = argparse.ArgumentParser(prog="zerocode providers")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(args_list)
    config = load_config(Path.cwd())
    if args.json:
        payload = []
        for name, spec in applied_providers(config).items():
            key = resolve_api_key(spec, config)
            payload.append(
                {
                    "name": name,
                    "label": spec.label,
                    "base_url": spec.base_url,
                    "key_envs": list(spec.api_key_envs),
                    "keyless": spec.keyless,
                    "enabled": provider_enabled(spec, config),
                    "available": provider_available(spec, config),
                    "key": mask_key(key),
                    "free_models": [model.id for model in spec.models if model.is_free],
                }
            )
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return 0
    print_providers_table(console, config)
    return 0


def print_providers_table(console: Console, config: Config) -> None:
    table = Table(title="Fournisseurs", box=box.SIMPLE, header_style="bold cyan")
    table.add_column("Nom")
    table.add_column("Statut")
    table.add_column("Cle")
    table.add_column("Gratuits", justify="right")
    table.add_column("URL", overflow="fold")
    for name, spec in applied_providers(config).items():
        key = resolve_api_key(spec, config)
        if not provider_enabled(spec, config):
            status = "desactive"
        elif provider_available(spec, config):
            status = "disponible"
        else:
            status = "sans cle"
        key_label = "anonyme" if spec.keyless and not key else mask_key(key)
        free_count = len([model for model in spec.models if model.is_free])
        table.add_row(name, status, key_label, str(free_count), spec.base_url)
    console.print(table)
    console.print(
        Text(
            "Sans cle, Kilo Gateway reste disponible en anonyme. "
            "`zerocode setup` pour ajouter les autres offres gratuites.",
            style="dim",
        )
    )


def print_models_table(console: Console, *, free_only: bool = True) -> None:
    table = Table(
        title="Modèles" + (" gratuits" if free_only else ""),
        box=box.SIMPLE,
        header_style="bold cyan",
    )
    table.add_column("Modele", overflow="fold")
    table.add_column("Fournisseur")
    table.add_column("Type")
    table.add_column("Contexte", justify="right")
    table.add_column("Notes", overflow="fold")
    for provider, model in all_choices():
        if free_only and not model.is_free:
            continue
        table.add_row(
            model.id,
            provider.name,
            model.tier,
            _format_context(model.context),
            model.notes[:80],
        )
    console.print(table)


def print_sessions_table(console: Console, store: SessionStore) -> None:
    items = store.list()
    if not items:
        console.print(Text("Aucune session enregistree.", style="dim"))
        return
    table = Table(title="Sessions", box=box.SIMPLE, header_style="bold cyan")
    table.add_column("ID")
    table.add_column("Mise a jour")
    table.add_column("Modele")
    table.add_column("Messages", justify="right")
    table.add_column("Jetons", justify="right")
    table.add_column("cwd", overflow="fold")
    for item in items[:50]:
        table.add_row(
            item["id"],
            _format_timestamp(item["updated_at"]),
            item["model"],
            str(item["messages"]),
            str(item["total_tokens"]),
            item["cwd"],
        )
    console.print(table)
    console.print(Text(f"Dossier: {store.root}", style="dim"))


def sessions_command(args_list: list[str], console: Console) -> int:
    parser = argparse.ArgumentParser(prog="zerocode sessions")
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--delete", metavar="ID")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(args_list)
    store = SessionStore()

    if args.delete:
        if store.delete(args.delete):
            console.print(Text(f"Session supprimee: {args.delete}", style="green"))
            return 0
        console.print(Text(f"Session introuvable: {args.delete}", style="red"))
        return 1

    if args.clear:
        if not args.yes:
            if not sys.stdin.isatty():
                console.print(Text("Ajoute --yes pour confirmer la suppression.", style="yellow"))
                return 1
            try:
                if not Confirm.ask("Supprimer toutes les sessions ?", default=False, console=console):
                    return 0
            except (EOFError, KeyboardInterrupt):
                return 0
        removed = store.clear()
        console.print(Text(f"{removed} session(s) supprimee(s).", style="green"))
        return 0

    if args.json:
        console.print_json(json.dumps(store.list(), ensure_ascii=False))
        return 0
    print_sessions_table(console, store)
    return 0


def config_command(args_list: list[str], console: Console) -> int:
    parser = argparse.ArgumentParser(prog="zerocode config")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--path", action="store_true")
    args = parser.parse_args(args_list)

    cwd = Path.cwd().resolve()
    if args.path:
        console.print(Text(f"globale: {default_config_path()}"))
        project = project_config_path(cwd)
        console.print(Text(f"projet:  {project if project else '(aucune)'}"))
        console.print(Text(f"cles:    {keys_path()}"))
        return 0

    config = load_config(cwd)
    if args.init:
        path = save_config(config)
        console.print(Text(f"Configuration ecrite: {path}", style="green"))
        return 0

    payload = config.public_dict()
    payload["_sources"] = config.sources
    payload["_config_path"] = str(default_config_path())
    payload["_keys_path"] = str(keys_path())
    console.print_json(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _check_line(console: Console, ok: bool, label: str, detail: str) -> None:
    mark = "OK" if ok else "!!"
    style = "green" if ok else "yellow"
    console.print(Text(f"[{mark}] {label:<16} {detail}", style=style))


def _print_keys_table(console: Console, config: Config) -> None:
    table = Table(title="Clés configurées", box=box.SIMPLE, header_style="bold cyan")
    table.add_column("Fournisseur")
    table.add_column("Variable")
    table.add_column("Etat")
    for name, spec in PROVIDERS.items():
        if not spec.api_key_envs:
            continue
        key = resolve_api_key(spec, config)
        if key:
            source = "env" if any(os.environ.get(env) for env in spec.api_key_envs) else "fichier"
            state = f"{mask_key(key)} ({source})"
        else:
            state = "absente"
        table.add_row(name, ", ".join(spec.api_key_envs), state)
    console.print(table)
    console.print(Text(f"Fichier de cles: {keys_path()}", style="dim"))


def _format_context(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    if value >= 1_000:
        return f"{value // 1_000}k"
    return str(value)


def _format_timestamp(value: str) -> str:
    return value.replace("T", " ").replace("+00:00", "").strip()


def _init_project_file(context: ToolContext, console: Console) -> None:
    path = context.cwd / "ZEROCODE.md"
    if path.exists():
        console.print(Text(f"{path} existe deja.", style="yellow"))
        return
    template = """# ZEROCODE.md

## Contexte
Decris ici le projet en quelques lignes.

## Commandes
- Tests:
- Lint:
- Build:

## Conventions
- Style de code:
- Architecture:
- Points a ne pas modifier:

## Securite
- Ne jamais lire ni afficher de secrets.
"""
    path.write_text(template, encoding="utf-8")
    console.print(Text(f"Cree: {path}", style="green"))


if __name__ == "__main__":
    raise SystemExit(main())

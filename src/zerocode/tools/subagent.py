from __future__ import annotations

from typing import Any

from ..errors import ToolError
from .base import Tool, ToolContext, ToolRegistry

SPECIALIST_ROLES = (
    "explorer",
    "architect",
    "reviewer",
    "security",
    "performance",
    "tester",
    "researcher",
)

ROLE_DESCRIPTIONS = {
    "explorer": "Explore the codebase and report how the relevant parts work.",
    "architect": "Analyze architecture and propose a practical implementation design.",
    "reviewer": "Review code for bugs, regressions, edge cases and maintainability.",
    "security": "Review trust boundaries, injection risks, secrets, auth and permissions.",
    "performance": "Find measurable bottlenecks and propose low-risk optimizations.",
    "tester": "Design and inspect tests, coverage gaps and verification strategy.",
    "researcher": "Research external technical documentation and compare viable approaches.",
}

ROLE_PROMPTS = {
    "explorer": "Cartographie le code concerné, les dépendances et les flux d'exécution.",
    "architect": "Raisonne comme un architecte logiciel senior. Compare les options, explicite les compromis et propose les changements minimaux cohérents.",
    "reviewer": "Agis comme un reviewer exigeant. Cherche les erreurs de logique, cas limites, régressions, API incohérentes et tests manquants. Priorise par gravité.",
    "security": "Agis comme un ingénieur AppSec. Examine les frontières de confiance, autorisations, injection, secrets, SSRF, traversée de chemins, désérialisation et dépendances. Ne suppose jamais qu'un motif statique prouve une vulnérabilité.",
    "performance": "Agis comme un ingénieur performance. Identifie les coûts réels probables, allocations, I/O, concurrence et goulots d'étranglement. Évite les optimisations spéculatives.",
    "tester": "Agis comme un ingénieur QA. Repère les parcours critiques, tests absents, cas limites, stratégies de régression et commandes de validation.",
    "researcher": "Agis comme un chercheur technique. Utilise la recherche web et les sources officielles lorsque possible. Distingue les faits vérifiés des hypothèses et cite les liens utiles.",
}


def run_subagent_tool(args: dict[str, Any], ctx: ToolContext) -> str:
    task = str(args.get("task", "")).strip()
    role = str(args.get("role", "explorer")).strip().lower()
    if not task:
        raise ToolError("La description de la tâche (task) ne peut pas être vide.")
    if role not in SPECIALIST_ROLES:
        raise ToolError("Rôle de sous-agent inconnu.")
    runner = ctx.run_subagent
    if runner is None:
        raise ToolError("Le sous-agent n'est pas disponible dans ce contexte.")
    return runner(task, role)


def register_subagent_tools(registry: ToolRegistry) -> None:
    role_options = ", ".join(f"{role}: {ROLE_DESCRIPTIONS[role]}" for role in SPECIALIST_ROLES)
    registry.register(
        Tool(
            name="subagent",
            description=(
                "Delegate a focused read-only task to an isolated specialist agent. "
                "Available roles: " + role_options + ". "
                "Use separate specialist calls for independent reviews; the main agent remains responsible for edits."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Clear, focused task with files or questions to investigate.",
                    },
                    "role": {
                        "type": "string",
                        "enum": list(SPECIALIST_ROLES),
                        "description": "Specialist profile. Defaults to explorer.",
                    },
                },
                "required": ["task"],
            },
            handler=run_subagent_tool,
            approval="never",
        )
    )


def roles_catalog() -> list[dict[str, str]]:
    """Liste publique des profils de sous-agents, pour l'interface desktop."""
    return [{"id": role, "description": ROLE_DESCRIPTIONS[role]} for role in SPECIALIST_ROLES]

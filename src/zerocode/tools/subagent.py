from __future__ import annotations

from typing import Any

from ..errors import ToolError
from .base import Tool, ToolContext, ToolRegistry


def run_subagent_tool(args: dict[str, Any], ctx: ToolContext) -> str:
    task = str(args.get("task", "")).strip()
    if not task:
        raise ToolError("La description de la tache (task) ne peut pas etre vide.")
    runner = ctx.run_subagent
    if runner is None:
        raise ToolError("Le sous-agent d'exploration n'est pas disponible dans ce contexte.")
    return runner(task)


def register_subagent_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="subagent",
            description=(
                "Delegate a focused read-only codebase exploration, search, or analysis task "
                "to an isolated subagent. Returns a concise synthesis without cluttering the "
                "main conversation context."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Clear, specific exploration or verification task to perform.",
                    },
                },
                "required": ["task"],
            },
            handler=run_subagent_tool,
            approval="never",
        )
    )

from __future__ import annotations

from typing import Any

from ..errors import ToolError
from .base import Tool, ToolContext, ToolRegistry

VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
MARKERS = {
    "pending": "[ ]",
    "in_progress": "[~]",
    "completed": "[x]",
    "cancelled": "[-]",
}


def todo_write(args: dict[str, Any], ctx: ToolContext) -> str:
    raw_todos = args.get("todos")
    if not isinstance(raw_todos, list):
        raise ToolError("todos doit etre une liste.")
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(raw_todos, start=1):
        if not isinstance(item, dict):
            raise ToolError(f"todos[{index}] doit etre un objet.")
        content = str(item.get("content", "")).strip()
        status = str(item.get("status", "pending")).strip()
        if not content:
            raise ToolError(f"todos[{index}].content est vide.")
        if status not in VALID_STATUSES:
            raise ToolError(
                f"todos[{index}].status invalide: {status}. "
                f"Valeurs: {', '.join(sorted(VALID_STATUSES))}."
            )
        normalized.append({"content": content, "status": status})
    ctx.todos[:] = normalized
    if not normalized:
        return "Liste de taches vide."
    lines = [f"{MARKERS[item['status']]} {item['content']}" for item in normalized]
    return "Plan de travail:\n" + "\n".join(lines)


def register_todo_tools(registry: ToolRegistry) -> None:
    registry.register(
        Tool(
            name="todo_write",
            description=(
                "Create or update the task plan for the current session. "
                "Use it for multi-step work and keep exactly one task in_progress when possible."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "Full task list. It replaces the previous list.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": sorted(VALID_STATUSES),
                                },
                            },
                            "required": ["content", "status"],
                        },
                    }
                },
                "required": ["todos"],
            },
            handler=todo_write,
            approval="never",
        )
    )

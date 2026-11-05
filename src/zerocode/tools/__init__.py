from __future__ import annotations

from typing import Any

from .base import PermissionManager, Tool, ToolContext, ToolRegistry
from .diagnostics import register_diagnostic_tools
from .files import register_file_tools
from .search import register_search_tools
from .shell import register_shell_tools
from .subagent import register_subagent_tools
from .todo import register_todo_tools
from .web import register_web_tools

__all__ = [
    "PermissionManager",
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "build_registry",
]


def build_registry(
    context: ToolContext,
    permissions: PermissionManager,
    ui: Any | None = None,
    *,
    include_subagent: bool = True,
) -> ToolRegistry:
    registry = ToolRegistry(context, permissions, ui)
    register_file_tools(registry)
    register_search_tools(registry)
    register_diagnostic_tools(registry)
    register_shell_tools(registry)
    register_todo_tools(registry)
    register_web_tools(registry)
    if include_subagent:
        register_subagent_tools(registry)
    return registry

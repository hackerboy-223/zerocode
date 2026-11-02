from __future__ import annotations

import sys

import pytest

from zerocode.mcp import register_mcp_tools
from zerocode.tools import PermissionManager, ToolContext, build_registry
from zerocode.types import ToolCall

SERVER = '''
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    method = message["method"]
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {}}
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo text",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                }
            ]
        }
    elif method == "tools/call":
        result = {
            "content": [
                {"type": "text", "text": message["params"]["arguments"]["text"]}
            ]
        }
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
'''


@pytest.mark.parametrize("timeout", [True, float("inf"), float("nan"), 3_601])
def test_mcp_non_finite_or_excessive_timeout_is_skipped(tmp_path, timeout):
    context = ToolContext(cwd=tmp_path)
    permissions = PermissionManager(mode="allow", interactive=False)
    registry = build_registry(context, permissions)
    manager = register_mcp_tools(
        registry,
        {"demo": {"command": sys.executable, "timeout": timeout}},
        cwd=tmp_path,
    )
    try:
        assert manager.clients == []
        assert not any(name.startswith("mcp_") for name in registry.names())
    finally:
        manager.close()


def test_mcp_invalid_timeout_is_skipped(tmp_path):
    context = ToolContext(cwd=tmp_path)
    permissions = PermissionManager(mode="allow", interactive=False)
    registry = build_registry(context, permissions)
    manager = register_mcp_tools(
        registry,
        {"demo": {"command": sys.executable, "timeout": "soon"}},
        cwd=tmp_path,
    )
    try:
        assert manager.clients == []
        assert not any(name.startswith("mcp_") for name in registry.names())
    finally:
        manager.close()


def test_mcp_stdio_tool_roundtrip(tmp_path):
    server = tmp_path / "server.py"
    server.write_text(SERVER, encoding="utf-8")
    context = ToolContext(cwd=tmp_path)
    permissions = PermissionManager(mode="allow", interactive=False)
    registry = build_registry(context, permissions)
    manager = register_mcp_tools(
        registry,
        {"demo": {"command": sys.executable, "args": [str(server)]}},
        cwd=tmp_path,
    )
    try:
        assert "mcp_demo_echo" in registry.names()
        result = registry.execute(
            ToolCall(id="call-1", name="mcp_demo_echo", arguments={"text": "bonjour"})
        )
        assert result == "bonjour"
    finally:
        manager.close()

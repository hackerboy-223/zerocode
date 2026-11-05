from __future__ import annotations

from pathlib import Path

import pytest

from zerocode.agent import Agent
from zerocode.config import Config
from zerocode.session import SessionStore
from zerocode.tools import PermissionManager, ToolContext, build_registry
from zerocode.types import Completion, ToolCall, Usage
from zerocode.ui import NullUI


class FakeRouter:
    def __init__(self, completions):
        self.completions = list(completions)
        self.last = None
        self.calls = 0
        self.messages = None
        self.needs_vision = None

    def complete(
        self,
        messages,
        tools,
        *,
        model=None,
        provider=None,
        callbacks=None,
        needs_vision=False,
    ):
        self.calls += 1
        self.messages = [dict(message) for message in messages]
        self.needs_vision = needs_vision
        completion = self.completions.pop(0)
        if completion.content and callbacks and callbacks.on_text:
            callbacks.on_text(completion.content)
        self.last = completion
        return completion

    def context_window(self, model=None):
        return 200_000


def build_agent(tmp_path, completions):
    config = Config(model="auto", max_steps=5)
    context = ToolContext(cwd=tmp_path)
    permissions = PermissionManager(mode="allow", interactive=False)
    registry = build_registry(context, permissions, NullUI())
    store = SessionStore(tmp_path / "sessions")
    session = store.new(tmp_path, "auto")
    router = FakeRouter(completions)
    agent = Agent(config, router, registry, session, NullUI(), store=store)
    return agent, router, store, context


def test_agent_executes_tool_then_finishes(tmp_path):
    first = Completion(
        content="",
        tool_calls=[
            ToolCall(
                id="call-1",
                name="todo_write",
                arguments={
                    "todos": [{"content": "verifier", "status": "in_progress"}]
                },
            )
        ],
        finish_reason="tool_calls",
        provider="kilo",
        model="kilo-auto/free",
        usage=Usage(prompt_tokens=5, completion_tokens=3, total_tokens=8, requests=1),
    )
    second = Completion(
        content="Termine.",
        finish_reason="stop",
        provider="kilo",
        model="kilo-auto/free",
        usage=Usage(prompt_tokens=7, completion_tokens=2, total_tokens=9, requests=1),
    )
    agent, router, store, context = build_agent(tmp_path, [first, second])

    result = agent.run_turn("fais le travail")

    assert result == "Termine."
    assert router.calls == 2
    assert context.todos == [{"content": "verifier", "status": "in_progress"}]
    assert agent.usage.total_tokens == 17
    assert agent.usage.requests == 2
    assert any(message.get("role") == "tool" for message in agent.messages)
    assert agent.session.todos == context.todos
    assert store.path_for(agent.session).is_file()


class InterruptingUI(NullUI):
    def interrupted(self) -> bool:
        return True


def test_agent_stops_when_ui_requests_interruption(tmp_path):
    completion = Completion(content="Bonjour.", finish_reason="stop")
    agent, router, _, _ = build_agent(tmp_path, [completion])
    agent.ui = InterruptingUI()

    with pytest.raises(KeyboardInterrupt):
        agent.run_turn("salut")

    assert router.calls == 0


def test_agent_stops_without_tool_calls(tmp_path):
    completion = Completion(content="Bonjour.", finish_reason="stop")
    agent, router, _, _ = build_agent(tmp_path, [completion])
    assert agent.run_turn("salut") == "Bonjour."
    assert router.calls == 1
    assert agent.messages[-1]["content"] == "Bonjour."


def test_agent_rejects_empty_prompt(tmp_path):
    agent, router, _, _ = build_agent(tmp_path, [])
    assert agent.run_turn("   ") == ""
    assert router.calls == 0


def test_agent_reset_keeps_only_system(tmp_path):
    agent, _, _, context = build_agent(tmp_path, [Completion(content="ok")])
    agent.run_turn("salut")
    agent.tools.execute(
        ToolCall(
            id="call-1",
            name="todo_write",
            arguments={"todos": [{"content": "x", "status": "pending"}]},
        )
    )
    agent.reset()
    assert len(agent.messages) == 1
    assert agent.messages[0]["role"] == "system"
    assert agent.usage.total_tokens == 0
    assert context.todos == []


def test_agent_load_session_restores_state(tmp_path):
    agent, _, store, context = build_agent(tmp_path, [])
    other = store.new(tmp_path / "other", "glm-5.3-flash", "nvidia")
    other.messages = [
        {"role": "system", "content": "custom"},
        {"role": "user", "content": "ancien"},
    ]
    other.todos = [{"content": "reste", "status": "pending"}]
    store.save(other)

    agent.load_session(other)

    assert agent.config.model == "glm-5.3-flash"
    assert agent.config.provider == "nvidia"
    assert agent.messages[1]["content"] == "ancien"
    assert context.todos == [{"content": "reste", "status": "pending"}]
    assert context.cwd == Path(other.cwd)


def test_agent_plan_mode_is_read_only(tmp_path):
    agent, _, _, _ = build_agent(tmp_path, [])
    agent.set_mode("plan")
    names = [schema["function"]["name"] for schema in agent.tools.schemas()]
    assert "read" in names
    assert "list" in names
    assert "write" not in names
    assert "edit" not in names
    assert "bash" not in names
    assert "MODE PLAN ACTIF" in agent.messages[0]["content"]

    result = agent.tools.execute(
        ToolCall(
            id="call-plan",
            name="write",
            arguments={"path": "x.txt", "content": "interdit"},
        )
    )
    assert "mode plan" in result
    assert not (tmp_path / "x.txt").exists()

    agent.set_mode("build")
    names = [schema["function"]["name"] for schema in agent.tools.schemas()]
    assert "write" in names
    assert "MODE PLAN ACTIF" not in agent.messages[0]["content"]


def test_agent_full_stack_mode_applies_and_restores_preset(tmp_path):
    agent, _, _, _ = build_agent(tmp_path, [])
    config = agent.config
    config.reasoning_effort = "low"
    config.temperature = 0.8
    config.max_tokens = 4_096
    config.max_steps = 7
    config.permissions = "ask"
    config.command_timeout = 45
    config.compact_threshold = 0.5
    config.show_reasoning = False
    agent.tools.permissions.mode = "ask"

    agent.set_mode("full-stack")

    assert agent.mode == "full-stack"
    assert config.reasoning_effort == "max"
    assert config.temperature == 0.2
    assert config.max_tokens == 128_000
    assert config.max_steps == 500
    assert config.permissions == "allow"
    assert config.command_timeout == 3_600
    assert config.compact_threshold == 0.95
    assert config.show_reasoning is True
    assert agent.tools.permissions.mode == "allow"
    assert agent.tools.context.command_timeout == 3_600
    assert agent.tools.read_only is False
    assert "MODE FULL-STACK AUTONOME ACTIF" in agent.messages[0]["content"]
    names = [schema["function"]["name"] for schema in agent.tools.schemas()]
    assert "write" in names
    assert "bash" in names

    agent.set_mode("build")

    assert agent.mode == "build"
    assert config.reasoning_effort == "low"
    assert config.temperature == 0.8
    assert config.max_tokens == 4_096
    assert config.max_steps == 7
    assert config.permissions == "ask"
    assert config.command_timeout == 45
    assert config.compact_threshold == 0.5
    assert config.show_reasoning is False
    assert agent.tools.permissions.mode == "ask"
    assert agent.tools.context.command_timeout == 45
    assert "MODE FULL-STACK AUTONOME ACTIF" not in agent.messages[0]["content"]


def test_agent_think_modes_update_system_prompt_and_visibility(tmp_path):
    agent, _, _, _ = build_agent(tmp_path, [])
    assert agent.config.show_reasoning is False
    assert "MODE THINK" not in agent.messages[0]["content"]

    for level in ("low", "high", "max"):
        agent.set_think(level)
        assert agent.config.show_reasoning is True
        assert agent.config.reasoning_effort == level
        assert f"MODE THINK ({level.upper()}) ACTIF" in agent.messages[0]["content"]
        assert "<think>" in agent.messages[0]["content"]

    agent.set_think("off")
    assert agent.config.show_reasoning is False
    assert "MODE THINK" not in agent.messages[0]["content"]



def test_agent_compacts_long_context(tmp_path):
    completion = Completion(content="ok")
    agent, _, _, _ = build_agent(tmp_path, [completion])
    agent.router.context_window = lambda model=None: 32_000
    for index in range(12):
        agent.messages.append({"role": "user", "content": f"question {index} " + ("x" * 3_000)})
        agent.messages.append({"role": "assistant", "content": "reponse " + ("y" * 3_000)})
    before = len(agent.messages)
    agent.compact(force=True)
    assert len(agent.messages) < before
    assert "Contexte anterieur" in agent.messages[0]["content"]


def test_agent_sends_images_as_multimodal_content(tmp_path):
    completion = Completion(content="vu", finish_reason="stop")
    agent, router, _, _ = build_agent(tmp_path, [completion])

    result = agent.run_turn("analyse", images=["data:image/png;base64,AAAA"])

    assert result == "vu"
    assert router.needs_vision is True
    user = [message for message in router.messages if message["role"] == "user"][-1]
    assert user["content"][0] == {"type": "text", "text": "analyse"}
    assert user["content"][1]["type"] == "image_url"


def test_agent_repairs_truncated_tool_calls(tmp_path):
    truncated = Completion(
        content="",
        tool_calls=[ToolCall(id="call-1", name="read", arguments={"path": "missing.txt"})],
        finish_reason="length",
    )
    agent, _, _, _ = build_agent(tmp_path, [truncated])

    assert agent.run_turn("lis le fichier") == ""
    tool_messages = [message for message in agent.messages if message["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call-1"
    assert "interrompu avant execution" in tool_messages[0]["content"]

def test_mode_switch_preserves_compacted_context(tmp_path):
    agent, _, _, _ = build_agent(tmp_path, [])
    summary = (
        "## Contexte anterieur (resume automatique)\n"
        "- Utilisateur: Keep the existing authentication contract."
    )
    agent.messages[0]["content"] += "\n\n" + summary

    agent.set_mode("plan")
    assert "Keep the existing authentication contract" in agent.messages[0]["content"]
    assert "MODE PLAN ACTIF" in agent.messages[0]["content"]

    agent.set_mode("build")
    assert "Keep the existing authentication contract" in agent.messages[0]["content"]
    assert "MODE PLAN ACTIF" not in agent.messages[0]["content"]
    assert agent.messages[0]["content"].count(
        "## Contexte anterieur (resume automatique)"
    ) == 1

def test_agent_stops_after_repeated_identical_tool_failure(tmp_path):
    failed_call = ToolCall(
        id="call-failed",
        name="read",
        arguments={"path": "missing.txt"},
    )
    first = Completion(
        content="",
        tool_calls=[failed_call],
        finish_reason="tool_calls",
    )
    second = Completion(
        content="",
        tool_calls=[
            ToolCall(
                id="call-failed-again",
                name="read",
                arguments={"path": "missing.txt"},
            )
        ],
        finish_reason="tool_calls",
    )
    unreachable = Completion(content="Cela ne doit pas être appelé.")

    agent, router, _, _ = build_agent(tmp_path, [first, second, unreachable])

    result = agent.run_turn("lis le fichier absent")

    assert "arrêté la boucle" in result
    assert router.calls == 2
    tool_results = [message for message in agent.messages if message.get("role") == "tool"]
    assert len(tool_results) == 2
    assert all(message["content"].startswith("ERREUR:") for message in tool_results)


def test_full_stack_agent_auto_continues_when_todos_remain(tmp_path):
    first = Completion(
        content="Plan cree.",
        tool_calls=[
            ToolCall(
                id="call-todo-1",
                name="todo_write",
                arguments={
                    "todos": [
                        {"content": "Creer module", "status": "in_progress"},
                    ]
                },
            )
        ],
        finish_reason="tool_calls",
    )
    second = Completion(
        content="Module en cours...",
        finish_reason="stop",
    )
    third = Completion(
        content="",
        tool_calls=[
            ToolCall(
                id="call-todo-2",
                name="todo_write",
                arguments={
                    "todos": [
                        {"content": "Creer module", "status": "completed"},
                    ]
                },
            )
        ],
        finish_reason="tool_calls",
    )
    fourth = Completion(
        content="Tout est termine et verifie.",
        finish_reason="stop",
    )
    agent, router, _, _ = build_agent(tmp_path, [first, second, third, fourth])
    agent.set_mode("full-stack")
    result = agent.run_turn("construis le module")
    assert result == "Tout est termine et verifie."
    assert router.calls == 4


def test_agent_executes_read_only_tools_in_parallel_and_supports_subagent(tmp_path):
    (tmp_path / "a.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta\n", encoding="utf-8")

    first = Completion(
        content="",
        tool_calls=[
            ToolCall(id="call-a", name="read", arguments={"path": "a.txt"}),
            ToolCall(id="call-b", name="read", arguments={"path": "b.txt"}),
        ],
        finish_reason="tool_calls",
    )
    second = Completion(
        content="",
        tool_calls=[
            ToolCall(
                id="call-sub",
                name="subagent",
                arguments={"task": "Synthetise le contenu de a.txt et b.txt"},
            ),
        ],
        finish_reason="tool_calls",
    )
    sub_completion = Completion(
        content="Synthese sous-agent: alpha + beta.",
        finish_reason="stop",
    )
    final = Completion(
        content="Termine avec synthese.",
        finish_reason="stop",
    )
    agent, router, _, _ = build_agent(
        tmp_path, [first, second, sub_completion, final]
    )
    result = agent.run_turn("analyse a.txt et b.txt")
    assert result == "Termine avec synthese."
    assert router.calls == 4
    tool_outputs = [
        msg["content"] for msg in agent.messages if msg.get("role") == "tool"
    ]
    assert any("alpha" in out for out in tool_outputs)
    assert any("beta" in out for out in tool_outputs)
    assert any("Synthese sous-agent: alpha + beta." in out for out in tool_outputs)


def test_agent_expands_at_file_mentions_and_remember_instruction(tmp_path):
    from zerocode.prompts import load_project_instructions, remember_project_instruction

    (tmp_path / "module.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=123\n", encoding="utf-8")

    completion = Completion(content="Vu module.py", finish_reason="stop")
    agent, router, _, _ = build_agent(tmp_path, [completion])

    result = agent.run_turn("Explique @module.py et ignore @.env")
    assert result == "Vu module.py"
    user_msg = [m for m in router.messages if m["role"] == "user"][-1]["content"]
    assert "<referenced-files>" in user_msg
    assert "def hello():" in user_msg
    assert "SECRET=123" not in user_msg
    assert agent.last_assistant_text() == "Vu module.py"

    saved_path = remember_project_instruction(tmp_path, "Toujours utiliser pytest -q")
    assert saved_path.is_file()
    assert "Toujours utiliser pytest -q" in load_project_instructions(tmp_path)


def test_agent_skills_builtin_and_custom_discovery(tmp_path):
    custom_dir = tmp_path / ".zerocode" / "skills"
    custom_dir.mkdir(parents=True)
    (custom_dir / "reseau-pro.md").write_text(
        "# Diagnostic BGP & VLAN\nVerifier systématiquement les tables de routage et MTU.\n",
        encoding="utf-8",
    )

    agent, _, _, _ = build_agent(tmp_path, [])
    # Default active skills include ultra-dev, cyber-sec, sys-tech
    assert "COMPETENCE ULTRA-DEV" in agent.messages[0]["content"]
    assert "COMPETENCE EXPERT CYBERSECURITE" in agent.messages[0]["content"]
    assert "COMPETENCE TECHNICIEN SYSTEME" in agent.messages[0]["content"]

    ok, msg = agent.toggle_skill("reseau-pro")
    assert ok is True
    assert "reseau-pro" in msg
    assert "COMPETENCE PERSONNALISEE (reseau-pro)" in agent.messages[0]["content"]
    assert "tables de routage et MTU" in agent.messages[0]["content"]

    ok_all, _ = agent.toggle_skill("all")
    assert ok_all is True
    assert "COMPETENCE DURCISSEMENT & REMEDIATION SECURITE" in agent.messages[0]["content"]

    ok_off, _ = agent.toggle_skill("off")
    assert ok_off is True
    assert agent.skills == []
    assert "COMPETENCE ULTRA-DEV" not in agent.messages[0]["content"]






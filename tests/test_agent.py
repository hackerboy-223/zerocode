from __future__ import annotations

from pathlib import Path

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

    def complete(self, messages, tools, *, model=None, provider=None, callbacks=None):
        self.calls += 1
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

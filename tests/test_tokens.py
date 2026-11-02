from __future__ import annotations

from zerocode.tokens import (
    compact_messages,
    estimate_messages,
    estimate_tokens,
    truncate_text,
)


def test_estimate_tokens_is_monotonic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") >= 1
    assert estimate_tokens("a" * 100) > estimate_tokens("a" * 10)


def test_truncate_keeps_head_and_tail():
    text = "start-" + ("x" * 200) + "-end"
    result = truncate_text(text, 80)
    assert result.startswith("start-")
    assert result.endswith("-end")
    assert "tronque" in result
    assert len(result) <= 80


def test_compact_messages_keeps_system_and_removes_orphan_tools():
    messages = [{"role": "system", "content": "system prompt"}]
    for index in range(12):
        messages.append({"role": "user", "content": f"question {index} " + ("x" * 200)})
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call-{index}",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    }
                ],
            }
        )
        messages.append({"role": "tool", "tool_call_id": f"call-{index}", "content": "ok"})

    result = compact_messages(messages, 400, keep_last=4, force=True)

    assert result[0]["role"] == "system"
    assert "Contexte anterieur" in result[0]["content"]
    assert estimate_messages(result) <= 400
    assert result[1]["role"] != "tool"
    tool_ids = {
        call["id"]
        for message in result
        if message.get("role") == "assistant"
        for call in message.get("tool_calls") or []
    }
    for message in result:
        if message.get("role") == "tool":
            assert message["tool_call_id"] in tool_ids


def test_compact_without_system_preserves_tail():
    messages = [
        {"role": "user", "content": "old " + ("a" * 300)},
        {"role": "assistant", "content": "old answer " + ("b" * 300)},
        {"role": "user", "content": "recent"},
    ]
    result = compact_messages(messages, 120, keep_last=2, force=True)
    assert result[0]["role"] == "system"
    assert any("recent" in str(message.get("content")) for message in result)

def test_compaction_preserves_tool_arguments_and_useful_results():
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "Inspect the authentication flow"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-auth",
                    "type": "function",
                    "function": {
                        "name": "read",
                        "arguments": '{"path":"src/auth/session.py"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-auth",
            "content": "Found refresh_token validation in SessionManager.",
        },
    ]
    for index in range(8):
        messages.extend([
            {"role": "user", "content": f"Follow-up {index} " + ("x" * 250)},
            {"role": "assistant", "content": f"Analysis {index} " + ("y" * 250)},
        ])

    result = compact_messages(messages, 900, keep_last=4, force=True)
    summary = result[0]["content"]

    assert "src/auth/session.py" in summary
    assert "SessionManager" in summary

def test_repeated_compaction_keeps_one_bounded_rolling_summary():
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "Initial objective: preserve the login flow. " + ("a" * 900)},
        {"role": "assistant", "content": "Decision: keep the existing session contract. " + ("b" * 900)},
        {"role": "user", "content": "Intermediate notes " + ("c" * 900)},
        {"role": "assistant", "content": "Intermediate response " + ("d" * 900)},
        {"role": "user", "content": "Current question"},
        {"role": "assistant", "content": "Current answer"},
    ]
    first = compact_messages(messages, 1_000, keep_last=2, force=True)
    first.extend([
        {"role": "user", "content": "New implementation detail: refresh tokens are rotated."},
        {"role": "assistant", "content": "The rotation path is now verified."},
        {"role": "user", "content": "Continue the task"},
        {"role": "assistant", "content": "Ready."},
    ])

    second = compact_messages(first, 1_000, keep_last=2, force=True)
    system = second[0]["content"]

    assert system.count("## Contexte anterieur (resume automatique)") == 1
    assert "Initial objective" in system
    assert "New implementation detail" in system
    assert len(system) < 20_000


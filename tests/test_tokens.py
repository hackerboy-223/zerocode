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

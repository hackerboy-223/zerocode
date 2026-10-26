from __future__ import annotations

from typing import Any

from .types import Completion, Usage


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 3.5) + 1)


def _content_tokens(content: Any) -> int:
    if isinstance(content, str):
        return estimate_tokens(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, str):
                total += estimate_tokens(part)
            elif isinstance(part, dict):
                total += estimate_tokens(str(part.get("text", "")))
        return total
    return 0


def estimate_message_tokens(message: dict[str, Any]) -> int:
    total = 4
    total += _content_tokens(message.get("content"))
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        total += estimate_tokens(str(function.get("name", "")))
        total += estimate_tokens(str(function.get("arguments", "")))
    return total


def estimate_messages(messages: list[dict[str, Any]]) -> int:
    return 8 + sum(estimate_message_tokens(message) for message in messages)


def truncate_text(text: str, max_chars: int, *, head_ratio: float = 0.68) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    marker = f"\n\n[... tronque: {len(text)} caracteres au total ...]\n\n"
    budget = max(0, max_chars - len(marker))
    head = int(budget * head_ratio)
    tail = budget - head
    return text[:head] + marker + (text[-tail:] if tail else "")


def _summarize(messages: list[dict[str, Any]], max_chars: int) -> str:
    lines: list[str] = []
    for message in messages:
        role = message.get("role", "")
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        text = " ".join(text.split())
        if role == "user" and text:
            lines.append(f"- Utilisateur: {text[:280]}")
        elif role == "assistant" and text:
            lines.append(f"- Assistant: {text[:280]}")
        elif role == "assistant" and message.get("tool_calls"):
            names = [
                str((call.get("function") or {}).get("name", "?"))
                for call in message.get("tool_calls") or []
            ]
            lines.append(f"- Outils demandes: {', '.join(names)}")
        elif role == "tool" and text:
            lines.append(f"- Resultat d'outil: {text[:180]}")
    if not lines:
        return ""
    summary = "\n".join(lines)
    return truncate_text(summary, max_chars, head_ratio=0.55)


def _drop_orphan_tools(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known_ids: set[str] = set()
    result: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                call_id = call.get("id")
                if call_id:
                    known_ids.add(str(call_id))
            result.append(message)
        elif role == "tool":
            if str(message.get("tool_call_id")) in known_ids:
                result.append(message)
        else:
            result.append(message)
    while result and result[0].get("role") == "tool":
        result.pop(0)
    if result and result[0].get("role") == "assistant" and result[0].get("tool_calls"):
        removed_ids = {
            str(call.get("id"))
            for call in result[0].get("tool_calls") or []
            if call.get("id")
        }
        result.pop(0)
        if removed_ids:
            result = [
                message
                for message in result
                if not (
                    message.get("role") == "tool"
                    and str(message.get("tool_call_id")) in removed_ids
                )
            ]
        while result and result[0].get("role") == "tool":
            result.pop(0)
    return result


def _shrink_contents(messages: list[dict[str, Any]], limit: int = 12_000) -> None:
    for message in messages:
        content = message.get("content")
        if isinstance(content, str) and len(content) > limit:
            message["content"] = truncate_text(content, limit)


def compact_messages(
    messages: list[dict[str, Any]],
    max_tokens: int,
    *,
    keep_last: int = 8,
    force: bool = False,
) -> list[dict[str, Any]]:
    if not messages:
        return []
    if not force and estimate_messages(messages) <= max_tokens:
        return messages

    has_system = messages[0].get("role") == "system"
    system = dict(messages[0]) if has_system else {"role": "system", "content": ""}
    body = messages[1:] if has_system else list(messages)

    keep_last = max(2, min(keep_last, len(body)))
    start = max(0, len(body) - keep_last)
    while start < len(body) and body[start].get("role") == "tool":
        start += 1
    if (
        start < len(body)
        and body[start].get("role") == "assistant"
        and body[start].get("tool_calls")
        and start > 0
        and body[start - 1].get("role") == "user"
    ):
        start -= 1

    removed = body[:start]
    kept = [dict(message) for message in body[start:]]
    kept = _drop_orphan_tools(kept)

    summary_budget = min(8_000, max(600, int(max_tokens * 1.2)))
    summary = _summarize(removed, summary_budget)
    base_system = str(system.get("content") or "")
    if summary:
        title = "## Contexte anterieur (resume automatique)"
        system["content"] = f"{base_system}\n\n{title}\n{summary}".strip()

    result = [system, *kept]
    _shrink_contents(result)

    while estimate_messages(result) > max_tokens and len(kept) > 2:
        kept = _drop_orphan_tools(kept[1:])
        result = [system, *kept]
        _shrink_contents(result, limit=6_000)

    if estimate_messages(result) > max_tokens:
        for message in result:
            content = message.get("content")
            if isinstance(content, str):
                message["content"] = truncate_text(content, 4_000)
    return result


def usage_from_completion(completion: Completion, messages: list[dict[str, Any]]) -> Usage:
    if completion.usage.total_tokens or completion.usage.prompt_tokens:
        return completion.usage
    prompt = estimate_messages(messages)
    completion_tokens = estimate_tokens(completion.content + completion.reasoning)
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion_tokens,
        total_tokens=prompt + completion_tokens,
        requests=1,
        estimated=True,
    )

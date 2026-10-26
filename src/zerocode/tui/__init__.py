from __future__ import annotations

from typing import Any


def run_tui(
    config: Any,
    agent: Any,
    router: Any,
    store: Any,
    permissions: Any,
    context: Any,
    chain: list[str],
) -> int:
    from .app import ZeroCodeApp

    app = ZeroCodeApp(config, agent, router, store, permissions, context, chain)
    app.run()
    return 0


__all__ = ["run_tui"]

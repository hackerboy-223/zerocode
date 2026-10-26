from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from textual.widgets import Input, Markdown, Static

from zerocode.config import Config
from zerocode.session import SessionStore
from zerocode.tools import PermissionManager, ToolContext
from zerocode.tui.app import SessionItem, ZeroCodeApp
from zerocode.tui.screens import CommandPaletteScreen, ConfirmScreen, FilePickerScreen
from zerocode.tui.widgets import PromptInput, ThinkingIndicator, ToolCard
from zerocode.types import Usage


class FakeTools:
    def __init__(self) -> None:
        self.ui: Any = None

    def tools(self) -> list[Any]:
        return []


class FakeAgent:
    def __init__(self, session: Any, tools: FakeTools, store: SessionStore) -> None:
        self.session = session
        self.tools = tools
        self.store = store
        self.usage = Usage()
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": "test"}]
        self.mode = "build"
        self.ui: Any = None

    def run_turn(self, text: str) -> str:
        self.messages.append({"role": "user", "content": text})
        self.ui.stream_text("## Bonjour\n\n")
        self.ui.stream_text("Le fichier `a.txt` est prêt.")
        self.ui.end_assistant()
        self.usage.total_tokens += 10
        self.usage.requests += 1
        return "Bonjour"

    def session_path(self) -> str:
        return "/tmp/session.json"

    def set_model(self, model: str, provider: str | None = None) -> None:
        self.session.model = model

    def set_provider(self, provider: str | None) -> None:
        self.session.provider = provider

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def load_session(self, session: Any) -> None:
        self.session = session

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": "test"}]

    def compact(self, force: bool = False) -> None:
        return None


class FakeRouter:
    last = None

    def preview(
        self, model: str | None = None, provider: str | None = None
    ) -> list[str]:
        return ["kilo/kilo-auto/free"]

    def context_window(self, model: str | None = None) -> int:
        return 128_000


def _make_app(tmp_path: Path) -> tuple[ZeroCodeApp, FakeAgent]:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "b.py").write_text("print('b')\n", encoding="utf-8")
    config = Config(base_dir=tmp_path)
    store = SessionStore(tmp_path / "sessions")
    session = store.new(tmp_path, config.model, config.provider)
    tools = FakeTools()
    agent = FakeAgent(session, tools, store)
    router = FakeRouter()
    context = ToolContext(cwd=tmp_path)
    permissions = PermissionManager(mode="ask", interactive=True)
    app = ZeroCodeApp(
        config,
        agent,
        router,
        store,
        permissions,
        context,
        router.preview(),
    )
    return app, agent


def test_tui_mounts_with_branding(tmp_path):
    async def scenario() -> None:
        app, _ = _make_app(tmp_path)
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            brand = str(app.query_one("#brandbar", Static).content)
            status = str(app.query_one("#status", Static).content)
            assert "H@CKERBOY" in brand
            assert "github.com/hackerboy-223" in brand
            assert "kilo/kilo-auto/free" in status
            assert "CHAT" in str(app.query_one("#modebar", Static).content)
            assert app.query_one("#prompt", Input) is not None
            app.store.save(app.agent.session)
            app._refresh_sessions()
            assert any(item.has_class("current") for item in app.query(SessionItem))

    asyncio.run(scenario())


def test_tui_command_palette_and_file_picker(tmp_path):
    async def scenario() -> None:
        app, _ = _make_app(tmp_path)
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+k")
            await pilot.pause()
            assert isinstance(app.screen, CommandPaletteScreen)
            await pilot.press("escape")
            await pilot.pause()

            prompt = app.query_one("#prompt", Input)
            prompt.focus()
            prompt.value = "regarde @"
            await pilot.pause()
            assert isinstance(app.screen, FilePickerScreen)
            await pilot.press("enter")
            await pilot.pause()
            assert "a.txt" in prompt.value

    asyncio.run(scenario())


def test_tui_mode_cycles_and_streams(tmp_path):
    async def scenario() -> None:
        app, _ = _make_app(tmp_path)
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            await pilot.press("tab")
            assert app._mode == "todos"
            assert "PLAN" in str(app.query_one("#modebar", Static).content)
            assert not app.query_one("#inspector").has_class("hidden")
            await pilot.press("tab")
            assert app._mode == "tools"
            await pilot.press("tab")
            assert app._mode == "chat"
            assert app.query_one("#inspector").has_class("hidden")

            prompt = app.query_one("#prompt", Input)
            prompt.focus()
            prompt.value = "test"
            await pilot.press("enter")
            for _ in range(100):
                await asyncio.sleep(0.02)
                if not app._busy:
                    break
            await pilot.pause()
            assert not app._busy
            sources = [widget.source for widget in app.query(Markdown)]
            assert any("Bonjour" in source for source in sources)

    asyncio.run(scenario())


def test_tui_commands_and_help(tmp_path):
    async def scenario() -> None:
        app, _ = _make_app(tmp_path)
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            await pilot.press("f1")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "HelpScreen"
            await pilot.press("escape")
            await pilot.pause()

            app.command_handler.handle("/help")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "HelpScreen"
            await pilot.press("escape")
            await pilot.pause()

            app.command_handler.handle("/todos")
            await pilot.pause()
            assert app._mode == "todos"
            assert not app.query_one("#inspector").has_class("hidden")

            app.command_handler.handle("/sessions")
            app.command_handler.handle("/clear")
            await pilot.pause()
            assert app._mode == "todos"
            assert len(app.query("#chat > *")) > 0

    asyncio.run(scenario())


def test_tui_prompt_history_and_tool_cards(tmp_path):
    async def scenario() -> None:
        app, _ = _make_app(tmp_path)
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt", PromptInput)
            prompt.focus()
            for text in ("premier", "second"):
                prompt.value = text
                await pilot.press("enter")
                for _ in range(100):
                    await asyncio.sleep(0.02)
                    if not app._busy:
                        break
                await pilot.pause()

            await pilot.press("up")
            assert prompt.value == "second"
            await pilot.press("up")
            assert prompt.value == "premier"
            await pilot.press("down")
            assert prompt.value == "second"
            await pilot.press("down")
            assert prompt.value == ""

            app._tool_start("bash", {"command": "echo hi"})
            await pilot.pause()
            card = app.query_one(ToolCard)
            assert not card.done
            app._tool_result("bash", "exit_code: 0\nhi")
            await pilot.pause()
            assert card.done
            assert card.has_class("success")
            assert "2 ligne" in str(card.title)
            await pilot.press("f2")
            assert card.collapsed
            await pilot.press("f2")
            assert not card.collapsed

            await pilot.press("f6")
            assert app.focused is app.query_one("#files")
            await pilot.press("f6")
            assert app.focused is app.query_one("#sessions")
            await pilot.press("f6")
            assert app.focused is app.query_one("#chat")
            await pilot.press("f6")
            assert app.focused is prompt

    asyncio.run(scenario())


def test_tui_work_modes_and_thinking(tmp_path):
    async def scenario() -> None:
        app, agent = _make_app(tmp_path)
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            assert app.work_mode == "build"
            await pilot.press("shift+tab")
            assert app.work_mode == "plan"
            assert agent.mode == "plan"
            assert "PLAN" in str(app.query_one("#modebar", Static).content)
            assert "lecture seule" in app.query_one("#prompt", Input).placeholder
            await pilot.press("shift+tab")
            assert app.work_mode == "build"
            assert agent.mode == "build"

            app.command_handler.handle("/plan")
            assert app.work_mode == "plan"
            app.command_handler.handle("/build")
            assert app.work_mode == "build"

            app._start_thinking()
            await pilot.pause()
            assert isinstance(app._thinking, ThinkingIndicator)
            assert app._thinking.is_mounted
            assert "réflexion" in str(app._thinking.content)
            app._stop_thinking()
            await pilot.pause()
            await pilot.pause()
            assert app._thinking is None
            assert not app.query(ThinkingIndicator)

    asyncio.run(scenario())


def test_tui_permission_round_trip(tmp_path):
    async def scenario() -> None:
        app, _ = _make_app(tmp_path)
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            result: dict[str, bool] = {}

            def worker() -> None:
                result["allowed"] = app.bridge.confirm_tool(
                    "bash", {"command": "rm -rf build"}
                )

            thread = threading.Thread(target=worker)
            thread.start()
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("y")
            thread.join(timeout=5)
            assert not thread.is_alive()
            assert result["allowed"] is True

    asyncio.run(scenario())

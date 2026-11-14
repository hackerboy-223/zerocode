from __future__ import annotations

import json

from zerocode.tools import PermissionManager, ToolContext, build_registry
from zerocode.tools.project import _verification_commands, project_map
from zerocode.types import ToolCall


def test_project_map_detects_stack_and_hides_secret_files(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^19.0.0"}, "scripts": {"build": "vite build"}}),
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.tsx").write_text("export default 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=do-not-show\n", encoding="utf-8")

    result = project_map({}, ToolContext(cwd=tmp_path))

    assert "JavaScript / TypeScript" in result
    assert "package.json" in result
    assert "src/main.tsx" in result
    assert ".env" not in result
    assert "do-not-show" not in result


def test_project_verify_detects_declared_node_scripts(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run", "build": "vite build"}}),
        encoding="utf-8",
    )

    commands = _verification_commands(tmp_path, ["tests", "build"])
    assert ("tests", "npm run test") in commands
    assert ("build", "npm run build") in commands


def test_project_verify_selects_lockfile_package_manager(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    commands = _verification_commands(tmp_path, ["tests"])
    assert commands == [("tests", "pnpm run test")]


def test_subagent_dispatches_to_requested_specialist(tmp_path):
    context = ToolContext(cwd=tmp_path, run_subagent=lambda task, role: f"{role}:{task}")
    registry = build_registry(context, PermissionManager(mode="allow", interactive=False))
    result = registry.execute(
        ToolCall(id="sub-1", name="subagent", arguments={"task": "inspect authentication", "role": "security"})
    )

    assert result == "security:inspect authentication"


def test_subagent_rejects_unknown_specialist(tmp_path):
    context = ToolContext(cwd=tmp_path, run_subagent=lambda task, role: "unexpected")
    registry = build_registry(context, PermissionManager(mode="allow", interactive=False))
    result = registry.execute(
        ToolCall(id="sub-2", name="subagent", arguments={"task": "inspect", "role": "root"})
    )

    assert result.startswith("ERREUR:")
    assert "Rôle de sous-agent inconnu" in result

def test_project_map_detects_swift_dotnet_and_ruby(tmp_path):
    (tmp_path / "Package.swift").write_text("// swift package\n", encoding="utf-8")
    (tmp_path / "app.csproj").write_text("<Project />\n", encoding="utf-8")
    (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n", encoding="utf-8")

    result = project_map({}, ToolContext(cwd=tmp_path))

    assert "Swift" in result
    assert ".NET" in result
    assert "Ruby" in result
    assert "Package.swift" in result
    assert "app.csproj" in result


def test_project_verify_detects_ruby_and_swift_checks(tmp_path):
    (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n", encoding="utf-8")
    (tmp_path / "Rakefile").write_text("task :test\n", encoding="utf-8")
    (tmp_path / "Package.swift").write_text("// swift package\n", encoding="utf-8")

    commands = _verification_commands(tmp_path, ["tests", "build"])
    assert ("tests", "bundle exec rake test") in commands
    assert ("tests", "swift test") in commands
    assert ("build", "swift build") in commands


def test_project_verify_detects_flutter_checks(tmp_path):
    (tmp_path / "pubspec.yaml").write_text(
        "name: demo\ndependencies:\n  flutter:\n    sdk: flutter\n",
        encoding="utf-8",
    )

    commands = _verification_commands(tmp_path, ["tests", "lint"])
    assert ("tests", "flutter test") in commands
    assert ("lint", "flutter analyze") in commands

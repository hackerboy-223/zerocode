from __future__ import annotations

import os

import pytest

KEY_ENV_NAMES = (
    "KILO_API_KEY",
    "NVIDIA_API_KEY",
    "TOGETHER_API_KEY",
    "OPENCODE_ZEN_API_KEY",
    "OPENCODE_API_KEY",
    "ZAI_API_KEY",
    "ZHIPU_API_KEY",
    "Z_AI_API_KEY",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MISTRAL_API_KEY",
    "SAMBANOVA_API_KEY",
    "OLLAMA_BASE_URL",
)


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("NO_COLOR", "1")
    for name in list(os.environ):
        if name.startswith("ZEROCODE_") or name in KEY_ENV_NAMES:
            monkeypatch.delenv(name, raising=False)
    return tmp_path

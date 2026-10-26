from __future__ import annotations

import json
import stat

import pytest

from zerocode.config import (
    Config,
    ConfigError,
    default_config_path,
    delete_key,
    keys_path,
    load_config,
    load_key_store,
    mask_key,
    save_config,
    store_key,
    validate_config,
)


def test_defaults(tmp_path):
    config = load_config(tmp_path)
    assert config.model == "glm-5.3"
    assert config.free_only is True
    assert config.fallback is True
    assert config.permissions == "ask"
    assert config.base_dir == tmp_path.resolve()
    assert config.sources == []


def test_project_config_and_global_config_merge(tmp_path):
    save_config(Config(model="auto", max_tokens=4096, permissions="ask"))
    project = tmp_path / "zerocode.json"
    project.write_text(
        json.dumps(
            {
                "provider": "groq",
                "providers": {"groq": {"enabled": True}},
            }
        ),
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.model == "auto"
    assert config.max_tokens == 4096
    assert config.provider == "groq"
    assert config.provider_config("groq") == {"enabled": True}
    assert str(project) in config.sources
    assert str(default_config_path()) in config.sources


def test_environment_and_explicit_overrides_win(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEROCODE_MODEL", "auto")
    monkeypatch.setenv("ZEROCODE_FREE_ONLY", "false")
    config = load_config(tmp_path, {"model": "glm-5.3-flash", "temperature": 0.7})
    assert config.model == "glm-5.3-flash"
    assert config.free_only is False
    assert config.temperature == 0.7


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("temperature", -1),
        ("max_tokens", 10),
        ("max_steps", 0),
        ("permissions", "sometimes"),
        ("reasoning_effort", "medium"),
        ("compact_threshold", 0.99),
    ],
)
def test_invalid_values_are_rejected(tmp_path, key, value):
    (tmp_path / "zerocode.json").write_text(json.dumps({key: value}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_unknown_provider_options_are_rejected(tmp_path):
    (tmp_path / "zerocode.json").write_text(
        json.dumps({"providers": {"groq": {"timeout": 3}}}),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_provider_url_validation(tmp_path):
    (tmp_path / "zerocode.json").write_text(
        json.dumps({"providers": {"groq": {"base_url": "ftp://example.test"}}}),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_key_store_roundtrip_and_mode(tmp_path):
    path = store_key("groq", "gsk-secret-value")
    assert path == keys_path()
    assert load_key_store()["groq"] == "gsk-secret-value"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & 0o077 == 0
    assert mask_key("gsk-secret-value") == "gsk-...alue"
    assert delete_key("groq") is True
    assert delete_key("groq") is False
    assert load_key_store() == {}


def test_invalid_config_json_is_reported(tmp_path):
    (tmp_path / "zerocode.json").write_text("{", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_validate_config_accepts_defaults():
    validate_config(Config())

from __future__ import annotations

from zerocode.catalog import (
    AUTO_CHAIN,
    GLM53_CHAIN,
    GLM53_FLASH_CHAIN,
    PROVIDERS,
    all_choices,
    find_model,
    get_provider,
    model_chain,
)


def test_catalog_ids_are_unique_per_provider():
    for provider in PROVIDERS.values():
        ids = [model.id for model in provider.models]
        assert len(ids) == len(set(ids)), provider.name


def test_free_models_exist():
    assert PROVIDERS["kilo"].free_models
    assert PROVIDERS["zai"].free_models
    assert "glm-4.7-flash" in {model.id for model in PROVIDERS["zai"].free_models}


def test_new_openrouter_free_models_are_tool_capable():
    expected = {
        "cohere/north-mini-code:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia/nemotron-3.5-lightning:free",
        "nvidia/nemotron-3.5-super-vl:free",
        "thinkingmachines/inkling-small:free",
        "xingchen-agi/xing4.0-29b-a4b:free",
        "google/gemma-4-26b-a4b:free",
    }
    openrouter_ids = {model.id for model in PROVIDERS["openrouter"].free_models}
    assert expected <= openrouter_ids
    for model_id in expected:
        model = PROVIDERS["openrouter"].model(model_id)
        assert model is not None and model.tools


def test_alias_chains():
    assert model_chain("auto") == AUTO_CHAIN
    assert model_chain("glm-5.3")[: len(GLM53_CHAIN)] == GLM53_CHAIN
    assert model_chain("glm-5.3-flash")[: len(GLM53_FLASH_CHAIN)] == GLM53_FLASH_CHAIN
    assert model_chain("glm-5.3-flash-free")[: len(GLM53_FLASH_CHAIN)] == GLM53_FLASH_CHAIN
    assert model_chain("unknown") == ()


def test_lookup_helpers():
    assert get_provider("kilo") is not None
    assert get_provider("missing") is None
    matches = find_model("glm-4.7")
    assert matches
    assert all("glm-4.7" in model.id for _, model in matches)
    assert any(model.id == "glm-5.3-flash-free" for _, model in all_choices())

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

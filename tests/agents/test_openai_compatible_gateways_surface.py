"""``resolve_model_params_for_model`` had no caller anywhere; the endpoint resolver stays."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.agents.openai_compatible_gateways import (
    CUSTOM_PROVIDER_API_KEY_ENV,
    CUSTOM_PROVIDER_BASE_URL_ENV,
    SINGLETON_PROVIDER_ID,
    resolve_gateway_endpoint,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_BASE_URL = "https://gateway.example/v1"
_API_KEY = "gateway-placeholder-key"


def test_resolve_model_params_for_model_is_gone(monkeypatch: MonkeyPatch) -> None:
    """The zero-caller helper is deleted; the endpoint resolver still resolves the gateway."""
    import mergecraft.agents.openai_compatible_gateways as module

    assert "resolve_model_params_for_model" not in module.__all__
    assert not hasattr(module, "resolve_model_params_for_model")
    # Surviving surface: the shared endpoint resolver still resolves the singleton gateway.
    for index in range(1, 8):
        monkeypatch.delenv(f"{CUSTOM_PROVIDER_API_KEY_ENV}_{index}", raising=False)
        monkeypatch.delenv(f"{CUSTOM_PROVIDER_BASE_URL_ENV}_{index}", raising=False)
    monkeypatch.setenv(CUSTOM_PROVIDER_BASE_URL_ENV, _BASE_URL)
    monkeypatch.setenv(CUSTOM_PROVIDER_API_KEY_ENV, _API_KEY)
    assert resolve_gateway_endpoint("default/gpt-4o") == (
        SINGLETON_PROVIDER_ID,
        _BASE_URL,
        _API_KEY,
    )
